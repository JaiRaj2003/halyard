/** Operator words for the system's internal values.
 *
 *  Every enum the API returns is technical: `NEEDS_ENTITY_REVIEW`,
 *  `snapshot_only`, `same_account_same_title_family`. None of it belongs on a
 *  screen. Screens ask this module for the words instead, so terminology can be
 *  changed in one place, and an unmapped value degrades to a readable phrase
 *  rather than shouting an identifier at the operator.
 *
 *  Nothing here softens uncertainty: an unverified route stays unverified and a
 *  snapshot-only edge still says its timing is unknown.
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
  | 'relation'
  | 'origin'
  | 'event'
  | 'match_method'
  | 'issue'

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
    NONE: 'No route yet',
    CANDIDATES_IDENTIFIED: 'Candidate routes found',
    ROUTE_SELECTED: 'Route selected',
    CONNECTOR_CONFIRMED: 'Connector confirmed',
    ROUTE_FAILED: 'Route ruled out',
  },
  outcome: {
    UNKNOWN: 'Not recorded',
    INTRO_SENT: 'Introduction sent',
    MEETING_BOOKED: 'Meeting booked',
    OPPORTUNITY_CREATED: 'Opportunity created',
    DECLINED: 'Declined',
    NO_INTRO: 'No introduction made',
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
    direct_target_person: 'Knows the requested person',
    colleague_at_target_account: 'Knows a colleague at the account',
    investor_relationship_to_account: 'Investor relationship with the account',
  },
  confidence: {
    high: 'Strong evidence',
    medium: 'Some evidence',
    low: 'Weak evidence',
    none: 'No evidence',
  },
  resolution: {
    resolved: 'Confirmed',
    unresolved: 'Not yet identified',
    ambiguous: 'Several possible matches',
    no_match: 'Nothing in the data matches',
  },
  owner_source: {
    observed_owner: 'owner evidenced in the source data',
    fallback_requester: 'fallback: the requester, no owner was evidenced',
    manual_assignment: 'assigned by an operator',
    configured_triage_owner: 'the configured triage owner',
  },
  relation: {
    same_canonical_account: 'Same account',
    same_account_same_title_family: 'Same account, same kind of role',
    same_account_same_target_person: 'Same account, same person',
    explicit_reask: 'Explicitly re-asked',
  },
  origin: {
    historical_corpus: 'Imported from the historical corpus',
    live_intake: 'Entered in Halyard',
  },
  event: {
    connector_asked: 'Connector asked',
    connector_responded: 'Connector replied',
    intro_sent: 'Introduction sent',
    meeting_booked: 'Meeting booked',
    opportunity_created: 'Opportunity created',
    target_confirmed: 'Target confirmed',
    route_confirmed: 'Route selected',
    route_rejected: 'Route ruled out',
    intake: 'Request received',
  },
  match_method: {
    crm_account_id: 'the CRM account ID',
    exact_name: 'an exact name match',
    normalized_name: 'a normalized name match',
    domain: 'the email domain',
    alias: 'a known alias',
    fuzzy_name: 'a close name match',
  },
  issue: {
    high: 'Blocking',
    medium: 'Worth checking',
    low: 'Minor',
  },
}

/** Turn an unmapped internal value into something a person can read. */
function humanize(value: string): string {
  const words = value.replaceAll('_', ' ').replaceAll(':', ': ').trim().toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** The operator-facing words for one internal value. */
export function label(vocabulary: Vocabulary, value: string | null | undefined): string {
  if (!value) return '—'
  const mapped = WORDS[vocabulary][value]
  if (mapped) return mapped
  // Timeline events are prefixed by their source: `slack:intro_confirmed`,
  // `transition:PATH_REVIEW->AWAITING_CONNECTOR`.
  if (vocabulary === 'event' && value.includes(':')) {
    const [prefix, rest] = [value.slice(0, value.indexOf(':')), value.slice(value.indexOf(':') + 1)]
    if (prefix === 'transition' && rest.includes('->')) {
      const [, to] = rest.split('->')
      return `Moved to ${label('state', to).toLowerCase()}`
    }
    return `${humanize(rest)} (${prefix})`
  }
  return humanize(value)
}

export type Tone = 'neutral' | 'info' | 'warn' | 'bad' | 'good'

/** What a badge is telling the operator to *do*.
 *
 *  One vocabulary for every screen, keyed on actionability rather than on how
 *  good a relationship looks: red is for work that is being blocked or missed
 *  now, amber for a human judgment the system cannot make, green for something
 *  progressing under its own steam, and neutral for context that needs nobody.
 *  It says nothing about relationship strength or the odds of an introduction.
 */
export type Actionability = 'act' | 'verify' | 'healthy' | 'context'

export const ACTION_TONE: Record<Actionability, Tone> = {
  act: 'bad',
  verify: 'warn',
  healthy: 'good',
  context: 'neutral',
}

/** Carried alongside every toned badge so the colour is never the only signal —
 *  the glyph and the badge's own words both survive a greyscale screen. */
export const ACTION_GLYPH: Record<Actionability, string> = {
  act: '!',
  verify: '?',
  healthy: '✓',
  context: '·',
}

export const ACTION_MEANING: Record<Actionability, string> = {
  act: 'Needs intervention',
  verify: 'Needs a human judgment',
  healthy: 'Progressing',
  context: 'Context only',
}

/** What a workflow state asks of the operator. */
export function stateActionability(state: string): Actionability {
  if (state === 'BLOCKED') return 'act'
  if (state === 'COMPLETED' || state === 'INTRO_SENT' || state === 'AWAITING_CONNECTOR') return 'healthy'
  if (state === 'CLOSED') return 'context'
  // Triage, target confirmation, route review and "no corroborated route yet"
  // are all waiting on a person to decide something.
  return 'verify'
}

/** Colour for a workflow state. */
export function stateTone(state: string): Tone {
  return ACTION_TONE[stateActionability(state)]
}

/** A connector's load in words. "5 / 4" is telemetry; the operator is deciding
 *  how much of someone's goodwill to spend, and needs both numbers named. */
export function loadPhrase(asks: number | null | undefined, capacity: number | null | undefined, windowDays = 30): string {
  const count = asks ?? 0
  const asked = `${count} ask${count === 1 ? '' : 's'} in the last ${windowDays} days`
  return capacity === null || capacity === undefined
    ? `${asked} · they state no capacity`
    : `${asked} · stated capacity ${capacity} a month`
}

/** The one-line judgment on that load, or null when capacity is unknown and
 *  there is therefore nothing honest to say. */
export function loadVerdict(
  asks: number | null | undefined,
  capacity: number | null | undefined,
  overCapacity?: boolean,
): { level: Actionability; text: string } | null {
  if (capacity === null || capacity === undefined) return null
  const count = asks ?? 0
  if (overCapacity ?? count > capacity) return { level: 'act', text: 'Above stated capacity' }
  if (count >= capacity) return { level: 'verify', text: 'At stated capacity' }
  return { level: 'healthy', text: 'Capacity available' }
}
