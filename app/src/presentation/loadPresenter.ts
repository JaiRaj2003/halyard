/** Connector load in the words of someone managing goodwill, not telemetry.
 *
 *  Inputs are the counts and stated capacity the leadership API already
 *  serves; the verdict thresholds are the server's `over_capacity` flag where
 *  it exists. No score is derived here.
 */

import { Actionability } from './labels'

export interface LoadReading {
  /** "5 active asks · stated capacity 4" */
  phrase: string
  /** "High request load" / "At stated capacity" / "Available capacity" / "Capacity not tracked" */
  verdict: string
  level: Actionability
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export function loadReading(
  asks: number | null | undefined,
  capacity: number | null | undefined,
  overCapacity?: boolean | null,
): LoadReading {
  const count = asks ?? 0
  const asksText = `${plural(count, 'active ask')}`
  if (capacity === null || capacity === undefined) {
    return { phrase: `${asksText} · capacity not stated`, verdict: 'Capacity not tracked', level: 'context' }
  }
  const phrase = `${asksText} · stated capacity ${capacity}`
  if (overCapacity ?? count > capacity) return { phrase, verdict: 'High request load', level: 'act' }
  if (count >= capacity) return { phrase, verdict: 'At stated capacity', level: 'verify' }
  return { phrase, verdict: 'Available capacity', level: 'healthy' }
}
