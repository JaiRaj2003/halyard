/** Typed access to the Halyard API. Every shape here mirrors a server serializer. */

export interface RequestSummary {
  id: number
  request_id: string
  origin: string
  requester: string
  operational_owner: string
  operational_owner_id: number
  operational_owner_source: string
  observed_owner: string | null
  was_ownerless_at_ingest: boolean
  account: string
  account_id: number | null
  target: string
  target_title: string
  target_resolution_status: string
  workflow_state: string
  route_status: string
  outcome: string
  next_action: string
  next_action_due_at: string | null
  is_overdue: boolean
  requested_at: string | null
  last_activity_at: string | null
  age_days: number
  days_since_activity: number
  potentially_stale: boolean
  selected_connector: string | null
  raw_ask: string
  state_evidence: string
  deal_value_usd: number
  urgency: string
  related_count?: number
  due_soon?: boolean
}

export interface Candidate {
  id: number
  label: string
  detail: string
  method: string
  confidence: string
  account?: AccountSummary
}

export interface Factor {
  key: string
  label: string
  present: boolean
  detail: string
  direction: string
}

export interface ConnectorSummary {
  id: number | null
  name: string
  on_roster: boolean
  stated_monthly_capacity: number | null
  recent_asks_30d?: number
  over_capacity?: boolean
  note?: string
}

export interface CandidatePath {
  id: number
  rank: number
  recommended: boolean
  recommendation_label: string
  factors: Factor[]
  connector: ConnectorSummary
  hop_type: string
  observability: string
  connector_reachable: boolean
  same_title_family: boolean
  relationship_date: string | null
  confidence: string
  limitations: string
  evidence: string
  source_file: string
  review_status?: string
  review_note?: string
}

export interface PathPayload {
  request_id: string
  disclaimer: string
  ordering: string
  counts: Record<string, number>
  paths: CandidatePath[]
}

export interface RelatedRequest {
  relation_type: string
  detail: string
  days_apart: number | null
  within_window: boolean
  same_requester?: boolean
  request: RequestSummary
}

export interface TimelineEvent {
  occurred_at: string | null
  recorded_at: string | null
  event_type: string
  detail: string
  actor: string
  asserted_by: string
  is_state_evidence: boolean
}

export interface TargetDetail {
  raw_target_text: string
  raw_target_name: string
  raw_target_title: string
  normalized_title_family: string
  raw_account_text: string
  account: AccountSummary | null
  resolved_person: { id: number; display_name: string; title: string } | null
  resolution_status: string
  resolution_method: string
  resolution_confidence: string
  resolution_evidence: string
  candidate_matches: string[]
}

export interface AccountSummary {
  id: number
  name: string
  crm_account_id: string
  domain: string
  domain_group: string
  is_crm_account: boolean
  review_status: string
  match_evidence: string
  competing_candidates: string[]
}

export interface RecordedOutcome {
  connector: string
  asked_date: string | null
  responded: boolean | null
  intro_sent: boolean | null
  meeting_booked: boolean | null
  opportunity_created: boolean | null
  opportunity_value_usd: number | null
}

export interface RequestDetail extends RequestSummary {
  target_detail: TargetDetail | null
  recorded_outcome: RecordedOutcome | null
  operationalized_at: string | null
  closure_reason: string
  events: TimelineEvent[]
}

export interface ParseResult {
  grammar: string
  confidence: string
  evidence: string
  warnings: string[]
  proposed: {
    account_text: string
    person_name: string
    title: string
    normalized_title_family: string
    domains: string[]
  }
}

export interface NextDecision {
  decision: string
  prompt: string
  blocking: boolean
}

export interface IntakeResult {
  request: RequestDetail
  parse: ParseResult
  account_candidates: Candidate[]
  person_candidates: Candidate[]
  account_activity: RelatedRequest[]
  account_activity_note: string
  paths: PathPayload
  next_decision: NextDecision
}

export interface QueueView {
  key: string
  label: string
  definition: string
}

export interface QueuePayload {
  view: QueueView
  counts: Record<string, number>
  total: number
  limit: number
  offset: number
  items: RequestSummary[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : response.statusText
    throw new ApiError(response.status, detail)
  }
  return body as T
}

export interface IntakeSubmission {
  raw_ask: string
  requester_name: string
  account_text?: string
  target_person_name?: string
  target_title?: string
  deal_value_usd?: number
  urgency?: string
}

export const api = {
  startIntake: (body: IntakeSubmission) =>
    request<IntakeResult>('/api/intake/start', { method: 'POST', body: JSON.stringify(body) }),

  intake: (key: string) => request<IntakeResult>(`/api/intake/${encodeURIComponent(key)}`),

  confirmTarget: (key: string, body: { account_id?: number | null; person_id?: number | null; target_title?: string; note?: string }) =>
    request<IntakeResult>(`/api/requests/${encodeURIComponent(key)}/target`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  reviewRoute: (key: string, body: { path_id: number; decision: 'confirm' | 'reject'; note?: string }) =>
    request<IntakeResult>(`/api/requests/${encodeURIComponent(key)}/route`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  queue: (view: string, params: Record<string, string> = {}) =>
    request<QueuePayload>(`/api/queue?${new URLSearchParams({ view, limit: '100', ...params })}`),

  queueViews: () => request<{ views: QueueView[] }>('/api/queue/views'),

  requestDetail: (key: string) => request<RequestDetail>(`/api/requests/${encodeURIComponent(key)}`),

  transition: (key: string, body: { to_state: string; note?: string; outcome?: string }) =>
    request<RequestDetail>(`/api/requests/${encodeURIComponent(key)}/transition`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
