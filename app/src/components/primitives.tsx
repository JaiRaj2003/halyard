/** Small shared pieces: the console has a deliberately narrow visual vocabulary. */

import { ReactNode } from 'react'
import { label, stateTone } from '../lib/labels'

export function Card({ title, subtitle, actions, children }: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-lg border border-line bg-white shadow-sm">
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3">
          <div>
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

const TONES: Record<string, string> = {
  neutral: 'bg-slate-100 text-slate-700 border-slate-200',
  info: 'bg-blue-50 text-blue-800 border-blue-200',
  warn: 'bg-amber-50 text-amber-800 border-amber-200',
  bad: 'bg-red-50 text-red-800 border-red-200',
  good: 'bg-green-50 text-green-800 border-green-200',
}

export function Tag({ tone = 'neutral', children }: { tone?: keyof typeof TONES | string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone] ?? TONES.neutral}`}>
      {children}
    </span>
  )
}

export function StateTag({ state }: { state: string }) {
  return <Tag tone={stateTone(state)}>{label('state', state)}</Tag>
}

/** Detail an operator can ask for but should not have to read. */
export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="cursor-pointer list-none text-xs font-medium text-accent hover:underline marker:hidden">
        <span className="group-open:hidden">{summary} ▸</span>
        <span className="hidden group-open:inline">{summary} ▾</span>
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-sm">{children || <span className="text-muted">—</span>}</dd>
    </div>
  )
}

export function Button({ variant = 'primary', ...props }: { variant?: 'primary' | 'secondary' | 'quiet' } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles = {
    primary: 'bg-accent text-white hover:bg-blue-800 disabled:bg-blue-300',
    secondary: 'border border-line bg-white hover:bg-slate-50 disabled:text-muted',
    quiet: 'text-accent hover:underline disabled:text-muted',
  }[variant]
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed ${styles} ${props.className ?? ''}`}
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
  if (days > 0) return `${days}d ago`
  return `in ${Math.abs(days)}d`
}

export function shortDate(iso: string | null): string {
  return iso ? new Date(iso).toISOString().slice(0, 10) : '—'
}
