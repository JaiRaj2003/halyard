import { describe, expect, it } from 'vitest'
import {
  STANDING_WORDS, orderForDisplay, routeAction, routeChain, routeReasons, standingWithSelection,
} from './routePresenter'
import { loadReading } from './loadPresenter'
import { path, request } from './fixtures.test-support'

const contact = {
  id: 9,
  name: 'Sabine Dellinger',
  title: 'Chief Data Officer',
  organization: {
    id: 12, name: 'Vantage Ridge Utilities', crm_account_id: 'A1001', domain: '', domain_group: '',
    is_crm_account: true, review_status: 'resolved', match_evidence: '', competing_candidates: [],
  },
}

describe('routeChain', () => {
  it('names the contact and title when the payload identifies one', () => {
    const chain = routeChain(path({ contact }), request())
    expect(chain.connector).toBe('Priya Natarajan')
    expect(chain.via).toBe('Sabine Dellinger · Chief Data Officer')
    expect(chain.viaNamed).toBe(true)
    expect(chain.account).toBe('Vantage Ridge Utilities')
  })

  it('falls back to an unnamed contact at the account', () => {
    const chain = routeChain(path(), request())
    expect(chain.via).toBe('Contact at Vantage Ridge Utilities')
    expect(chain.viaNamed).toBe(false)
  })
})

describe('selection', () => {
  const recommended = path({ id: 1, recommended: true })
  const other = path({ id: 2, connector: { id: 4, name: 'Tomás Beckett', on_roster: true, stated_monthly_capacity: 3 } })

  it('keeps a selected route on top regardless of server order', () => {
    const selected = { ...other, review_status: 'selected' }
    expect(orderForDisplay([recommended, selected]).map((p) => p.id)).toEqual([2, 1])
  })

  it('stops calling another route recommended once one is selected', () => {
    expect(standingWithSelection(recommended, false)).toBe('recommended')
    expect(standingWithSelection(recommended, true)).toBe('alternative')
    expect(standingWithSelection({ ...other, review_status: 'selected' }, true)).toBe('selected')
    expect(STANDING_WORDS.selected.text).toBe('Selected for validation')
  })
})

describe('routeReasons and routeAction', () => {
  it('leads with two supporting factors and one caveat, over-capacity kept apart', () => {
    const reasons = routeReasons(
      path({
        factors: [
          { key: 'a', statement: 'Connection existed before this request', direction: 'for' },
          { key: 'b', statement: 'Supported by two sources', direction: 'for' },
          { key: 'c', statement: 'Connector is on the managed roster', direction: 'for' },
          { key: 'connector_over_stated_capacity', statement: 'Connector is above stated capacity', direction: 'limiting' },
          { key: 'd', statement: 'No direct buyer relationship verified', direction: 'limiting' },
        ],
      }),
    )
    expect(reasons.strengths).toHaveLength(2)
    expect(reasons.caveat).toBe('No direct buyer relationship verified')
    expect(reasons.overCapacity).toBe('Connector is above stated capacity')
  })

  it('asks whether the connector can reach the person, never promises they will', () => {
    const action = routeAction(path({ contact }), request())
    expect(action).toBe('Ask Priya Natarajan to confirm whether they can reach Sabine Dellinger')
    expect(action).not.toMatch(/will|guarantee|intro(duce|duction) (is|available)/i)
  })
})

describe('loadReading', () => {
  it('reads high load, capacity and availability in plain words', () => {
    expect(loadReading(5, 4)).toMatchObject({ phrase: '5 active asks · stated capacity 4', verdict: 'High request load', level: 'act' })
    expect(loadReading(4, 4)).toMatchObject({ verdict: 'At stated capacity', level: 'verify' })
    expect(loadReading(1, 4)).toMatchObject({ phrase: '1 active ask · stated capacity 4', verdict: 'Available capacity', level: 'healthy' })
  })

  it('says when capacity is not tracked instead of inventing one', () => {
    expect(loadReading(2, null)).toMatchObject({ verdict: 'Capacity not tracked', level: 'context' })
  })

  it('defers to the server flag when it is present', () => {
    expect(loadReading(3, 4, true).verdict).toBe('High request load')
  })
})
