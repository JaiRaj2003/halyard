/** The single place operator-facing words live.
 *
 *  The API speaks in stable internal identifiers (`NEEDS_ENTITY_REVIEW`,
 *  `snapshot_only`, `connections_aldridge.csv`). Screens never render those:
 *  they ask `label(kind, value)` and get the operator's phrase. Changing a
 *  word means changing it here, once. An identifier this table does not know
 *  is spelt out plainly rather than leaking, so a new backend value can never
 *  appear on screen in SNAKE_CASE.
 *
 *  Mapping changes words, not meaning. Every uncertain phrase here stays
 *  uncertain, and no phrase promises access the evidence cannot support.
 */

export type Vocabulary =
  | 'state'
  | 'route_status'
  | 'outcome'
  | 'route_signal'
  | 'observability'
  | 'hop'
  | 'confidence'
  | 'resolution'
  | 'owner_source'
  | 'relationship'
  | 'origin'
  | 'event'
  | 'match_method'
  | 'issue'
  | 'view'
  | 'action_source'
  | 'relation'

const WORDS: Record<Vocabulary, Record<string, string>> = {
  state: {
    NEEDS_TRIAGE: 'Needs triage',
    NEEDS_ENTITY_REVIEW: 'Needs target confirmation',
    PATH_REVIEW: 'Needs route review',
    AWAITING_CONNECTOR: 'Waiting on connector',
    INTRO_SENT: 'Introduction sent',
    COMPLETED: 'Completed',
    NO_OBSERVABLE_PATH: 'No corroborated route yet',
    BLOCKED: 'Blocked',
    CLOSED: 'Closed',
  },
  route_status: {
    NONE: 'No route chosen',
    PROPOSED: 'Route proposed',
    CONFIRMED: 'Route confirmed',
    REJECTED: 'Route ruled out',
  },
  outcome: {
    UNKNOWN: 'Not recorded',
    INTRO_SENT: 'Introduction sent',
    MEETING_BOOKED: 'Meeting booked',
    OPPORTUNITY_CREATED: 'Opportunity created',
    DECLINED: 'Declined',
    NO_RESPONSE: 'No response',
  },
  route_signal: {
    corroborated_path: 'Route evidence in the network',
    unverified_suggested_route: 'Unverified route suggested',
    none: 'No route signal',
  },
  observability: {
    historically_observable: 'Connection existed before this request',
    snapshot_only: 'Current network signal · historical timing unknown',
    post_dates_request: 'Connection appeared after this request',
  },
  hop: {
    direct_target_person: 'Knows the requested person directly',
    colleague_at_target_account: 'Knows a colleague at the target account',
    investor_relationship_to_account: 'Investor or board relationship to the account',
  },
  confidence: {
    high: 'High confidence',
    medium: 'Medium confidence',
    low: 'Low confidence',
    none: 'No evidence',
  },
  resolution: {
    resolved: 'Confirmed',
    ambiguous: 'Ambiguous · needs confirmation',
    unresolved: 'Not identified',
    unmatched: 'No match in the data',
    persona_only: 'Role given, not a named person',
    needs_review: 'Needs confirmation',
  },
  owner_source: {
    observed_owner: 'Owner named in the source data',
    fallback_requester: 'Requester holds ownership until confirmed',
    configured_triage_owner: 'Configured triage owner',
    explicit_intake: 'Named at intake',
    manual_assignment: 'Confirmed by an operator',
  },
  action_source: {
    ingest_operationalization: 'Review target set when backlog was imported',
    live_intake: 'Assigned at intake',
    operator: 'Assigned by an operator',
  },
  relation: {
    same_canonical_account: 'Same account',
    same_account_same_title_family: 'Same account, same kind of role',
    same_account_same_target_person: 'Same account, same person',
    explicit_reask: 'Explicitly re-asked',
  },
  relationship: {
    connection_export: 'Executive network',
    investor_portfolio: 'Investor/advisor network',
    slack_mention: 'Slack thread',
    crm: 'CRM record',
  },
  origin: {
    historical_corpus: 'Imported backlog',
    live_intake: 'Live request',
  },
  event: {
    created: 'Request created',
    request_created: 'Request created',
    enrichment_failed: 'Analysis failed · request kept',
    imported: 'Imported from the historical corpus',
    operationalized: 'Brought under Halyard',
    owner_assigned: 'Owner assigned',
    owner_changed: 'Owner changed',
    state_changed: 'State changed',
    target_confirmed: 'Target confirmed',
    route_confirmed: 'Route selected for validation',
    route_rejected: 'Route ruled out',
    connector_asked: 'Connector asked',
    connector_responded: 'Connector responded',
    intro_sent: 'Introduction sent',
    meeting_booked: 'Meeting booked',
    opportunity_created: 'Opportunity created',
    note: 'Note',
    'slack:bump': 'Follow-up nudge in Slack',
    'slack:blocker_note': 'Blocker raised in Slack',
    'slack:entity_warning': 'Identity doubt raised in Slack',
    'slack:no_knowledge': 'No route known, per Slack',
    'slack:possible_duplicate_query': 'Possible duplicate queried in Slack',
    'slack:qualification_question': 'Qualification question in Slack',
    'slack:referral_suggestion': 'Route suggested in Slack',
    'slack:routing_challenge': 'Routing challenged in Slack',
    'slack:volunteer_offer': 'Route volunteered in Slack',
    'slack:unclassified': 'Slack message',
    'derived:referral_suggestion': 'Route suggestion recorded from Slack',
    'derived:additional_ask_like_message': 'Further ask recorded from Slack',
  },
  match_method: {
    exact_name: 'Exact name match',
    alias: 'Known alias',
    domain: 'Matched by domain',
    fuzzy: 'Approximate match',
    persona: 'Role matched, no named person',
    no_candidate: 'No candidate in the data',
    exact: 'Exact match',
    unique_surname: 'Only person with this surname at the account',
  },
  issue: {
    high: 'Needs a decision',
    medium: 'Worth checking',
    low: 'For the record',
  },
  view: {
    needs_attention: 'Needs attention',
    in_flight: 'In flight',
    needs_triage: 'Needs triage',
    needs_entity_review: 'Needs target confirmation',
    path_review: 'Needs route review',
    needs_ownership_review: 'Owner to confirm',
    awaiting_connector: 'Waiting on connector',
    unverified_route: 'Unverified route',
    no_observable_path: 'No corroborated route yet',
    stale: 'Quiet under Halyard',
    overlapping: 'Account overlaps',
    due_soon: 'Due soon',
    overdue: 'Overdue',
    completed: 'Completed',
    outcome_unknown: 'Outcome not recorded',
    legacy_backlog: 'Imported backlog',
    legacy_backlog_quiet: 'No recent historical activity',
    legacy_backlog_remediation: 'Imported review target passed',
    all: 'All requests',
  },
}

/** Plain-English fallback for an identifier the table has not met. */
function humanize(value: string): string {
  const words = value.replaceAll(/[_:-]+/g, ' ').trim().toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : ''
}

export function label(kind: Vocabulary, value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  return WORDS[kind][value] ?? humanize(value)
}

/** Timeline event types, including the `transition:FROM->TO` family. */
export function eventLabel(eventType: string | null | undefined): string {
  if (!eventType) return ''
  const transition = /^transition:([A-Z_]+)->([A-Z_]+)$/.exec(eventType)
  if (transition) return `${label('state', transition[1])} → ${label('state', transition[2])}`
  return label('event', eventType)
}

const DETAIL_TOKENS: Record<string, string> = {
  fallback_requester: 'the requester, as fallback',
  observed_owner: 'an owner named in the source data',
  configured_triage_owner: 'the configured triage owner',
  explicit_intake: 'the name given at intake',
  manual_assignment: 'operator assignment',
  ...Object.fromEntries(Object.keys(WORDS.state).map((key) => [key, label('state', key).toLowerCase()])),
  ...Object.fromEntries(Object.entries(WORDS.observability).map(([key, text]) => [key, text.toLowerCase()])),
}

/** Free-text event detail written by the server, with any internal token it
 *  quotes (an owner source, a state) replaced by the operator's word for it. */
export function eventDetail(detail: string | null | undefined): string {
  if (!detail) return ''
  return detail.replaceAll(/\b[a-z]+(?:_[a-z]+)+\b|\b[A-Z]+(?:_[A-Z]+)+\b/g, (token) => DETAIL_TOKENS[token] ?? token)
}

/** Where a relationship record came from, in the operator's words. Files are
 *  provenance and stay available in disclosures; this is what the card says. */
export function sourceLabel(file: string | null | undefined): string {
  const name = (file ?? '').toLowerCase()
  if (!name) return 'Source not recorded'
  if (name.startsWith('connections')) return 'Executive network'
  if (name.includes('investor')) return 'Investor/advisor network'
  if (name.includes('slack')) return 'Slack thread'
  if (name.includes('crm') || name.includes('account')) return 'CRM record'
  if (name.includes('outcome')) return 'Recorded outcome'
  return humanize(name.replace(/\.[a-z]+$/, ''))
}

/** Actionability — the one visual language shared by every screen.
 *
 *  It answers "does somebody need to do something here", never "how strong is
 *  this relationship". Colour is paired with text and an icon everywhere it
 *  appears, so the meaning survives without it. */
export type Actionability = 'act' | 'verify' | 'healthy' | 'context'

export const ACTION_MEANING: Record<Actionability, string> = {
  act: 'Action required',
  verify: 'Needs judgement',
  healthy: 'Progressing',
  context: 'Context',
}

/** Where each workflow state sits on that scale. */
export const STATE_ACTIONABILITY: Record<string, Actionability> = {
  NEEDS_TRIAGE: 'verify',
  NEEDS_ENTITY_REVIEW: 'verify',
  PATH_REVIEW: 'verify',
  AWAITING_CONNECTOR: 'healthy',
  INTRO_SENT: 'healthy',
  COMPLETED: 'healthy',
  NO_OBSERVABLE_PATH: 'act',
  BLOCKED: 'act',
  CLOSED: 'context',
}

export function stateActionability(state: string | null | undefined): Actionability {
  return (state && STATE_ACTIONABILITY[state]) || 'context'
}

export const SETTLED_STATES = new Set(['COMPLETED', 'CLOSED'])

export function isSettled(state: string | null | undefined): boolean {
  return !!state && SETTLED_STATES.has(state)
}
