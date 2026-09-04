/** Small shared pieces: the console has a deliberately narrow visual vocabulary. */

import { ReactNode } from 'react'
import { ACTION_MEANING, Actionability, label, stateActionability } from '../presentation/labels'
import { ActionIcon, ChevronIcon } from './icons'

export function Card({ id, title, subtitle, actions, tone = 'default', children }: {
  id?: string
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  /** `quiet` marks context the operator can skip; `accent` marks the decision. */
  tone?: 'default' | 'quiet' | 'accent'
  children: ReactNode
}) {
  const frame = {
    default: 'border-line bg-white shadow-sm',
    quiet: 'border-dashed border-line bg-slate-50',
    accent: 'border-blue-200 bg-white shadow-sm',
  }[tone]
  return (
    <section id={id} className={`scroll-mt-4 rounded-lg border ${frame}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold tracking-tight">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

/** Blue is reserved for the recommendation and the selected thing; the four
 *  actionability tones say what a badge wants from the operator. */
const TONES: Record<string, string> = {
  neutral: 'bg-slate-100 text-slate-700 border-slate-200',
  info: 'bg-blue-50 text-blue-800 border-blue-200',
  warn: 'bg-amber-50 text-amber-800 border-amber-200',
  bad: 'bg-red-50 text-red-800 border-red-200',
  good: 'bg-green-50 text-green-800 border-green-200',
}

const ACTION_TONE: Record<Actionability, keyof typeof TONES> = {
  act: 'bad',
  verify: 'warn',
  healthy: 'good',
  context: 'neutral',
}

export function Tag({ tone = 'neutral', icon, children }: {
  tone?: keyof typeof TONES | string
  /** Prefixes the badge with its actionability mark, so colour is never load-bearing. */
  icon?: Actionability
  children: ReactNode
}) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone] ?? TONES.neutral}`}>
      {icon && <ActionIcon level={icon} className="h-3 w-3 opacity-80" />}
      {children}
    </span>
  )
}

/** A badge that says what it wants from the operator, in the shared vocabulary. */
export function ActionTag({ level, children }: { level: Actionability; children: ReactNode }) {
  return <Tag tone={ACTION_TONE[level]} icon={level}>{children}</Tag>
}

export function StateTag({ state }: { state: string }) {
  return <ActionTag level={stateActionability(state)}>{label('state', state)}</ActionTag>
}

/** Panel framing for the four treatments, used by callouts and route cards. */
export const LEVEL_PANEL: Record<Actionability, string> = {
  act: 'border-red-200 bg-red-50',
  verify: 'border-amber-200 bg-amber-50',
  healthy: 'border-green-200 bg-green-50',
  context: 'border-line bg-slate-50',
}

export const LEVEL_TEXT: Record<Actionability, string> = {
  act: 'text-red-800',
  verify: 'text-amber-800',
  healthy: 'text-green-800',
  context: 'text-slate-700',
}

/** A short, framed statement of what the operator is looking at and why. */
export function Callout({ level, title, children, actions }: {
  level: Actionability
  title: ReactNode
  children?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div role="note" className={`flex flex-wrap items-start justify-between gap-3 rounded-md border px-4 py-3 ${LEVEL_PANEL[level]}`}>
      <div className="min-w-0 flex-1">
        <p className={`flex items-center gap-1.5 text-sm font-semibold ${LEVEL_TEXT[level]}`}>
          <ActionIcon level={level} className="h-3.5 w-3.5" />
          {title}
        </p>
        {children && <div className="mt-1 text-sm text-ink">{children}</div>}
      </div>
      {actions}
    </div>
  )
}

/** The four treatments, spelled out once where the operator first meets them. */
export function ActionLegend() {
  const levels: Actionability[] = ['act', 'verify', 'healthy', 'context']
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
      {levels.map((level) => (
        <ActionTag key={level} level={level}>{ACTION_MEANING[level]}</ActionTag>
      ))}
    </p>
  )
}

/** Detail an operator can ask for but should not have to read. */
export function Disclosure({ summary, children, defaultOpen = false }: {
  summary: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-accent hover:underline marker:hidden">
        <ChevronIcon className="h-3 w-3 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}

export function Field({ label, wrap = false, children }: { label: string; wrap?: boolean; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${wrap ? '' : 'truncate'}`}>{children || <span className="text-muted">—</span>}</dd>
    </div>
  )
}

export function Button({ variant = 'primary', size = 'md', ...props }: {
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger'
  size?: 'sm' | 'md'
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles = {
    primary: 'bg-accent text-white hover:bg-blue-800 disabled:bg-blue-300',
    secondary: 'border border-line bg-white hover:bg-slate-50 disabled:text-muted',
    quiet: 'text-accent hover:underline disabled:text-muted',
    danger: 'border border-red-200 bg-white text-bad hover:bg-red-50 disabled:text-muted',
  }[variant]
  const sizing = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm'
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-md font-medium transition disabled:cursor-not-allowed ${sizing} ${styles} ${props.className ?? ''}`}
    />
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-dashed border-line px-4 py-6 text-center text-sm text-muted">{children}</p>
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="animate-pulse px-1 py-6 text-sm text-muted" role="status">
      Loading {what}…
    </p>
  )
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-bad">
      {error}
    </p>
  )
}

export function relative(iso: string | null): string {
  if (!iso) return '—'
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days > 0) return `${days}d ago`
  return `in ${Math.abs(days)}d`
}

export function shortDate(iso: string | null): string {
  return iso ? new Date(iso).toISOString().slice(0, 10) : '—'
}
