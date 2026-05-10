'use client'

// Sprint D6.84 — Confidence tier router admin page (Phase D2).
//
// Reads /admin/tier-router/summary + /admin/tier-router/log to surface
// the shadow vs current side-by-side compare. Each row in the log:
//
//   - what today's pipeline rendered (current_answer)
//   - what the tier router would render (shadow_answer)
//   - why (classifier verdict, self-consistency pass, web confidence)
//
// "Differs only" filter is the cheap way to see the blast radius of
// flipping CONFIDENCE_TIERS_MODE=live. If most rows tier=1, the live
// flip is low-risk because ✓ Verified looks identical to today.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

interface ShadowRow {
  id: number
  conversation_id: string
  user_id: string | null
  user_email: string | null
  query: string
  mode: 'shadow' | 'live'
  current_answer: string
  current_judge_verdict: string | null
  current_layer_c_fired: boolean
  current_verified_citations_count: number
  current_web_confidence: number | null
  shadow_tier: 1 | 2 | 3 | 4
  shadow_label: 'verified' | 'industry_standard' | 'relaxed_web' | 'best_effort'
  shadow_answer: string | null
  shadow_reason: string | null
  shadow_classifier_verdict: 'yes' | 'no' | 'uncertain' | null
  shadow_classifier_reasoning: string | null
  shadow_self_consistency_pass: boolean | null
  shadow_classifier_latency_ms: number | null
  shadow_self_consistency_latency_ms: number | null
  shadow_total_latency_ms: number | null
  shadow_error: string | null
  differs: boolean
  created_at: string
}

interface ShadowList {
  items: ShadowRow[]
  total: number
  limit: number
  offset: number
}

interface Summary {
  window_days: number
  total_rows: number
  counts_by_tier: Record<string, number>
  counts_by_label: Record<string, number>
  differs_count: number
  differs_pct: number
  classifier_yes_count: number
  classifier_yes_rate: number
  self_consistency_pass_count: number
  self_consistency_pass_rate: number
  avg_total_latency_ms: number | null
}

const TIER_INFO: Record<ShadowRow['shadow_label'], { label: string; icon: string; color: string }> = {
  verified:           { label: 'Verified',          icon: '✓', color: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  industry_standard:  { label: 'Industry Standard', icon: '⚓', color: 'bg-teal-500/15 text-teal-300 border-teal-500/30' },
  relaxed_web:        { label: 'Relaxed Web',       icon: '🌐', color: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  best_effort:        { label: 'Best Effort',       icon: '⚠', color: 'bg-slate-500/15 text-slate-300 border-slate-500/30' },
}

export default function TierRouterAdminPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#050811] text-[#f0ece4]">
        <AppHeader title="Tier router audit" />
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          <Content />
        </main>
      </div>
    </AuthGuard>
  )
}

function Content() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [list, setList] = useState<ShadowList | null>(null)
  const [diffOnly, setDiffOnly] = useState(false)
  const [tierFilter, setTierFilter] = useState<number | null>(null)
  const [emailFilter, setEmailFilter] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    (async () => {
      try {
        const s = await apiRequest<Summary>('/admin/tier-router/summary?window_days=14')
        setSummary(s)
      } catch {
        setSummary(null)
      }
    })()
  }, [])

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams()
    params.set('limit', '50')
    if (diffOnly) params.set('differs_only', 'true')
    if (tierFilter != null) params.set('tier', String(tierFilter))
    if (emailFilter.trim()) params.set('user_email', emailFilter.trim())
    apiRequest<ShadowList>(`/admin/tier-router/log?${params.toString()}`)
      .then(setList)
      .catch(() => setList(null))
      .finally(() => setLoading(false))
  }, [diffOnly, tierFilter, emailFilter])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Tier router audit</h1>
        <p className="text-sm text-slate-400 leading-relaxed max-w-3xl">
          Side-by-side comparison of what the production pipeline rendered vs what
          the new confidence tier router would render. While the system is in
          <code className="px-1 mx-1 bg-slate-800/60 rounded text-slate-300">shadow</code>
          mode, this table is the only place the tier decisions are visible — users
          still see today&apos;s behavior. Flipping
          <code className="px-1 mx-1 bg-slate-800/60 rounded text-slate-300">CONFIDENCE_TIERS_MODE=live</code>
          on the API would change the rendered answer for the rows where
          <span className="font-semibold text-amber-300"> Differs </span>
          is true.
        </p>
      </div>

      {summary && <SummaryCard s={summary} />}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => setDiffOnly(d => !d)}
          className={
            'px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ' +
            (diffOnly
              ? 'bg-amber-500/15 text-amber-300 border-amber-500/40'
              : 'bg-slate-800/40 text-slate-300 border-slate-700/60 hover:bg-slate-700/40')
          }
        >
          {diffOnly ? '✓ Differs only' : 'Differs only'}
        </button>

        {[1, 2, 3, 4].map(t => (
          <button
            key={t}
            onClick={() => setTierFilter(tierFilter === t ? null : t)}
            className={
              'px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ' +
              (tierFilter === t
                ? 'bg-teal-500/15 text-teal-300 border-teal-500/40'
                : 'bg-slate-800/40 text-slate-300 border-slate-700/60 hover:bg-slate-700/40')
            }
          >
            Tier {t}
          </button>
        ))}

        <input
          type="text"
          placeholder="Filter by user email…"
          value={emailFilter}
          onChange={e => setEmailFilter(e.target.value)}
          className="ml-auto px-3 py-1.5 rounded-md text-xs bg-slate-800/40 text-slate-200
            border border-slate-700/60 focus:outline-none focus:border-slate-500/80
            w-56"
        />
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !list || list.items.length === 0 ? (
        <p className="text-sm text-slate-500">
          No shadow log rows match these filters. If the table is empty entirely,
          the API may not be in shadow mode yet (set
          <code className="px-1 mx-1 bg-slate-800/60 rounded text-slate-300">CONFIDENCE_TIERS_MODE=shadow</code>
          on the API service and roll it).
        </p>
      ) : (
        <div className="space-y-2">
          {list.items.map(row => (
            <RowCard
              key={row.id}
              row={row}
              expanded={expandedId === row.id}
              onToggle={() => setExpandedId(expandedId === row.id ? null : row.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SummaryCard({ s }: { s: Summary }) {
  return (
    <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <Metric label={`Rows (${s.window_days}d)`} value={s.total_rows.toLocaleString()} />
        <Metric
          label="Would differ"
          value={`${s.differs_count.toLocaleString()} (${s.differs_pct.toFixed(1)}%)`}
          tone={s.differs_pct > 5 ? 'amber' : 'slate'}
        />
        <Metric
          label="Classifier yes-rate"
          value={`${s.classifier_yes_rate.toFixed(1)}%`}
        />
        <Metric
          label="Self-consistency pass"
          value={
            s.classifier_yes_count > 0
              ? `${s.self_consistency_pass_rate.toFixed(1)}%`
              : 'n/a'
          }
        />
        <Metric label="Avg latency" value={s.avg_total_latency_ms != null ? `${Math.round(s.avg_total_latency_ms)} ms` : 'n/a'} />
        {Object.entries(s.counts_by_label).map(([label, count]) => (
          <Metric
            key={label}
            label={`Tier · ${label}`}
            value={count.toLocaleString()}
          />
        ))}
      </div>
    </div>
  )
}

function Metric({ label, value, tone = 'slate' }: { label: string; value: string; tone?: 'slate' | 'amber' }) {
  const valueClass = tone === 'amber' ? 'text-amber-300' : 'text-slate-100'
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-base font-semibold ${valueClass}`}>{value}</div>
    </div>
  )
}

function RowCard({ row, expanded, onToggle }: { row: ShadowRow; expanded: boolean; onToggle: () => void }) {
  const t = TIER_INFO[row.shadow_label]
  return (
    <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-start gap-3 text-left hover:bg-slate-800/30
          transition-colors"
      >
        <span className={`shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${t.color}`}>
          <span aria-hidden>{t.icon}</span>
          <span>{t.label}</span>
        </span>
        {row.differs && (
          <span className="shrink-0 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium
            bg-amber-500/15 text-amber-300 border border-amber-500/30">
            Differs
          </span>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-200 truncate" title={row.query}>{row.query}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {row.user_email ?? 'unknown'} · {new Date(row.created_at).toLocaleString()}
            {row.shadow_total_latency_ms != null && <> · {row.shadow_total_latency_ms} ms</>}
          </p>
        </div>
        <span className="text-slate-500 text-xs shrink-0">{expanded ? '−' : '+'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-700/30 space-y-3">
          <DetailGrid row={row} />
          <SideBySide
            currentLabel="Current pipeline"
            current={row.current_answer}
            shadowLabel={`Shadow · ${t.label}`}
            shadow={row.shadow_answer || row.current_answer}
          />
          <Link
            href={`/admin/chat-preview/${row.conversation_id}`}
            className="text-xs text-teal-400 hover:underline"
          >
            View full conversation →
          </Link>
        </div>
      )}
    </div>
  )
}

function DetailGrid({ row }: { row: ShadowRow }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
      <Field label="Mode" value={row.mode} />
      <Field label="Judge verdict (current)" value={row.current_judge_verdict ?? '—'} />
      <Field label="Layer C fired" value={row.current_layer_c_fired ? 'yes' : 'no'} />
      <Field label="Verified citations" value={String(row.current_verified_citations_count)} />
      <Field label="Web confidence" value={row.current_web_confidence != null ? `${row.current_web_confidence}/5` : '—'} />
      <Field label="Classifier" value={row.shadow_classifier_verdict ?? '—'} />
      <Field
        label="Self-consistency"
        value={row.shadow_self_consistency_pass == null ? '—' : (row.shadow_self_consistency_pass ? 'pass' : 'fail')}
      />
      <Field label="Total latency" value={row.shadow_total_latency_ms != null ? `${row.shadow_total_latency_ms} ms` : '—'} />
      {row.shadow_reason && (
        <div className="col-span-full">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">Decision reason</div>
          <div className="text-slate-300 leading-relaxed">{row.shadow_reason}</div>
        </div>
      )}
      {row.shadow_classifier_reasoning && (
        <div className="col-span-full">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">Classifier reasoning</div>
          <div className="text-slate-300 leading-relaxed">{row.shadow_classifier_reasoning}</div>
        </div>
      )}
      {row.shadow_error && (
        <div className="col-span-full">
          <div className="text-[10px] uppercase tracking-wider text-rose-500 mb-0.5">Error</div>
          <div className="text-rose-300 leading-relaxed">{row.shadow_error}</div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-slate-200">{value}</div>
    </div>
  )
}

function SideBySide({
  currentLabel,
  current,
  shadowLabel,
  shadow,
}: {
  currentLabel: string
  current: string
  shadowLabel: string
  shadow: string
}) {
  const sameContent = current.trim() === shadow.trim()
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <Pane label={currentLabel} body={current} dimmed={false} />
      <Pane label={shadowLabel} body={shadow} dimmed={sameContent} />
    </div>
  )
}

function Pane({ label, body, dimmed }: { label: string; body: string; dimmed: boolean }) {
  return (
    <div className={`bg-slate-950/60 rounded border border-slate-700/40 ${dimmed ? 'opacity-60' : ''}`}>
      <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-400 border-b border-slate-700/30">
        {label}
        {dimmed && <span className="ml-2 text-slate-600">(identical)</span>}
      </div>
      <div className="px-3 py-2 text-xs text-slate-200 whitespace-pre-wrap leading-relaxed
        max-h-96 overflow-y-auto">
        {body}
      </div>
    </div>
  )
}
