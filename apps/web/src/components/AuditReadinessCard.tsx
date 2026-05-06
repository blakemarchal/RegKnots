'use client'

// Sprint D6.64 — audit readiness assessment.

import { useState } from 'react'
import { AILoadingState } from './AILoadingState'
import { apiRequest } from '@/lib/api'

interface Finding {
  severity: 'critical' | 'warning' | 'info'
  area: string
  headline: string
  detail: string
  affected: string
  citation: string | null
}

interface Audit {
  workspace_id: string | null
  score_percent: number
  score_label: string
  narrative: string
  findings: Finding[]
  counts: { critical?: number; warning?: number; info?: number }
  model_used: string
}

const SEV_INFO: Record<Finding['severity'], { label: string; class: string; bar: string }> = {
  critical: { label: 'Critical', class: 'border-rose-500/40 bg-rose-500/5',     bar: 'bg-rose-400' },
  warning:  { label: 'Warning',  class: 'border-amber-500/40 bg-amber-500/5',   bar: 'bg-amber-400' },
  info:     { label: 'Info',     class: 'border-white/10 bg-white/3',           bar: 'bg-white/30' },
}

interface Props {
  workspaceId?: string | null
}

export function AuditReadinessCard({ workspaceId }: Props) {
  const [analysis, setAnalysis] = useState<Audit | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (workspaceId) params.set('workspace_id', workspaceId)
      const url = `/me/audit-readiness${params.toString() ? `?${params}` : ''}`
      const result = await apiRequest<Audit>(url)
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Audit failed')
    } finally {
      setLoading(false)
    }
  }

  // Score color: green ≥85, amber 65-84, rose <65
  function scoreColor(s: number): string {
    if (s >= 85) return 'text-emerald-300'
    if (s >= 65) return 'text-amber-300'
    return 'text-rose-300'
  }
  function scoreBarColor(s: number): string {
    if (s >= 85) return 'bg-emerald-400'
    if (s >= 65) return 'bg-amber-400'
    return 'bg-rose-400'
  }

  return (
    <div className="bg-[#111827] border border-[#2dd4bf]/20 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-1">
            Audit Readiness
          </p>
          <p className="font-display font-bold text-[#f0ece4] text-base">
            Where do you stand right now?
          </p>
          <p className="font-mono text-xs text-[#6b7594] mt-1 max-w-md">
            We assess your stored credentials, vessel docs, and sea-time against
            the regulatory bar. Score, gaps, and what to fix first.
          </p>
        </div>
        {!analysis && !loading && (
          <button
            onClick={() => void run()}
            className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 rounded-lg px-3 py-2 transition-[filter]
              flex items-center gap-2 flex-shrink-0"
          >
            <span>✨</span>
            Assess readiness
          </button>
        )}
      </div>

      {loading && (
        <AILoadingState
          variant="card"
          messages={[
            'Pulling your credentials + vessel docs + sea-time…',
            'Cross-checking expirations and missing supporting docs…',
            'Scoring against the regulatory bar…',
            'Drafting the assessment…',
          ]}
        />
      )}

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3
          font-mono text-xs text-rose-400 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => void run()} className="text-[#2dd4bf] hover:underline">
            Try again
          </button>
        </div>
      )}

      {analysis && (
        <>
          {/* Score block */}
          <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-4 flex items-center gap-4">
            <div className="text-center">
              <p className={`font-display font-black text-4xl leading-none ${scoreColor(analysis.score_percent)}`}>
                {analysis.score_percent}
              </p>
              <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mt-0.5">
                /100
              </p>
            </div>
            <div className="flex-1 min-w-0">
              <p className={`font-mono text-sm font-bold ${scoreColor(analysis.score_percent)}`}>
                {analysis.score_label}
              </p>
              <div className="w-full bg-white/5 rounded-full h-1.5 mt-2">
                <div
                  className={`h-full rounded-full transition-all ${scoreBarColor(analysis.score_percent)}`}
                  style={{ width: `${Math.max(2, Math.min(100, analysis.score_percent))}%` }}
                />
              </div>
              <div className="flex items-center gap-3 mt-2 font-mono text-[10px] text-[#6b7594]">
                {(analysis.counts.critical ?? 0) > 0 && (
                  <span><span className="text-rose-300">●</span> {analysis.counts.critical} critical</span>
                )}
                {(analysis.counts.warning ?? 0) > 0 && (
                  <span><span className="text-amber-300">●</span> {analysis.counts.warning} warning</span>
                )}
                {(analysis.counts.info ?? 0) > 0 && (
                  <span><span className="text-[#6b7594]">●</span> {analysis.counts.info} info</span>
                )}
              </div>
            </div>
          </div>

          {analysis.narrative && (
            <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
              {analysis.narrative}
            </p>
          )}

          {analysis.findings.length > 0 && (
            <div className="space-y-2">
              {analysis.findings.map((f, i) => {
                const info = SEV_INFO[f.severity]
                return (
                  <div key={i} className={`rounded-lg border p-3 ${info.class}`}>
                    <div className="flex items-baseline justify-between gap-2 flex-wrap mb-1">
                      <p className="font-mono text-xs text-[#f0ece4] font-bold break-words">
                        {f.headline}
                      </p>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded
                          bg-white/5 border border-white/10 text-[#f0ece4]/70 whitespace-nowrap">
                          {f.area}
                        </span>
                        {f.citation && (
                          <span className="font-mono text-[10px] px-1.5 py-0.5 rounded
                            bg-white/5 border border-white/10 text-[#2dd4bf] whitespace-nowrap">
                            {f.citation}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="font-mono text-[11px] text-[#f0ece4]/85 leading-relaxed">
                      {f.detail}
                    </p>
                    {f.affected && (
                      <p className="font-mono text-[10px] text-[#6b7594] mt-1">
                        Affected: <span className="text-[#f0ece4]/70">{f.affected}</span>
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          <button
            onClick={() => { setAnalysis(null); setError(null) }}
            className="font-mono text-[10px] text-[#6b7594] hover:text-[#2dd4bf] self-start"
          >
            ↻ Re-assess
          </button>
        </>
      )}
    </div>
  )
}
