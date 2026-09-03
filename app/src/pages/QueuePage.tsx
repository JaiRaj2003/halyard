/** The operator queue. Views are named and defined by the server. */

import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, QueuePayload, QueueView } from '../lib/api'
import { ErrorNote, Loading, StateTag, Tag, relative, shortDate } from '../components/primitives'

function Row({ item }: { item: QueuePayload['items'][number] }) {
  return (
    <tr className="border-b border-line align-top last:border-0 hover:bg-slate-50">
      <td className="px-3 py-2">
        <Link to={`/requests/${item.request_id}`} className="text-sm font-medium text-accent hover:underline">
          {item.request_id}
        </Link>
        <p className="max-w-xs truncate text-xs text-muted">{item.target_title || item.target || 'target unresolved'}</p>
      </td>
      <td className="px-3 py-2 text-sm">{item.account || <span className="text-muted">unresolved</span>}</td>
      <td className="px-3 py-2 text-sm">{item.requester}</td>
      <td className="px-3 py-2 text-sm">{item.selected_connector ?? <span className="text-muted">none selected</span>}</td>
      <td className="px-3 py-2"><StateTag state={item.workflow_state} /></td>
      <td className="px-3 py-2 text-sm">{item.operational_owner}</td>
      <td className="px-3 py-2 text-xs text-muted">{relative(item.last_activity_at)}</td>
      <td className="px-3 py-2">
        <p className="max-w-xs truncate text-sm">{item.next_action}</p>
        <p className="text-xs text-muted">due {shortDate(item.next_action_due_at)}</p>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {item.is_overdue && <Tag tone="bad">overdue</Tag>}
          {item.potentially_stale && <Tag tone="warn">quiet</Tag>}
          {item.was_ownerless_at_ingest && <Tag tone="warn">fallback owner</Tag>}
          {(item.related_count ?? 0) > 0 && <Tag>{item.related_count} related</Tag>}
        </div>
      </td>
    </tr>
  )
}

export default function QueuePage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'in_flight'
  const [views, setViews] = useState<QueueView[]>([])
  const [data, setData] = useState<QueuePayload | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.queueViews().then((body) => setViews(body.views)).catch(() => setViews([]))
  }, [])

  useEffect(() => {
    setData(null)
    api
      .queue(view)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [view])

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Operator queue</h1>

      <nav className="flex flex-wrap gap-1.5">
        {views.map((option) => (
          <button
            key={option.key}
            title={option.definition}
            onClick={() => setParams({ view: option.key })}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium ${
              option.key === view ? 'border-ink bg-ink text-white' : 'border-line bg-white text-muted hover:text-ink'
            }`}
          >
            {option.label}
            {data && <span className="ml-1.5 opacity-70">{data.counts[option.key]}</span>}
          </button>
        ))}
      </nav>

      {error && <ErrorNote error={error} />}
      {!data && !error && <Loading what="queue" />}

      {data && (
        <>
          <p className="text-sm text-muted">
            <span className="font-medium text-ink">{data.total}</span> {data.view.label.toLowerCase()} — {data.view.definition}
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-white">
            <table className="min-w-full">
              <thead className="border-b border-line bg-slate-50 text-left text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  {['Request', 'Account', 'Requester', 'Connector', 'State', 'Owner', 'Last activity', 'Next action', ''].map((heading) => (
                    <th key={heading} className="px-3 py-2 font-medium">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <Row key={item.request_id} item={item} />
                ))}
              </tbody>
            </table>
            {data.items.length === 0 && <p className="px-4 py-8 text-center text-sm text-muted">Nothing in this view.</p>}
          </div>
        </>
      )}
    </div>
  )
}
