/** Request detail: the whole working surface for one ask. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, CandidatePath, IntakeResult } from '../lib/api'
import {
  ActionTag, Button, Callout, Card, Disclosure, Empty, ErrorNote, Field, LEVEL_PANEL, LEVEL_TEXT, Loading, StateTag,
  Tag, relative, shortDate,
} from '../components/primitives'
import { ActionIcon, ArrowIcon } from '../components/icons'
import { eventDetail, eventLabel, label, sourceLabel } from '../presentation/labels'
import {
  attentionReasons, flags, nextActionSource, ownerStatus, primaryCta, targetHeadline, timing,
} from '../presentation/requestPresenter'
import {
  STANDING_WORDS, orderForDisplay, routeAction, routeChain, routeReasons, standingWithSelection,
} from '../presentation/routePresenter'

function scrollTo(anchor: string) {
  document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** Target, status, owner, next action — in that order, above everything else. */
function Hero({ data, onChange }: { data: IntakeResult; onChange: (result: IntakeResult) => void }) {
  const request = data.request
  const head = targetHeadline(request, request.target_detail)
  const when = timing(request)
  const owner = ownerStatus(request)
  const cta = primaryCta(data)
  const badges = flags(request).filter((flag) => flag.key !== 'owner')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function confirmOwner() {
    setBusy(true)
    setError('')
    try {
      await api.setOwner(request.request_id, {
        operational_owner_id: request.operational_owner_id,
        note: 'Ownership confirmed in review',
      })
      onChange(await api.intake(request.request_id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-lg border border-line bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-6 px-6 pt-5">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 text-[11px] uppercase tracking-wide text-muted">
            <span>{request.request_id}</span>
            <span aria-hidden>·</span>
            <span>{label('origin', request.origin)}</span>
            <span aria-hidden>·</span>
            <span>
              {request.origin === 'live_intake' ? 'raised' : 'first asked'} {shortDate(request.requested_at)}
            </span>
          </p>
          <h1 className="mt-1 text-2xl font-semibold leading-tight tracking-tight">{head.headline}</h1>
          <p className="mt-0.5 text-base">
            {head.accountId ? (
              <Link to={`/accounts/${head.accountId}`} className="font-medium text-accent hover:underline">
                {head.account}
              </Link>
            ) : (
              <span className="font-medium">{head.account || 'Account not yet identified'}</span>
            )}
            <span className="text-muted"> · {head.subline}</span>
          </p>
          {head.unconfirmedName && (
            <p className="mt-1 text-sm text-muted">
              Named in the source as <span className="text-ink">{head.unconfirmedName}</span> · unconfirmed
            </p>
          )}
        </div>

        <dl className="grid w-full shrink-0 grid-cols-2 gap-x-8 gap-y-3 sm:w-auto">
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Status</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-1.5">
              <StateTag state={request.workflow_state} />
              {badges.map((flag) => (
                <ActionTag key={flag.key} level={flag.level}>{flag.text}</ActionTag>
              ))}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted">Owner</dt>
            <dd className="mt-1 text-sm font-medium">{owner.name}</dd>
            <dd className="mt-1 flex flex-wrap items-center gap-1.5">
              {owner.confirmed ? (
                <span className="text-xs text-muted">{owner.note}</span>
              ) : (
                <>
                  <ActionTag level="verify">{owner.flag}</ActionTag>
                  <Button size="sm" variant="secondary" disabled={busy} onClick={confirmOwner}>
                    Confirm owner
                  </Button>
                </>
              )}
            </dd>
          </div>
        </dl>
      </div>
      {error && <div className="px-6 pt-3"><ErrorNote error={error} /></div>}

      <div className={`mt-5 flex flex-wrap items-start justify-between gap-4 border-t px-6 py-4 ${LEVEL_PANEL[when.actionability === 'act' ? 'act' : 'context']}`}>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Next action</p>
          <p className="mt-0.5 text-lg font-semibold leading-snug">
            {request.next_action || 'Nothing outstanding — this request is settled.'}
          </p>
          <p className="mt-1 text-xs text-muted">{nextActionSource(request)}</p>
        </div>
        {when.kind !== 'none' && (
          <div className="text-right">
            <p className={`flex items-center justify-end gap-1 text-[11px] font-semibold uppercase tracking-wide ${LEVEL_TEXT[when.actionability]}`}>
              <ActionIcon level={when.actionability} className="h-3 w-3" />
              {when.label}
            </p>
            <p className={`mt-0.5 text-lg font-semibold tabular-nums ${when.actionability === 'act' ? 'text-bad' : ''}`}>
              {shortDate(when.dateIso)}
            </p>
            <p className="text-xs text-muted">{when.note}</p>
          </div>
        )}
        {cta.kind !== 'none' && cta.kind !== 'confirm_owner' && (
          <div className="flex w-full justify-end sm:w-auto sm:self-center">
            <Button onClick={() => scrollTo(cta.anchor)}>
              {cta.text}
              <ArrowIcon className="ml-1.5 h-3 w-3" />
            </Button>
          </div>
        )}
        {cta.kind === 'confirm_owner' && (
          <div className="flex w-full justify-end sm:w-auto sm:self-center">
            <Button disabled={busy} onClick={confirmOwner}>{cta.text}</Button>
          </div>
        )}
      </div>
    </section>
  )
}

function Attention({ data }: { data: IntakeResult }) {
  const reasons = attentionReasons(data.request)
  if (reasons.length === 0) return null
  const request = data.request
  const level = request.workflow_state === 'BLOCKED' || timing(request).kind === 'overdue' ? 'act' : 'verify'
  return (
    <Callout level={level} title={reasons.length === 1 ? 'Why this needs attention' : `Why this needs attention (${reasons.length})`}>
      <ul className="space-y-0.5">
        {reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </Callout>
  )
}

function TargetPanel({ data, onChange }: { data: IntakeResult; onChange: (result: IntakeResult) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const target = data.request.target_detail
  const head = targetHeadline(data.request, target)

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

  const ambiguous = data.account_candidates.length > 1 || data.person_candidates.length > 1
  const resolution = target?.resolution_status ?? 'unresolved'
  const resolutionLevel = head.personConfirmed ? 'healthy' : ambiguous ? 'verify' : 'context'

  return (
    <Card id="target" title="Target" subtitle="What the ask names, and what the supplied data can confirm.">
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Field label="Role">{head.personConfirmed ? head.subline : head.headline}</Field>
        <Field label="Account">{head.account}</Field>
        <Field label="Named person" wrap>
          {head.personConfirmed ? head.headline : head.unconfirmedName || <span className="text-muted">Not named</span>}
        </Field>
        <Field label="Identification" wrap>
          <ActionTag level={resolutionLevel}>{label('resolution', resolution)}</ActionTag>
        </Field>
      </dl>

      {data.parse.warnings.length > 0 && (
        <ul className="mt-3 space-y-1">
          {data.parse.warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-1.5 text-xs text-warn">
              <ActionIcon level="verify" className="mt-0.5 h-3 w-3 shrink-0" />
              {warning}
            </li>
          ))}
        </ul>
      )}

      {error && <div className="mt-3"><ErrorNote error={error} /></div>}

      {data.account_candidates.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">
            {data.account_candidates.length === 1 ? 'Account match' : `${data.account_candidates.length} possible accounts — pick one`}
          </p>
          <ul className="mt-2 space-y-2">
            {data.account_candidates.map((candidate) => (
              <li key={candidate.id} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{candidate.label}</p>
                  <p className="truncate text-xs text-muted">
                    {candidate.detail} · {label('match_method', candidate.method)} · {label('confidence', candidate.confidence).toLowerCase()}
                  </p>
                  {candidate.account?.competing_candidates?.map((note) => (
                    <p key={note} className="truncate text-xs text-warn">{note}</p>
                  ))}
                </div>
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => confirm({ account_id: candidate.id })}>
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
            {data.person_candidates.length === 1 ? 'Person match' : `${data.person_candidates.length} possible people — pick one`}
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
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => confirm({ person_id: candidate.id })}>
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

      <div className="mt-4 border-t border-line pt-3">
        <Disclosure summary="How the target was read">
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Field label="Account text" wrap>{data.parse.proposed.account_text}</Field>
            <Field label="Person text" wrap>{data.parse.proposed.person_name}</Field>
            <Field label="Role text" wrap>{data.parse.proposed.title}</Field>
            <Field label="Parse" wrap>{label('confidence', data.parse.confidence)}</Field>
          </dl>
          <p className="mt-2 text-xs text-muted">{data.parse.evidence}</p>
          {target?.resolution_evidence && <p className="mt-1 text-xs text-muted">{target.resolution_evidence}</p>}
        </Disclosure>
      </div>
    </Card>
  )
}

/** One route, read top-down: who, how it lands, why, what is wrong with it.
 *
 *  Collapsed it carries only what a routing decision needs. Everything the
 *  ordering used — every factor, the provenance, the timing, the connector's
 *  load — stays one click away under "Why this?", never deleted.
 */
function PathRow({ path, data, anySelected, busy, onDecide }: {
  path: CandidatePath
  data: IntakeResult
  anySelected: boolean
  busy: boolean
  onDecide: (pathId: number, decision: 'confirm' | 'reject') => void
}) {
  const request = data.request
  const standing = standingWithSelection(path, anySelected)
  const words = STANDING_WORDS[standing]
  const chain = routeChain(path, request)
  const reasons = routeReasons(path)
  const open = standing !== 'selected' && standing !== 'rejected'
  const frame = standing === 'selected' ? LEVEL_PANEL.healthy
    : standing === 'rejected' ? 'border-line bg-slate-50 opacity-60'
    : standing === 'recommended' ? 'border-blue-200 bg-white shadow-sm'
    : 'border-line bg-white'

  return (
    <li className={`rounded-lg border px-4 py-3.5 ${frame}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold">{path.connector.name}</span>
            {standing === 'recommended' ? (
              <Tag tone="info" icon="healthy">{words.text}</Tag>
            ) : (
              <ActionTag level={words.level}>{words.text}</ActionTag>
            )}
          </div>

          <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-sm">
            <span className="font-medium">{chain.connector}</span>
            <ArrowIcon className="h-3 w-3 text-muted" />
            <span className={chain.viaNamed ? 'font-medium' : 'text-muted'}>{chain.via}</span>
            <ArrowIcon className="h-3 w-3 text-muted" />
            <span>{chain.account}</span>
          </p>
          <p className="text-xs text-muted">{chain.hop}</p>

          <ul className="mt-2 space-y-0.5">
            {reasons.strengths.map((statement) => (
              <li key={statement} className="flex items-start gap-1.5 text-sm text-ink">
                <ActionIcon level="healthy" className="mt-1 h-3 w-3 shrink-0 text-green-700" />
                <span>{statement}</span>
              </li>
            ))}
            {reasons.overCapacity && (
              <li className="flex items-start gap-1.5 text-sm text-bad">
                <ActionIcon level="act" className="mt-1 h-3 w-3 shrink-0" />
                <span>{reasons.overCapacity}</span>
              </li>
            )}
            {reasons.caveat && (
              <li className="flex items-start gap-1.5 text-sm text-warn">
                <ActionIcon level="verify" className="mt-1 h-3 w-3 shrink-0" />
                <span>{reasons.caveat}</span>
              </li>
            )}
          </ul>

          {standing === 'selected' && (
            <p className={`mt-2 text-sm font-medium ${LEVEL_TEXT.healthy}`}>
              Next: {request.next_action || routeAction(path, request)}
            </p>
          )}
        </div>

        {open && (
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <Button disabled={busy} onClick={() => onDecide(path.id, 'confirm')}>
              Select for validation
            </Button>
            <Button variant="quiet" size="sm" disabled={busy} onClick={() => onDecide(path.id, 'reject')}>
              Rule out
            </Button>
          </div>
        )}
      </div>

      <div className="mt-3 border-t border-line pt-2.5">
        <Disclosure summary="Why this?">
          <ul className="grid gap-1 lg:grid-cols-2">
            {path.factors.map((factor) => (
              <li key={factor.key} className={`flex items-start gap-1.5 text-xs ${factor.direction === 'limiting' ? 'text-warn' : 'text-ink'}`}>
                <ActionIcon level={factor.direction === 'limiting' ? 'verify' : 'healthy'} className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{factor.statement}</span>
              </li>
            ))}
          </ul>
          <dl className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Field label="Timing" wrap>{label('observability', path.observability)}</Field>
            <Field label="Evidence strength" wrap>{label('confidence', path.confidence)}</Field>
            <Field label="Connected" wrap>{path.relationship_date ? shortDate(path.relationship_date) : 'No date recorded'}</Field>
            <Field label="Connector" wrap>
              {path.connector.on_roster ? 'On the managed roster' : 'Observed, outside the managed roster'}
            </Field>
          </dl>
          <p className="mt-2 text-xs text-muted">
            {path.factors.find((factor) => factor.key === 'connector_recent_ask')?.statement
              ?? 'No ask recorded against this connector in the current window'}
            {path.connector.stated_monthly_capacity !== null
              ? ` · stated capacity ${path.connector.stated_monthly_capacity} a month.`
              : ' · capacity not stated.'}
            {path.connector.note ? ` ${path.connector.note}` : ''}
          </p>
          {path.limitations && <p className="mt-1 text-xs text-warn">Limitation: {path.limitations}</p>}
          {path.evidence && <p className="mt-1 text-xs text-muted">Evidence: {path.evidence}</p>}
          {path.source_file && (
            <p className="mt-1 text-xs text-muted">Source: {sourceLabel(path.source_file)} ({path.source_file})</p>
          )}
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

  const paths = orderForDisplay(data.paths.paths)
  const anySelected = paths.some((path) => path.review_status === 'selected')
  const request = data.request
  return (
    <Card id="routes" title="Routes to investigate" subtitle={data.paths.disclaimer} tone={paths.length > 0 ? 'accent' : 'default'}>
      {error && <div className="mb-3"><ErrorNote error={error} /></div>}
      {paths.length === 0 ? (
        request.route_signal === 'unverified_suggested_route' ? (
          <Callout level="verify" title="Unverified route suggested in the source thread — validate before routing">
            <p>
              {request.suggested_route_person || 'Someone'} may hold a route. The supplied network does not corroborate
              it, so it is not a candidate path and is not shown as one.
            </p>
            {request.suggested_route_evidence && <p className="mt-1 text-xs text-muted">{request.suggested_route_evidence}</p>}
          </Callout>
        ) : (
          <Empty>
            {data.paths.note || 'No route signal: neither the supplied network nor any message in the thread offers a route.'}{' '}
            The request stays active, owned and on the queue — it is not closed by the absence of evidence.
          </Empty>
        )
      ) : (
        <>
          <p className="mb-3 text-xs text-muted">{data.paths.ordering}</p>
          <ul className="space-y-3">
            {paths.map((path) => (
              <PathRow key={path.id} path={path} data={data} anySelected={anySelected} busy={busy} onDecide={decide} />
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}

function ActivityPanel({ data }: { data: IntakeResult }) {
  return (
    <Card title="Other activity on this account" subtitle={data.account_activity_note}>
      {data.account_activity.length === 0 ? (
        <Empty>No other request touches this account.</Empty>
      ) : (
        <ul className="space-y-2">
          {data.account_activity.map((related) => {
            const head = targetHeadline(related.request)
            return (
              <li key={related.request.request_id} className="rounded-md border border-line px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/requests/${related.request.request_id}`} className="text-sm font-medium text-accent hover:underline">
                    {head.headline}
                  </Link>
                  <StateTag state={related.request.workflow_state} />
                  <ActionTag level={related.relation_type === 'explicit_reask' ? 'verify' : 'context'}>
                    {label('relation', related.relation_type)}
                  </ActionTag>
                  {related.days_apart !== null && <span className="text-xs text-muted">{related.days_apart}d apart</span>}
                </div>
                <p className="mt-1 text-xs text-muted">{related.detail}</p>
                <p className="mt-0.5 truncate text-xs text-muted">
                  {related.request.request_id} · asked by {related.request.requester} · owner {related.request.operational_owner}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function Timeline({ data }: { data: IntakeResult }) {
  const events = [...data.request.events].reverse()
  const recent = events.slice(0, 6)
  const older = events.slice(6)
  const row = (event: (typeof events)[number], index: number) => (
    <li key={`${event.event_type}-${event.occurred_at}-${index}`} className="flex gap-3 text-sm">
      <span className="w-24 shrink-0 text-xs text-muted">{shortDate(event.occurred_at)}</span>
      <span className="min-w-0">
        <span className="font-medium">{eventLabel(event.event_type)}</span>
        {event.detail && <span className="text-muted"> — {eventDetail(event.detail)}</span>}
        {event.actor && <span className="text-xs text-muted"> ({event.actor})</span>}
      </span>
    </li>
  )
  return (
    <Card title="Timeline" subtitle={events.length === 0 ? undefined : `${events.length} recorded events, newest first`}>
      {events.length === 0 ? (
        <Empty>Nothing recorded yet beyond creation.</Empty>
      ) : (
        <>
          <ol className="space-y-2">{recent.map(row)}</ol>
          {older.length > 0 && (
            <div className="mt-3">
              <Disclosure summary={`Earlier events (${older.length})`}>
                <ol className="space-y-2">{older.map((event, index) => row(event, index + recent.length))}</ol>
              </Disclosure>
            </div>
          )}
        </>
      )}
    </Card>
  )
}

function RequestRecord({ data }: { data: IntakeResult }) {
  const request = data.request
  return (
    <Card title="Request record" tone="quiet">
      <blockquote className="border-l-2 border-line pl-3 text-sm italic text-muted">“{request.raw_ask}”</blockquote>
      <dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Field label="Requested by">{request.requester}</Field>
        <Field label="Owner assigned" wrap>{label('owner_source', request.operational_owner_source)}</Field>
        <Field label="Route">{request.selected_connector ?? label('route_status', request.route_status)}</Field>
        <Field label="Outcome">{label('outcome', request.outcome)}</Field>
        <Field label="Last activity">{relative(request.last_activity_at)}</Field>
        <Field label="Route evidence">{label('route_signal', request.route_signal)}</Field>
        <Field label="Target status">{label('resolution', request.target_resolution_status)}</Field>
        <Field label="Deal context">
          {request.urgency ? `${request.urgency} urgency` : ''}
          {request.deal_value_usd ? ` · $${request.deal_value_usd.toLocaleString()}` : ''}
        </Field>
      </dl>
      <div className="mt-4">
        <Disclosure summary="How this status was reached">
          <p className="text-xs text-muted">{request.state_evidence}</p>
          {request.operationalized_at && (
            <p className="mt-1 text-xs text-muted">Brought under Halyard {shortDate(request.operationalized_at)}.</p>
          )}
          {request.target_detail && (
            <p className="mt-1 text-xs text-muted">
              Source target text: “{request.target_detail.raw_target_text}”
            </p>
          )}
        </Disclosure>
      </div>
    </Card>
  )
}

/** Shown once, straight after intake: proof the request already exists and is owned. */
function SavedBanner({ data, onDismiss }: { data: IntakeResult; onDismiss: () => void }) {
  const request = data.request
  const when = timing(request)
  return (
    <Callout
      level="healthy"
      title={`Request saved as ${request.request_id}`}
      actions={<Button size="sm" variant="secondary" onClick={onDismiss}>Dismiss</Button>}
    >
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        <li>Owner assigned: <span className="font-medium">{request.operational_owner}</span></li>
        <li>
          Next action: <span className="font-medium">{request.next_action}</span>
          {when.dateIso && <span className="text-muted"> · due {shortDate(when.dateIso)}</span>}
        </li>
        <li>Original text kept as written.</li>
      </ul>
    </Callout>
  )
}

export default function RequestPage() {
  const { requestId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const justSaved = params.get('saved') === '1'
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
        ← Back to the queue
      </Link>
      {justSaved && <SavedBanner data={data} onDismiss={() => setParams({}, { replace: true })} />}
      <Hero data={data} onChange={setData} />
      <Attention data={data} />
      <PathsPanel data={data} onChange={setData} />
      <div className="grid gap-4 lg:grid-cols-2">
        <TargetPanel data={data} onChange={setData} />
        <ActivityPanel data={data} />
      </div>
      <Timeline data={data} />
      <RequestRecord data={data} />
    </div>
  )
}
