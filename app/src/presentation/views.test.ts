import { describe, expect, it } from 'vitest'
import { COHORTS, DEFAULT_VIEW, cohortCounts, inCohort, splitViews } from './queuePresenter'
import { denominatorWords, layout, metricLevel, metricTitle, slaEmptySentence } from './leadershipPresenter'
import { accessCoverage, coverageSummary, motionSummary, titleFamily } from './accountPresenter'
import { account, metric, request } from './fixtures.test-support'

describe('queue presentation', () => {
  it('opens on needs attention and keeps secondary views out of the primary row', () => {
    expect(DEFAULT_VIEW).toBe('needs_attention')
    const views = ['stale', 'needs_attention', 'all', 'overdue', 'completed', 'awaiting_connector', 'overlapping'].map((key) => ({
      key, label: key, definition: '',
    }))
    const { primary, secondary } = splitViews(views)
    expect(primary.map((view) => view.key)).toEqual(['needs_attention', 'awaiting_connector', 'overlapping', 'completed', 'all'])
    expect(secondary.map((view) => view.key)).toEqual(['stale', 'overdue'])
  })

  it('splits cohorts by origin only', () => {
    const items = [request({ origin: 'live_intake' }), request(), request()]
    expect(cohortCounts(items)).toEqual({ all: 3, live: 1, imported: 2 })
    expect(items.filter((item) => inCohort(item, 'live'))).toHaveLength(1)
    expect(COHORTS.map((cohort) => cohort.text)).toEqual(['All', 'Current workflow', 'Imported backlog'])
  })
})

describe('leadership presentation', () => {
  it('names each denominator and never shows a bare slash', () => {
    expect(denominatorWords(metric({ key: 'in_flight', denominator: 200 }))).toBe('of 200 requests')
    expect(denominatorWords(metric({ key: 'connectors_over_capacity', denominator: 6 }))).toBe('of 6 roster connectors')
    expect(denominatorWords(metric({ denominator: null }))).toBe('')
    expect(metricTitle(metric({ key: 'legacy_backlog' }))).toBe('Imported backlog awaiting review')
  })

  it('keeps legacy metrics out of current health and hides empty SLA cards', () => {
    const metrics = [
      metric({ key: 'overdue', denominator: 0 }),
      metric({ key: 'due_soon', denominator: 0 }),
      metric({ key: 'in_flight', value: 186, denominator: 200 }),
      metric({ key: 'legacy_backlog', value: 186, denominator: 200, group: 'legacy_backlog' }),
      metric({ key: 'legacy_backlog_quiet', value: 177, denominator: 186, group: 'legacy_backlog' }),
      metric({ key: 'outcome_unknown', value: 0, denominator: 200 }),
    ]
    const out = layout(metrics)
    expect(out.slaCards).toHaveLength(0)
    expect(out.slaEmpty.map((m) => m.key)).toEqual(['overdue', 'due_soon'])
    expect(out.primary.map((m) => m.key)).toEqual(['in_flight'])
    expect(out.legacyPrimary.map((m) => m.key)).toEqual(['legacy_backlog'])
    expect(out.legacySupporting.map((m) => m.key)).toEqual(['legacy_backlog_quiet'])
    expect(out.supporting.map((m) => m.key)).toEqual(['outcome_unknown'])
    expect(slaEmptySentence(0)).toMatch(/Imported review targets are reported separately/)
    expect(slaEmptySentence(3)).toBe('')
  })

  it('maps actionability from the metric, not its size alone', () => {
    expect(metricLevel(metric({ key: 'overdue', value: 1 }))).toBe('act')
    expect(metricLevel(metric({ key: 'overdue', value: 0 }))).toBe('healthy')
    expect(metricLevel(metric({ key: 'needs_ownership_review', value: 180 }))).toBe('verify')
    expect(metricLevel(metric({ key: 'legacy_backlog', value: 186, group: 'legacy_backlog' }))).toBe('context')
  })
})

describe('account access coverage', () => {
  const view = account({
    known_people: [
      { id: 1, display_name: 'Sabine Dellinger', title: 'Chief Data Officer', title_family: 'data' },
      { id: 2, display_name: 'Marc Ito', title: 'Controller', title_family: 'finance' },
      { id: 3, display_name: 'Lena Voss', title: 'VP Finance', title_family: 'finance' },
      { id: 4, display_name: 'Omar Haddad', title: 'CISO', title_family: 'security' },
      { id: 5, display_name: 'Zed Quill', title: 'Chief Vibes Officer', title_family: '' },
    ],
    coverage: {
      note: '', connector_count: 2, edge_count: 4, has_historically_observable_path: false,
      connectors: [
        { connector_id: 1, connector: 'Priya', on_roster: true, edge_count: 2, named_contacts: ['Marc Ito', 'Sabine Dellinger'], sources: [] },
        { connector_id: 2, connector: 'Tomás', on_roster: true, edge_count: 2, named_contacts: ['Lena Voss', 'Unknown Person'], sources: [] },
      ],
    },
  })

  it('classifies titles conservatively', () => {
    expect(titleFamily('Chief Information Security Officer')).toBe('security')
    expect(titleFamily('VP Data & Analytics')).toBe('data')
    expect(titleFamily('Chief Executive Officer')).toBe('executive')
    expect(titleFamily('Head of Widgets')).toBe('')
    expect(titleFamily(null)).toBe('')
  })

  it('derives per-function states from edges and titles only', () => {
    const coverage = accessCoverage(view)
    const state = Object.fromEntries(coverage.families.map((family) => [family.key, family.state]))
    expect(state.finance).toBe('multiple')
    expect(state.data).toBe('single')
    expect(state.security).toBe('indirect')
    expect(state.executive).toBe('none')
    expect(state.engineering).toBe('none')
    expect(coverage.unclassified).toBe(1)
    expect(coverage.untitled).toBe(1)
    for (const family of coverage.families) {
      expect(family.verdict).not.toMatch(/guarantee|strong relationship|likely|probab/i)
    }
  })

  it('summarises without promising an introduction', () => {
    const text = coverageSummary(accessCoverage(view))
    expect(text).toMatch(/^Observable routes into 2 of 8 functions; contacts known but unreached in 1\./)
    expect(text).toMatch(/not an introduction that is available/)
  })

  it('says when no title exists rather than reporting gaps', () => {
    const bare = accessCoverage(account({ known_people: [{ id: 1, display_name: 'A', title: '', title_family: '' }] }))
    expect(bare.families.every((family) => family.state === 'unknown')).toBe(true)
    expect(coverageSummary(bare)).toMatch(/cannot be judged by function/)
  })

  it('summarises account motion by state', () => {
    expect(motionSummary([])).toBe('Nothing in flight against this account.')
    expect(
      motionSummary([request({ workflow_state: 'PATH_REVIEW' }), request({ workflow_state: 'PATH_REVIEW' }), request({ workflow_state: 'COMPLETED' })]),
    ).toBe('2 open: 2 needs route review.')
  })
})
