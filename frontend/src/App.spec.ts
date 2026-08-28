import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.vue'
import type { DemoRun } from './types'

const mocks = vi.hoisted(() => ({
  listRuns: vi.fn(),
  templates: vi.fn(),
  createRun: vi.fn(),
  resumeRun: vi.fn(),
  getRun: vi.fn(),
  decideApproval: vi.fn(),
  cancelRun: vi.fn(),
  evaluationCases: vi.fn(),
  listEvaluations: vi.fn(),
  getEvaluation: vi.fn(),
  createEvaluation: vi.fn(),
  cancelEvaluation: vi.fn(),
}))

vi.mock('./api', () => ({
  api: {
    ...mocks,
    runEventsUrl: (id: string) => `/api/runs/${id}/events`,
    evaluationEventsUrl: (id: string) => `/api/evaluations/${id}/events`,
    evaluationReportUrl: (id: string) => `/api/evaluations/${id}/report`,
    artifactUrl: (path: string) => path,
  },
}))

function makeRun(overrides: Partial<DemoRun> = {}): DemoRun {
  return {
    id: 'run-1',
    status: 'completed',
    progress: 100,
    current_agent: null,
    request: {
      client_name: '复杂客户',
      project_name: '复杂协同 Demo',
      industry: '冷链物流',
      scenario: '需要识别异常、比较处置方案并追踪状态。',
      audience: '区域运营负责人',
      must_haves: ['异常筛选', '方案比较', '状态追踪'],
      brand_tone: '克制、清晰',
      primary_color: '#0071e3',
      provider: 'deepseek',
      require_execution_approval: false,
    },
    events: [],
    tool_receipts: [],
    approvals: [],
    outputs: {
      reviewer: {
        status: 'reviewed',
        decision: 'pass_with_open_gates',
        overall_score: 92,
        confidence: 0.9,
        dimension_scores: { demo_clarity: 12 },
        requirement_coverage: [],
        issues: [],
        real_features: ['导航高亮切换'],
        simulated_features: ['异常筛选'],
        scope_boundaries: [],
        open_gates: ['真实 ERP/WMS 系统集成', '生产鉴权与部署'],
        evidence: { source_mode: 'agent_generated_files', browser_status: 'passed' },
      },
    },
    artifacts: [],
    agent_calls: 8,
    revision_count: 0,
    quality_gate: 'passed',
    error: null,
    checkpoint: 'completed',
    cancel_requested: false,
    resume_count: 0,
    last_event_sequence: 0,
    created_at: '2026-08-26T00:00:00Z',
    updated_at: '2026-08-26T00:05:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listRuns.mockResolvedValue([])
  mocks.templates.mockResolvedValue([])
  mocks.evaluationCases.mockResolvedValue([])
  mocks.listEvaluations.mockResolvedValue([])
})

describe('DemoPilot control plane', () => {
  it('offers all 30 cases for Mock while preserving the three-case real-provider cap', async () => {
    const wrapper = mount(App)
    await flushPromises()

    const evaluation = wrapper.get('.evaluation-config')
    expect(evaluation.text()).toContain('30 个用例')
    expect(evaluation.text()).toContain('简单要求 · 单页核心流程')
    expect(evaluation.text()).toContain('复杂要求 · 多步骤联动')

    await evaluation.findAll('select')[0].setValue('deepseek')
    await flushPromises()
    expect(evaluation.text()).toContain('最多 3 条')
    expect(evaluation.text()).not.toContain('30 个用例')
    wrapper.unmount()
  })

  it('creates a DeepSeek run from the brief form', async () => {
    const created = makeRun({ status: 'queued', progress: 0, checkpoint: null })
    mocks.createRun.mockResolvedValue(created)
    const wrapper = mount(App)
    await flushPromises()

    await wrapper.get('form.brief-card').trigger('submit')
    await flushPromises()

    expect(mocks.createRun).toHaveBeenCalledOnce()
    expect(mocks.createRun.mock.calls[0][0].provider).toBe('deepseek')
    expect(wrapper.text()).toContain('复杂协同 Demo')
    wrapper.unmount()
  })

  it('resumes a failed run from its checkpoint', async () => {
    const failed = makeRun({
      status: 'failed',
      progress: 80,
      quality_gate: 'failed',
      checkpoint: 'artifacts:iteration:0',
      error: 'Reviewer 返回为空',
    })
    const resumed = makeRun({ status: 'queued', progress: 80, checkpoint: 'resume:artifacts:iteration:0' })
    mocks.listRuns.mockResolvedValue([failed])
    mocks.resumeRun.mockResolvedValue(resumed)
    const wrapper = mount(App)
    await flushPromises()

    await wrapper.get('.delivery-actions button').trigger('click')
    await flushPromises()

    expect(mocks.resumeRun).toHaveBeenCalledWith('run-1')
    expect(wrapper.text()).toContain('排队中')
    wrapper.unmount()
  })

  it('shows simulation as completed scope instead of an open gate', async () => {
    mocks.listRuns.mockResolvedValue([makeRun()])
    const wrapper = mount(App)
    await flushPromises()

    expect(wrapper.text()).toContain('既定演示边界')
    expect(wrapper.text()).toContain('业务数据使用本地虚构样例')
    expect(wrapper.text()).not.toContain('真正未解决项')
    expect(wrapper.get('.reviewer-verdict span').text()).toBe('通过')
    wrapper.unmount()
  })
})
