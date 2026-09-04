/** Leadership view: only numbers that state what they are true of, each one
 *  clickable through to the exact rows the queue counted. */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, ConnectorLoad, Leadership, LeadershipMetric } from '../lib/api'
import { ActionLegend, ActionTag, Callout, Card, Disclosure, ErrorNote, LEVEL_TEXT, Loading } from '../components/primitives'
import { ActionIcon } from '../components/icons'
import { ACTION_MEANING, label } from '../presentation/labels'
import {
  denominatorWords, layout, metricLevel, metricTitle, ownershipStory, slaEmptySentence,
} from '../presentation/leadershipPresenter'
import { loadReading } from '../presentation/loadPresenter'

function MetricCard({ metric }: { metric: LeadershipMetric }) {
  const level = metricLevel(metric)
  const figure = (
    <>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{metricTitle(metric)}</p>
      <p className="mt-1.5 flex items-baseline gap-2">
        <span className="text-3xl font-semibold leading-none tabular-nums">{metric.value}</span>
        {metric.denominator !== null && <span className="text-sm text-muted">{denominatorWords(metric)}</span>}
      </p>
      <p className={`mt-2 flex items-center gap-1 text-[11px] font-medium ${LEVEL_TEXT[level]}`}>
        <ActionIcon level={level} className="h-3 w-3" />
        {ACTION_MEANING[level]}
        <span className="font-normal text-muted"> · {metric.window}</span>
      </p>
    </>
  )
  return (
    <div className="flex h-full flex-col rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-accent">
      {metric.drill_down_view ? (
        <Link to={`/queue?view=${metric.drill_down_view}`} className="block focus:outline-none focus:ring-2 focus:ring-accent">
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
  const level = metricLevel(metric)
  return (
    <li className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <ActionIcon level={level} className={`h-3 w-3 ${LEVEL_TEXT[level]}`} />
          {metric.drill_down_view ? (
            <Link to={`/queue?view=${metric.drill_down_view}`} className="text-sm text-accent hover:underline">
              {metricTitle(metric)}
            </Link>
          ) : (
            <span className="text-sm">{metricTitle(metric)}</span>
          )}
        </span>
        <span className="block text-xs text-muted">
          {metric.definition} <span className="whitespace-nowrap">({metric.window})</span>
        </span>
      </span>
      <span className="whitespace-nowrap tabular-nums">
        <span className="font-semibold">{metric.value}</span>
        {metric.denominator !== null && <span className="text-xs text-muted"> {denominatorWords(metric)}</span>}
      </span>
    </li>
  )
}

function LoadTable({ load }: { load: ConnectorLoad }) {
  const rows = load.connectors
    .filter((row) => row.on_roster || row.asks_in_window > 0 || row.open_asks > 0)
    .sort((a, b) => Number(b.on_roster) - Number(a.on_roster) || b.asks_in_window - a.asks_in_window)
    .slice(0, 12)
  return (
    <Card
      title="Connector goodwill in use"
      subtitle={`Asks made of each connector in the last ${load.window_days} days against the capacity they stated. ${load.off_roster_observed} observed connectors are outside the managed roster and state no capacity, so their load cannot be judged.`}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No connector has been asked inside the current window.</p>
      ) : (
        <table className="w-full text-left">
          <thead className="text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">Connector</th>
              <th className="py-1 pr-3 font-medium">Load</th>
              <th className="py-1 pr-3 font-medium">Still open</th>
              <th className="py-1 font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const reading = loadReading(row.asks_in_window, row.stated_monthly_capacity, row.over_capacity)
              return (
                <tr key={row.connector_id} className="border-t border-line">
                  <td className="py-1.5 pr-3 text-sm">
                    {row.connector}
                    {!row.on_roster && <span className="block text-[11px] text-muted">Outside managed roster</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-sm">
                    <span className="flex flex-wrap items-center gap-2">
                      <ActionTag level={reading.level}>{reading.verdict}</ActionTag>
                      <span className="text-muted">{reading.phrase}</span>
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-sm tabular-nums">{row.open_asks}</td>
                  <td className="py-1.5 text-xs text-muted">{row.on_roster ? row.note : ''}</td>
                </tr>
              )
            })}
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

  const parts = layout(data.metrics)
  const story = ownershipStory(data.requests_total, data.historically_ownerless_at_ingest, data.requests_with_operational_owner)
  const slaSentence = parts.slaEmpty.length > 0 ? slaEmptySentence(data.requests_worked_under_halyard) : ''
  const settled = Object.entries(data.by_workflow_state)
    .filter(([state]) => state === 'COMPLETED' || state === 'CLOSED')
    .reduce((sum, [, count]) => sum + count, 0)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Leadership view</h1>
          <p className="mt-1 text-sm text-muted">
            Live requests are judged on the real clock; imported backlog is reported separately and never as a breach of an SLA that did not exist.
          </p>
        </div>
        <ActionLegend />
      </div>

      <section className="rounded-lg border border-green-200 bg-green-50 px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-green-800">Ownership</p>
        <p className="mt-1 text-base font-semibold leading-snug">{story.headline}</p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Requests</dt>
            <dd className="text-lg font-semibold tabular-nums">{story.total}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">No evidenced owner in the source</dt>
            <dd className="text-lg font-semibold tabular-nums">{story.ownerlessBefore}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">With an operational owner now</dt>
            <dd className="text-lg font-semibold tabular-nums">{story.ownedNow}</dd>
          </div>
        </dl>
        <p className="mt-2 text-xs text-muted">{data.ownership_note}</p>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Current operational health</h2>
        <p className="mt-1 text-sm text-muted">
          Requests Halyard is working now, judged against the live clock and the configured SLA defaults.{' '}
          {data.requests_worked_under_halyard} of {data.requests_total} requests have had an action assigned here
          {data.live_requests_total > 0 ? `; ${data.live_requests_total} arrived through live intake.` : '.'}
        </p>
        {slaSentence && (
          <div className="mt-3">
            <Callout level="healthy" title="Nothing overdue, due soon or quiet under the live workflow">{slaSentence}</Callout>
          </div>
        )}
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[...parts.slaCards, ...parts.primary].map((metric) => (
            <MetricCard key={metric.key} metric={metric} />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-line bg-slate-50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
              <ActionIcon level="context" className="h-3 w-3" />
              Imported backlog · context, not current SLA failure
            </h2>
            <p className="mt-1 text-sm text-muted">{data.legacy_note}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {parts.legacyPrimary.map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>
        </div>
        {parts.legacySupporting.length > 0 && (
          <ul className="mt-3 divide-y divide-line border-t border-line pt-1">
            {parts.legacySupporting.map((metric) => (
              <MetricRow key={metric.key} metric={metric} />
            ))}
          </ul>
        )}
      </section>

      {parts.supporting.length > 0 && (
        <Card title="Supporting detail" subtitle="The rest of the current picture, same denominators and windows.">
          <ul className="divide-y divide-line">
            {parts.supporting.map((metric) => (
              <MetricRow key={metric.key} metric={metric} />
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Workflow states" subtitle={`Every one of the ${data.requests_total} requests, by where it stands.`}>
          <ul className="space-y-1">
            {Object.entries(data.by_workflow_state).map(([state, count]) => (
              <li key={state} className="flex items-center justify-between text-sm">
                <Link to="/queue?view=all" className="text-accent hover:underline">
                  {label('state', state)}
                </Link>
                <span className="tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card
          title="Recorded outcomes"
          subtitle={`All ${data.requests_total} requests; ${data.requests_total - settled} are still open and have no outcome yet. Silence is never read as a result.`}
        >
          <ul className="space-y-1">
            {Object.entries(data.by_outcome).map(([outcome, count]) => (
              <li key={outcome} className="flex items-center justify-between text-sm">
                <span>{outcome === 'UNKNOWN' ? 'Not recorded (open or unknown)' : label('outcome', outcome)}</span>
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
              <th className="py-1 font-medium">Overdue under Halyard</th>
            </tr>
          </thead>
          <tbody>
            {data.by_owner.slice(0, 12).map((row) => (
              <tr key={row.owner} className="border-t border-line">
                <td className="py-1.5 pr-3 text-sm">{row.owner}</td>
                <td className="py-1.5 pr-3 text-sm tabular-nums">{row.open}</td>
                <td className="py-1.5 text-sm tabular-nums">
                  {row.overdue > 0 ? <ActionTag level="act">{row.overdue}</ActionTag> : <span className="text-muted">0</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <p className="text-xs text-muted">Clock: {data.clock}. As of {data.as_of}.</p>
    </div>
  )
}
