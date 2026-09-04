/** How the queue's server-defined views are arranged for an operator.
 *
 *  The server names and defines every view and computes every count; this
 *  module only decides which views lead, which sit under "More filters", and
 *  how a fetched page is narrowed by origin on the client.
 */

import { QueueView, RequestSummary } from '../lib/api'
import { label } from './labels'

export const DEFAULT_VIEW = 'needs_attention'

/** In the order they appear. Anything the server offers beyond these is secondary. */
export const PRIMARY_VIEWS = ['needs_attention', 'awaiting_connector', 'overlapping', 'completed', 'all'] as const

export function splitViews(views: QueueView[]): { primary: QueueView[]; secondary: QueueView[] } {
  const byKey = new Map(views.map((view) => [view.key, view]))
  const primary = PRIMARY_VIEWS.flatMap((key) => {
    const view = byKey.get(key)
    return view ? [view] : []
  })
  const primaryKeys = new Set(primary.map((view) => view.key))
  const secondary = views.filter((view) => !primaryKeys.has(view.key))
  return { primary, secondary }
}

export function viewLabel(view: QueueView): string {
  return label('view', view.key) || view.label
}

export type Cohort = 'all' | 'live' | 'imported'

export const COHORTS: { key: Cohort; text: string }[] = [
  { key: 'all', text: 'All' },
  { key: 'live', text: 'Current workflow' },
  { key: 'imported', text: 'Imported backlog' },
]

export function inCohort(item: RequestSummary, cohort: Cohort): boolean {
  if (cohort === 'all') return true
  return cohort === 'live' ? item.origin === 'live_intake' : item.origin !== 'live_intake'
}

export function cohortCounts(items: RequestSummary[]): Record<Cohort, number> {
  return {
    all: items.length,
    live: items.filter((item) => item.origin === 'live_intake').length,
    imported: items.filter((item) => item.origin !== 'live_intake').length,
  }
}

/** Search terms are matched by the server; this is only for the summary line. */
export function resultSummary(total: number, shown: number, view: QueueView, q: string, cohort: Cohort): string {
  const what = viewLabel(view).toLowerCase()
  const parts = [`${shown === total ? total : `${shown} of ${total}`} ${what}`]
  if (q.trim()) parts.push(`matching “${q.trim()}”`)
  if (cohort !== 'all') parts.push(`in ${COHORTS.find((option) => option.key === cohort)?.text.toLowerCase()}`)
  return parts.join(' ')
}
