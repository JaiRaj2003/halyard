/** Account view: CRM facts, what the network actually covers, and everything
 *  already in flight against this account. Coverage is observed edges only. */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AccountView, api, ApiError, RequestSummary } from '../lib/api'
import { Card, Empty, ErrorNote, Field, Loading, StateTag, Tag, relative, shortDate } from '../components/primitives'
import { label } from '../lib/labels'

function RequestList({ items, empty }: { items: RequestSummary[]; empty: string }) {
  if (items.length === 0) return <Empty>{empty}</Empty>
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <li key={item.request_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
          <Link to={`/requests/${item.request_id}`} className="text-sm font-medium text-accent hover:underline">
            {item.request_id}
          </Link>
          <span className="text-sm">{item.target_title || item.target || 'target unresolved'}</span>
          <StateTag state={item.workflow_state} />
          {item.sla_breached && <Tag tone="bad">overdue</Tag>}
          {item.legacy_backlog && <Tag>legacy backlog</Tag>}
          {item.potentially_stale && item.sla_managed && <Tag tone="warn">quiet {item.days_since_activity}d</Tag>}
          <span className="ml-auto text-xs text-muted">
            {item.operational_owner} · {relative(item.last_activity_at)}
          </span>
        </li>
      ))}
    </ul>
  )
}

export default function AccountPage() {
  const { accountId } = useParams()
  const [data, setData] = useState<AccountView | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setData(null)
    setError('')
    api
      .accountView(Number(accountId))
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
  }, [accountId])

  if (error) return <ErrorNote error={error} />
  if (!data) return <Loading what="account" />

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{data.name}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
          {data.crm_account_id ? `CRM ${data.crm_account_id}` : 'not a CRM account'}
          {data.domain && <span>· {data.domain}</span>}
          {!data.is_crm_account && <Tag tone="warn">observed only, no CRM record</Tag>}
          {data.review_status !== 'resolved' && <Tag tone="warn">{label('resolution', data.review_status)}</Tag>}
        </p>
      </div>

      <Card title="CRM">
        <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Field label="Industry">{data.industry}</Field>
          <Field label="HQ">{data.hq}</Field>
          <Field label="Employees">{data.employee_count ?? ''}</Field>
          <Field label="Stage">{data.stage}</Field>
          <Field label="ARR potential">{data.arr_potential_usd ? `$${data.arr_potential_usd.toLocaleString()}` : ''}</Field>
          <Field label="CRM owner">{data.crm_owner}</Field>
          <Field label="Requests">{String(data.request_count)}</Field>
          <Field label="People known">{String(data.known_people_count)}</Field>
        </dl>
        {data.shares_domain_with.length > 0 && (
          <p className="mt-3 text-xs text-warn">
            Shares a domain with {data.shares_domain_with.map((other) => other.name).join(', ')}. Separate CRM accounts are
            kept separate; the shared domain is coordination context only.
          </p>
        )}
        {data.match_evidence && <p className="mt-2 text-xs text-muted">Match evidence: {data.match_evidence}</p>}
      </Card>

      <Card title="Network coverage" subtitle={data.coverage.note}>
        {data.coverage.connectors.length === 0 ? (
          <Empty>No observed relationship reaches this account.</Empty>
        ) : (
          <table className="w-full text-left">
            <thead className="text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Connector</th>
                <th className="py-1 pr-3 font-medium">Observed edges</th>
                <th className="py-1 pr-3 font-medium">Named contacts</th>
                <th className="py-1 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {data.coverage.connectors.map((row) => (
                <tr key={row.connector_id} className="border-t border-line align-top">
                  <td className="py-1.5 pr-3 text-sm">
                    {row.connector} {!row.on_roster && <Tag tone="warn">not on roster</Tag>}
                  </td>
                  <td className="py-1.5 pr-3 text-sm tabular-nums">{row.edge_count}</td>
                  <td className="py-1.5 pr-3 text-xs text-muted">{row.named_contacts.join(', ') || '—'}</td>
                  <td className="py-1.5 text-xs text-muted">{row.sources.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!data.coverage.has_historically_observable_path && data.coverage.connectors.length > 0 && (
          <p className="mt-3 text-xs text-warn">
            No candidate path here was observable before its request was made. Edges shown are snapshot-only evidence.
          </p>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Active requests" subtitle="Everything currently in flight against this account.">
          <RequestList items={data.active_requests} empty="Nothing in flight." />
        </Card>
        <Card title="Settled requests" subtitle="Completed, closed, or recorded with no observable path.">
          <RequestList items={data.settled_requests} empty="Nothing settled yet." />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Prior observed introductions" subtitle="Introductions recorded as actually sent.">
          {data.prior_observed_introductions.length === 0 ? (
            <Empty>No introduction into this account was ever recorded as sent.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {data.prior_observed_introductions.map((intro) => (
                <li key={`${intro.request_id}-${intro.connector}`} className="flex flex-wrap items-baseline gap-2 py-2 text-sm">
                  <Link to={`/requests/${intro.request_id}`} className="font-medium text-accent hover:underline">
                    {intro.request_id}
                  </Link>
                  <span>via {intro.connector}</span>
                  <span className="text-xs text-muted">intro {shortDate(intro.intro_date)}</span>
                  {intro.meeting_booked && <Tag tone="good">meeting booked</Tag>}
                  {intro.opportunity_created && <Tag tone="good">opportunity</Tag>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Known people" subtitle="People evidenced at this account across the supplied sources.">
          {data.known_people.length === 0 ? (
            <Empty>No individual at this account is resolvable from the supplied data.</Empty>
          ) : (
            <ul className="space-y-1">
              {data.known_people.slice(0, 12).map((person) => (
                <li key={person.id} className="text-sm">
                  {person.display_name} <span className="text-xs text-muted">{person.title}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {(data.data_quality_issues.length > 0 || data.coverage_gaps.length > 0) && (
        <Card title="Open data questions" subtitle="Unresolved issues affecting what can be claimed here.">
          <ul className="space-y-2">
            {data.data_quality_issues.map((issue, index) => (
              <li key={`issue-${index}`} className="text-xs">
                <Tag tone={issue.severity === 'high' ? 'bad' : 'warn'}>{label('issue', issue.severity)}</Tag>{' '}
                <span className="text-muted">{issue.detail}</span>
              </li>
            ))}
            {data.coverage_gaps.map((gap, index) => (
              <li key={`gap-${index}`} className="text-xs">
                <Tag>Coverage gap</Tag> <span className="text-muted">{gap.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
