/** Inline icons. Each actionability level has one mark so a badge reads the
 *  same in greyscale; a few workflow marks share the stroke style. */

import { Actionability } from '../presentation/labels'

const BASE = 'shrink-0'

function Svg({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`${BASE} ${className}`}
    >
      {children}
    </svg>
  )
}

export function AlertIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M8 2.5 14.2 13H1.8L8 2.5Z" />
      <path d="M8 6.5v3M8 11.6v.1" />
    </Svg>
  )
}

export function QuestionIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M6.2 6.3a1.9 1.9 0 0 1 3.7.5c0 1.2-1.9 1.4-1.9 2.6M8 11.6v.1" />
    </Svg>
  )
}

export function CheckIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="8" r="6.2" />
      <path d="m5.2 8.2 1.9 1.9 3.8-4" />
    </Svg>
  )
}

export function InfoIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.2v4M8 4.8v.1" />
    </Svg>
  )
}

export function ClockIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 4.5V8l2.4 1.5" />
    </Svg>
  )
}

export function ArrowIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M2.5 8h11M9.5 4l4 4-4 4" />
    </Svg>
  )
}

export function SearchIcon({ className = 'h-3.5 w-3.5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="7" cy="7" r="4.5" />
      <path d="m10.5 10.5 3 3" />
    </Svg>
  )
}

export function ChevronIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="m6 3.5 4.5 4.5L6 12.5" />
    </Svg>
  )
}

export function ActionIcon({ level, className }: { level: Actionability; className?: string }) {
  switch (level) {
    case 'act':
      return <AlertIcon className={className} />
    case 'verify':
      return <QuestionIcon className={className} />
    case 'healthy':
      return <CheckIcon className={className} />
    default:
      return <InfoIcon className={className} />
  }
}
