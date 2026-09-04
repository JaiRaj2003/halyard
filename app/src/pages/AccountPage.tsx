/** Account view: where the network reaches into this account, what is already
 *  in flight against it, and the CRM facts underneath. Coverage is observed
 *  edges only. */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AccountView, api, ApiError, RequestSummary } from '../lib/api'
import {
  ActionLegend, ActionTag, Card, Disclosure, Empty, ErrorNote, Field, LEVEL_TEXT, Loading, StateTag, shortDate,
} from '../components/primitives'
import { ActionIcon } from '../components/icons'
import { accessCoverage, coverageSummary, motionSummary } from '../presentation/accountPresenter'
import { label, sourceLabel } from '../presentation/labels'
import { flags, liveFirst, targetHeadline, timing } from '../presentation/requestPresenter'

/** Where the network reaches into this account, by function rather than by
 *  contact. Derived entirely from the contacts and observed edges already on
 *  this page — it compresses them, and claims nothing they do not say. */
function AccessCoverage({ account }: { account: AccountView }) {
  const coverage = accessCoverage(account)
  return (
    <Card title="Access coverage by function" subtitle={coverageSummary(coverage)}>
      <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {coverage.families.map((family) => (
          <li key={family.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-line pb-2 last:border-0">
            <span className="w-44 shrink-0 text-sm font-medium">{family.label}</span>
            <ActionTag level={family.actionability}>{family.verdict}</ActionTag>
            <span className="min-w-0 flex-1 truncate text-xs text-muted">
              {family.connectors.length > 0
                ? `via ${family.connectors.join(', ')}`
                : family.contacts.length > 0
                  ? `${family.contacts.length} contact${family.contacts.length === 1 ? '' : 's'} known here`
                  : ''}
            </span>
          </li>
        ))}
      </ul>
      {(coverage.unclassified > 0 || coverage.untitled > 0) && (
        <p className="mt-3 text-xs text-muted">
          {coverage.unclassified > 0 &&
            `${coverage.unclassified} contact${coverage.unclassified === 1 ? '' : 's'} here hold a title that maps to no function above. `}
          {coverage.untitled > 0 &&
            `${coverage.untitled} contact${coverage.untitled === 1 ? '' : 's'} named by an edge have no title recorded. `}
          Neither counts towards coverage in either direction.
        </p>
      )}
    </Card>
  )
}

function RequestList({ items, empty }: { items: RequestSummary[]; empty: string }) {
  if (items.length === 0) return <Empty>{empty}</Empty>
  return (
    <ul className="divide-y divide-line">
      {liveFirst(items).map((item) => {
        const head = targetHeadline(item)
        const when = timing(item)
        const badges = flags(item).filter((flag) => !['overdue', 'due_soon', 'imported'].includes(flag.key))
        return (
          <li key={item.request_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
            <Link to={`/requests/${item.request_id}`} className="text-sm font-medium text-accent hover:underline">
              {head.headline}
            </Link>
            <span className="text-[11px] text-muted">{item.request_id}</span>
            <StateTag state={item.workflow_state} />
            {badges.map((flag) => (
              <ActionTag key={flag.key} level={flag.level}>{flag.text}</ActionTag>
            ))}
            <span className="ml-auto flex items-center gap-1.5 text-xs text-muted">
              {item.operational_owner}
              {when.kind !== 'none' && (
                <>
                  <span aria-hidden>·</span>
                  <span className={`flex items-center gap-1 ${LEVEL_TEXT[when.actionability]}`}>
                    <ActionIcon level={when.actionability} className="h-3 w-3" />
                    {when.label} {shortDate(when.dateIso)}
                  </span>
                </>
              )}
            </span>
          </li>
        )
      })}
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

  const issues = data.data_quality_issues.length + data.coverage_gaps.length
  const facts = [data.industry, data.hq, data.stage].filter(Boolean).join(' · ')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{data.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            {facts && <span>{facts}</span>}
            {data.arr_potential_usd ? <span>· ${data.arr_potential_usd.toLocaleString()} ARR potential</span> : null}
            {data.crm_owner && <span>· CRM owner {data.crm_owner}</span>}
            {!data.is_crm_account && <ActionTag level="verify">Observed only · no CRM record</ActionTag>}
            {data.review_status !== 'resolved' && (
              <ActionTag level="verify">{label('resolution', data.review_status)}</ActionTag>
            )}
          </p>
        </div>
        <ActionLegend />
      </div>

      <AccessCoverage account={data} />

      <Card title="Active on this account" subtitle={motionSummary(data.active_requests)}>
        <RequestList items={data.active_requests} empty="Nothing in flight." />
        {data.shares_domain_with.length > 0 && (
          <p className="mt-3 text-xs text-muted">
            <ActionTag level="context">Shared domain</ActionTag>{' '}
            Also used by {data.shares_domain_with.map((other) => other.name).join(', ')}. Separate CRM accounts stay
            separate; the shared domain is coordination context only.
          </p>
        )}
      </Card>

      <Card title="Routes and known contacts" subtitle={data.coverage.note}>
        {data.coverage.connectors.length === 0 ? (
          <Empty>No observed relationship reaches this account.</Empty>
        ) : (
          <table className="w-full text-left">
            <thead className="text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Connector</th>
                <th className="py-1 pr-3 font-medium">Reaches</th>
                <th className="py-1 font-medium">Observed relationships</th>
              </tr>
            </thead>
            <tbody>
              {data.coverage.connectors.map((row) => (
                <tr key={row.connector_id} className="border-t border-line align-top">
                  <td className="py-1.5 pr-3 text-sm">
                    {row.connector}
                    {!row.on_roster && <span className="block text-[11px] text-muted">Outside managed roster</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-sm">
                    {row.named_contacts.length > 0 ? row.named_contacts.join(', ') : <span className="text-muted">Contact at the account, unnamed</span>}
                  </td>
                  <td className="py-1.5 text-xs text-muted tabular-nums">
                    {row.edge_count} · {row.sources.length > 0 ? [...new Set(row.sources.map(sourceLabel))].join(', ') : 'Source not recorded'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!data.coverage.has_historically_observable_path && data.coverage.connectors.length > 0 && (
          <p className={`mt-3 flex items-center gap-1.5 text-xs ${LEVEL_TEXT.verify}`}>
            <ActionIcon level="verify" className="h-3 w-3" />
            None of these relationships is dated before its request; they are current network signal with historical timing unknown.
          </p>
        )}
        {data.known_people.length > 0 && (
          <div className="mt-3">
            <Disclosure summary={`People evidenced at this account (${data.known_people.length})`}>
              <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                {data.known_people.map((person) => (
                  <li key={person.id} className="text-sm">
                    {person.display_name}{' '}
                    <span className="text-xs text-muted">{person.title || 'title not recorded'}</span>
                  </li>
                ))}
              </ul>
            </Disclosure>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Prior introductions" subtitle="Introductions recorded as actually sent into this account.">
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
                  <span className="text-xs text-muted">{shortDate(intro.intro_date)}</span>
                  {intro.meeting_booked && <ActionTag level="healthy">Meeting booked</ActionTag>}
                  {intro.opportunity_created && <ActionTag level="healthy">Opportunity created</ActionTag>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Settled requests" subtitle="Completed or closed against this account.">
          <RequestList items={data.settled_requests} empty="Nothing settled yet." />
        </Card>
      </div>

      <Card title="CRM record">
        <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Field label="CRM account">{data.crm_account_id || 'Not a CRM account'}</Field>
          <Field label="Domain">{data.domain}</Field>
          <Field label="Industry">{data.industry}</Field>
          <Field label="HQ">{data.hq}</Field>
          <Field label="Employees">{data.employee_count ?? ''}</Field>
          <Field label="Stage">{data.stage}</Field>
          <Field label="ARR potential">{data.arr_potential_usd ? `$${data.arr_potential_usd.toLocaleString()}` : ''}</Field>
          <Field label="CRM owner">{data.crm_owner}</Field>
          <Field label="Requests">{String(data.request_count)}</Field>
          <Field label="People known">{String(data.known_people_count)}</Field>
        </dl>
        {data.match_evidence && (
          <p className="mt-3 text-xs text-muted">How this account was matched: {data.match_evidence}</p>
        )}
      </Card>

      {issues > 0 && (
        <Card
          title={`Data issues to review (${issues})`}
          subtitle="Unresolved questions in the source data that limit what can be claimed here."
        >
          <ul className="space-y-2">
            {data.data_quality_issues.map((issue, index) => (
              <li key={`issue-${index}`} className="text-xs">
                <ActionTag level={issue.severity === 'high' ? 'act' : 'verify'}>
                  {label('issue', issue.severity)}
                </ActionTag>{' '}
                <span className="text-muted">{issue.detail}</span>
              </li>
            ))}
            {data.coverage_gaps.map((gap, index) => (
              <li key={`gap-${index}`} className="text-xs">
                <ActionTag level="context">Coverage gap</ActionTag> <span className="text-muted">{gap.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
