<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { SalesSession } from '../salesTypes'

const sessions = ref<SalesSession[]>([])
const selected = ref<SalesSession | null>(null)
const brief = ref('')
const answer = ref('')
const acknowledged = ref(false)
const followUp = ref(false)
const busy = ref(false)
const error = ref('')
const input = ref<HTMLTextAreaElement | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let polling = false
let requestKey = crypto.randomUUID()
const labels: Record<SalesSession['status'], string> = {
  analyzing: '理解需求中', needs_details: '等待补充', unsupported: '需要调整范围', ready: '等待确认',
  queued: '排队中', building: '构建与返工', testing: '浏览器检查中', published: '已验收发布',
  failed: '未发布', cancelled: '已取消', interrupted: '等待恢复',
}
const canAnswer = computed(() => selected.value && !selected.value.active && (['needs_details', 'unsupported', 'ready', 'failed'].includes(selected.value.status) || followUp.value))
const canRetry = computed(() => selected.value && ['failed', 'cancelled', 'interrupted'].includes(selected.value.status))

function accept(session: SalesSession) {
  selected.value = session
  sessions.value = [session, ...sessions.value.filter(item => item.id !== session.id)]
  localStorage.setItem('demopilot:sales-session', session.id)
}

async function operate(action: () => Promise<SalesSession>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { accept(await action()) } catch (exception) { error.value = exception instanceof Error ? exception.message : '请求失败，请重试' }
  finally { busy.value = false }
}

async function create() {
  if (brief.value.trim().length < 3) return
  await operate(async () => {
    const session = await api.createSalesSession(brief.value.trim(), requestKey)
    requestKey = crypto.randomUUID()
    return session
  })
}

async function reply() {
  if (!selected.value || !answer.value.trim()) return
  const id = selected.value.id
  const value = answer.value.trim()
  await operate(async () => {
    const session = await api.answerSalesSession(id, value)
    answer.value = ''
    followUp.value = false
    return session
  })
}

async function confirm() {
  if (!selected.value?.draft_hash || !acknowledged.value) return
  const { id, draft_hash } = selected.value
  await operate(() => api.confirmSalesSession(id, draft_hash))
}

async function refresh() {
  try {
    const items = await api.salesSessions()
    sessions.value = items
    const id = selected.value?.id ?? localStorage.getItem('demopilot:sales-session')
    const previous = items.find(item => item.id === id)
    if (previous) selected.value = previous
    error.value = ''
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '无法连接服务' }
}

async function poll() {
  if (!selected.value?.active || polling) return
  polling = true
  const id = selected.value.id
  try {
    const session = await api.salesSession(id)
    if (selected.value?.id === id) accept(session)
    error.value = ''
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '连接中断，任务记录仍保留' }
  finally { polling = false }
}

function startNew() {
  selected.value = null
  brief.value = ''
  answer.value = ''
  followUp.value = false
  acknowledged.value = false
  requestKey = crypto.randomUUID()
  localStorage.removeItem('demopilot:sales-session')
  void nextTick(() => input.value?.focus())
}

watch(() => selected.value?.draft_hash, () => { acknowledged.value = false })
onMounted(() => {
  void refresh()
  timer = setInterval(() => void poll(), 1500)
  window.addEventListener('demopilot:new-sales-demo', startNew)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('demopilot:new-sales-demo', startNew)
})
</script>

<template>
  <section id="sales-core" class="sales-workbench" aria-label="销售报价工作台">
    <div class="sc-heading">
      <div><span class="section-kicker">SALES → CORE BUILDER</span><h2>先说一句需求，剩下的在这里完成。</h2><p>问清报价规则，确认后生成。测试失败自动返工，通过后才能打开 Demo。</p></div>
      <button type="button" class="sc-secondary" @click="startNew">新建报价需求</button>
    </div>
    <div v-if="error" class="sc-error" role="alert">{{ error }} <button type="button" @click="refresh">重新连接</button></div>
    <div class="sc-layout">
      <div class="sc-conversation">
        <form v-if="!selected" class="sc-start" @submit.prevent="create">
          <label for="sales-brief">用一句话描述你要演示的报价功能</label>
          <textarea id="sales-brief" ref="input" v-model="brief" rows="5" maxlength="4000" placeholder="例如：客户买得多可以优惠，经理审批后让客户确认报价。" required />
          <p class="sc-note">当前支持报价与审批场景。缺少的价格、优惠和审批细节，意图助手会继续询问。</p>
          <button class="sc-primary" type="submit" :disabled="busy || brief.trim().length < 3">{{ busy ? '提交中…' : '让意图助手问清楚' }}</button>
        </form>
        <template v-else>
          <div class="sc-session-title"><h3>{{ selected.title }}</h3><span class="sc-badge" :class="{ accepted: selected.status === 'published' }">{{ labels[selected.status] }}</span></div>
          <div class="sc-messages" aria-label="需求问答">
            <article v-for="(message, index) in selected.messages" :key="index" class="sc-message" :class="message.role">
              <b>{{ message.role === 'user' ? '你的需求与补充' : '意图助手追问' }}</b><p>{{ message.content }}</p>
            </article>
          </div>
          <form v-if="canAnswer" class="sc-answer" @submit.prevent="reply">
            <label for="sales-answer">{{ selected.status === 'ready' ? '补充或修改规则（确认前可调整）' : '回答问题或补充需求' }}</label>
            <textarea id="sales-answer" v-model="answer" rows="4" maxlength="6000" placeholder="请说明演示商品和单价、优惠门槛，以及谁来审批。" required />
            <button type="submit" class="sc-primary" :disabled="busy || !answer.trim()">提交补充信息</button>
          </form>
          <p v-if="selected.active" class="sc-working" role="status"><span class="sc-pulse" />{{ selected.stage }}<small>可以刷新页面，已保存的进展不会丢失。</small></p>
        </template>
      </div>

      <div class="sc-delivery" aria-label="需求确认与交付">
        <template v-if="selected">
          <h3>从需求到交付</h3>
          <ol class="sc-steps"><li>理解与追问</li><li>确认业务规则</li><li>构建与测试返工</li><li :class="{ accepted: selected.status === 'published' }">通过后发布</li></ol>
          <div v-if="selected.draft && !selected.active && selected.status === 'ready'" class="sc-confirmation">
            <h4>请核对这次要实现的规则</h4>
            <ul><li v-for="line in selected.summary" :key="line">{{ line }}</li></ul>
            <div class="sc-examples"><b>按这些规则计算，预期结果为：</b><p v-for="example in selected.examples" :key="example.quantity">{{ example.label }} → <strong>{{ example.total }} 元</strong></p></div>
            <p class="sc-note">还会检查：越权操作、重复审批、修改后旧审批失效、不同报价记录互不影响。</p>
            <label class="sc-ack"><input v-model="acknowledged" type="checkbox" /><span>我确认上述规则和预期金额，开始构建与测试</span></label>
            <button type="button" class="sc-primary" :disabled="busy || !acknowledged" @click="confirm">确认规则并生成 Demo</button>
          </div>
          <div v-if="selected.revision && !['analyzing', 'needs_details', 'ready', 'unsupported'].includes(selected.status)" class="sc-build-status"><b>需求第 {{ selected.revision }} 版</b><span>第 {{ selected.iteration }} / {{ selected.call_cap }} 轮</span><p>{{ selected.stage }}</p></div>
          <div v-if="selected.checks && ['building', 'testing', 'published', 'failed'].includes(selected.status)" class="sc-checks" :class="{ accepted: selected.checks.status === 'passed' }"><b>浏览器业务检查：{{ selected.checks.passed }}/{{ selected.checks.planned }}</b><ul v-if="selected.checks.issues.length"><li v-for="issue in selected.checks.issues" :key="issue">{{ issue }}</li></ul></div>
          <div v-if="selected.status === 'published' && selected.demo_url" class="sc-published"><h4>已验收，发布到本机展示区</h4><a class="sc-primary" :href="api.artifactUrl(selected.demo_url)" target="_blank" rel="noopener noreferrer">打开已验收 Demo</a><button class="sc-secondary" type="button" @click="followUp = true">继续修改需求</button></div>
          <p v-else-if="selected.revision" class="sc-hidden">当前候选保持隐藏，通过检查后才会出现打开入口。</p>
          <p v-if="selected.error" class="sc-error" role="alert">{{ selected.error }}</p>
          <div class="sc-actions"><button v-if="selected.active" type="button" class="sc-secondary" :disabled="busy" @click="operate(() => api.cancelSalesSession(selected!.id))">取消当前任务</button><button v-if="canRetry" type="button" class="sc-primary" :disabled="busy" @click="operate(() => api.retrySalesSession(selected!.id))">{{ selected.status === 'interrupted' ? '恢复任务' : '重新尝试' }}</button></div>
          <details v-if="selected.events.length" class="sc-events" open><summary>过程记录（{{ selected.events.length }}）</summary><ol><li v-for="event in selected.events.slice(-16)" :key="event.sequence"><span>{{ new Date(event.time).toLocaleTimeString('zh-CN') }}</span>{{ event.message }}</li></ol></details>
          <details v-if="selected.versions.length" class="sc-events"><summary>历史已验收版本</summary><p v-for="version in selected.versions" :key="version.revision"><a :href="api.artifactUrl(version.url)" target="_blank" rel="noopener noreferrer">第 {{ version.revision }} 版 · {{ version.title }}</a></p></details>
        </template>
        <div v-else class="sc-explainer"><span>01 → 04</span><h3>把意图变成可验收的结果</h3><p>不必预先写完整 Prompt。回答必要问题，确认业务规则，再交给 Codex CLI 构建。</p><p>金额和审批由真实浏览器逐步检查；未通过会把具体问题送回 Core，最多三轮。</p><p>发布指本机演示展示，不连接客户生产系统。</p></div>
      </div>
    </div>
    <div v-if="sessions.length" class="sc-history"><div><h3>已保存的报价任务</h3><button class="sc-secondary" type="button" @click="refresh">刷新记录</button></div><button v-for="session in sessions.slice(0, 8)" :key="session.id" class="sc-history-item" type="button" @click="accept(session); followUp = false"><span>{{ session.title }}</span><b>{{ labels[session.status] }}</b></button></div>
  </section>
</template>

<style scoped>
.sales-workbench{margin:26px 0 34px;color:#172438}.sc-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:20px}.sc-heading h2{font-size:25px;letter-spacing:-.04em;margin:9px 0}.sc-heading p,.sc-note{color:#6d7685;font-size:13px;line-height:1.7}.sc-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}.sc-conversation,.sc-delivery{border:1px solid #e4e9f0;border-radius:22px;padding:26px;background:#fff;min-width:0;box-shadow:0 8px 32px #10274406}.sc-primary,.sc-secondary{display:inline-flex;align-items:center;justify-content:center;border-radius:11px;padding:11px 16px;font-size:13px;font-weight:650;cursor:pointer;text-decoration:none;border:1px solid transparent}.sc-primary{background:#1765dc;color:white}.sc-secondary{background:#f2f5fa;color:#355073;border-color:#e2e8f0}.sc-primary:disabled,.sc-secondary:disabled{opacity:.45;cursor:not-allowed}.sales-workbench label{font-size:13px;line-height:1.6;color:#30445f}.sales-workbench textarea{font-size:14px;padding:14px;line-height:1.7;background:#f8fafc;min-height:100px}.sc-start>.sc-primary,.sc-answer>.sc-primary{margin-top:12px}.sc-session-title{display:flex;gap:12px;align-items:start;justify-content:space-between}.sc-session-title h3{margin:0;font-size:18px;line-height:1.5}.sc-badge{padding:5px 9px;border-radius:20px;font-size:11px;background:#eef3fb;color:#526e93;white-space:nowrap}.sc-badge.accepted,.sc-checks.accepted{background:#eaf8ee;color:#19733d}.sc-messages{display:grid;gap:12px;margin:22px 0}.sc-message{padding:15px 17px;background:#f1f6fd;border-radius:15px}.sc-message.user{background:#f5f6f8}.sc-message b{font-size:11px;color:#60718a}.sc-message p{font-size:14px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0}.sc-delivery>h3{margin:0 0 18px;font-size:17px}.sc-steps{list-style:none;display:grid;grid-template-columns:repeat(4,1fr);padding:0;margin:0 0 22px;font-size:11px;gap:7px}.sc-steps li{padding:10px 7px;border-radius:8px;background:#f0f4fa;color:#547092;text-align:center}.sc-steps li.accepted{background:#eaf8ee;color:#19733d}.sc-confirmation h4,.sc-published h4{font-size:16px;margin:16px 0}.sc-confirmation ul{padding-left:20px;font-size:13px;line-height:1.9}.sc-examples{padding:15px;background:#f5f8fc;border-radius:12px;font-size:12px;line-height:1.7}.sc-examples p{margin:7px 0}.sc-ack{display:flex!important;gap:9px;align-items:flex-start;margin:18px 0!important}.sc-ack input{width:17px;height:17px;flex-shrink:0;margin-top:3px}.sc-working{font-size:14px;color:#45658e;line-height:1.8;padding:17px 0}.sc-working small{display:block;color:#8792a3;font-size:11px;margin-left:18px}.sc-pulse{display:inline-block;width:8px;height:8px;background:#2974de;border-radius:50%;margin-right:10px;animation:pulse 1.6s infinite}.sc-build-status{padding:16px;background:#f3f7fd;border-radius:12px;font-size:13px;line-height:1.7}.sc-build-status>span{float:right;color:#60718a}.sc-build-status p{margin:8px 0 0}.sc-checks{padding:14px;background:#fff4e7;border-radius:12px;font-size:12px;line-height:1.7;margin-top:12px;overflow-wrap:anywhere;max-height:260px;overflow:auto}.sc-checks ul{padding-left:18px}.sc-published{margin:18px 0}.sc-published .sc-secondary{margin-left:10px}.sc-hidden{font-size:12px;color:#7d8795;line-height:1.7}.sc-error{color:#a54038;background:#fff0ee;border-radius:12px;padding:13px 16px;line-height:1.7;font-size:13px;margin:14px 0}.sc-error button{background:none;border:0;color:inherit;text-decoration:underline;cursor:pointer}.sc-actions{display:flex;gap:10px;margin:15px 0}.sc-events{font-size:12px;line-height:1.7;color:#69798e;border-top:1px solid #edf0f4;padding-top:14px;margin-top:20px}.sc-events summary{cursor:pointer;font-weight:650}.sc-events ol{padding-left:18px;max-height:220px;overflow:auto}.sc-events li{margin:9px 0}.sc-events li span{display:block;font-size:10px;color:#9ba5b4}.sc-explainer>span{font-size:32px;font-weight:700;color:#b3c6e2}.sc-explainer h3{font-size:22px;margin:18px 0}.sc-explainer p{font-size:14px;color:#6b7c92;line-height:1.9}.sc-history{margin-top:20px;border:1px solid #e3e9f1;background:#fff;border-radius:18px;padding:20px}.sc-history>div{display:flex;justify-content:space-between;align-items:center}.sc-history h3{font-size:15px}.sc-history-item{display:flex;justify-content:space-between;gap:15px;width:100%;padding:13px 0;background:none;border:0;border-top:1px solid #edf1f6;cursor:pointer;text-align:left;font-size:13px;color:#36506f}.sc-history-item b{font-size:11px;white-space:nowrap}@keyframes pulse{50%{opacity:.3}}@media(max-width:1000px){.sc-layout{grid-template-columns:1fr}.sc-heading{align-items:flex-start}.sc-heading h2{font-size:21px}.sc-heading>.sc-secondary{flex-shrink:0}.sc-conversation,.sc-delivery{padding:20px}}@media(prefers-reduced-motion:reduce){.sc-pulse{animation:none}}
</style>
