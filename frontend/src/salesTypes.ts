export interface SalesSession {
  id: string
  title: string
  status: 'analyzing' | 'needs_details' | 'unsupported' | 'ready' | 'queued' | 'building' | 'testing' | 'published' | 'failed' | 'cancelled' | 'interrupted'
  stage: string
  revision: number
  messages: { role: 'user' | 'assistant'; content: string }[]
  questions: string[]
  draft: Record<string, unknown> | null
  draft_hash: string | null
  summary: string[]
  examples: { label: string; total: string; quantity: number }[]
  source_quotes?: string[]
  events: { sequence: number; kind: string; message: string; time: string; issues?: string[] }[]
  versions: { revision: number; artifact: string; url: string; title: string; published_at: string }[]
  demo_url: string | null
  iteration: number
  checks: { status: string; passed: number; planned: number; issues: string[] } | null
  error: string | null
  active: boolean
  call_cap: number
  connection?: { state: string; message: string; reason: string; retry_required: boolean; consecutive_failures: number }
  updated_at: string
}
