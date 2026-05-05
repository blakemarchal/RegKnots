'use client'

// Sprint D6.58 audit tooling — web fallback events admin page.
//
// The Chats tab shows individual conversations but doesn't give a
// view into WHY fallback fired (or didn't), which surface tier was
// picked, which providers contributed, what the cosine signal was,
// or why a result was blocked. This page is that view.
//
// Each row is one entry in web_fallback_responses. Filters:
//   - Tier: verified | consensus | reference | blocked | all
//   - Path: ensemble | single-llm | all
//   - Time: last 24h | 7d | 30d
//
// Click a row to see the full per-event detail: providers fired,
// agreement count, source URL + domain, confidence, retrieval cosine,
// quote (if any), and surface_blocked_reason.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

type Tier = 'verified' | 'consensus' | 'reference' | 'blocked'
type TierFilter = Tier | 'all'
type PathFilter = 'all' | 'ensemble' | 'single'

interface FallbackEvent {
  id: string
  created_at: string
  query: string
  surface_tier: Tier | null
  is_ensemble: boolean
  ensemble_providers: string[] | null
  ensemble_agreement_count: number | null
  confidence: number | null
  source_url: string | null
  source_domain: string | null
  quote_text: string | null
  quote_verified: boolean
  surfaced: boolean
  surface_blocked_reason: string | null
  retrieval_top1_cosine: number | null
  latency_ms: number
  user_email: string | null
  conversation_id: string | null
  answer_text: string | null
}

interface FallbackStats {
  total_7d: number
  surfaced_7d: number
  ensemble_7d: number
  by_tier: Partial<Record<Tier, number>>
  by_blocked_reason: Record<string, number>
}


const TIER_INFO: Record<Tier, { label: string; color: string }> = {
  verified:  { label: 'Verified',  color: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  consensus: { label: 'Consensus', color: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
  reference: { label: 'Reference', color: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  blocked:   { label: 'Blocked',   color: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
}


export default function WebFallbackAdminPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#050811] text-[#f0ece4]">
        <AppHeader title="Web fallback audit" />
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          <Content />
        </main>
      </div>
    </AuthGuard>
  )
}


function Content() {
  const [events, setEvents] = useState<FallbackEvent[] | null>(null)
  const [stats, setStats] = useState<FallbackStats | null>(null)
  const [tier, setTier] = useState<TierFilter>('all')
  const [path, setPath] = useState<PathFilter>('all')
  const [hours, setHours] = useState<number>(168)  // 7 days default
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => { void load() }, [tier, path, hours]) // eslint-disable-line react-hooks/exhaustive-deps

  async function load() {
    setError(null)
    const qp = new URLSearchParams()
    if (tier !== 'all') qp.set('tier', tier)
    if (path !== 'all') qp.set('path', path)
    qp.set('hours', String(hours))
    qp.set('limit', '200')
    try {
      const [list, agg] = await Promise.all([
        apiRequest<FallbackEvent[]>(`/admin/web-fallback?${qp.toString()}`),
        apiRequest<FallbackStats>('/admin/web-fallback/stats'),
      ])
      setEvents(list)
      setStats(agg)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load.')
    }
  }

  return (
    <>
      <header className="mb-6">
        <div className="text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-2">
          <Link href="/admin" className="text-[#2dd4bf] hover:underline">← Admin</Link>
        </div>
        <h1 className="text-2xl font-bold mb-1">Web fallback events</h1>
        <p className="text-sm text-[#6b7594]">
          Every fallback fire — single-LLM (Slice 1) and Big-3 ensemble (Slice 3).
          Use to audit which queries fired, which tier surfaced, and why blocked
          ones blocked.
        </p>
      </header>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="Last 7d total" value={stats.total_7d} />
          <StatCard label="Surfaced 7d" value={`${stats.surfaced_7d} (${pct(stats.surfaced_7d, stats.total_7d)}%)`} />
          <StatCard label="Ensemble 7d" value={`${stats.ensemble_7d} (${pct(stats.ensemble_7d, stats.total_7d)}%)`} />
          <StatCard
            label="Top blocked reason"
            value={topBlock(stats.by_blocked_reason)}
          />
        </div>
      )}

      {/* Tier breakdown */}
      {stats && (
        <div className="mb-6 rounded-lg border border-white/8 bg-[#0a0e1a]/60 p-4">
          <p className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594] mb-3">
            Surface tiers (last 7d)
          </p>
          <div className="flex flex-wrap gap-3">
            {(Object.keys(TIER_INFO) as Tier[]).map(t => {
              const n = stats.by_tier[t] ?? 0
              const info = TIER_INFO[t]
              return (
                <div key={t} className={`px-3 py-1.5 rounded-md border text-xs font-mono ${info.color}`}>
                  {info.label}: <span className="font-bold">{n}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <FilterPill
          label="Tier"
          options={['all', 'verified', 'consensus', 'reference', 'blocked']}
          value={tier}
          onChange={(v) => setTier(v as TierFilter)}
        />
        <FilterPill
          label="Path"
          options={['all', 'ensemble', 'single']}
          value={path}
          onChange={(v) => setPath(v as PathFilter)}
        />
        <FilterPill
          label="Window"
          options={['24', '168', '720']}
          labels={['24h', '7d', '30d']}
          value={String(hours)}
          onChange={(v) => setHours(parseInt(v))}
        />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-400/30 bg-red-400/5 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {events === null && (
        <p className="text-sm text-[#6b7594]">Loading…</p>
      )}

      {events && events.length === 0 && (
        <div className="rounded-lg border border-dashed border-white/10 p-8 text-center">
          <p className="text-sm text-[#6b7594]">No fallback events match the current filter.</p>
        </div>
      )}

      <ul className="space-y-2">
        {(events ?? []).map((ev) => (
          <li key={ev.id}>
            <EventRow
              ev={ev}
              expanded={expandedId === ev.id}
              onToggle={() => setExpandedId(expandedId === ev.id ? null : ev.id)}
            />
          </li>
        ))}
      </ul>
    </>
  )
}


function pct(n: number, total: number): string {
  if (!total) return '0'
  return ((n / total) * 100).toFixed(0)
}


function topBlock(by: Record<string, number>): string {
  const entries = Object.entries(by)
  if (entries.length === 0) return '—'
  entries.sort((a, b) => b[1] - a[1])
  return `${entries[0][0]} (${entries[0][1]})`
}


function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-white/8 bg-[#0a0e1a]/60 p-4">
      <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">{label}</p>
      <p className="text-2xl font-bold text-[#f0ece4]">{value}</p>
    </div>
  )
}


function FilterPill({
  label, options, labels, value, onChange,
}: {
  label: string
  options: string[]
  labels?: string[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594] mr-1">
        {label}:
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-xs bg-[#111827] border border-white/10 rounded-md px-2 py-1
                   text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/50"
      >
        {options.map((o, i) => (
          <option key={o} value={o} style={{ backgroundColor: '#111827' }}>
            {labels?.[i] ?? o}
          </option>
        ))}
      </select>
    </div>
  )
}


function EventRow({
  ev, expanded, onToggle,
}: {
  ev: FallbackEvent
  expanded: boolean
  onToggle: () => void
}) {
  const tier = ev.surface_tier
  const info = tier ? TIER_INFO[tier] : null
  const tierBadge = info ? (
    <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${info.color}`}>
      {info.label}
    </span>
  ) : (
    <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border bg-white/5 text-[#6b7594] border-white/10">
      —
    </span>
  )
  return (
    <div className="rounded-lg border border-white/8 bg-[#0a0e1a]/60">
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-white/5 transition-colors"
      >
        {tierBadge}
        {ev.is_ensemble && (
          <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border bg-purple-500/10 text-purple-300/80 border-purple-500/20">
            Big-3
          </span>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#f0ece4] truncate">{ev.query}</p>
          <p className="text-[11px] text-[#6b7594] mt-0.5 truncate">
            {new Date(ev.created_at).toLocaleString()}
            {ev.user_email && <> · {ev.user_email}</>}
            {ev.source_domain && <> · <span className="text-[#f0ece4]/70">{ev.source_domain}</span></>}
            {typeof ev.confidence === 'number' && <> · conf {ev.confidence}/5</>}
            {typeof ev.retrieval_top1_cosine === 'number' && (
              <> · cos {ev.retrieval_top1_cosine.toFixed(3)}</>
            )}
            {ev.surface_blocked_reason && <> · <span className="text-rose-300/80">{ev.surface_blocked_reason}</span></>}
          </p>
        </div>
        <span className="text-[#6b7594] text-xs ml-2 flex-shrink-0">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-white/8 px-4 py-4 space-y-4 text-sm">
          {ev.is_ensemble && ev.ensemble_providers && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Ensemble providers ({ev.ensemble_providers.length}/3 succeeded)
              </p>
              <div className="flex gap-2">
                {(['claude', 'gpt', 'grok'] as const).map(p => {
                  const ok = ev.ensemble_providers!.includes(p)
                  return (
                    <span key={p}
                      className={`px-2 py-0.5 rounded font-mono text-[11px] border ${
                        ok
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                          : 'bg-rose-500/10 text-rose-300/80 border-rose-500/30'
                      }`}>
                      {ok ? '✓' : '✗'} {p}
                    </span>
                  )
                })}
              </div>
              {typeof ev.ensemble_agreement_count === 'number' && (
                <p className="text-[11px] text-[#6b7594] mt-2">
                  Agreement: {ev.ensemble_agreement_count}/3 providers agreed on the picked answer
                </p>
              )}
            </div>
          )}

          {ev.answer_text && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Answer surfaced
              </p>
              <p className="text-sm text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
                {ev.answer_text}
              </p>
            </div>
          )}

          {ev.quote_text && (
            <div className="bg-[#0d1225] border border-white/8 rounded-md p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Quote {ev.quote_verified ? '(verified verbatim)' : '(not verified)'}
              </p>
              <blockquote className="font-mono text-[12px] italic text-[#f0ece4]/80">
                &ldquo;{ev.quote_text}&rdquo;
              </blockquote>
            </div>
          )}

          {ev.source_url && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Source
              </p>
              <a href={ev.source_url} target="_blank" rel="noopener noreferrer"
                 className="text-xs font-mono text-[#2dd4bf] underline break-all">
                {ev.source_url}
              </a>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px] font-mono text-[#6b7594]">
            <Field label="Tier" value={ev.surface_tier ?? '—'} />
            <Field label="Surfaced" value={ev.surfaced ? 'true' : 'false'} />
            <Field label="Latency" value={`${ev.latency_ms}ms`} />
            <Field label="Confidence" value={ev.confidence?.toString() ?? '—'} />
            <Field label="Retrieval cosine" value={ev.retrieval_top1_cosine?.toFixed(3) ?? '—'} />
            <Field label="Quote verified" value={ev.quote_verified ? 'yes' : 'no'} />
            {ev.surface_blocked_reason && (
              <Field label="Blocked reason" value={ev.surface_blocked_reason} />
            )}
          </div>

          {ev.conversation_id && (
            <div className="pt-2 border-t border-white/8">
              <Link
                href={`/admin/chat-tail?conversation_id=${ev.conversation_id}`}
                className="px-3 py-1.5 rounded-md border border-white/10
                           text-xs font-medium text-[#f0ece4]/80 hover:bg-white/5
                           transition-colors inline-block"
              >
                View conversation →
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-[#6b7594]/70">{label}: </span>
      <span className="text-[#f0ece4]/80">{value}</span>
    </div>
  )
}
