/** Leadership view: only numbers that state what they are true of, each one
 *  clickable through to the exact rows the queue counted. */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, ConnectorLoad, Leadership, LeadershipMetric } from '../lib/api'
import { Card, Disclosure, ErrorNote, Loading, Tag } from '../components/primitives'
import { label } from '../lib/labels'

/** The handful of numbers a leader acts on. Everything else is supporting
 *  detail lower down the page — present, but not competing for attention. */
const PRIMARY: string[] = [
  'in_flight',
  'overdue',
  'due_soon',
  'stale',
  'awaiting_connector',
  'overlapping',
  'connectors_over_capacity',
]

/** Legacy figures that earn a card rather than a line. */
const PRIMARY_LEGACY: string[] = ['legacy_backlog', 'legacy_backlog_remediation']

function MetricCard({ metric }: { metric: LeadershipMetric }) {
  const figure = (
    <>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{metric.label}</p>
      <p className="mt-1.5 text-3xl font-semibold leading-none tabular-nums">
        {metric.value}
        {metric.denominator !== null && <span className="text-base font-normal text-muted"> / {metric.denominator}</span>}
      </p>
      <p className="mt-2 text-[11px] uppercase tracking-wide text-muted">{metric.window}</p>
    </>
  )
  return (
    <div className="flex h-full flex-col rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-accent">
      {/* Only the figure navigates: the disclosure has to stay outside the link
          or asking what a metric counts would drill into the queue instead. */}
      {metric.drill_down_view ? (
        <Link
          to={`/queue?view=${metric.drill_down_view}`}
          className="block focus:outline-none focus:ring-2 focus:ring-accent"
        >
          {figure}
          <span className="mt-2 block text-xs font-medium text-accent">See the {metric.value} requests →</span>
        </Link>
      ) : (
        figure
      )}
      <div className="mt-auto pt-3">
        <Disclosure summary="What this counts">
          <p className="text-xs text-muted">{metric.definition}</p>
        </Disclosure>
      </div>
    </div>
  )
}

/** A supporting number: same discipline, a quarter of the space. */
function MetricRow({ metric }: { metric: LeadershipMetric }) {
  const figure = (
    <span className="tabular-nums">
      <span className="font-semibold">{metric.value}</span>
      {metric.denominator !== null && <span className="text-muted"> / {metric.denominator}</span>}
    </span>
  )
  return (
    <li className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="min-w-0">
        {metric.drill_down_view ? (
          <Link to={`/queue?view=${metric.drill_down_view}`} className="text-sm text-accent hover:underline">
            {metric.label}
          </Link>
        ) : (
          <span className="text-sm">{metric.label}</span>
        )}
        <span className="block text-xs text-muted">
          {metric.definition} <span className="whitespace-nowrap">({metric.window})</span>
        </span>
      </span>
      {figure}
    </li>
  )
}

function LoadTable({ load }: { load: ConnectorLoad }) {
  const rows = load.connectors.filter((row) => row.asks_in_window > 0 || row.open_asks > 0).slice(0, 12)
  return (
    <Card
      title="Connector load"
      subtitle={`Asks in the rolling ${load.window_days} days, against stated capacity where one exists. ${load.off_roster_observed} observed connectors are not on the managed roster and state no capacity.`}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No connector has been asked inside the current window.</p>
      ) : (
        <table className="w-full text-left">
          <thead className="text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">Connector</th>
              <th className="py-1 pr-3 font-medium">Asks in window</th>
              <th className="py-1 pr-3 font-medium">Stated capacity</th>
              <th className="py-1 pr-3 font-medium">Open asks</th>
              <th className="py-1 font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.connector_id} className="border-t border-line">
                <td className="py-1.5 pr-3 text-sm">{row.connector}</td>
                <td className="py-1.5 pr-3 text-sm tabular-nums">{row.asks_in_window}</td>
                <td className="py-1.5 pr-3 text-sm tabular-nums">{row.stated_monthly_capacity ?? '—'}</td>
                <td className="py-1.5 pr-3 text-sm tabular-nums">{row.open_asks}</td>
                <td className="py-1.5 text-xs text-muted">
                  {row.over_capacity && <Tag tone="warn">above stated capacity</Tag>} {row.note}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

export default function LeadershipPage() {
  const [data, setData] = useState<Leadership | null>(null)
  const [load, setLoad] = useState<ConnectorLoad | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.leadership(), api.connectorLoad()])
      .then(([leadership, connectorLoad]) => {
        setData(leadership)
        setLoad(connectorLoad)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [])

  if (error) return <ErrorNote error={error} />
  if (!data || !load) return <Loading what="leadership metrics" />

  const legacy = data.metrics.filter((metric) => metric.group === 'legacy_backlog')
  const current = data.metrics.filter((metric) => metric.group !== 'legacy_backlog')
  const headline = PRIMARY.map((key) => current.find((metric) => metric.key === key)).filter(
    (metric): metric is LeadershipMetric => metric !== undefined,
  )
  const supporting = current.filter((metric) => !PRIMARY.includes(metric.key))
  const legacyHeadline = legacy.filter((metric) => PRIMARY_LEGACY.includes(metric.key))
  const legacySupporting = legacy.filter((metric) => !PRIMARY_LEGACY.includes(metric.key))

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Leadership view</h1>
        <p className="mt-1 text-sm text-muted">{data.clock}</p>
      </div>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Current operational health</h2>
        <p className="mt-1 text-sm text-muted">
          Requests Halyard is working now, judged against the live clock and the configured SLA defaults.{' '}
          {data.requests_worked_under_halyard} of {data.requests_total} requests have had an action assigned here.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {headline.map((metric) => (
            <MetricCard key={metric.key} metric={metric} />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-line bg-slate-50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Legacy backlog</h2>
            <p className="mt-1 text-sm text-muted">{data.legacy_note}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {legacyHeadline.map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>
        </div>
        <ul className="mt-3 divide-y divide-line border-t border-line pt-1">
          {legacySupporting.map((metric) => (
            <MetricRow key={metric.key} metric={metric} />
          ))}
        </ul>
      </section>

      <Card title="Supporting detail" subtitle="The rest of the current picture, same denominators and windows.">
        <ul className="divide-y divide-line">
          {supporting.map((metric) => (
            <MetricRow key={metric.key} metric={metric} />
          ))}
        </ul>
      </Card>

      <Card title="Ownership" subtitle="The historical fact and the current guarantee, kept apart.">
        <p className="text-sm">{data.ownership_note}</p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Requests</dt>
            <dd className="text-lg font-semibold tabular-nums">{data.requests_total}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">With an operational owner</dt>
            <dd className="text-lg font-semibold tabular-nums">{data.requests_with_operational_owner}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Ownerless at ingest</dt>
            <dd className="text-lg font-semibold tabular-nums">{data.historically_ownerless_at_ingest}</dd>
          </div>
        </dl>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Workflow states" subtitle="Denominator: every request in the system.">
          <ul className="space-y-1">
            {Object.entries(data.by_workflow_state).map(([state, count]) => (
              <li key={state} className="flex items-center justify-between text-sm">
                <Link to={`/queue?view=all`} className="text-accent hover:underline">
                  {label('state', state)}
                </Link>
                <span className="tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Recorded outcomes" subtitle="Unknown stays unknown; silence is never read as a result.">
          <ul className="space-y-1">
            {Object.entries(data.by_outcome).map(([outcome, count]) => (
              <li key={outcome} className="flex items-center justify-between text-sm">
                <span>{label('outcome', outcome)}</span>
                <span className="tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <LoadTable load={load} />

      <Card
        title="Owners"
        subtitle="Open requests per operational owner, and how many of the actions Halyard assigned them are overdue."
      >
        <table className="w-full text-left">
          <thead className="text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">Owner</th>
              <th className="py-1 pr-3 font-medium">Open</th>
              <th className="py-1 font-medium">Overdue</th>
            </tr>
          </thead>
          <tbody>
            {data.by_owner.slice(0, 12).map((row) => (
              <tr key={row.owner} className="border-t border-line">
                <td className="py-1.5 pr-3 text-sm">{row.owner}</td>
                <td className="py-1.5 pr-3 text-sm tabular-nums">{row.open}</td>
                <td className="py-1.5 text-sm tabular-nums">{row.overdue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
