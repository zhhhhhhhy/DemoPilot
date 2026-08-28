<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import type { EvaluationCase, EvaluationRequest, EvaluationRun } from '../types'

const cases = ref<EvaluationCase[]>([])
const evaluations = ref<EvaluationRun[]>([])
const selectedId = ref<string | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let stream: EventSource | undefined
let fallbackTimer: number | undefined

const form = reactive<EvaluationRequest>({
  provider: 'mock',
  case_ids: [],
  case_limit: 5,
  complexity: 'all',
  concurrency: 2,
  version_label: 'harness-v1',
  baseline_id: null,
  skill_profile: 'approved',
  first_pass_only: false,
  builder_preflight_enabled: true,
  thresholds: {
    min_success_rate: 0.9,
    min_average_score: 80,
    min_browser_pass_rate: 0.9,
    min_feature_coverage_rate: 0.95,
    max_average_agent_calls: 12,
  },
})

const selected = computed(() => evaluations.value.find((item) => item.id === selectedId.value) ?? evaluations.value[0] ?? null)
const completedEvaluations = computed(() => evaluations.value.filter((item) => item.status === 'completed').length)
const activeEvaluation = computed(() => evaluations.value.some((item) => ['queued', 'running'].includes(item.status)))
const realProvider = computed(() => form.provider !== 'mock')
const complexityOrder = ['simple', 'complex'] as const
const complexityCounts = computed(() => ({
  simple: cases.value.filter((item) => item.complexity === 'simple').length,
  complex: cases.value.filter((item) => item.complexity === 'complex').length,
}))
const availableCaseCount = computed(() => form.complexity === 'all' ? cases.value.length : complexityCounts.value[form.complexity])
const caseLimitOptions = computed(() => {
  const cap = availableCaseCount.value || 30
  if (realProvider.value) return [1, 2, 3].filter((count) => count <= cap)
  const options = [5, 10, 20, 30].filter((count) => count <= cap)
  if (cap > 0 && !options.includes(cap)) options.push(cap)
  return options.sort((left, right) => left - right)
})

watch(() => form.provider, (provider) => {
  form.case_limit = provider === 'mock' ? Math.max(5, form.case_limit) : Math.min(3, form.case_limit)
  form.concurrency = provider === 'mock' ? 2 : 1
})

watch([() => form.complexity, caseLimitOptions], () => {
  if (!caseLimitOptions.value.includes(form.case_limit)) {
    form.case_limit = caseLimitOptions.value.at(-1) ?? 1
  }
})

function mergeEvaluation(updated: EvaluationRun) {
  const index = evaluations.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) evaluations.value[index] = updated
  else evaluations.value.unshift(updated)
}

function stopUpdates() {
  stream?.close()
  stream = undefined
  if (fallbackTimer) window.clearInterval(fallbackTimer)
  fallbackTimer = undefined
}

async function refresh(id: string) {
  try {
    const updated = await api.getEvaluation(id)
    mergeEvaluation(updated)
    if (['completed', 'failed', 'cancelled'].includes(updated.status)) stopUpdates()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '评测刷新失败'
  }
}

function startUpdates(id: string) {
  stopUpdates()
  stream = new EventSource(api.evaluationEventsUrl(id))
  stream.addEventListener('evaluation', (event) => {
    const updated = JSON.parse((event as MessageEvent).data) as EvaluationRun
    mergeEvaluation(updated)
    if (['completed', 'failed', 'cancelled'].includes(updated.status)) stopUpdates()
  })
  stream.onerror = () => {
    stream?.close()
    stream = undefined
    fallbackTimer = window.setInterval(() => void refresh(id), 1200)
  }
}

async function load() {
  try {
    const [caseList, evaluationList] = await Promise.all([api.evaluationCases(), api.listEvaluations()])
    cases.value = caseList
    evaluations.value = evaluationList
    selectedId.value ||= evaluationList[0]?.id ?? null
    if (selected.value && ['queued', 'running'].includes(selected.value.status)) startUpdates(selected.value.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '无法加载评测中心'
  }
}

async function createEvaluation() {
  loading.value = true
  errorMessage.value = ''
  try {
    const created = await api.createEvaluation({ ...form, case_ids: [] })
    mergeEvaluation(created)
    selectedId.value = created.id
    startUpdates(created.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建评测失败'
  } finally {
    loading.value = false
  }
}

async function cancelEvaluation() {
  if (!selected.value) return
  mergeEvaluation(await api.cancelEvaluation(selected.value.id))
  stopUpdates()
}

function selectEvaluation(evaluation: EvaluationRun) {
  selectedId.value = evaluation.id
  if (['queued', 'running'].includes(evaluation.status)) startUpdates(evaluation.id)
  else stopUpdates()
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`
}

function signed(value: unknown, digits = 1) {
  if (typeof value !== 'number') return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

function statusLabel(status: EvaluationRun['status']) {
  return { queued: '排队中', running: '评测中', completed: '已完成', failed: '运行失败', cancelled: '已取消' }[status]
}

function complexityLabel(complexity: 'all' | 'simple' | 'complex' | null) {
  return { all: '全部难度', simple: '简单要求', complex: '复杂要求' }[complexity ?? 'all']
}

onMounted(() => void load())
onBeforeUnmount(stopUpdates)
</script>

<template>
  <section id="evaluations" class="evaluation-center">
    <div class="evaluation-heading">
      <div><span class="section-kicker">AUTOMATIC EVALUATION</span><h2>自动评测中心</h2><p>用固定需求集重复验证 Agent Team，而不是只看一次成功 Demo。</p></div>
      <div class="evaluation-summary"><span><strong>{{ cases.length }}</strong> 标准用例</span><span><strong>{{ complexityCounts.simple }}</strong> 简单要求</span><span><strong>{{ complexityCounts.complex }}</strong> 复杂要求</span><span><strong>{{ completedEvaluations }}</strong> 历史版本</span></div>
    </div>

    <div v-if="errorMessage" class="evaluation-error">{{ errorMessage }}<button type="button" @click="errorMessage = ''">关闭</button></div>

    <div class="evaluation-layout">
      <form class="evaluation-config" @submit.prevent="createEvaluation">
        <div><span class="section-kicker">NEW EVALUATION</span><h3>设置本轮边界</h3></div>
        <label>版本标签<input v-model="form.version_label" required maxlength="60" /></label>
        <label>模型内核<select v-model="form.provider"><option value="mock">Mock · 全量回归</option><option value="deepseek">DeepSeek · 真实评测</option><option value="aihubmix">AIHubMix · 真实评测</option><option value="zju">ZJU · 真实评测</option></select></label>
        <label>需求难度<select v-model="form.complexity"><option value="all">全部难度</option><option value="simple">简单要求 · 单页核心流程</option><option value="complex">复杂要求 · 多步骤联动</option></select></label>
        <label>Skill 配置<select v-model="form.skill_profile"><option value="approved">已批准 Skill</option><option value="baseline">Baseline · 不加载 Skill</option><option value="candidate">Candidate · 候选 Skill</option></select></label>
        <label><input v-model="form.first_pass_only" type="checkbox" /> 仅评测首轮，不允许 Reviewer 返工</label>
        <label><input v-model="form.builder_preflight_enabled" type="checkbox" /> 启用 Builder 确定性预检（关闭仅用于 A/B 对照）</label>
        <label>用例数量<select v-model.number="form.case_limit"><option v-for="count in caseLimitOptions" :key="count" :value="count">{{ count }} 个用例</option></select></label>
        <div class="eval-budget" :class="{ real: realProvider }"><strong>{{ realProvider ? '真实 API 保护已开启' : '离线回归模式' }}</strong><span>{{ realProvider ? '最多 3 条、并发 1，不会静默扩大调用。' : '使用确定性 Provider，可运行完整 30 条。' }}</span></div>
        <div class="threshold-grid"><span>成功率 ≥ {{ percent(form.thresholds.min_success_rate) }}</span><span>平均分 ≥ {{ form.thresholds.min_average_score }}</span><span>浏览器 ≥ {{ percent(form.thresholds.min_browser_pass_rate) }}</span><span>调用数 ≤ {{ form.thresholds.max_average_agent_calls }}</span></div>
        <button class="evaluation-run-button" type="submit" :disabled="loading || Boolean(activeEvaluation)">{{ loading ? '正在创建…' : activeEvaluation ? '已有评测运行中' : `运行 ${form.case_limit} 条评测` }}</button>
      </form>

      <div class="evaluation-results">
        <div v-if="!selected" class="evaluation-empty"><strong>还没有评测记录</strong><p>先运行 5 条 Mock 基线，评测中心会生成可追溯报告。</p></div>
        <template v-else>
          <div class="evaluation-result-head"><div><span class="eval-status" :class="`eval-${selected.status}`">{{ statusLabel(selected.status) }}</span><h3>{{ selected.request.version_label }}</h3><p>{{ selected.request.provider }} · {{ selected.metrics.completed_cases }}/{{ selected.metrics.total_cases }} 用例完成</p></div><div class="evaluation-actions"><button v-if="activeEvaluation" type="button" @click="cancelEvaluation">取消</button><a v-if="selected.report_url" :href="api.evaluationReportUrl(selected.id)">下载报告</a></div></div>
          <div class="evaluation-progress"><span :style="{ width: `${selected.progress}%` }"></span></div>

          <div class="metric-grid">
            <article><span>任务成功率</span><strong>{{ percent(selected.metrics.success_rate) }}</strong><small>{{ selected.metrics.passed_cases }} / {{ selected.metrics.total_cases }}</small></article>
            <article><span>首轮成功率</span><strong>{{ percent(selected.metrics.first_pass_success_rate) }}</strong><small>{{ selected.metrics.first_pass_passed_cases }} / {{ selected.metrics.total_cases }}</small></article>
            <article><span>平均质量分</span><strong>{{ selected.metrics.average_score.toFixed(1) }}</strong><small>满分 100</small></article>
            <article><span>首轮质量分</span><strong>{{ selected.metrics.first_pass_average_score.toFixed(1) }}</strong><small>禁止返工快照</small></article>
            <article><span>浏览器通过</span><strong>{{ percent(selected.metrics.browser_pass_rate) }}</strong><small>真实点击验证</small></article>
            <article><span>功能覆盖</span><strong>{{ percent(selected.metrics.feature_coverage_rate) }}</strong><small>must-have 映射</small></article>
            <article><span>平均调用</span><strong>{{ selected.metrics.average_agent_calls.toFixed(1) }}</strong><small>每个 Demo</small></article>
            <article><span>平均耗时</span><strong>{{ selected.metrics.average_duration_seconds.toFixed(1) }}s</strong><small>端到端</small></article>
          </div>

          <div v-if="Object.keys(selected.metrics.complexity_breakdown || {}).length" class="complexity-grid">
            <article v-for="complexity in complexityOrder" v-show="selected.metrics.complexity_breakdown?.[complexity]" :key="complexity" :class="`complexity-${complexity}`">
              <div><span>{{ complexityLabel(complexity) }}</span><strong>{{ selected.metrics.complexity_breakdown?.[complexity]?.passed_cases }} / {{ selected.metrics.complexity_breakdown?.[complexity]?.total_cases }}</strong></div>
              <span>成功率 {{ percent(selected.metrics.complexity_breakdown?.[complexity]?.success_rate || 0) }}</span>
              <span>平均分 {{ selected.metrics.complexity_breakdown?.[complexity]?.average_score.toFixed(1) }}</span>
              <span>返工率 {{ percent(selected.metrics.complexity_breakdown?.[complexity]?.revision_rate || 0) }}</span>
            </article>
          </div>

          <div v-if="selected.gates.length" class="gate-row"><div v-for="gate in selected.gates" :key="gate.name" :class="{ passed: gate.passed }"><span>{{ gate.passed ? '✓' : '!' }}</span><strong>{{ gate.name }}</strong><small>{{ gate.actual }} {{ gate.operator }} {{ gate.threshold }}</small></div></div>

          <div v-if="selected.comparison.baseline_id" class="comparison-card"><div><span class="section-kicker">VERSION DELTA</span><strong>对比 {{ selected.comparison.baseline_id }}</strong></div><span>首轮成功率 {{ signed(selected.comparison.first_pass_success_rate_delta, 2) }}</span><span>首轮质量分 {{ signed(selected.comparison.first_pass_average_score_delta) }}</span><span>调用数 {{ signed(selected.comparison.average_agent_calls_delta) }}</span><span>耗时 {{ signed(selected.comparison.average_duration_seconds_delta) }}s</span></div>
          <div v-if="selected.skill_promotion.applicable" class="comparison-card"><div><span class="section-kicker">SKILL PROMOTION</span><strong>{{ selected.skill_promotion.eligible ? '候选 Skill 达到晋级门' : '候选 Skill 暂不接入' }}</strong></div><span>{{ selected.skill_promotion.reason }}</span><span>{{ selected.skill_promotion.reasons || [] }}</span></div>

          <div class="case-results"><div class="case-results-head"><strong>逐用例证据</strong><span>任务 ID 可回到 Agent Team 追踪</span></div><div v-for="result in selected.results" :key="result.case_id" class="case-result"><span class="case-dot" :class="`case-${result.status}`"></span><div><strong>{{ result.case_name }} <em v-if="result.complexity" class="complexity-badge" :class="`complexity-badge-${result.complexity}`">{{ complexityLabel(result.complexity) }}</em></strong><small>{{ result.case_id }} · {{ result.failure_category === 'none' ? result.source_mode : result.failure_category }}</small><p v-if="result.issues[0]">{{ result.issues[0] }}</p></div><div class="case-score"><strong>{{ result.status === 'pending' ? '—' : result.score }}</strong><small>{{ result.run_id || result.status }}</small></div></div></div>
        </template>
      </div>
    </div>

    <div v-if="evaluations.length" class="evaluation-history"><div class="section-heading compact"><div><span class="section-kicker">HISTORY</span><h3>评测版本</h3></div><span>{{ evaluations.length }} 次</span></div><div><button v-for="evaluation in evaluations.slice(0, 8)" :key="evaluation.id" type="button" :class="{ selected: selected?.id === evaluation.id }" @click="selectEvaluation(evaluation)"><span :class="`history-${evaluation.verdict}`"></span><div><strong>{{ evaluation.request.version_label }}</strong><small>{{ evaluation.request.provider }} · {{ complexityLabel(evaluation.request.complexity || 'all') }} · {{ evaluation.case_ids.length }} cases</small></div><em>{{ evaluation.status === 'completed' ? percent(evaluation.metrics.success_rate) : `${evaluation.progress}%` }}</em></button></div></div>
  </section>
</template>
