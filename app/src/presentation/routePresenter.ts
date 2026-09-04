/** How a candidate path reads on a route card.
 *
 *  The server orders the paths and says which it recommends; this module only
 *  decides which of the server's facts a collapsed card leads with. Nothing here
 *  re-ranks, scores or infers a relationship the payload does not assert.
 */

import { CandidatePath, RequestSummary } from '../lib/api'
import { Actionability, label } from './labels'

export interface RouteChain {
  connector: string
  /** "Sabine Dellinger · Chief Data Officer", or "Contact at Vantage Ridge" when unnamed. */
  via: string
  viaNamed: boolean
  /** The account the chain lands in. */
  account: string
  /** What the hop is, in operator words. */
  hop: string
}

export function routeChain(path: CandidatePath, request: RequestSummary): RouteChain {
  const account = path.contact?.organization?.name || request.account || 'the target account'
  if (path.contact) {
    const via = path.contact.title ? `${path.contact.name} · ${path.contact.title}` : path.contact.name
    return { connector: path.connector.name, via, viaNamed: true, account, hop: label('hop', path.hop_type) }
  }
  return {
    connector: path.connector.name,
    via: `Contact at ${account}`,
    viaNamed: false,
    account,
    hop: label('hop', path.hop_type),
  }
}

export type RouteStanding = 'selected' | 'rejected' | 'recommended' | 'alternative'

export function routeStanding(path: CandidatePath): RouteStanding {
  if (path.review_status === 'selected') return 'selected'
  if (path.review_status === 'rejected') return 'rejected'
  return path.recommended ? 'recommended' : 'alternative'
}

export const STANDING_WORDS: Record<RouteStanding, { text: string; level: Actionability }> = {
  selected: { text: 'Selected for validation', level: 'healthy' },
  rejected: { text: 'Ruled out', level: 'context' },
  recommended: { text: 'Recommended to investigate first', level: 'healthy' },
  alternative: { text: 'Alternative route', level: 'context' },
}

/** Selected route on top, then the server's order untouched. The recommendation
 *  tag stays where the server put it, but a card the operator has already
 *  chosen is never shown below one they have not. */
export function orderForDisplay(paths: CandidatePath[]): CandidatePath[] {
  const selected = paths.filter((path) => path.review_status === 'selected')
  const rest = paths.filter((path) => path.review_status !== 'selected')
  return [...selected, ...rest]
}

/** Once a route is selected, other cards stop claiming to be recommended first;
 *  the decision has been made and the label would contradict it. */
export function standingWithSelection(path: CandidatePath, anySelected: boolean): RouteStanding {
  const standing = routeStanding(path)
  if (anySelected && standing === 'recommended') return 'alternative'
  return standing
}

export interface RouteReasons {
  /** Up to two supporting factor sentences. */
  strengths: string[]
  /** The one caveat worth a collapsed card, or null. */
  caveat: string | null
  /** Connector over stated capacity, as a factor sentence, or null. */
  overCapacity: string | null
}

export function routeReasons(path: CandidatePath): RouteReasons {
  const supporting = path.factors.filter((factor) => factor.direction !== 'limiting')
  const limiting = path.factors.filter((factor) => factor.direction === 'limiting')
  const overCapacity = limiting.find((factor) => factor.key === 'connector_over_stated_capacity')
  const caveat = limiting.find((factor) => factor !== overCapacity)?.statement || path.limitations || null
  return {
    strengths: supporting.slice(0, 2).map((factor) => factor.statement),
    caveat,
    overCapacity: overCapacity?.statement ?? null,
  }
}

/** The concrete thing the operator does next with this route. Validation
 *  wording: whether the connector can reach the person, never that they will. */
export function routeAction(path: CandidatePath, request: RequestSummary): string {
  const chain = routeChain(path, request)
  const who = chain.viaNamed && path.contact ? path.contact.name : `a contact at ${chain.account}`
  return `Ask ${path.connector.name} to confirm whether they can reach ${who}`
}

/** Card-level tone: selected is healthy, over-capacity is a red caveat on the
 *  card body, rejected is context, otherwise neutral. */
export function routeLevel(path: CandidatePath, anySelected: boolean): Actionability {
  const standing = standingWithSelection(path, anySelected)
  if (standing === 'selected') return 'healthy'
  if (standing === 'rejected') return 'context'
  if (routeReasons(path).overCapacity) return 'act'
  return standing === 'recommended' ? 'healthy' : 'context'
}
