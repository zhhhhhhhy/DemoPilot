<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from './api'
import AgentTimeline from './components/AgentTimeline.vue'
import EvaluationCenter from './components/EvaluationCenter.vue'
import type { DemoRequest, DemoRun, DemoTemplate, ProviderName } from './types'

interface ReviewerIssue {
  id: string
  severity: string
  category: string
  requirement: string
  evidence: string
  root_cause: string
  repair_instruction: string
  verification: string
}

interface RequirementReview {
  requirement: string
  status: string
  evidence: string
}

interface ReviewerOutput {
  status: string
  decision: string
  overall_score: number
  confidence: number
  dimension_scores: Record<string, number>
  requirement_coverage: RequirementReview[]
  issues: ReviewerIssue[]
  real_features: string[]
  simulated_features: string[]
  scope_boundaries: string[]
  open_gates: string[]
  evidence: { source_mode?: string; browser_status?: string; validator_issue_count?: number }
}

const runs = ref<DemoRun[]>([])
const templates = ref<DemoTemplate[]>([])
const selectedRunId = ref<string | null>(null)
const isSubmitting = ref(false)
const isActing = ref(false)
const loadError = ref('')
const formElement = ref<HTMLElement | null>(null)
let pollTimer: number | undefined
let eventSource: EventSource | undefined

const form = reactive({
  client_name: '远山科技',
  project_name: '智能运营指挥台',
  industry: '企业服务',
  scenario: '运营团队每天需要在多个系统之间切换，无法快速判断优先级并追踪结果。',
  audience: '运营负责人',
  must_haves: '运营总览，智能任务分派，效果追踪',
  brand_tone: '简洁、可信、现代',
  primary_color: '#0071e3',
  provider: 'deepseek' as ProviderName,
  require_execution_approval: true,
})

const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value) ?? runs.value[0] ?? null)
const completedCount = computed(() => runs.value.filter((run) => run.status === 'completed').length)
const activeCount = computed(() => runs.value.filter((run) => ['queued', 'running', 'waiting_approval'].includes(run.status)).length)
const demoArtifact = computed(() => selectedRun.value?.artifacts.find((artifact) => artifact.kind === 'demo'))
const archiveArtifact = computed(() => selectedRun.value?.artifacts.find((artifact) => artifact.kind === 'archive'))
const pendingApproval = computed(() => selectedRun.value?.approvals?.find((approval) => approval.status === 'pending'))
const recentReceipts = computed(() => selectedRun.value?.tool_receipts?.slice(-6).reverse() ?? [])

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : []
}

const intentionalBoundaryPattern = /erp|wms|crm|真实系统|真实集成|真实客户数据|实时数据|实时库存|数据接入|数据同步|数据库|预测|实时计算|后端|审批|权限|角色|生产鉴权|生产部署|生产环境/i
const defaultScopeBoundaries = ['纯展示型静态售前 Demo', '业务数据使用本地虚构样例', '业务交互仅在浏览器内模拟并可重置']

function normalizeReviewerOutput(output: Record<string, unknown>): ReviewerOutput {
  const raw = output as Record<string, unknown>
  const rawIssues = Array.isArray(raw.issues) ? raw.issues : []
  const issues: ReviewerIssue[] = rawIssues.map((item, index) => {
    if (typeof item === 'string') {
      return { id: `legacy-${index}`, severity: 'medium', category: 'quality', requirement: '旧版 QA', evidence: item, root_cause: '旧版记录未结构化根因', repair_instruction: '根据证据修复最终产物', verification: '重新运行产物与浏览器验证' }
    }
    const issue = (item ?? {}) as Record<string, unknown>
    return {
      id: String(issue.id ?? `review-${index}`),
      severity: String(issue.severity ?? 'medium'),
      category: String(issue.category ?? 'quality'),
      requirement: String(issue.requirement ?? '评审标准'),
      evidence: String(issue.evidence ?? issue.message ?? '未提供证据'),
      root_cause: String(issue.root_cause ?? '待定位'),
      repair_instruction: String(issue.repair_instruction ?? '根据证据修复最终产物'),
      verification: String(issue.verification ?? '重新运行验证'),
    }
  })
  const openGates = stringList(raw.open_gates).filter((item) => !intentionalBoundaryPattern.test(item))
  const rawDecision = String(raw.decision ?? 'pass')
  const decision = rawDecision === 'pass_with_open_gates' && !issues.length && !openGates.length ? 'pass' : rawDecision
  const rawScore = Number(raw.overall_score ?? 0)
  return {
    status: String(raw.status ?? 'reviewed'),
    decision,
    overall_score: decision === 'revise' && rawScore >= 80 ? 79 : rawScore,
    confidence: Number(raw.confidence ?? 0),
    dimension_scores: (raw.dimension_scores ?? {}) as Record<string, number>,
    requirement_coverage: (Array.isArray(raw.requirement_coverage) ? raw.requirement_coverage : []) as RequirementReview[],
    issues,
    real_features: stringList(raw.real_features),
    simulated_features: stringList(raw.simulated_features),
    scope_boundaries: stringList(raw.scope_boundaries).length ? stringList(raw.scope_boundaries) : defaultScopeBoundaries,
    open_gates: openGates,
    evidence: (raw.evidence ?? {}) as ReviewerOutput['evidence'],
  } satisfies ReviewerOutput
}

const reviewerOutput = computed(() => {
  const output = selectedRun.value?.outputs.reviewer ?? selectedRun.value?.outputs.qa
  return output ? normalizeReviewerOutput(output) : null
})
const reviewerHistory = computed(() => Object.entries(selectedRun.value?.outputs ?? {})
  .filter(([key]) => /^reviewer_iteration_\d+$/.test(key))
  .map(([key, value]) => ({ iteration: Number(key.split('_').at(-1)), review: normalizeReviewerOutput(value) }))
  .sort((left, right) => left.iteration - right.iteration))
function reviewerDecisionLabel(decision: string) {
  return { revise: '要求返工', pass: '通过', pass_with_open_gates: '带开放项通过' }[decision] ?? '等待最终评审'
}
const reviewerDecision = computed(() => ({
  revise: '要求返工',
  pass: '通过',
  pass_with_open_gates: '带开放项通过',
}[reviewerOutput.value?.decision ?? ''] ?? '等待最终评审'))
const reviewerDimensions: Record<string, string> = {
  requirement_coverage: '需求覆盖',
  interaction: '交互可用',
  artifact: '项目完整',
  safety: '安全边界',
  demo_clarity: '演示清晰',
  provenance: '来源追踪',
}

function payloadFromForm(): DemoRequest {
  return {
    ...form,
    must_haves: form.must_haves.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
  }
}

function useTemplate(template: DemoTemplate) {
  form.project_name = template.name
  form.industry = template.industry
  form.scenario = template.scenario
  form.must_haves = template.must_haves.join('，')
  formElement.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function loadDashboard() {
  try {
    const [runList, templateList] = await Promise.all([api.listRuns(), api.templates()])
    runs.value = runList
    templates.value = templateList
    selectedRunId.value ||= runList[0]?.id ?? null
    const selected = runList.find((run) => run.id === selectedRunId.value)
    if (selected && !['completed', 'failed', 'cancelled'].includes(selected.status)) startLiveUpdates(selected.id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '无法连接后端'
  }
}

async function refreshRun(id: string) {
  try {
    const updated = await api.getRun(id)
    const index = runs.value.findIndex((run) => run.id === id)
    if (index >= 0) runs.value[index] = updated
    else runs.value.unshift(updated)
    if (['completed', 'failed', 'cancelled'].includes(updated.status)) stopLiveUpdates()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '刷新任务失败'
  }
}

function startPolling(id: string) {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(() => void refreshRun(id), 900)
}

function stopLiveUpdates() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
  eventSource?.close()
  eventSource = undefined
}

function mergeRun(updated: DemoRun) {
  const index = runs.value.findIndex((run) => run.id === updated.id)
  if (index >= 0) runs.value[index] = updated
  else runs.value.unshift(updated)
}

function startLiveUpdates(id: string) {
  stopLiveUpdates()
  if (typeof EventSource === 'undefined') {
    startPolling(id)
    return
  }
  eventSource = new EventSource(api.runEventsUrl(id))
  eventSource.addEventListener('run', (event) => {
    const updated = JSON.parse((event as MessageEvent).data) as DemoRun
    mergeRun(updated)
    if (['completed', 'failed', 'cancelled'].includes(updated.status)) stopLiveUpdates()
  })
  eventSource.onerror = () => {
    eventSource?.close()
    eventSource = undefined
    startPolling(id)
  }
}

async function submitBrief() {
  isSubmitting.value = true
  loadError.value = ''
  try {
    const run = await api.createRun(payloadFromForm())
    runs.value.unshift(run)
    selectedRunId.value = run.id
    startLiveUpdates(run.id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '创建失败'
  } finally {
    isSubmitting.value = false
  }
}

function selectRun(run: DemoRun) {
  selectedRunId.value = run.id
  if (!['completed', 'failed', 'cancelled'].includes(run.status)) startLiveUpdates(run.id)
}

async function decideApproval(decision: 'approve' | 'decline') {
  if (!selectedRun.value || !pendingApproval.value) return
  isActing.value = true
  try {
    const updated = await api.decideApproval(selectedRun.value.id, pendingApproval.value.id, decision)
    mergeRun(updated)
    if (decision === 'approve') startLiveUpdates(updated.id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '审批失败'
  } finally {
    isActing.value = false
  }
}

async function cancelSelected() {
  if (!selectedRun.value) return
  isActing.value = true
  try {
    mergeRun(await api.cancelRun(selectedRun.value.id))
    stopLiveUpdates()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '取消失败'
  } finally {
    isActing.value = false
  }
}

async function resumeSelected() {
  if (!selectedRun.value) return
  isActing.value = true
  try {
    const updated = await api.resumeRun(selectedRun.value.id)
    mergeRun(updated)
    startLiveUpdates(updated.id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '恢复失败'
  } finally {
    isActing.value = false
  }
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function statusLabel(status: DemoRun['status']) {
  return { queued: '排队中', running: '生成中', waiting_approval: '待审批', completed: '已完成', failed: '失败', cancelled: '已取消' }[status]
}

onMounted(() => void loadDashboard())
onBeforeUnmount(stopLiveUpdates)
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="app-brand"><span class="app-logo">D</span><span>DemoPilot</span></div>
      <nav class="side-nav" aria-label="主导航">
        <a class="side-link active" href="#workspace"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg><span>工作台</span></a>
        <a class="side-link" href="#runs"><svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9h-9V3Z"/><path d="M15 3.7A9 9 0 0 1 20.3 9H15V3.7Z"/></svg><span>Demo 记录</span></a>
        <a class="side-link" href="#team"><svg viewBox="0 0 24 24"><circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c.5-4 2-6 5-6s4.5 2 5 6M14 15c3.5-.7 6 1 6.5 4"/></svg><span>Agent Team</span></a>
        <a class="side-link" href="#evaluations"><svg viewBox="0 0 24 24"><path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/><path d="m4 7 6-4 6 6 5-5"/></svg><span>自动评测</span></a>
      </nav>
      <div class="sidebar-bottom">
        <div class="mode-card"><span class="mode-dot"></span><div><strong>Team Workflow</strong><small>管理、并行、验证、返工</small></div></div>
        <p>真实模型模式需显式选择，不会静默调用外部服务。</p>
      </div>
    </aside>

    <main id="workspace" class="workspace">
      <header class="topbar">
        <div><span class="section-kicker">AGENT TEAM WORKSPACE</span><h1>上午好，销售团队。</h1><p>把客户的一段需求，变成一套可以讲、可以点、可以交付的 Demo。</p></div>
        <button class="new-demo-button" type="button" @click="formElement?.scrollIntoView({ behavior: 'smooth' })"><span>＋</span> 新建 Demo</button>
      </header>

      <div v-if="loadError" class="error-banner" role="alert"><span>连接提示</span>{{ loadError }}<button type="button" @click="loadError = ''">关闭</button></div>

      <section class="summary-grid" aria-label="工作台概览">
        <article class="summary-card featured"><span>本月已生成</span><strong>{{ completedCount || 0 }}</strong><p>套可交付客户 Demo</p><div class="summary-orb"></div></article>
        <article class="summary-card"><div class="summary-icon blue"><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg></div><span>交付成功</span><strong>{{ completedCount }}</strong><p>含规格、讲解词与 QA</p></article>
        <article class="summary-card"><div class="summary-icon violet"><svg viewBox="0 0 24 24"><path d="M12 3v5M12 16v5M3 12h5M16 12h5M5.6 5.6l3.5 3.5M14.9 14.9l3.5 3.5M18.4 5.6l-3.5 3.5M9.1 14.9l-3.5 3.5"/></svg></div><span>正在生成</span><strong>{{ activeCount }}</strong><p>9 个协作节点 · 含 Contract Agent 与 Reviewer</p></article>
      </section>

      <EvaluationCenter />

      <section class="template-section">
        <div class="section-heading"><div><span class="section-kicker">START FAST</span><h2>从常用场景开始</h2></div><span>选择后仍可自由修改</span></div>
        <div class="template-row">
          <button v-for="(template, index) in templates" :key="template.id" class="template-card" type="button" @click="useTemplate(template)">
            <span class="template-index">0{{ index + 1 }}</span><div><strong>{{ template.name }}</strong><p>{{ template.industry }} · {{ template.must_haves.length }} 个核心模块</p></div><span class="template-arrow">↗</span>
          </button>
        </div>
      </section>

      <section class="work-grid">
        <div id="runs" class="run-column">
          <div class="section-heading compact"><div><span class="section-kicker">RECENT WORK</span><h2>最近的 Demo</h2></div><span>{{ runs.length }} 个任务</span></div>
          <div v-if="!runs.length" class="empty-state"><div class="empty-glyph">✦</div><h3>第一套 Demo，正等着一个好问题。</h3><p>在右侧填写客户需求，Agent Team 会完成从洞察到交付的全过程。</p></div>
          <div v-else class="run-list">
            <button v-for="run in runs.slice(0, 6)" :key="run.id" type="button" class="run-card" :class="{ selected: selectedRun?.id === run.id }" @click="selectRun(run)">
              <div class="run-brand" :style="{ background: run.request.primary_color }">{{ run.request.client_name.slice(0, 1) }}</div>
              <div class="run-copy"><div><strong>{{ run.request.project_name }}</strong><span class="status-chip" :class="`status-${run.status}`">{{ statusLabel(run.status) }}</span></div><p>{{ run.request.client_name }} · {{ run.request.industry }}</p><small>{{ formatTime(run.created_at) }}</small></div>
              <div class="run-progress"><strong>{{ run.progress }}%</strong><span><i :style="{ width: `${run.progress}%` }"></i></span></div>
            </button>
          </div>
        </div>

        <form ref="formElement" class="brief-card" @submit.prevent="submitBrief">
          <div class="brief-heading"><div><span class="section-kicker">NEW BRIEF</span><h2>告诉团队客户想要什么</h2></div><div class="live-pill"><span></span>就绪</div></div>
          <div class="form-row"><label>客户名称<input v-model="form.client_name" required minlength="2" maxlength="80" placeholder="例如：远山科技" /></label><label>Demo 名称<input v-model="form.project_name" required minlength="2" maxlength="100" /></label></div>
          <div class="form-row"><label>行业<input v-model="form.industry" required maxlength="80" /></label><label>演示对象<input v-model="form.audience" required maxlength="200" /></label></div>
          <label>客户场景<textarea v-model="form.scenario" required minlength="10" maxlength="2000" rows="4"></textarea><small>{{ form.scenario.length }} / 2000</small></label>
          <label>必须出现的能力<input v-model="form.must_haves" placeholder="使用逗号分隔" /><small>例如：经营看板，智能分析，报告导出</small></label>
          <div class="form-row"><label>品牌气质<input v-model="form.brand_tone" maxlength="100" /></label><label>主色<div class="color-control"><input v-model="form.primary_color" type="color" /><input v-model="form.primary_color" pattern="^#[0-9A-Fa-f]{6}$" /></div></label></div>
          <div class="provider-control"><div><strong>执行内核</strong><span>默认使用 DeepSeek 驱动完整 Agent Team；Mock 仅用于离线回归</span></div><select v-model="form.provider"><option value="deepseek">DeepSeek · 默认开发内核</option><option value="mock">Mock · 仅离线回归</option><option value="aihubmix">AIHubMix · 手动备用</option><option value="zju">ZJU · 手动备用</option><option value="claude">Claude · 未配置</option></select></div>
          <label class="approval-toggle"><input v-model="form.require_execution_approval" type="checkbox" /><span><strong>生成文件前需要人工批准</strong><small>规划可自动完成；只有任务级沙箱准备写入产物时暂停。</small></span></label>
          <button class="submit-button" type="submit" :disabled="isSubmitting"><span v-if="isSubmitting" class="button-spinner"></span><span v-else>✦</span>{{ isSubmitting ? '正在组建团队…' : '让 Agent Team 开始工作' }}</button>
          <p class="form-boundary">不会连接客户生产系统，也不会自动对外发布。所有产物需由销售复核后交付。</p>
        </form>
      </section>

      <section v-if="selectedRun" id="team" class="delivery-section">
        <div class="section-heading"><div><span class="section-kicker">DELIVERY ROOM</span><h2>{{ selectedRun.request.project_name }}</h2></div><div class="delivery-actions"><button v-if="['queued', 'running', 'waiting_approval'].includes(selectedRun.status)" type="button" :disabled="isActing" @click="cancelSelected">取消任务</button><button v-if="['failed', 'cancelled'].includes(selectedRun.status)" type="button" :disabled="isActing" @click="resumeSelected">从检查点恢复</button><a v-if="demoArtifact" :href="api.artifactUrl(demoArtifact.download_url)" target="_blank" rel="noreferrer">打开 Demo</a><a v-if="archiveArtifact" class="primary-link" :href="api.artifactUrl(archiveArtifact.download_url)">下载交付包</a></div></div>
        <div class="delivery-grid">
          <article class="agent-panel"><div class="panel-title"><div><h3>Agent Team</h3><p>{{ selectedRun.agent_calls }} 次调用 · {{ selectedRun.revision_count }} 次返工 · {{ selectedRun.tool_receipts?.length ?? 0 }} 条工具凭证</p></div><strong>{{ selectedRun.progress }}%</strong></div><div class="overall-progress"><span :style="{ width: `${selectedRun.progress}%` }"></span></div><div v-if="pendingApproval" class="approval-card"><span>需要你的批准</span><strong>允许在本任务沙箱生成交付文件？</strong><p>{{ pendingApproval.reason }}</p><div><button type="button" :disabled="isActing" @click="decideApproval('decline')">拒绝</button><button class="approve-button" type="button" :disabled="isActing" @click="decideApproval('approve')">批准并继续</button></div></div><AgentTimeline :events="selectedRun.events" :run-status="selectedRun.status" /><div v-if="recentReceipts.length" class="receipt-list"><div class="receipt-heading"><strong>工具调用凭证</strong><span>真实落盘后生成</span></div><div v-for="receipt in recentReceipts" :key="receipt.id" class="receipt-row"><span :class="`receipt-${receipt.status}`"></span><div><strong>{{ receipt.tool_name }}</strong><small>{{ receipt.output_summary }}</small></div><code v-if="Object.values(receipt.sha256)[0]">{{ Object.values(receipt.sha256)[0].slice(0, 8) }}</code></div></div></article>
          <article class="preview-panel">
            <div class="browser-bar"><div class="traffic-lights"><span></span><span></span><span></span></div><div class="address">demopilot.local / {{ selectedRun.id }}</div><span class="secure-mark">⌁</span></div>
            <iframe v-if="demoArtifact" :key="demoArtifact.download_url" :src="api.artifactUrl(demoArtifact.download_url)" title="生成的客户 Demo 预览"></iframe>
            <div v-else class="preview-wait"><div class="preview-pulse">D</div><h3>{{ selectedRun.status === 'failed' ? '生成中断' : selectedRun.status === 'waiting_approval' ? '等待批准后生成' : selectedRun.status === 'cancelled' ? '任务已取消' : '团队正在搭建 Demo' }}</h3><p>{{ selectedRun.error || '完成后，这里会出现可交互预览。' }}</p></div>
          </article>
        </div>
        <article v-if="reviewerOutput" class="reviewer-panel">
          <div class="reviewer-heading">
            <div><span class="section-kicker">INDEPENDENT REVIEWER</span><h3>需求、项目与证据的独立评审</h3><p>Reviewer 属于 Agent Team，但不修改文件，也不接受 Builder 自报完成。</p></div>
            <div class="reviewer-verdict" :class="`review-${reviewerOutput.decision}`"><strong>{{ reviewerOutput.overall_score ?? '—' }}</strong><span>{{ reviewerDecision }}</span><small>置信度 {{ Math.round((reviewerOutput.confidence ?? 0) * 100) }}%</small></div>
          </div>
          <div class="review-dimensions">
            <div v-for="(score, key) in reviewerOutput.dimension_scores" :key="key"><span>{{ reviewerDimensions[String(key)] ?? key }}</span><strong>{{ score }}</strong></div>
          </div>
          <div class="review-columns">
            <section><div class="review-section-title"><strong>需求覆盖</strong><span>{{ reviewerOutput.evidence?.source_mode ?? 'unknown' }}</span></div><div class="requirement-review"><div v-for="item in reviewerOutput.requirement_coverage" :key="item.requirement"><span :class="`requirement-${item.status}`"></span><div><strong>{{ item.requirement }}</strong><small>{{ item.evidence }}</small></div><em>{{ item.status }}</em></div></div></section>
            <section><div class="review-section-title"><strong>问题、根因与复验</strong><span>{{ reviewerOutput.issues.length }} 项</span></div><div v-if="reviewerOutput.issues.length" class="review-issues"><details v-for="issue in reviewerOutput.issues" :key="issue.id"><summary><span :class="`severity-${issue.severity}`">{{ issue.severity }}</span><strong>{{ issue.evidence }}</strong></summary><p><b>根因</b>{{ issue.root_cause }}</p><p><b>修复</b>{{ issue.repair_instruction }}</p><p><b>复验</b>{{ issue.verification }}</p></details></div><div v-else class="review-clean"><span>✓</span><div><strong>没有触发硬门禁的问题</strong><p>仍需人工确认视觉、销售说服力和客户业务正确性。</p></div></div></section>
          </div>
          <div class="review-boundaries"><div><strong>已验证真实交互</strong><span>{{ reviewerOutput.real_features.join('、') || '无' }}</span></div><div><strong>样例数据模拟能力</strong><span>{{ reviewerOutput.simulated_features.join('、') || '无' }}</span></div><div><strong>既定演示边界</strong><span>{{ reviewerOutput.scope_boundaries.join('、') || '纯展示型静态 Demo，使用本地虚构数据' }}</span></div><div v-if="reviewerOutput.open_gates.length" class="unresolved"><strong>真正未解决项</strong><span>{{ reviewerOutput.open_gates.join('、') }}</span></div></div>
          <div v-if="reviewerHistory.length" class="review-history">
            <div class="review-section-title"><strong>评审与返工轨迹</strong><span>{{ reviewerHistory.length }} 轮 · 旧问题不会被最终通过覆盖</span></div>
            <details v-for="item in reviewerHistory" :key="item.iteration" :open="item.review.decision === 'revise'">
              <summary><span>第 {{ item.iteration + 1 }} 轮</span><strong>{{ reviewerDecisionLabel(item.review.decision) }}</strong><em>{{ item.review.overall_score }} 分 · {{ item.review.issues.length }} 个问题</em></summary>
              <div v-if="item.review.issues.length" class="review-history-issues"><article v-for="issue in item.review.issues" :key="issue.id"><strong>{{ issue.evidence }}</strong><p><b>根因</b>{{ issue.root_cause }}</p><p><b>修复</b>{{ issue.repair_instruction }}</p><p><b>复验</b>{{ issue.verification }}</p></article></div>
              <div v-else class="review-history-pass">✓ 本轮没有触发硬门禁的问题，演示范围内完整通过。</div>
            </details>
          </div>
        </article>
      </section>
    </main>
  </div>
</template>
