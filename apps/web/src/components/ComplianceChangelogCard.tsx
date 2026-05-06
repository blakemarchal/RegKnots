'use client'

// Sprint D6.64 — compliance changelog. What changed in the regs that
// actually affects THIS user (filtered against their stored profile).

import { useState } from 'react'
import { AILoadingState } from './AILoadingState'
import { apiRequest } from '@/lib/api'

interface ChangelogItem {
  title: string
  citation: string
  why_it_affects_you: string
  severity: 'high' | 'medium' | 'low'
  effective_date: string | null
}

interface Changelog {
  window_days: number
  items: ChangelogItem[]
  narrative: string
  model_used: string
}

const SEVERITY_INFO: Record<ChangelogItem['severity'], { label: string; class: string }> = {
  high:   { label: 'High',   class: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  medium: { label: 'Medium', class: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  low:    { label: 'Low',    class: 'bg-white/5 text-[#6b7594] border-white/10' },
}

interface Props {
  /** Default 7d. Caller can pass 14, 30, 90 for digest views. */
  defaultWindowDays?: number
}

export function ComplianceChangelogCard({ defaultWindowDays = 7 }: Props) {
  const [windowDays, setWindowDays] = useState(defaultWindowDays)
  const [analysis, setAnalysis] = useState<Changelog | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(days: number = windowDays) {
    setLoading(true)
    setError(null)
    try {
      const result = await apiRequest<Changelog>(`/me/compliance-changelog?window_days=${days}`)
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Changelog failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-[#111827] border border-[#2dd4bf]/20 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-1">
            Compliance Changelog
          </p>
          <p className="font-display font-bold text-[#f0ece4] text-base">
            What changed that affects you
          </p>
          <p className="font-mono text-xs text-[#6b7594] mt-1 max-w-md">
            We scan recent corpus updates (NVICs, CFR amendments, IMO resolutions)
            and filter to the ones your profile actually intersects.
          </p>
        </div>
        {!analysis && !loading && (
          <div className="flex items-center gap-2">
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              className="bg-[#0a0e1a] border border-white/10 rounded px-2 py-2
                font-mono text-xs text-[#f0ece4]"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button
              onClick={() => void run()}
              className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
                hover:brightness-110 rounded-lg px-3 py-2 transition-[filter]
                flex items-center gap-2"
            >
              <span>✨</span>
              Run digest
            </button>
          </div>
        )}
      </div>

      {loading && (
        <AILoadingState
          variant="card"
          messages={[
            'Pulling recent corpus changes…',
            'Reading your stored profile…',
            'Filtering to changes that intersect your record…',
            'Drafting the digest…',
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
          <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
            {analysis.narrative}
          </p>

          {analysis.items.length === 0 ? (
            <p className="font-mono text-xs text-[#6b7594] italic">
              Nothing relevant in the last {analysis.window_days} days.
            </p>
          ) : (
            <div className="space-y-2">
              {analysis.items.map((it, i) => {
                const sev = SEVERITY_INFO[it.severity]
                return (
                  <div key={i} className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
                    <div className="flex items-baseline justify-between gap-2 flex-wrap mb-1">
                      <p className="font-mono text-xs text-[#f0ece4] font-bold break-words">
                        {it.title}
                      </p>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded border uppercase tracking-wider ${sev.class}`}>
                          {sev.label}
                        </span>
                        {it.citation && (
                          <span className="font-mono text-[10px] px-1.5 py-0.5 rounded
                            bg-white/5 border border-white/10 text-[#2dd4bf] whitespace-nowrap">
                            {it.citation}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="font-mono text-[11px] text-[#f0ece4]/85 leading-relaxed">
                      {it.why_it_affects_you}
                    </p>
                    {it.effective_date && (
                      <p className="font-mono text-[10px] text-[#6b7594] mt-1">
                        Effective: {it.effective_date}
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
            ↻ Run again
          </button>
        </>
      )}
    </div>
  )
}
