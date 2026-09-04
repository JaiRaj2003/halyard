/** Persona-level access coverage for one account.
 *
 *  The account page already lists connectors, their observed edge counts and
 *  the contacts they name, plus every person evidenced at the account with a
 *  recorded title. Read one contact at a time that answers "who do we know";
 *  compressed by function it answers the question an operator actually has:
 *  *where do we have observable access, and where do we have none*.
 *
 *  Nothing here is fetched or inferred beyond that join. A family is covered
 *  only when an observed relationship edge names a contact whose recorded title
 *  falls in it — an edge is where to investigate, never an introduction that is
 *  available. Where the data cannot say, the state says so rather than guessing:
 *  a title we do not recognise leaves the family at "not enough data", not at
 *  "no route".
 *
 *  The vocabulary mirrors the server's `halyard/services/relevance.py` groups
 *  so the two never contradict each other on screen, but this is presentation
 *  only: nothing here feeds ranking.
 */

import { AccountView } from './api'
import { Actionability } from './labels'

interface Family {
  key: string
  label: string
  /** Matched against the lower-cased title, longest-first, first hit wins. */
  words: string[]
}

/** Ordered: a "VP Data & Analytics" is data before it is technology, and a
 *  security title never falls through to the generic technology bucket. */
const FAMILIES: Family[] = [
  { key: 'security', label: 'Security', words: ['ciso', 'security', 'infosec', 'trust and safety'] },
  { key: 'finance', label: 'Finance', words: ['cfo', 'finance', 'financial', 'controller', 'treasurer', 'accounting', 'procurement'] },
  { key: 'data', label: 'Data & analytics', words: ['chief data', 'data', 'analytics', 'machine learning', 'insights'] },
  { key: 'engineering', label: 'Engineering & technology', words: ['cto', 'cio', 'chief technology', 'chief information officer', 'chief digital', 'engineering', 'engineer', 'technology', 'technical', 'architecture', 'architect', 'platform', 'infrastructure', 'devops', 'developer', 'it'] },
  { key: 'product', label: 'Product', words: ['product', 'design', 'ux'] },
  { key: 'operations', label: 'Operations', words: ['coo', 'operations', 'operating', 'supply chain', 'logistics', 'program manager', 'automation'] },
  { key: 'marketing', label: 'Marketing', words: ['cmo', 'marketing', 'brand', 'demand generation', 'communications', 'growth'] },
  { key: 'executive', label: 'Executive leadership', words: ['ceo', 'chief executive', 'president', 'founder', 'general manager', 'managing director', 'chief of staff', 'innovation'] },
]

/** Families always shown, so an absence of access is as visible as its presence. */
const ALWAYS_SHOWN = new Set(['executive', 'finance', 'security', 'engineering'])

/** The function a recorded title belongs to, or "" when it is unrecognised. */
export function titleFamily(title: string | null | undefined): string {
  const normalized = ` ${(title ?? '').toLowerCase().replaceAll(/[^a-z0-9]+/g, ' ').trim()} `
  if (!normalized.trim()) return ''
  // "Chief Executive Officer" reads as executive, not as the generic "officer"
  // any C-level title contains, so the specific families are tried first and
  // executive is last in FAMILIES.
  for (const family of FAMILIES) {
    if (family.words.some((word) => normalized.includes(` ${word} `))) return family.key
  }
  return ''
}

export type CoverageState = 'multiple' | 'single' | 'indirect' | 'none' | 'unknown'

export interface FamilyCoverage {
  key: string
  label: string
  state: CoverageState
  /** Operator-facing state, grounded in what an observed edge can support. */
  verdict: string
  actionability: Actionability
  connectors: string[]
  contacts: string[]
}

export interface AccessCoverage {
  families: FamilyCoverage[]
  /** Contacts at the account whose recorded title matches no known family. */
  unclassified: number
  /** Contacts named by an edge whose title is not recorded here at all. */
  untitled: number
}

/** Compress an account's contacts and observed edges into per-function access. */
export function accessCoverage(account: AccountView): AccessCoverage {
  const titles = new Map(account.known_people.map((person) => [person.display_name, person.title]))
  const byFamily = new Map<string, { connectors: Set<string>; contacts: Set<string> }>()
  const bucket = (key: string) => {
    if (!byFamily.has(key)) byFamily.set(key, { connectors: new Set(), contacts: new Set() })
    return byFamily.get(key)!
  }

  let unclassified = 0
  for (const person of account.known_people) {
    const family = titleFamily(person.title)
    if (!family) {
      if (person.title) unclassified += 1
      continue
    }
    bucket(family).contacts.add(person.display_name)
  }

  let untitled = 0
  for (const row of account.coverage.connectors) {
    for (const contact of row.named_contacts) {
      const title = titles.get(contact)
      if (!title) {
        untitled += 1
        continue
      }
      const family = titleFamily(title)
      if (!family) continue
      bucket(family).connectors.add(row.connector)
    }
  }

  // With no recorded title anywhere, absence of coverage says nothing about the
  // network — it says the data is thin, and the states below must not imply more.
  const anyTitles = account.known_people.some((person) => titleFamily(person.title) !== '')

  const families = FAMILIES.map(({ key, label }): FamilyCoverage => {
    const found = byFamily.get(key)
    const connectors = [...(found?.connectors ?? [])].sort()
    const contacts = [...(found?.contacts ?? [])].sort()
    const state: CoverageState = connectors.length > 1 ? 'multiple'
      : connectors.length === 1 ? 'single'
      : contacts.length > 0 ? 'indirect'
      : anyTitles ? 'none'
      : 'unknown'
    return { key, label, state, connectors, contacts, ...VERDICTS[state] }
  })

  return {
    families: families.filter((family) => family.state !== 'unknown' || ALWAYS_SHOWN.has(family.key)),
    unclassified,
    untitled,
  }
}

const VERDICTS: Record<CoverageState, { verdict: string; actionability: Actionability }> = {
  multiple: { verdict: 'Several observable routes', actionability: 'healthy' },
  single: { verdict: 'One route worth investigating', actionability: 'verify' },
  indirect: { verdict: 'Contacts known, no connector reaches them', actionability: 'verify' },
  none: { verdict: 'No corroborated route', actionability: 'act' },
  unknown: { verdict: 'Not enough data', actionability: 'context' },
}
