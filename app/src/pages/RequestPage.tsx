/** Request detail: the whole working surface for one ask. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, CandidatePath, IntakeResult } from '../lib/api'
import {
  Button, Card, Disclosure, Empty, ErrorNote, Field, Loading, StateTag, Tag, relative, shortDate,
} from '../components/primitives'
import { label } from '../lib/labels'

/** Target, status, owner, next action — in that order, above everything else. */
function Hero({ data }: { data: IntakeResult }) {
  const request = data.request
  const decision = data.next_decision
  const overdue = request.sla_breached
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-6 px-6 pt-5">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-wide text-muted">
            {request.request_id} · {label('origin', request.origin)} · raised {relative(request.requested_at)}
          </p>
          <h1 className="mt-1 text-2xl font-semibold leading-tight tracking-tight">
            {request.target || request.target_title || 'Target not yet identified'}
          </h1>
          <p className="mt-0.5 text-base text-muted">
            at{' '}
            {request.account_id ? (
              <Link to={`/accounts/${request.account_id}`} className="text-accent hover:underline">
                {request.account}
              </Link>
            ) : (
              <span>{request.account || 'an account that is not yet identified'}</span>
            )}
          </p>
          <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm italic text-muted">
            “{request.raw_ask}”
          </blockquote>
        </div>

        <dl className="grid w-full shrink-0 grid-cols-2 gap-x-8 gap-y-3 sm:w-auto">
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Status</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-1.5">
              <StateTag state={request.workflow_state} />
              {overdue && <Tag tone="bad">overdue</Tag>}
              {request.legacy_backlog && <Tag>legacy backlog</Tag>}
              {request.potentially_stale && request.sla_managed && (
                <Tag tone="warn">quiet {Math.round(request.days_since_activity)}d</Tag>
              )}
              {request.route_signal === 'unverified_suggested_route' && (
                <Tag tone="warn">{label('route_signal', request.route_signal)}</Tag>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Owner</dt>
            <dd className="mt-1 text-sm font-medium">{request.operational_owner}</dd>
            {request.was_ownerless_at_ingest && (
              <dd className="mt-1"><Tag tone="warn">needs ownership review</Tag></dd>
            )}
          </div>
        </dl>
      </div>

      <div
        className={`mt-5 flex flex-wrap items-start justify-between gap-4 border-t px-6 py-4 ${
          overdue ? 'border-red-200 bg-red-50' : 'border-line bg-slate-50'
        }`}
      >
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Next action</p>
          <p className="mt-0.5 text-lg font-semibold leading-snug">
            {request.next_action || 'Nothing outstanding — this request is settled.'}
          </p>
          {decision.prompt && <p className="mt-1 max-w-3xl text-sm text-muted">{decision.prompt}</p>}
        </div>
        {request.next_action_due_at && (
          <div className="text-right">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Due</p>
            <p className={`mt-0.5 text-lg font-semibold tabular-nums ${overdue ? 'text-bad' : ''}`}>
              {shortDate(request.next_action_due_at)}
            </p>
            <p className="text-xs text-muted">
              {overdue ? 'past due' : relative(request.next_action_due_at)}
              {request.legacy_backlog && ' · remediation target set at import'}
            </p>
          </div>
        )}
      </div>

      <div className="border-t border-line px-6 py-3">
        <Disclosure summary="Request record">
          <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Field label="Requester">{request.requester}</Field>
            <Field label="Owner assigned" wrap>{label('owner_source', request.operational_owner_source)}</Field>
            <Field label="Route">
              {request.selected_connector ?? label('route_status', request.route_status)}
            </Field>
            <Field label="Outcome">{label('outcome', request.outcome)}</Field>
            <Field label="Last activity">{relative(request.last_activity_at)}</Field>
            <Field label="Route evidence">{label('route_signal', request.route_signal)}</Field>
            <Field label="Target status">{label('resolution', request.target_resolution_status)}</Field>
            <Field label="How this status was reached" wrap>{request.state_evidence}</Field>
          </dl>
        </Disclosure>
      </div>
    </section>
  )
}

function TargetPanel({ data, onChange }: { data: IntakeResult; onChange: (result: IntakeResult) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const target = data.request.target_detail

  async function confirm(body: { account_id?: number; person_id?: number }) {
    setBusy(true)
    setError('')
    try {
      onChange(await api.confirmTarget(data.request.request_id, body))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Target"
      subtitle={`Read from the ask: ${data.parse.evidence}. ${label('confidence', data.parse.confidence)}.`}
    >
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Field label="Account text">{data.parse.proposed.account_text}</Field>
        <Field label="Person">{data.parse.proposed.person_name}</Field>
        <Field label="Role">{data.parse.proposed.title}</Field>
        <Field label="Target status">{label('resolution', target?.resolution_status ?? 'unresolved')}</Field>
      </dl>

      {data.parse.warnings.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-warn">
          {data.parse.warnings.map((warning) => (
            <li key={warning}>· {warning}</li>
          ))}
        </ul>
      )}

      {error && <div className="mt-3"><ErrorNote error={error} /></div>}

      {data.account_candidates.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">
            {data.account_candidates.length === 1 ? 'Account match' : `${data.account_candidates.length} possible accounts`}
          </p>
          <ul className="mt-2 space-y-2">
            {data.account_candidates.map((candidate) => (
              <li key={candidate.id} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{candidate.label}</p>
                  <p className="truncate text-xs text-muted">
                    {candidate.detail} · matched on {label('match_method', candidate.method)} · {label('confidence', candidate.confidence).toLowerCase()}
                  </p>
                  {candidate.account?.competing_candidates?.map((note) => (
                    <p key={note} className="truncate text-xs text-warn">{note}</p>
                  ))}
                </div>
                <Button variant="secondary" disabled={busy} onClick={() => confirm({ account_id: candidate.id })}>
                  This one
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.person_candidates.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">
            {data.person_candidates.length} possible people
          </p>
          <ul className="mt-2 space-y-2">
            {data.person_candidates.map((candidate) => (
              <li key={candidate.id} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{candidate.label}</p>
                  <p className="truncate text-xs text-muted">
                    {candidate.detail} · {label('confidence', candidate.confidence).toLowerCase()}
                  </p>
                </div>
                <Button variant="secondary" disabled={busy} onClick={() => confirm({ person_id: candidate.id })}>
                  This one
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.account_candidates.length === 0 && data.person_candidates.length === 0 && (
        <p className="mt-4 text-xs text-muted">
          Nothing in the supplied data matches this target. The request stays open and owned; resolving it needs
          information Halyard does not hold.
        </p>
      )}
    </Card>
  )
}

/** One route, read top-down: who, how good, why, what is wrong with it.
 *
 *  Collapsed it carries only what a routing decision needs. Everything the
 *  ordering used — every factor, the provenance, the timing, the connector's
 *  load — stays one click away under "Why this?", never deleted.
 */
function PathRow({ path, busy, onDecide }: {
  path: CandidatePath
  busy: boolean
  onDecide: (pathId: number, decision: 'confirm' | 'reject') => void
}) {
  const rejected = path.review_status === 'rejected'
  const selected = path.review_status === 'selected'
  const supporting = path.factors.filter((factor) => factor.direction !== 'limiting')
  const limiting = path.factors.filter((factor) => factor.direction === 'limiting')
  const caveat = limiting[0]?.statement || path.limitations
  const load = path.connector.over_capacity
    ? `Asked ${path.connector.recent_asks_30d ?? 0} times in the last 30 days — above their stated capacity`
    : null

  return (
    <li
      className={`rounded-lg border px-4 py-3.5 ${
        selected ? 'border-green-300 bg-green-50'
        : rejected ? 'border-line bg-slate-50 opacity-60'
        : path.recommended ? 'border-accent/40 bg-white shadow-sm'
        : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold">{path.connector.name}</span>
            {selected && <Tag tone="good">selected route</Tag>}
            {rejected && <Tag>ruled out</Tag>}
            {!selected && !rejected && path.recommendation_label && (
              <Tag tone={path.recommended ? 'info' : 'neutral'}>{path.recommendation_label}</Tag>
            )}
          </div>
          <p className="mt-1 text-sm">{label('hop', path.hop_type)}</p>

          <ul className="mt-2 space-y-0.5">
            {supporting.slice(0, 2).map((factor) => (
              <li key={factor.key} className="text-sm text-muted">· {factor.statement}</li>
            ))}
          </ul>
          {(caveat || load) && (
            <p className="mt-2 text-sm text-warn">{load ?? caveat}</p>
          )}
        </div>

        {!selected && !rejected && (
          <div className="flex shrink-0 gap-2">
            <Button disabled={busy} onClick={() => onDecide(path.id, 'confirm')}>
              Investigate this route
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => onDecide(path.id, 'reject')}>
              Rule out
            </Button>
          </div>
        )}
      </div>

      <div className="mt-3 border-t border-line pt-2.5">
        <Disclosure summary="Why this?">
          <ul className="grid gap-1 lg:grid-cols-2">
            {path.factors.map((factor) => (
              <li key={factor.key} className={`text-xs ${factor.direction === 'limiting' ? 'text-warn' : 'text-ink'}`}>
                {factor.direction === 'limiting' ? '! ' : '+ '}
                {factor.statement}
              </li>
            ))}
          </ul>
          <dl className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Field label="Timing" wrap>{label('observability', path.observability)}</Field>
            <Field label="Evidence strength" wrap>{label('confidence', path.confidence)}</Field>
            <Field label="Connected" wrap>{path.relationship_date ? shortDate(path.relationship_date) : 'no date recorded'}</Field>
            <Field label="Connector" wrap>
              {path.connector.on_roster ? 'On the managed roster' : 'Observed, not on the managed roster'}
            </Field>
          </dl>
          <p className="mt-2 text-xs text-muted">
            Asked {path.connector.recent_asks_30d ?? 0} times in the last 30 days
            {path.connector.stated_monthly_capacity !== null
              ? ` against a stated capacity of ${path.connector.stated_monthly_capacity} a month.`
              : '; they state no capacity.'}
            {path.connector.note ? ` ${path.connector.note}` : ''}
          </p>
          {path.limitations && <p className="mt-1 text-xs text-warn">Limitation: {path.limitations}</p>}
          {path.evidence && <p className="mt-1 text-xs text-muted">Evidence: {path.evidence}</p>}
          {path.source_file && <p className="mt-1 text-xs text-muted">Source: {path.source_file}</p>}
          {path.review_note && <p className="mt-1 text-xs text-muted">Note: {path.review_note}</p>}
        </Disclosure>
      </div>
    </li>
  )
}

function PathsPanel({ data, onChange }: { data: IntakeResult; onChange: (result: IntakeResult) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function decide(pathId: number, decision: 'confirm' | 'reject') {
    setBusy(true)
    setError('')
    try {
      onChange(await api.reviewRoute(data.request.request_id, { path_id: pathId, decision }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const paths = data.paths.paths
  return (
    <Card title="Routes to investigate" subtitle={data.paths.disclaimer}>
      {error && <div className="mb-3"><ErrorNote error={error} /></div>}
      {paths.length === 0 ? (
        data.request.route_signal === 'unverified_suggested_route' ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="text-sm font-medium">
              Unverified route suggested in the source thread — needs validation before routing.
            </p>
            <p className="mt-1 text-sm">
              {data.request.suggested_route_person} may hold a route. The supplied network does not corroborate it, so
              it is not a candidate path.
            </p>
            <p className="mt-1 text-xs text-muted">{data.request.suggested_route_evidence}</p>
          </div>
        ) : (
          <Empty>
            {data.paths.note ||
              'No route signal: neither the supplied network nor any message in the thread offers a route.'}{' '}
            The request stays active, owned and on the queue — it is not closed by the absence of evidence.
          </Empty>
        )
      ) : (
        <>
          <p className="mb-3 text-xs text-muted">{data.paths.ordering}</p>
          <ul className="space-y-3">
            {paths.map((path) => (
              <PathRow key={path.id} path={path} busy={busy} onDecide={decide} />
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}

function ActivityPanel({ data }: { data: IntakeResult }) {
  return (
    <Card title="Related activity on this account" subtitle={data.account_activity_note}>
      {data.account_activity.length === 0 ? (
        <Empty>No other request touches this account.</Empty>
      ) : (
        <ul className="space-y-2">
          {data.account_activity.map((related) => (
            <li key={related.request.request_id} className="rounded-md border border-line px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <Link to={`/requests/${related.request.request_id}`} className="text-sm font-medium text-accent hover:underline">
                  {related.request.request_id}
                </Link>
                <StateTag state={related.request.workflow_state} />
                <Tag tone={related.relation_type === 'explicit_reask' ? 'warn' : 'neutral'}>
                  {label('relation', related.relation_type)}
                </Tag>
                {related.days_apart !== null && <span className="text-xs text-muted">{related.days_apart}d apart</span>}
              </div>
              <p className="mt-1 text-xs text-muted">{related.detail}</p>
              <p className="mt-0.5 truncate text-xs text-muted">
                {related.request.requester} · {related.request.target_title || related.request.target || 'target unresolved'}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Timeline({ data }: { data: IntakeResult }) {
  return (
    <Card title="Timeline" subtitle={data.request.state_evidence}>
      <ol className="space-y-2">
        {data.request.events.map((event, index) => (
          <li key={index} className="flex gap-3 text-sm">
            <span className="w-24 shrink-0 text-xs text-muted">{shortDate(event.occurred_at)}</span>
            <span className="min-w-0">
              <span className="font-medium">{label('event', event.event_type)}</span>
              {event.detail && <span className="text-muted"> — {event.detail}</span>}
              {event.actor && <span className="text-xs text-muted"> ({event.actor})</span>}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  )
}

export default function RequestPage() {
  const { requestId = '' } = useParams()
  const [data, setData] = useState<IntakeResult | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await api.intake(requestId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }, [requestId])

  useEffect(() => {
    void load()
  }, [load])

  if (error) return <ErrorNote error={error} />
  if (!data) return <Loading what="request" />

  return (
    <div className="space-y-4">
      <Link to="/queue" className="text-xs text-accent hover:underline">
        ← back to the queue
      </Link>
      <Hero data={data} />
      <PathsPanel data={data} onChange={setData} />
      <div className="grid gap-4 lg:grid-cols-2">
        <TargetPanel data={data} onChange={setData} />
        <ActivityPanel data={data} />
      </div>
      <Timeline data={data} />
    </div>
  )
}
