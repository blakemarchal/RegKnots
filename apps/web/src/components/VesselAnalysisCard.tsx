'use client'

// Sprint D6.64 — vessel-document analysis card.
// Drop-a-vessel-in, get the regulatory implications.

import { useState } from 'react'
import { AILoadingState } from './AILoadingState'
import { apiRequest } from '@/lib/api'

interface RegImplication {
  area: string
  citation: string
  summary: string
}

interface VesselAnalysis {
  vessel_id: string
  vessel_name: string
  narrative: string
  applicable_regulations: RegImplication[]
  inspection_focus: string[]
  required_certificates: string[]
  citations: string[]
  model_used: string
}

export function VesselAnalysisCard({ vesselId }: { vesselId: string }) {
  const [analysis, setAnalysis] = useState<VesselAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function analyze() {
    setLoading(true)
    setError(null)
    try {
      const result = await apiRequest<VesselAnalysis>(
        `/me/vessel-analysis/${vesselId}`,
      )
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  if (!analysis && !loading && !error) {
    return (
      <button
        onClick={() => void analyze()}
        className="w-full font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
          hover:brightness-110 rounded-lg px-3 py-2.5 transition-[filter]
          flex items-center justify-center gap-2"
      >
        <span>✨</span>
        Analyze regulatory implications
      </button>
    )
  }

  if (loading) {
    return (
      <AILoadingState
        variant="card"
        messages={[
          'Reading the vessel profile + COI extraction…',
          'Retrieving applicable CFR / SOLAS / MARPOL passages…',
          'Mapping the regulatory implications…',
          'Identifying inspection focus areas…',
          'Drafting the structured report…',
        ]}
      />
    )
  }

  if (error) {
    return (
      <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3
        font-mono text-xs text-rose-400 flex items-center justify-between gap-3">
        <span>{error}</span>
        <button onClick={() => void analyze()} className="text-[#2dd4bf] hover:underline">
          Try again
        </button>
      </div>
    )
  }

  if (!analysis) return null

  return (
    <div className="flex flex-col gap-4">
      {analysis.narrative && (
        <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
          {analysis.narrative}
        </p>
      )}

      {analysis.applicable_regulations.length > 0 && (
        <div>
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-wider mb-2">
            Applicable regulations
          </p>
          <div className="space-y-2">
            {analysis.applicable_regulations.map((r, i) => (
              <div key={i} className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
                <div className="flex items-baseline justify-between gap-2 flex-wrap mb-1">
                  <p className="font-mono text-xs text-[#f0ece4] font-bold">{r.area}</p>
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded
                    bg-white/5 border border-white/10 text-[#2dd4bf] whitespace-nowrap">
                    {r.citation}
                  </span>
                </div>
                <p className="font-mono text-[11px] text-[#f0ece4]/85 leading-relaxed">
                  {r.summary}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {analysis.inspection_focus.length > 0 && (
        <div>
          <p className="font-mono text-[10px] text-amber-300 uppercase tracking-wider mb-1.5">
            What inspectors will look at
          </p>
          <ul className="space-y-1 list-disc list-inside marker:text-amber-300">
            {analysis.inspection_focus.map((f, i) => (
              <li key={i} className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed">
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.required_certificates.length > 0 && (
        <div>
          <p className="font-mono text-[10px] text-emerald-300 uppercase tracking-wider mb-1.5">
            Required certificates
          </p>
          <ul className="space-y-1 list-disc list-inside marker:text-emerald-300">
            {analysis.required_certificates.map((c, i) => (
              <li key={i} className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="font-mono text-[10px] text-[#6b7594] italic">
        AI-assisted analysis grounded in the vessel profile + RegKnots&apos; CFR/SOLAS corpus.
        Verify against the regulation before relying.
      </p>
    </div>
  )
}
