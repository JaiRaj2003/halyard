/** How one request is read on screen: what it is for, where it stands, who
 *  holds it, what happens next and when.
 *
 *  Presentation only. Every input is a field the API already serves; nothing
 *  here changes a state, an owner or a date — it decides which of the server's
 *  facts lead and how they are worded.
 */

import { IntakeResult, RequestDetail, RequestSummary, TargetDetail } from '../lib/api'
import { Actionability, isSettled, label, stateActionability } from './labels'

/** The target as a headline: the role and account first, and a named person
 *  only once the data actually identifies one. A name found in the source but
 *  never resolved is shown as exactly that — a lead, not the target. */
export interface TargetHeadline {
  /** The strongest true statement: a confirmed person, else the role, else the raw ask. */
  headline: string
  /** Under the headline: role for a confirmed person, otherwise identification status. */
  subline: string
  account: string
  accountId: number | null
  /** A name present in the source that resolution could not confirm. */
  unconfirmedName: string | null
  personConfirmed: boolean
}

export function targetHeadline(item: RequestSummary, detail?: TargetDetail | null): TargetHeadline {
  const resolved = detail?.resolved_person ?? null
  const title = (item.target_title || detail?.raw_target_title || '').trim()
  const rawName = (detail?.raw_target_name || item.target || '').trim()
  const account = item.account || detail?.raw_account_text || ''

  if (resolved || (item.target_resolution_status === 'resolved' && rawName)) {
    return {
      headline: resolved?.display_name || rawName,
      subline: resolved?.title || title || 'Named person confirmed',
      account,
      accountId: item.account_id,
      unconfirmedName: null,
      personConfirmed: true,
    }
  }
  const nameIsTheAsk = rawName !== '' && rawName !== title && rawName !== account
  return {
    headline: title || (nameIsTheAsk ? rawName : '') || 'Target not yet identified',
    subline: title ? 'Specific person not yet identified' : nameIsTheAsk ? 'Named in the source · unconfirmed' : 'Role and person not yet identified',
    account,
    accountId: item.account_id,
    unconfirmedName: nameIsTheAsk && title ? rawName : null,
    personConfirmed: false,
  }
}

/** One line for a queue row or list item: role at account, never the bare
 *  unresolved name. */
export function targetLine(item: RequestSummary): string {
  const head = targetHeadline(item)
  return head.headline
}

/** What the due date on this request actually is. Imported requests carry a
 *  review target this system set at import; only an action assigned under
 *  Halyard can be due, due soon or overdue. */
export type TimingKind = 'legacy_target' | 'overdue' | 'due_soon' | 'due' | 'none'

export interface Timing {
  kind: TimingKind
  /** Column/row label, e.g. "Legacy review target", "Overdue", "Due". */
  label: string
  dateIso: string | null
  /** Short qualifier beside the date: "set at import", "in 2d", "3d past due". */
  note: string
  actionability: Actionability
}

function daysFromNow(iso: string, now: number): number {
  return Math.round((new Date(iso).getTime() - now) / 86_400_000)
}

export function timing(item: RequestSummary, now: number = Date.now()): Timing {
  const due = item.next_action_due_at
  if (!due || isSettled(item.workflow_state)) {
    return { kind: 'none', label: 'Timing', dateIso: null, note: '', actionability: 'context' }
  }
  if (!item.sla_managed) {
    return {
      kind: 'legacy_target',
      label: 'Legacy review target',
      dateIso: due,
      note: 'set at import',
      actionability: 'context',
    }
  }
  const delta = daysFromNow(due, now)
  if (item.sla_breached || delta < 0) {
    const days = Math.abs(delta)
    return {
      kind: 'overdue',
      label: 'Overdue',
      dateIso: due,
      note: days === 0 ? 'today' : `${days}d past due`,
      actionability: 'act',
    }
  }
  if (item.due_soon || delta <= 2) {
    return {
      kind: 'due_soon',
      label: 'Due soon',
      dateIso: due,
      note: delta === 0 ? 'today' : delta === 1 ? 'tomorrow' : `in ${delta}d`,
      actionability: 'verify',
    }
  }
  return { kind: 'due', label: 'Due', dateIso: due, note: `in ${delta}d`, actionability: 'healthy' }
}

/** Ownership as a status: every request has an owner; the question is only
 *  whether that owner has been confirmed. */
export interface OwnerStatus {
  name: string
  confirmed: boolean
  /** Short badge text when unconfirmed, else "". */
  flag: string
  /** Sentence for the hero. */
  note: string
}

export function ownerStatus(item: RequestSummary): OwnerStatus {
  const fallback = item.operational_owner_source === 'fallback_requester'
  return {
    name: item.operational_owner,
    confirmed: !fallback,
    flag: fallback ? 'Owner to confirm' : '',
    note: fallback
      ? `${item.operational_owner} holds this as requester until an operator confirms or reassigns it.`
      : label('owner_source', item.operational_owner_source),
  }
}

/** Badges beside the state, in the order an operator should read them. Each
 *  one is a fact the API asserts; nothing is inferred. */
export interface Flag {
  key: string
  text: string
  level: Actionability
}

export function flags(item: RequestSummary, now: number = Date.now()): Flag[] {
  const out: Flag[] = []
  const when = timing(item, now)
  if (when.kind === 'overdue') out.push({ key: 'overdue', text: 'Overdue', level: 'act' })
  if (when.kind === 'due_soon') out.push({ key: 'due_soon', text: 'Due soon', level: 'verify' })
  if (item.potentially_stale && item.sla_managed && !isSettled(item.workflow_state)) {
    out.push({ key: 'quiet', text: `Quiet ${Math.round(item.days_since_activity)}d`, level: 'verify' })
  }
  if (item.route_signal === 'unverified_suggested_route' && !isSettled(item.workflow_state)) {
    out.push({ key: 'unverified', text: 'Unverified route', level: 'verify' })
  }
  if (ownerStatus(item).flag) out.push({ key: 'owner', text: 'Owner to confirm', level: 'verify' })
  if (item.origin === 'live_intake') out.push({ key: 'live', text: 'Live request', level: 'healthy' })
  if (item.legacy_backlog) out.push({ key: 'imported', text: 'Imported backlog', level: 'context' })
  return out
}

/** Why this request is in front of the operator, as plain sentences. */
export function attentionReasons(item: RequestSummary, now: number = Date.now()): string[] {
  const reasons: string[] = []
  if (isSettled(item.workflow_state)) return reasons
  switch (item.workflow_state) {
    case 'NEEDS_TRIAGE':
      reasons.push('Not yet triaged: confirm the owner and target, then choose how to route it.')
      break
    case 'NEEDS_ENTITY_REVIEW':
      reasons.push('The target or account is ambiguous and needs a human to confirm which one is meant.')
      break
    case 'PATH_REVIEW':
      reasons.push('Candidate routes are ready for review; none has been selected.')
      break
    case 'NO_OBSERVABLE_PATH':
      reasons.push('No corroborated route exists yet; the request stays open and owned until one is found or it is closed.')
      break
    case 'BLOCKED':
      reasons.push('Blocked: something outside Halyard has to move before this can progress.')
      break
    default:
      break
  }
  if (item.route_signal === 'unverified_suggested_route') {
    reasons.push(
      `${item.suggested_route_person || 'Someone'} was suggested as a route in the source thread; nothing in the network corroborates it, so it must be validated before it is treated as a path.`,
    )
  }
  const when = timing(item, now)
  if (when.kind === 'overdue') reasons.push(`The action assigned here is ${when.note}.`)
  if (item.potentially_stale && item.sla_managed) {
    reasons.push(`No activity for ${Math.round(item.days_since_activity)} days under Halyard.`)
  }
  if (ownerStatus(item).flag) {
    reasons.push(
      item.origin === 'historical_corpus'
        ? 'Ownership fell back to the requester at import and has not been confirmed.'
        : 'The requester holds ownership until an operator confirms or reassigns it.',
    )
  }
  return reasons
}

/** The one button the hero offers. It points at the panel where the decision
 *  is made, or confirms the fallback owner in place. */
export type CtaKind = 'triage' | 'confirm_owner' | 'review_target' | 'validate_route' | 'none'

export interface Cta {
  kind: CtaKind
  text: string
  /** Element id to scroll to when the action is a review, "" when it is a call. */
  anchor: string
}

export function primaryCta(data: IntakeResult): Cta {
  const item = data.request
  if (isSettled(item.workflow_state)) return { kind: 'none', text: '', anchor: '' }
  if (item.workflow_state === 'NEEDS_ENTITY_REVIEW' || data.account_candidates.length > 1 || data.person_candidates.length > 1) {
    return { kind: 'review_target', text: 'Review target', anchor: 'target' }
  }
  if (item.workflow_state === 'PATH_REVIEW' && data.paths.paths.length > 0) {
    return { kind: 'validate_route', text: 'Validate route', anchor: 'routes' }
  }
  if (item.workflow_state === 'NEEDS_TRIAGE') {
    return { kind: 'triage', text: 'Start triage', anchor: data.paths.paths.length > 0 ? 'routes' : 'target' }
  }
  if (ownerStatus(item).flag) return { kind: 'confirm_owner', text: 'Confirm owner', anchor: '' }
  if (item.route_signal === 'unverified_suggested_route' && data.paths.paths.length === 0) {
    return { kind: 'validate_route', text: 'Validate route', anchor: 'routes' }
  }
  return { kind: 'none', text: '', anchor: '' }
}

export function stateLevel(item: RequestSummary): Actionability {
  return stateActionability(item.workflow_state)
}

/** Requests in a list: live work first, then everything else in the order the
 *  server returned it. Grouping by origin, not re-ranking within a group. */
export function liveFirst<T extends RequestSummary>(items: T[]): T[] {
  const live = items.filter((item) => item.origin === 'live_intake')
  const rest = items.filter((item) => item.origin !== 'live_intake')
  return [...live, ...rest]
}

/** The words for "what is this request's next step and where did it come from". */
export function nextActionSource(item: RequestDetail | RequestSummary): string {
  return label('action_source', item.next_action_source)
}
