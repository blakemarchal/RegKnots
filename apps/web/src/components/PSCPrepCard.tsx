'use client'

// Sprint D6.64 — personalized Port State Control prep.

import { useState } from 'react'
import { AILoadingState } from './AILoadingState'
import { apiRequest } from '@/lib/api'

interface PSCFocusArea {
  title: string
  rationale: string
  citation: string
}

interface PSCPrep {
  vessel_id: string | null
  vessel_name: string | null
  flag_state: string | null
  target_port_region: string | null
  narrative: string
  focus_areas: PSCFocusArea[]
  common_deficiencies: string[]
  documents_to_have_ready: string[]
  citations: string[]
  model_used: string
}

const REGIONS = [
  'USCG (US ports)',
  'Paris MOU (Europe)',
  'Tokyo MOU (Asia-Pacific)',
  'Caribbean MOU',
  'Indian Ocean MOU',
  'Black Sea MOU',
  'Mediterranean MOU',
  'Other',
] as const

interface Props {
  vesselId?: string | null
  /** Optional prefill for the region; user can override. */
  defaultRegion?: string
}

export function PSCPrepCard({ vesselId, defaultRegion }: Props) {
  const [region, setRegion] = useState<string>(defaultRegion || REGIONS[0])
  const [analysis, setAnalysis] = useState<PSCPrep | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (vesselId) params.set('vessel_id', vesselId)
      params.set('target_port_region', region)
      const result = await apiRequest<PSCPrep>(`/me/psc-prep?${params}`)
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Prep failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-[#111827] border border-[#2dd4bf]/20 rounded-2xl p-5 flex flex-col gap-3">
      <div>
        <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-1">
          PSC Co-Pilot
        </p>
        <p className="font-display font-bold text-[#f0ece4] text-base">
          Get a focused inspection brief
        </p>
        <p className="font-mono text-xs text-[#6b7594] mt-1">
          Based on this vessel&apos;s profile + the port region you&apos;re heading to,
          we surface the items inspectors actually check on this class of vessel.
        </p>
      </div>

      {!analysis && !loading && (
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-end">
          <div className="flex-1">
            <label className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider block mb-1">
              Target port region
            </label>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full bg-[#0a0e1a] border border-white/10 rounded
                px-2 py-2 font-mono text-xs text-[#f0ece4]"
            >
              {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <button
            onClick={() => void run()}
            className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 rounded-lg px-3 py-2.5 transition-[filter]
              flex items-center gap-2 flex-shrink-0"
          >
            <span>✨</span>
            Build prep brief
          </button>
        </div>
      )}

      {loading && (
        <AILoadingState
          variant="card"
          messages={[
            'Reading the vessel profile…',
            `Pulling ${region} concentrated inspection campaign data…`,
            'Cross-checking common deficiencies for this vessel class…',
            'Drafting your focused prep brief…',
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

          {analysis.focus_areas.length > 0 && (
            <div>
              <p className="font-mono text-[10px] text-amber-300 uppercase tracking-wider mb-2">
                Focus areas
              </p>
              <div className="space-y-2">
                {analysis.focus_areas.map((f, i) => (
                  <div key={i} className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
                    <div className="flex items-baseline justify-between gap-2 flex-wrap mb-1">
                      <p className="font-mono text-xs text-[#f0ece4] font-bold break-words">{f.title}</p>
                      {f.citation && (
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded
                          bg-white/5 border border-white/10 text-[#2dd4bf] whitespace-nowrap">
                          {f.citation}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-[11px] text-[#f0ece4]/85 leading-relaxed">
                      {f.rationale}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {analysis.common_deficiencies.length > 0 && (
            <div>
              <p className="font-mono text-[10px] text-rose-300 uppercase tracking-wider mb-1.5">
                Common deficiencies on this class of vessel
              </p>
              <ul className="space-y-1 list-disc list-inside marker:text-rose-300">
                {analysis.common_deficiencies.map((d, i) => (
                  <li key={i} className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed">
                    {d}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.documents_to_have_ready.length > 0 && (
            <div>
              <p className="font-mono text-[10px] text-emerald-300 uppercase tracking-wider mb-1.5">
                Have ready before they board
              </p>
              <ul className="space-y-1 list-disc list-inside marker:text-emerald-300">
                {analysis.documents_to_have_ready.map((d, i) => (
                  <li key={i} className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed">
                    {d}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            onClick={() => { setAnalysis(null); setError(null) }}
            className="font-mono text-[10px] text-[#6b7594] hover:text-[#2dd4bf] self-start"
          >
            ↻ Generate for another region
          </button>
        </>
      )}
    </div>
  )
}
