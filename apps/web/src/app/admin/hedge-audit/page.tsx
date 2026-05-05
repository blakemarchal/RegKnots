'use client'

// Sprint D6.58 Slice 2 — hedge audit admin dashboard.
//
// Every time the corpus hedges (or surfaces only a 'reference' tier
// web fallback), an async Haiku classifier writes a row to
// hedge_audits classifying WHY we missed and recommending a fix.
// This page is where Karynn / admin reviews those rows, marks them
// fixed/won't-fix, and tracks the ongoing improvement loop.
//
// The mariner-in-the-loop is structured here. Marketing pitches it
// — this page is where the work actually happens.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

type Classification =
  | 'VOCAB' | 'INTENT' | 'RANKING' | 'COSINE'
  | 'CORPUS_GAP' | 'JURISDICTION' | 'OTHER'
type Status = 'open' | 'fixed' | 'wontfix' | 'duplicate'
type StatusFilter = Status | 'all'

interface RetrievedSection {
  source?: string
  section_number?: string
  section_title?: string
  similarity?: number
}

interface HedgeAudit {
  id: string
  created_at: string
  classification: Classification
  status: Status
  query: string
  classifier_reasoning: string | null
  recommendation: string | null
  classifier_model: string | null
  web_surface_tier: string | null
  user_email: string | null
  user_full_name: string | null
  conversation_id: string | null
  top_retrieved_sections: RetrievedSection[]
  admin_notes: string | null
  fixed_at: string | null
  fixed_by_email: string | null
}

interface Stats {
  open_count: number
  fixed_last_7d: number
  by_classification: Partial<Record<Classification, number>>
}

const CLASSIFICATION_INFO: Record<Classification, { label: string; color: string; description: string }> = {
  VOCAB:        { label: 'Vocab',        color: 'bg-blue-500/15 text-blue-300 border-blue-500/30', description: "User's term ≠ corpus term" },
  INTENT:       { label: 'Intent',       color: 'bg-purple-500/15 text-purple-300 border-purple-500/30', description: 'Wrong section type retrieved' },
  RANKING:      { label: 'Ranking',      color: 'bg-amber-500/15 text-amber-300 border-amber-500/30', description: 'Right section ranked too low' },
  COSINE:       { label: 'Cosine',       color: 'bg-rose-500/15 text-rose-300 border-rose-500/30', description: 'Top-K all irrelevant' },
  CORPUS_GAP:   { label: 'Corpus gap',   color: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', description: 'Need to ingest source' },
  JURISDICTION: { label: 'Jurisdiction', color: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30', description: 'Wrong scope applied' },
  OTHER:        { label: 'Other',        color: 'bg-gray-500/15 text-gray-300 border-gray-500/30', description: 'Needs human review' },
}


export default function HedgeAuditAdminPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#050811] text-[#f0ece4]">
        <AppHeader title="Hedge audits" />
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          <Content />
        </main>
      </div>
    </AuthGuard>
  )
}


function Content() {
  const [audits, setAudits] = useState<HedgeAudit[] | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('open')
  const [classFilter, setClassFilter] = useState<Classification | 'all'>('all')
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => { void load() }, [statusFilter, classFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  async function load() {
    setError(null)
    const qp = new URLSearchParams()
    qp.set('status', statusFilter)
    if (classFilter !== 'all') qp.set('classification', classFilter)
    qp.set('limit', '100')
    try {
      const [list, agg] = await Promise.all([
        apiRequest<HedgeAudit[]>(`/admin/hedge-audits?${qp.toString()}`),
        apiRequest<Stats>('/admin/hedge-audits/stats'),
      ])
      setAudits(list)
      setStats(agg)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load.')
    }
  }

  async function updateAudit(id: string, status: Status, notes?: string) {
    try {
      await apiRequest(`/admin/hedge-audits/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status, admin_notes: notes ?? null }),
      })
      void load()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Update failed.')
    }
  }

  return (
    <>
      <header className="mb-6">
        <div className="text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-2">
          <Link href="/admin" className="text-[#2dd4bf] hover:underline">← Admin</Link>
        </div>
        <h1 className="text-2xl font-bold mb-1">Hedge audit queue</h1>
        <p className="text-sm text-[#6b7594]">
          Every hedged answer auto-classified. Mark fixed when you ship the
          underlying change (synonym, ingest, retrieval tweak).
        </p>
      </header>

      {/* Stats strip */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="Open" value={stats.open_count} />
          <StatCard label="Fixed (last 7d)" value={stats.fixed_last_7d} />
          <StatCard
            label="Top open class"
            value={topClass(stats.by_classification)}
          />
          <StatCard
            label="Open buckets"
            value={Object.keys(stats.by_classification).length}
          />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <FilterPill
          options={['open', 'fixed', 'wontfix', 'duplicate', 'all']}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as StatusFilter)}
          label="Status"
        />
        <FilterPill
          options={['all', 'VOCAB', 'INTENT', 'RANKING', 'COSINE', 'CORPUS_GAP', 'JURISDICTION', 'OTHER']}
          value={classFilter}
          onChange={(v) => setClassFilter(v as Classification | 'all')}
          label="Class"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-400/30 bg-red-400/5 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {audits === null && (
        <p className="text-sm text-[#6b7594]">Loading…</p>
      )}

      {audits && audits.length === 0 && (
        <div className="rounded-lg border border-dashed border-white/10 p-8 text-center">
          <p className="text-sm text-[#6b7594]">No audits match the current filter.</p>
        </div>
      )}

      <ul className="space-y-3">
        {(audits ?? []).map((a) => (
          <li key={a.id}>
            <AuditRow
              audit={a}
              expanded={expandedId === a.id}
              onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
              onMarkFixed={() => {
                const note = prompt('Optional fix notes:')
                if (note === null) return
                void updateAudit(a.id, 'fixed', note || undefined)
              }}
              onMarkWontFix={() => {
                const note = prompt('Optional reason:')
                if (note === null) return
                void updateAudit(a.id, 'wontfix', note || undefined)
              }}
              onReopen={() => void updateAudit(a.id, 'open')}
            />
          </li>
        ))}
      </ul>
    </>
  )
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
  options, value, onChange, label,
}: {
  options: string[]
  value: string
  onChange: (v: string) => void
  label: string
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
        {options.map((o) => (
          <option key={o} value={o} style={{ backgroundColor: '#111827' }}>
            {o}
          </option>
        ))}
      </select>
    </div>
  )
}


function AuditRow({
  audit, expanded, onToggle, onMarkFixed, onMarkWontFix, onReopen,
}: {
  audit: HedgeAudit
  expanded: boolean
  onToggle: () => void
  onMarkFixed: () => void
  onMarkWontFix: () => void
  onReopen: () => void
}) {
  const info = CLASSIFICATION_INFO[audit.classification]
  return (
    <div className="rounded-lg border border-white/8 bg-[#0a0e1a]/60">
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-white/5 transition-colors"
      >
        <span
          className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase
                     tracking-wider border ${info.color}`}
        >
          {info.label}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#f0ece4] truncate">{audit.query}</p>
          <p className="text-[11px] text-[#6b7594] mt-0.5">
            {new Date(audit.created_at).toLocaleString()}
            {audit.user_email && <> · {audit.user_email}</>}
            {audit.web_surface_tier && (
              <> · web fallback: <span className="text-[#f0ece4]/70">{audit.web_surface_tier}</span></>
            )}
            {audit.status !== 'open' && (
              <span className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase
                               bg-white/8 text-[#f0ece4]/70">
                {audit.status}
              </span>
            )}
          </p>
        </div>
        <span className="text-[#6b7594] text-xs ml-2 flex-shrink-0">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-white/8 px-4 py-4 space-y-4">
          {/* Reasoning */}
          {audit.classifier_reasoning && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Reasoning
              </p>
              <p className="text-sm text-[#f0ece4]/85 leading-relaxed">
                {audit.classifier_reasoning}
              </p>
            </div>
          )}

          {/* Recommendation */}
          {audit.recommendation && (
            <div className="bg-[#2dd4bf]/5 border border-[#2dd4bf]/20 rounded-md p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#2dd4bf] mb-1">
                Recommendation
              </p>
              <p className="text-sm text-[#f0ece4]/85 leading-relaxed">
                {audit.recommendation}
              </p>
            </div>
          )}

          {/* Top retrieved */}
          {audit.top_retrieved_sections.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Top retrieved (rank, similarity, source — section)
              </p>
              <ol className="text-xs font-mono text-[#f0ece4]/75 space-y-1">
                {audit.top_retrieved_sections.slice(0, 8).map((s, i) => (
                  <li key={i} className="truncate">
                    {i + 1}. [{(s.similarity ?? 0).toFixed(3)}] {s.source ?? '?'} ::{' '}
                    {s.section_number ?? '?'} — {s.section_title ?? ''}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {audit.admin_notes && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#6b7594] mb-1">
                Notes
              </p>
              <p className="text-sm text-[#f0ece4]/85 italic">{audit.admin_notes}</p>
            </div>
          )}

          {audit.fixed_at && (
            <p className="text-[11px] text-[#6b7594]">
              Fixed {new Date(audit.fixed_at).toLocaleString()}
              {audit.fixed_by_email && <> by {audit.fixed_by_email}</>}
            </p>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-white/8">
            {audit.conversation_id && (
              <Link
                href={`/admin?tab=chats&conversation_id=${audit.conversation_id}`}
                className="px-3 py-1.5 rounded-md border border-white/10
                           text-xs font-medium text-[#f0ece4]/80 hover:bg-white/5
                           transition-colors"
              >
                View chat →
              </Link>
            )}
            {audit.status === 'open' ? (
              <>
                <button
                  onClick={onMarkFixed}
                  className="px-3 py-1.5 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                             text-xs font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                             transition-colors"
                >
                  Mark fixed
                </button>
                <button
                  onClick={onMarkWontFix}
                  className="px-3 py-1.5 rounded-md border border-white/10
                             text-xs font-medium text-[#6b7594] hover:text-[#f0ece4]
                             hover:bg-white/5 transition-colors"
                >
                  Won&apos;t fix
                </button>
              </>
            ) : (
              <button
                onClick={onReopen}
                className="px-3 py-1.5 rounded-md border border-white/10
                           text-xs font-medium text-[#f0ece4]/80 hover:bg-white/5
                           transition-colors"
              >
                Re-open
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


function topClass(by: Partial<Record<Classification, number>>): string {
  const entries = Object.entries(by) as [Classification, number][]
  if (entries.length === 0) return '—'
  entries.sort((a, b) => b[1] - a[1])
  const [cls, n] = entries[0]
  return `${CLASSIFICATION_INFO[cls].label} (${n})`
}
