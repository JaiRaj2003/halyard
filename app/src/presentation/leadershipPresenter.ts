/** How the leadership metrics are arranged and worded.
 *
 *  Every number, denominator and window comes from the API. This module decides
 *  which metrics earn a card, how a zero-denominator metric is said out loud
 *  instead of printed as "0 / 0", and what actionability each figure carries.
 */

import { LeadershipMetric } from '../lib/api'
import { Actionability } from './labels'

/** Live-workflow SLA metrics: cards only once Halyard has assigned actions. */
export const SLA_KEYS = ['overdue', 'due_soon', 'stale'] as const

/** Current-workflow metrics that always earn a card, in display order. */
export const PRIMARY_CURRENT = [
  'in_flight',
  'awaiting_connector',
  'needs_ownership_review',
  'unverified_route',
  'overlapping',
  'connectors_over_capacity',
] as const

export const PRIMARY_LEGACY = ['legacy_backlog', 'legacy_backlog_remediation'] as const

const WORDS: Record<string, { title: string; of: string }> = {
  in_flight: { title: 'Requests in flight', of: 'requests' },
  overdue: { title: 'Overdue under Halyard', of: 'actions assigned here' },
  due_soon: { title: 'Due in the next two days', of: 'actions assigned here' },
  stale: { title: 'Quiet under Halyard', of: 'requests worked here' },
  awaiting_connector: { title: 'Waiting on a connector', of: 'open requests' },
  needs_ownership_review: { title: 'Owner still to confirm', of: 'open requests' },
  unverified_route: { title: 'Unverified route to validate', of: 'open requests' },
  no_observable_path: { title: 'No route signal', of: 'requests' },
  overlapping: { title: 'Requests on accounts with overlapping asks', of: 'requests' },
  outcome_unknown: { title: 'Settled without a recorded outcome', of: 'requests' },
  connectors_over_capacity: { title: 'Connectors above stated capacity', of: 'roster connectors' },
  legacy_backlog: { title: 'Imported backlog awaiting review', of: 'requests' },
  legacy_backlog_quiet: { title: 'No recent activity before import', of: 'imported requests' },
  legacy_backlog_remediation: { title: 'Imported review target passed', of: 'imported requests' },
}

export function metricTitle(metric: LeadershipMetric): string {
  return WORDS[metric.key]?.title ?? metric.label
}

/** "of 200 requests" — the denominator with its cohort named, never a bare slash. */
export function denominatorWords(metric: LeadershipMetric): string {
  if (metric.denominator === null) return ''
  return `of ${metric.denominator} ${WORDS[metric.key]?.of ?? 'in the cohort'}`
}

export function metricLevel(metric: LeadershipMetric): Actionability {
  const some = metric.value > 0
  switch (metric.key) {
    case 'overdue':
    case 'connectors_over_capacity':
      return some ? 'act' : 'healthy'
    case 'stale':
    case 'due_soon':
    case 'unverified_route':
    case 'needs_ownership_review':
    case 'no_observable_path':
      return some ? 'verify' : 'healthy'
    case 'awaiting_connector':
      return 'healthy'
    case 'in_flight':
    case 'overlapping':
    case 'outcome_unknown':
      return 'context'
    default:
      return 'context'
  }
}

export interface LeadershipLayout {
  /** SLA metrics with a real denominator; shown as cards ahead of the rest. */
  slaCards: LeadershipMetric[]
  /** SLA metrics whose denominator is zero; said in one sentence instead. */
  slaEmpty: LeadershipMetric[]
  primary: LeadershipMetric[]
  supporting: LeadershipMetric[]
  legacyPrimary: LeadershipMetric[]
  legacySupporting: LeadershipMetric[]
}

export function layout(metrics: LeadershipMetric[]): LeadershipLayout {
  const byKey = new Map(metrics.map((metric) => [metric.key, metric]))
  const pick = (keys: readonly string[]) => keys.flatMap((key) => (byKey.has(key) ? [byKey.get(key)!] : []))
  const sla = pick(SLA_KEYS)
  const slaCards = sla.filter((metric) => (metric.denominator ?? 0) > 0)
  const slaEmpty = sla.filter((metric) => (metric.denominator ?? 0) === 0)
  const primary = pick(PRIMARY_CURRENT)
  const shown = new Set<string>([...SLA_KEYS, ...PRIMARY_CURRENT, ...PRIMARY_LEGACY])
  const supporting = metrics.filter((metric) => metric.group !== 'legacy_backlog' && !shown.has(metric.key))
  const legacyPrimary = pick(PRIMARY_LEGACY)
  const legacySupporting = metrics.filter((metric) => metric.group === 'legacy_backlog' && !shown.has(metric.key))
  return { slaCards, slaEmpty, primary, supporting, legacyPrimary, legacySupporting }
}

/** The sentence that replaces "0 / 0" cards. */
export function slaEmptySentence(worked: number): string {
  if (worked > 0) return ''
  return 'No action has been assigned under Halyard yet, so nothing can be overdue, due soon or quiet under the live workflow. Imported review targets are reported separately below.'
}

export interface OwnershipStory {
  total: number
  ownerlessBefore: number
  ownedNow: number
  headline: string
}

export function ownershipStory(total: number, ownerlessBefore: number, ownedNow: number): OwnershipStory {
  const headline = ownedNow === total
    ? `${ownerlessBefore} of ${total} requests had no evidenced owner in the source data. Every request has an operational owner now.`
    : `${ownerlessBefore} of ${total} requests had no evidenced owner in the source data; ${ownedNow} of ${total} have an operational owner now.`
  return { total, ownerlessBefore, ownedNow, headline }
}
