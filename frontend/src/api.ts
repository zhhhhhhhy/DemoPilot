import type { DemoRequest, DemoRun, DemoTemplate, EvaluationCase, EvaluationRequest, EvaluationRun } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(payload.detail ?? '请求失败')
  }
  return response.json() as Promise<T>
}

export const api = {
  listRuns: () => request<DemoRun[]>('/api/runs'),
  getRun: (id: string) => request<DemoRun>(`/api/runs/${id}`),
  createRun: (payload: DemoRequest) =>
    request<DemoRun>('/api/runs', { method: 'POST', body: JSON.stringify(payload) }),
  decideApproval: (runId: string, approvalId: string, decision: 'approve' | 'decline') =>
    request<DemoRun>(`/api/runs/${runId}/approvals/${approvalId}`, {
      method: 'POST', body: JSON.stringify({ decision }),
    }),
  cancelRun: (id: string) => request<DemoRun>(`/api/runs/${id}/cancel`, { method: 'POST' }),
  resumeRun: (id: string) => request<DemoRun>(`/api/runs/${id}/resume`, { method: 'POST' }),
  templates: () => request<DemoTemplate[]>('/api/templates'),
  evaluationCases: () => request<EvaluationCase[]>('/api/evaluation-cases'),
  listEvaluations: () => request<EvaluationRun[]>('/api/evaluations'),
  getEvaluation: (id: string) => request<EvaluationRun>(`/api/evaluations/${id}`),
  createEvaluation: (payload: EvaluationRequest) =>
    request<EvaluationRun>('/api/evaluations', { method: 'POST', body: JSON.stringify(payload) }),
  cancelEvaluation: (id: string) =>
    request<EvaluationRun>(`/api/evaluations/${id}/cancel`, { method: 'POST' }),
  evaluationEventsUrl: (id: string) => `${API_BASE}/api/evaluations/${id}/events`,
  evaluationReportUrl: (id: string) => `${API_BASE}/api/evaluations/${id}/report`,
  runEventsUrl: (id: string) => `${API_BASE}/api/runs/${id}/events`,
  artifactUrl: (path: string) => `${API_BASE}${path}`,
}
