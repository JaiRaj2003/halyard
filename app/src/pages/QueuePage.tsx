/** The operator queue. Views are named, defined and counted by the server. */

import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, QueuePayload, QueueView, RequestSummary } from '../lib/api'
import { ActionLegend, ActionTag, Disclosure, ErrorNote, LEVEL_TEXT, Loading, StateTag, shortDate } from '../components/primitives'
import { ActionIcon, SearchIcon } from '../components/icons'
import {
  COHORTS, Cohort, DEFAULT_VIEW, cohortCounts, inCohort, resultSummary, splitViews, viewLabel,
} from '../presentation/queuePresenter'
import { flags, liveFirst, targetHeadline, timing } from '../presentation/requestPresenter'

function Row({ item }: { item: RequestSummary }) {
  const head = targetHeadline(item)
  const when = timing(item)
  const badges = flags(item).filter((flag) => !['overdue', 'due_soon', 'imported'].includes(flag.key))
  const live = item.origin === 'live_intake'
  return (
    <tr className={`border-b border-line align-top last:border-0 hover:bg-slate-50 ${live ? 'bg-green-50/40' : ''}`}>
      <td className="px-3 py-2">
        <Link to={`/requests/${item.request_id}`} className="block max-w-[16rem] truncate text-sm font-medium text-accent hover:underline">
          {head.headline}
        </Link>
        <p className="max-w-[16rem] truncate text-xs text-ink">{head.account || <span className="text-muted">Account not identified</span>}</p>
        <p className="text-[11px] text-muted">{item.request_id}</p>
      </td>
      <td className="px-3 py-2">
        <p className="max-w-[18rem] truncate text-sm" title={item.next_action}>{item.next_action || <span className="text-muted">—</span>}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          {badges.map((flag) => (
            <ActionTag key={flag.key} level={flag.level}>{flag.text}</ActionTag>
          ))}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-sm">{item.operational_owner}</td>
      <td className="whitespace-nowrap px-3 py-2">
        {when.kind === 'none' ? (
          <p className="text-xs text-muted">Settled</p>
        ) : (
          <>
            <p className={`flex items-center gap-1 text-xs font-medium ${LEVEL_TEXT[when.actionability]}`}>
              <ActionIcon level={when.actionability} className="h-3 w-3" />
              {when.label}
            </p>
            <p className="text-sm tabular-nums">{shortDate(when.dateIso)}</p>
          </>
        )}
        <p className="text-[11px] text-muted">
          {when.kind === 'legacy_target' ? 'Imported ' : 'Activity '}
          {shortDate(when.kind === 'legacy_target' ? item.requested_at : item.last_activity_at)}
        </p>
      </td>
      <td className="px-3 py-2"><StateTag state={item.workflow_state} /></td>
      <td className="px-3 py-2 text-sm">
        {item.selected_connector ?? <span className="text-xs text-muted">None selected</span>}
      </td>
    </tr>
  )
}

function ViewButton({ view, active, count, onPick }: { view: QueueView; active: boolean; count?: number; onPick: () => void }) {
  return (
    <button
      title={view.definition}
      onClick={onPick}
      className={`rounded-md border px-2.5 py-1 text-xs font-medium ${
        active ? 'border-ink bg-ink text-white' : 'border-line bg-white text-muted hover:text-ink'
      }`}
    >
      {viewLabel(view)}
      {count !== undefined && <span className="ml-1.5 tabular-nums opacity-70">{count}</span>}
    </button>
  )
}

export default function QueuePage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? DEFAULT_VIEW
  const q = params.get('q') ?? ''
  const cohortParam = params.get('cohort')
  const cohort: Cohort = cohortParam === 'live' || cohortParam === 'imported' ? cohortParam : 'all'
  const [draft, setDraft] = useState(q)
  const [views, setViews] = useState<QueueView[]>([])
  const [data, setData] = useState<QueuePayload | null>(null)
  const [error, setError] = useState('')

  function update(next: Partial<{ view: string; q: string; cohort: Cohort }>) {
    const merged = { view, q, cohort, ...next }
    const out: Record<string, string> = { view: merged.view }
    if (merged.q.trim()) out.q = merged.q.trim()
    if (merged.cohort !== 'all') out.cohort = merged.cohort
    setParams(out)
  }

  useEffect(() => {
    api.queueViews().then((body) => setViews(body.views)).catch(() => setViews([]))
  }, [])

  useEffect(() => {
    setDraft(q)
  }, [q])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (draft.trim() !== q.trim()) update({ q: draft })
    }, 250)
    return () => window.clearTimeout(handle)
  }, [draft])

  useEffect(() => {
    setData(null)
    setError('')
    api
      .queue(view, q.trim() ? { q: q.trim(), limit: '200' } : { limit: '200' })
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [view, q])

  const { primary, secondary } = useMemo(() => splitViews(views), [views])
  const items = useMemo(() => (data ? liveFirst(data.items.filter((item) => inCohort(item, cohort))) : []), [data, cohort])
  const cohorts = data ? cohortCounts(data.items) : null

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight">Operator queue</h1>
        <ActionLegend />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <nav aria-label="Queue views" className="flex flex-wrap gap-1.5">
          {primary.map((option) => (
            <ViewButton
              key={option.key}
              view={option}
              active={option.key === view}
              count={data?.counts[option.key]}
              onPick={() => update({ view: option.key })}
            />
          ))}
        </nav>
        <label className="relative ml-auto block">
          <span className="sr-only">Search requests</span>
          <SearchIcon className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Account, person, role, requester, owner or ID"
            className="w-72 rounded-md border border-line bg-white py-1 pl-7 pr-2 text-xs focus:border-accent focus:outline-none"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <div className="flex items-center gap-1">
          <span className="text-muted">Cohort</span>
          {COHORTS.map((option) => (
            <button
              key={option.key}
              onClick={() => update({ cohort: option.key })}
              className={`rounded px-2 py-0.5 font-medium ${
                option.key === cohort ? 'bg-slate-200 text-ink' : 'text-muted hover:text-ink'
              }`}
            >
              {option.text}
              {cohorts && <span className="ml-1 tabular-nums opacity-70">{cohorts[option.key]}</span>}
            </button>
          ))}
        </div>
        {secondary.length > 0 && (
          <Disclosure summary="More filters" defaultOpen={secondary.some((option) => option.key === view)}>
            <nav aria-label="Secondary queue views" className="flex flex-wrap gap-1.5">
              {secondary.map((option) => (
                <ViewButton
                  key={option.key}
                  view={option}
                  active={option.key === view}
                  count={data?.counts[option.key]}
                  onPick={() => update({ view: option.key })}
                />
              ))}
            </nav>
          </Disclosure>
        )}
      </div>

      {error && <ErrorNote error={error} />}
      {!data && !error && <Loading what="queue" />}

      {data && (
        <>
          <p className="text-sm text-muted">
            <span className="font-medium text-ink">{resultSummary(data.total, items.length, data.view, q, cohort)}</span>
            {' — '}{data.view.definition}
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-white">
            <table className="min-w-full">
              <thead className="border-b border-line bg-slate-50 text-left text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  {['Target / account', 'Next action', 'Owner', 'Timing', 'Status', 'Connector'].map((heading) => (
                    <th key={heading} className="px-3 py-2 font-medium">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <Row key={item.request_id} item={item} />
                ))}
              </tbody>
            </table>
            {items.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-muted">
                {q.trim() ? `Nothing in ${viewLabel(data.view).toLowerCase()} matches “${q.trim()}”.` : 'Nothing in this view.'}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
