import { describe, expect, it } from 'vitest'
import { attentionReasons, flags, liveFirst, ownerStatus, targetHeadline, timing } from './requestPresenter'
import { eventDetail, eventLabel, label } from './labels'
import { request } from './fixtures.test-support'

const NOW = new Date('2026-09-04T12:00:00Z').getTime()

describe('targetHeadline', () => {
  it('leads with the role and account when no person is confirmed', () => {
    const head = targetHeadline(request())
    expect(head.headline).toBe('Chief Operating Officer')
    expect(head.subline).toBe('Specific person not yet identified')
    expect(head.personConfirmed).toBe(false)
    expect(head.unconfirmedName).toBeNull()
  })

  it('keeps an unresolved source name as a lead, not the target', () => {
    const head = targetHeadline(request({ target: 'Perrine Salcedo-Oyelaran' }))
    expect(head.headline).toBe('Chief Operating Officer')
    expect(head.unconfirmedName).toBe('Perrine Salcedo-Oyelaran')
  })

  it('names the person only when resolution confirmed one', () => {
    const head = targetHeadline(request({ target: 'Dana Okafor', target_resolution_status: 'resolved' }))
    expect(head.headline).toBe('Dana Okafor')
    expect(head.personConfirmed).toBe(true)
  })
})

describe('timing', () => {
  it('reports an imported review target as context, never overdue', () => {
    const when = timing(request({ next_action_due_at: '2026-08-15T00:00:00Z', sla_managed: false }), NOW)
    expect(when.kind).toBe('legacy_target')
    expect(when.label).toBe('Legacy review target')
    expect(when.actionability).toBe('context')
  })

  it('marks a live action past its date as overdue and requiring action', () => {
    const when = timing(
      request({ origin: 'live_intake', sla_managed: true, legacy_backlog: false, next_action_due_at: '2026-09-01T00:00:00Z' }),
      NOW,
    )
    expect(when.kind).toBe('overdue')
    expect(when.actionability).toBe('act')
    expect(when.note).toBe('3d past due')
  })

  it('treats the next two days as due soon and later as healthy', () => {
    const soon = timing(request({ sla_managed: true, next_action_due_at: '2026-09-05T12:00:00Z' }), NOW)
    expect(soon.kind).toBe('due_soon')
    expect(soon.note).toBe('tomorrow')
    const later = timing(request({ sla_managed: true, next_action_due_at: '2026-09-11T12:00:00Z' }), NOW)
    expect(later.kind).toBe('due')
    expect(later.actionability).toBe('healthy')
  })

  it('has no timing once a request is settled', () => {
    expect(timing(request({ workflow_state: 'COMPLETED', sla_managed: true }), NOW).kind).toBe('none')
  })
})

describe('flags and ownership', () => {
  it('flags an imported request as backlog and a fallback owner as unconfirmed', () => {
    const item = request({ operational_owner_source: 'fallback_requester' })
    const keys = flags(item, NOW).map((flag) => flag.key)
    expect(keys).toContain('imported')
    expect(keys).toContain('owner')
    expect(keys).not.toContain('overdue')
    expect(keys).not.toContain('quiet')
    expect(ownerStatus(item).confirmed).toBe(false)
  })

  it('flags a live request as live and quiet only under Halyard', () => {
    const item = request({ origin: 'live_intake', legacy_backlog: false, sla_managed: true, potentially_stale: true, days_since_activity: 6 })
    const texts = flags(item, NOW).map((flag) => flag.text)
    expect(texts).toContain('Live request')
    expect(texts).toContain('Quiet 6d')
  })

  it('surfaces an unverified route as something to verify', () => {
    const [flag] = flags(request({ route_signal: 'unverified_suggested_route' }), NOW).filter((f) => f.key === 'unverified')
    expect(flag.level).toBe('verify')
  })
})

describe('liveFirst', () => {
  it('groups live requests ahead without reordering within a group', () => {
    const items = [request({ request_id: 'A' }), request({ request_id: 'B', origin: 'live_intake' }), request({ request_id: 'C' })]
    expect(liveFirst(items).map((item) => item.request_id)).toEqual(['B', 'A', 'C'])
  })
})

describe('labels', () => {
  it('never renders internal enum values', () => {
    expect(label('state', 'NEEDS_ENTITY_REVIEW')).toBe('Needs target confirmation')
    expect(label('state', 'NO_OBSERVABLE_PATH')).not.toMatch(/[A-Z_]{5,}/)
    expect(label('observability', 'snapshot_only')).not.toContain('snapshot_only')
  })

  it('translates transition events into state words', () => {
    expect(eventLabel('transition:NEEDS_TRIAGE->PATH_REVIEW')).toBe(
      `${label('state', 'NEEDS_TRIAGE')} → ${label('state', 'PATH_REVIEW')}`,
    )
    expect(eventLabel(null)).toBe('')
  })

  it('rewrites internal tokens quoted inside server event detail', () => {
    expect(eventDetail('intake; operational owner resolved via fallback_requester (Dana Whitfield)')).toBe(
      'intake; operational owner resolved via the requester, as fallback (Dana Whitfield)',
    )
    expect(eventDetail('moved to PATH_REVIEW after snapshot_only edge found')).not.toMatch(/PATH_REVIEW|snapshot_only/)
    expect(eventDetail('Ownership confirmed in review')).toBe('Ownership confirmed in review')
    expect(eventDetail(null)).toBe('')
  })
})

describe('attentionReasons', () => {
  it('describes a fallback owner at import for imported requests only', () => {
    const imported = attentionReasons(request({ operational_owner_source: 'fallback_requester' }), NOW)
    expect(imported.join(' ')).toContain('at import')

    const live = attentionReasons(
      request({ origin: 'live_intake', sla_managed: true, operational_owner_source: 'fallback_requester' }),
      NOW,
    )
    expect(live.join(' ')).not.toContain('import')
    expect(live.join(' ')).toContain('requester holds ownership')
  })
})
