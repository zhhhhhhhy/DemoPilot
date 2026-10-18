import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SalesWorkbench from './SalesWorkbench.vue'
import type { SalesSession } from '../salesTypes'

const mocks = vi.hoisted(() => ({ salesSessions: vi.fn(), salesSession: vi.fn(), createSalesSession: vi.fn(), answerSalesSession: vi.fn(), confirmSalesSession: vi.fn(), cancelSalesSession: vi.fn(), retrySalesSession: vi.fn() }))
vi.mock('../api', () => ({ api: { ...mocks, artifactUrl: (value: string) => value } }))

function session(overrides: Partial<SalesSession> = {}): SalesSession {
  return { id: 'a'.repeat(16), title: '报价测试', status: 'needs_details', stage: '请补充', revision: 0,
    messages: [{ role: 'assistant', content: '商品价格和优惠门槛是什么？' }], questions: ['商品价格和优惠门槛是什么？'],
    draft: null, draft_hash: null, summary: [], examples: [], events: [], versions: [], demo_url: null,
    iteration: 0, checks: null, error: null, active: false, call_cap: 3, updated_at: '2026-10-18T00:00:00Z', ...overrides }
}

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); vi.useFakeTimers(); mocks.salesSessions.mockResolvedValue([]) })
afterEach(() => { vi.useRealTimers() })

describe('Sales quotation workflow', () => {
  it('requires answers and explicit confirmation before building and only shows an accepted release', async () => {
    const needs = session()
    const ready = session({ status: 'ready', draft: { title: '报价' }, draft_hash: 'b'.repeat(64), summary: ['A 单价120元，满3件优惠10%'], examples: [{ label: '5件A', quantity: 5, total: '540.00' }] })
    const building = session({ ...ready, status: 'building', active: true, revision: 1, iteration: 1 })
    mocks.createSalesSession.mockResolvedValue(needs)
    mocks.answerSalesSession.mockResolvedValue(ready)
    mocks.confirmSalesSession.mockResolvedValue(building)
    const wrapper = mount(SalesWorkbench)
    await flushPromises()
    await wrapper.get('#sales-brief').setValue('做一个数量优惠报价')
    await wrapper.get('form.sc-start').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('商品价格和优惠门槛是什么？')
    expect(mocks.confirmSalesSession).not.toHaveBeenCalled()
    expect(wrapper.find('a.sc-primary').exists()).toBe(false)
    await wrapper.get('#sales-answer').setValue('A120，满3件优惠10%，经理审批')
    await wrapper.get('form.sc-answer').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.sc-confirmation button').attributes('disabled')).toBeDefined()
    await wrapper.get('.sc-ack input').setValue(true)
    await wrapper.get('.sc-confirmation button').trigger('click')
    await flushPromises()
    expect(mocks.confirmSalesSession).toHaveBeenCalledWith(needs.id, ready.draft_hash)
    expect(wrapper.find('a.sc-primary').exists()).toBe(false)
    mocks.salesSession.mockResolvedValue(session({ ...building, status: 'published', active: false, demo_url: '/api/sales-core/accepted/verified/index.html', checks: { status: 'passed', passed: 6, planned: 6, issues: [] } }))
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.get('a.sc-primary').attributes('href')).toContain('/accepted/verified/')
    expect(wrapper.text()).toContain('6/6')
    wrapper.unmount()
  })

  it('restores a persisted interrupted task and offers recovery without exposing candidates', async () => {
    const previous = session({ status: 'interrupted', revision: 1, error: '服务曾中断' })
    localStorage.setItem('demopilot:sales-session', previous.id)
    mocks.salesSessions.mockResolvedValue([previous])
    mocks.retrySalesSession.mockResolvedValue(session({ status: 'queued', revision: 2, active: true }))
    const wrapper = mount(SalesWorkbench)
    await flushPromises()
    expect(wrapper.text()).toContain('服务曾中断')
    expect(wrapper.find('a.sc-primary').exists()).toBe(false)
    const recover = wrapper.findAll('button').find(button => button.text() === '恢复任务')!
    await recover.trigger('click')
    await flushPromises()
    expect(mocks.retrySalesSession).toHaveBeenCalledWith(previous.id)
    expect(wrapper.text()).toContain('需求第 2 版')
    wrapper.unmount()
  })

  it('does not present the previous version check as acceptance of a new draft', async () => {
    const next = session({ status: 'ready', revision: 1, draft: { title: '新单价' }, draft_hash: 'c'.repeat(64),
      summary: ['A 单价150元'], checks: { status: 'passed', passed: 6, planned: 6, issues: [] } })
    localStorage.setItem('demopilot:sales-session', next.id)
    mocks.salesSessions.mockResolvedValue([next])
    const wrapper = mount(SalesWorkbench)
    await flushPromises()
    expect(wrapper.text()).toContain('A 单价150元')
    expect(wrapper.find('.sc-checks').exists()).toBe(false)
    expect(wrapper.find('a.sc-primary').exists()).toBe(false)
    wrapper.unmount()
  })
})
