/** Minimal API-shaped fixtures for presenter tests. Every field mirrors what
 *  the server serialises; tests override only what they exercise. */

import { AccountView, CandidatePath, LeadershipMetric, RequestSummary } from '../lib/api'

export function request(overrides: Partial<RequestSummary> = {}): RequestSummary {
  return {
    id: 1,
    request_id: 'R1001',
    origin: 'historical_corpus',
    requester: 'Ana Ruiz',
    operational_owner: 'Ana Ruiz',
    operational_owner_id: 7,
    operational_owner_source: 'observed_owner',
    observed_owner: 'Ana Ruiz',
    was_ownerless_at_ingest: false,
    account: 'Vantage Ridge Utilities',
    account_id: 12,
    target: '',
    target_title: 'Chief Operating Officer',
    target_resolution_status: 'persona',
    workflow_state: 'NEEDS_TRIAGE',
    route_status: 'none',
    outcome: 'unknown',
    next_action: 'Review imported request',
    next_action_due_at: '2026-08-15T00:00:00Z',
    is_overdue: false,
    requested_at: '2026-06-01T00:00:00Z',
    last_activity_at: '2026-06-01T00:00:00Z',
    age_days: 90,
    days_since_activity: 90,
    potentially_stale: true,
    selected_connector: null,
    raw_ask: 'Can someone introduce us to the COO at Vantage Ridge?',
    state_evidence: '',
    deal_value_usd: 0,
    urgency: '',
    next_action_source: 'ingest_operationalization',
    sla_managed: false,
    sla_breached: false,
    legacy_backlog: true,
    days_quiet_before_import: 70,
    route_signal: 'none',
    suggested_route_person: '',
    suggested_route_evidence: '',
    ...overrides,
  }
}

export function path(overrides: Partial<CandidatePath> = {}): CandidatePath {
  return {
    id: 1,
    rank: 1,
    recommended: false,
    recommendation_label: '',
    factors: [],
    connector: { id: 3, name: 'Priya Natarajan', on_roster: true, stated_monthly_capacity: 4 },
    contact: null,
    hop_type: 'colleague_at_account',
    observability: 'snapshot_only',
    connector_reachable: true,
    same_title_family: false,
    relationship_date: null,
    confidence: 'medium',
    limitations: '',
    evidence: '',
    source_file: 'connections_priya.csv',
    ...overrides,
  }
}

export function metric(overrides: Partial<LeadershipMetric> = {}): LeadershipMetric {
  return {
    key: 'in_flight',
    label: 'In flight',
    value: 0,
    denominator: 0,
    definition: '',
    window: '',
    drill_down_view: null,
    group: 'current_workflow',
    ...overrides,
  }
}

export function account(overrides: Partial<AccountView> = {}): AccountView {
  return {
    id: 12,
    name: 'Vantage Ridge Utilities',
    crm_account_id: 'A1001',
    domain: 'vantageridge.com',
    domain_group: '',
    is_crm_account: true,
    review_status: 'resolved',
    match_evidence: '',
    competing_candidates: [],
    industry: '',
    hq: '',
    employee_count: null,
    stage: '',
    arr_potential_usd: null,
    crm_owner: '',
    shares_domain_with: [],
    known_people: [],
    known_people_count: 0,
    relationship_edge_count: 0,
    request_count: 0,
    active_requests: [],
    settled_requests: [],
    coverage: { note: '', connector_count: 0, edge_count: 0, has_historically_observable_path: false, connectors: [] },
    prior_observed_introductions: [],
    data_quality_issues: [],
    coverage_gaps: [],
    ...overrides,
  }
}
