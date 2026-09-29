'use client'

// 2026-09-29 — admin UI primitives, so every admin page shares one header,
// card, pill, empty-state and button style instead of re-typing Tailwind.

import Link from 'next/link'
import type { Toast } from '../_lib/types'

export const TEXT_MUTED = 'text-[#8b93ad]'

export const btn = {
  primary:
    'inline-flex items-center justify-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider ' +
    'bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ' +
    'disabled:opacity-50 disabled:cursor-not-allowed',
  secondary:
    'inline-flex items-center justify-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider ' +
    'border border-[#2dd4bf]/35 text-[#2dd4bf] rounded-lg px-3 py-1.5 hover:bg-[#2dd4bf]/10 transition-colors ' +
    'disabled:opacity-50 disabled:cursor-not-allowed',
  quiet:
    'inline-flex items-center justify-center gap-1.5 font-mono text-xs border border-white/10 text-[#f0ece4]/80 ' +
    'rounded-lg px-3 py-1.5 hover:bg-white/5 transition-colors disabled:opacity-50',
  danger:
    'inline-flex items-center justify-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider ' +
    'border border-red-500/40 text-red-400/90 rounded-lg px-3 py-1.5 hover:bg-red-500/10 hover:text-red-400 ' +
    'transition-colors disabled:opacity-50',
}

export function Page({ title, description, actions, children }: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="px-4 md:px-8 py-6 md:py-8 max-w-[1500px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-3 mb-6">
        <div className="min-w-0">
          <h1 className="font-display text-2xl md:text-3xl font-bold tracking-wide text-[#f0ece4]">{title}</h1>
          {description && <p className={`font-mono text-xs ${TEXT_MUTED} mt-1.5 max-w-3xl leading-relaxed`}>{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

/** A titled block inside a page (h2), for pages with several sections. */
export function Section({ title, description, action, id, children }: {
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  id?: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="mb-10 scroll-mt-20">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
        <div>
          <h2 className="font-display text-lg md:text-xl font-bold tracking-wide text-[#f0ece4]">{title}</h2>
          {description && <p className={`font-mono text-[11px] ${TEXT_MUTED} mt-0.5`}>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Card({ title, subtitle, action, className = '', pad = true, children }: {
  title?: React.ReactNode
  subtitle?: React.ReactNode
  action?: React.ReactNode
  className?: string
  pad?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`bg-[#111827] rounded-xl border border-white/8 ${pad ? 'p-4 md:p-5' : ''} ${className}`}>
      {(title || action) && (
        <div className={`flex items-start justify-between gap-3 ${pad ? 'mb-3' : 'px-4 md:px-5 pt-4 md:pt-5 mb-3'}`}>
          <div className="min-w-0">
            {title && <h3 className={`font-mono text-[11px] uppercase tracking-wider ${TEXT_MUTED}`}>{title}</h3>}
            {subtitle && <p className="font-mono text-[11px] text-[#f0ece4]/60 mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

/** Small inline trend line for KPI tiles. */
export function Sparkline({ values, color = '#2dd4bf', height = 36 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return null
  const w = 100
  const max = Math.max(1, ...values)
  const step = w / (values.length - 1)
  const pts = values.map((v, i) => [i * step, height - 3 - (v / max) * (height - 6)] as const)
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `0,${height} ${line} ${w},${height}`
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} aria-hidden="true">
      <polygon points={area} fill={color} opacity={0.12} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

export function Kpi({ label, value, sub, series, seriesLabel, href }: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  series?: number[]
  seriesLabel?: string
  href?: string
}) {
  const body = (
    <>
      <p className={`font-mono text-[11px] uppercase tracking-wider ${TEXT_MUTED}`}>{label}</p>
      <p className="font-display text-4xl font-bold text-[#f0ece4] mt-1 leading-none tabular-nums">{value}</p>
      {sub && <p className="font-mono text-[11px] text-[#f0ece4]/65 mt-2 leading-snug">{sub}</p>}
      {series && series.length > 1 && (
        <div className="mt-3">
          <Sparkline values={series} />
          {seriesLabel && <p className={`font-mono text-[10px] ${TEXT_MUTED} mt-1`}>{seriesLabel}</p>}
        </div>
      )}
    </>
  )
  const cls = 'block bg-[#111827] rounded-xl border border-white/8 p-4 md:p-5'
  return href ? (
    <Link href={href} className={`${cls} hover:border-[#2dd4bf]/30 transition-colors`}>{body}</Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

const PILL_TONES = {
  teal: 'bg-[#2dd4bf]/15 text-[#2dd4bf] border-[#2dd4bf]/30',
  amber: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  red: 'bg-red-500/15 text-red-400 border-red-500/30',
  gray: 'bg-[#6b7594]/15 text-[#9aa3bf] border-[#6b7594]/30',
  purple: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
} as const

export type PillTone = keyof typeof PILL_TONES

export function Pill({ tone = 'gray', children, title }: { tone?: PillTone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center font-mono text-[10px] font-bold uppercase tracking-wider
      px-1.5 py-0.5 rounded border whitespace-nowrap ${PILL_TONES[tone]}`}>
      {children}
    </span>
  )
}

/** Count bubble for the sidebar and tabs; renders nothing for 0. */
export function CountBadge({ n, tone = 'amber' }: { n: number | null | undefined; tone?: 'amber' | 'red' | 'teal' }) {
  if (!n) return null
  const cls = tone === 'red' ? 'bg-red-500/85 text-white' : tone === 'teal' ? 'bg-[#2dd4bf] text-[#0a0e1a]' : 'bg-amber-400 text-[#0a0e1a]'
  return (
    <span className={`ml-auto min-w-[20px] h-5 px-1.5 inline-flex items-center justify-center rounded-full
      font-mono text-[10px] font-bold tabular-nums ${cls}`}>
      {n > 99 ? '99+' : n}
    </span>
  )
}

export function Empty({ children, tone = 'muted' }: { children: React.ReactNode; tone?: 'muted' | 'good' }) {
  return (
    <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 text-center">
      <p className={`font-mono text-sm ${tone === 'good' ? 'text-[#2dd4bf]' : TEXT_MUTED}`}>{children}</p>
    </div>
  )
}

export function Skeleton({ className = 'h-[72px]' }: { className?: string }) {
  return <div className={`bg-[#111827] rounded-xl border border-white/8 animate-pulse ${className}`} />
}

export function ToastBanner({ toast, className = '' }: { toast: Toast; className?: string }) {
  if (!toast) return null
  return (
    <div role="status" className={`font-mono text-xs px-3 py-2 rounded-lg border ${
      toast.ok ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/30 text-[#2dd4bf]' : 'bg-red-500/10 border-red-500/30 text-red-400'
    } ${className}`}>
      {toast.msg}
    </div>
  )
}

export function FilterPills<T extends string>({ options, value, onChange, counts }: {
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  counts?: Partial<Record<T, number>>
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist">
      {options.map((o) => {
        const active = value === o.value
        const n = counts?.[o.value]
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={`font-mono text-[11px] font-bold uppercase tracking-wider px-2.5 py-1.5 rounded-md border transition-colors
              ${active
                ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                : 'border-white/10 text-[#8b93ad] hover:text-[#f0ece4] hover:border-white/20'}`}
          >
            {o.label}
            {n !== undefined && <span className={`ml-1.5 ${active ? 'text-[#2dd4bf]/80' : 'text-[#6b7594]'}`}>{n}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** The pre-2026-09-29 stat tile, kept for the sections that were moved as-is. */
export function StatCard({ label, value, wide }: { label: string; value: string | number; wide?: boolean }) {
  return (
    <div className={`bg-[#111827] rounded-xl border border-white/8 px-4 py-3 ${wide ? 'col-span-full' : ''}`}>
      <p className={`font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>{label}</p>
      <p className="font-mono text-2xl font-bold text-[#2dd4bf] mt-1">{typeof value === 'number' ? value.toLocaleString() : value}</p>
    </div>
  )
}

/** Thin proportional bar for ranked lists. */
export function MeterBar({ value, max, color = '#2dd4bf' }: { value: number; max: number; color?: string }) {
  const w = max > 0 ? Math.max(3, Math.round((value / max) * 100)) : 0
  return (
    <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${w}%`, backgroundColor: color, opacity: 0.75 }} />
    </div>
  )
}
