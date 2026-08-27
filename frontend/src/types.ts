export type RunStatus = 'queued' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled'
export type AgentStatus = 'waiting' | 'running' | 'completed' | 'failed' | 'cancelled'
export type ProviderName = 'mock' | 'claude' | 'deepseek' | 'aihubmix' | 'zju'

export interface DemoRequest {
  client_name: string
  project_name: string
  industry: string
  scenario: string
  audience: string
  must_haves: string[]
  brand_tone: string
  primary_color: string
  provider: ProviderName
  require_execution_approval: boolean
}

export interface AgentEvent {
  id: string
  agent_id: string
  role: string
  status: AgentStatus
  message: string
  iteration: number
  created_at: string
  event_type: 'agent' | 'lifecycle' | 'approval' | 'hook' | 'gate'
  sequence: number
  payload: Record<string, unknown>
}

export interface ToolReceipt {
  id: string
  tool_name: string
  action: string
  agent_id: string
  status: 'succeeded' | 'failed'
  input_summary: string
  output_summary: string
  relative_paths: string[]
  sha256: Record<string, string>
  duration_ms: number
  created_at: string
}

export interface ApprovalRequest {
  id: string
  action: string
  reason: string
  risk: 'low' | 'medium' | 'high'
  requested_by: string
  status: 'pending' | 'approved' | 'declined' | 'auto_approved'
  created_at: string
  resolved_at: string | null
}

export interface Artifact {
  name: string
  kind: 'demo' | 'spec' | 'script' | 'qa' | 'archive' | 'evidence'
  relative_path: string
  download_url: string
}

export interface DemoRun {
  id: string
  status: RunStatus
  progress: number
  current_agent: string | null
  request: DemoRequest
  events: AgentEvent[]
  tool_receipts: ToolReceipt[]
  approvals: ApprovalRequest[]
  outputs: Record<string, Record<string, unknown>>
  artifacts: Artifact[]
  agent_calls: number
  revision_count: number
  quality_gate: 'pending' | 'passed' | 'passed_with_open_gates' | 'failed'
  error: string | null
  checkpoint: string | null
  cancel_requested: boolean
  resume_count: number
  last_event_sequence: number
  created_at: string
  updated_at: string
}

export interface DemoTemplate {
  id: string
  name: string
  industry: string
  scenario: string
  must_haves: string[]
}

export interface EvaluationCase {
  id: string
  name: string
  industry: string
  scenario: string
  audience: string
  must_haves: string[]
  brand_tone: string
  primary_color: string
  difficulty: 'basic' | 'standard' | 'edge'
  tags: string[]
}

export interface EvaluationThresholds {
  min_success_rate: number
  min_average_score: number
  min_browser_pass_rate: number
  min_feature_coverage_rate: number
  max_average_agent_calls: number
}

export interface EvaluationRequest {
  provider: ProviderName
  case_ids: string[]
  case_limit: number
  concurrency: number
  version_label: string
  baseline_id: string | null
  skill_profile: 'baseline' | 'candidate' | 'approved'
  first_pass_only: boolean
  builder_preflight_enabled: boolean
  thresholds: EvaluationThresholds
}

export interface EvaluationCaseResult {
  case_id: string
  case_name: string
  run_id: string | null
  status: 'pending' | 'running' | 'passed' | 'failed' | 'cancelled'
  passed: boolean
  score: number
  failure_category: string
  issues: string[]
  source_mode: string
  artifact_status: string
  browser_status: string
  security_status: string
  quality_gate: string
  feature_coverage: number
  agent_calls: number
  revision_count: number
  first_pass_passed: boolean
  first_pass_score: number
  first_pass_browser_status: string
  duration_seconds: number
  started_at: string | null
  completed_at: string | null
}

export interface EvaluationMetrics {
  total_cases: number
  completed_cases: number
  passed_cases: number
  first_pass_passed_cases: number
  success_rate: number
  first_pass_success_rate: number
  average_score: number
  first_pass_average_score: number
  browser_pass_rate: number
  feature_coverage_rate: number
  artifact_pass_rate: number
  fallback_rate: number
  revision_rate: number
  average_agent_calls: number
  average_duration_seconds: number
  failure_categories: Record<string, number>
}

export interface AcceptanceGate {
  name: string
  actual: number
  operator: '>=' | '<='
  threshold: number
  passed: boolean
}

export interface EvaluationRun {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  request: EvaluationRequest
  case_ids: string[]
  results: EvaluationCaseResult[]
  metrics: EvaluationMetrics
  gates: AcceptanceGate[]
  verdict: 'pending' | 'passed' | 'failed'
  comparison: Record<string, number | string | null>
  skill_promotion: Record<string, boolean | number | string | string[]>
  active_run_ids: string[]
  cancel_requested: boolean
  error: string | null
  report_url: string | null
  created_at: string
  updated_at: string
}
