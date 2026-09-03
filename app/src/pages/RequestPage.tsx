/** Request detail: the whole working surface for one ask. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, CandidatePath, IntakeResult } from '../lib/api'
import {
  Button, Card, Empty, ErrorNote, Field, Loading, StateTag, Tag, relative, shortDate,
} from '../components/primitives'

function Header({ data }: { data: IntakeResult }) {
  const request = data.request
  return (
    <Card
      title={<span className="text-base">{request.request_id}</span>}
      subtitle={`${request.origin.replaceAll('_', ' ')} · raised ${relative(request.requested_at)}`}
      actions={
        <div className="flex items-center gap-2">
          <StateTag state={request.workflow_state} />
          {request.is_overdue && <Tag tone="bad">overdue</Tag>}
          {request.potentially_stale && <Tag tone="warn">quiet {Math.round(request.days_since_activity)}d</Tag>}
          {request.was_ownerless_at_ingest && <Tag tone="warn">ownership review</Tag>}
        </div>
      }
    >
      <blockquote className="border-l-2 border-line pl-3 text-sm italic text-ink">“{request.raw_ask}”</blockquote>
      <dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Field label="Account">{request.account}</Field>
        <Field label="Target">{request.target || request.target_title}</Field>
        <Field label="Requester">{request.requester}</Field>
        <Field label="Owner">
          {request.operational_owner}{' '}
          <span className="text-xs text-muted">({request.operational_owner_source.replaceAll('_', ' ')})</span>
        </Field>
        <Field label="Next action">{request.next_action}</Field>
        <Field label="Due">{shortDate(request.next_action_due_at)}</Field>
        <Field label="Route">{request.selected_connector ?? request.route_status.replaceAll('_', ' ').toLowerCase()}</Field>
        <Field label="Outcome">{request.outcome.toLowerCase()}</Field>
      </dl>
    </Card>
  )
}

function NextDecision({ data }: { data: IntakeResult }) {
  const decision = data.next_decision
  return (
    <div className={`rounded-lg border px-5 py-3 ${decision.blocking ? 'border-amber-200 bg-amber-50' : 'border-line bg-white'}`}>
      <p className="text-[11px] uppercase tracking-wide text-muted">Next decision</p>
      <p className="text-sm font-medium">{decision.prompt}</p>
    </div>
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
      subtitle={`Read from the ask by the ${data.parse.grammar.replaceAll('_', ' ')} rule (${data.parse.confidence} confidence). ${data.parse.evidence}`}
    >
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Field label="Account text">{data.parse.proposed.account_text}</Field>
        <Field label="Person">{data.parse.proposed.person_name}</Field>
        <Field label="Role">{data.parse.proposed.title}</Field>
        <Field label="Resolution">{target?.resolution_status ?? 'unresolved'}</Field>
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
                    {candidate.detail} · matched on {candidate.method.replaceAll('_', ' ')} ({candidate.confidence} confidence)
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
                  <p className="truncate text-xs text-muted">{candidate.detail} · {candidate.confidence} confidence</p>
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

function PathRow({ path, busy, onDecide }: {
  path: CandidatePath
  busy: boolean
  onDecide: (pathId: number, decision: 'confirm' | 'reject') => void
}) {
  const rejected = path.review_status === 'rejected'
  const selected = path.review_status === 'selected'
  return (
    <li className={`rounded-md border px-4 py-3 ${selected ? 'border-green-300 bg-green-50' : rejected ? 'border-line bg-slate-50 opacity-70' : 'border-line'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{path.connector.name}</span>
            {path.recommendation_label && <Tag tone="info">{path.recommendation_label}</Tag>}
            {selected && <Tag tone="good">selected route</Tag>}
            {rejected && <Tag>rejected</Tag>}
            {!path.connector.on_roster && <Tag tone="warn">not on managed roster</Tag>}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {path.hop_type.replaceAll('_', ' ')} · {path.observability.replaceAll('_', ' ')} · {path.confidence} confidence
            {path.relationship_date && ` · connected ${shortDate(path.relationship_date)}`}
          </p>
        </div>
        {!selected && !rejected && (
          <div className="flex gap-2">
            <Button disabled={busy} onClick={() => onDecide(path.id, 'confirm')}>
              Route here
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => onDecide(path.id, 'reject')}>
              Rule out
            </Button>
          </div>
        )}
      </div>
      <ul className="mt-2 grid gap-1 lg:grid-cols-2">
        {path.factors.filter((factor) => factor.present).map((factor) => (
          <li key={factor.key} className={`text-xs ${factor.direction === 'against' ? 'text-warn' : 'text-muted'}`}>
            {factor.direction === 'against' ? '! ' : '· '}
            {factor.detail || factor.label}
          </li>
        ))}
      </ul>
      {path.limitations && <p className="mt-2 text-xs text-warn">Limitation: {path.limitations}</p>}
      {path.evidence && <p className="mt-1 text-xs text-muted">Evidence: {path.evidence}</p>}
      {path.review_note && <p className="mt-1 text-xs text-muted">Note: {path.review_note}</p>}
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
    <Card title="Candidate paths" subtitle={data.paths.disclaimer}>
      {error && <div className="mb-3"><ErrorNote error={error} /></div>}
      {paths.length === 0 ? (
        <Empty>
          No observable path in the supplied network. The request stays active, owned and on the queue — it is not
          closed by the absence of evidence.
        </Empty>
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
                  {related.relation_type.replaceAll('_', ' ')}
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
              <span className="font-medium">{event.event_type.replaceAll('_', ' ')}</span>
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
      <Header data={data} />
      <NextDecision data={data} />
      <div className="grid gap-4 lg:grid-cols-2">
        <TargetPanel data={data} onChange={setData} />
        <ActivityPanel data={data} />
      </div>
      <PathsPanel data={data} onChange={setData} />
      <Timeline data={data} />
    </div>
  )
}
