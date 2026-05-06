'use client'

// Sprint D6.63 Move B — Renewal Co-Pilot.
//
// Personalized readiness analysis for one stored credential. Reasons
// against the user's full record (other credentials, sea-time totals)
// + the controlling CFR / regulation passages from the corpus, then
// returns: an overall verdict (ready / partial / not_ready / expired),
// a per-requirement checklist (✓ / ✗ / ?), suggested actions, and
// CFR citations.
//
// Renders inline below a credential row. Lazy-loaded — only fires
// the (~$0.03 Sonnet) analysis when the user clicks the button.

import { useState } from 'react'
import { AILoadingState } from './AILoadingState'
import { apiRequest } from '@/lib/api'

interface RenewalRequirement {
  label: string
  status: 'satisfied' | 'missing' | 'unknown' | 'expiring'
  detail: string
}

interface RenewalReadiness {
  credential_id: string
  credential_label: string
  days_until_expiry: number | null
  expires_on: string | null
  overall_status: 'ready' | 'partial' | 'not_ready' | 'expired'
  narrative: string
  requirements: RenewalRequirement[]
  suggested_actions: string[]
  citations: string[]
  model_used: string
}


const STATUS_BADGE: Record<RenewalReadiness['overall_status'], { label: string; class: string }> = {
  ready:     { label: 'Ready to file',     class: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  partial:   { label: 'Almost there',      class: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  not_ready: { label: 'Gaps to close',     class: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  expired:   { label: 'Expired',           class: 'bg-red-500/20 text-red-300 border-red-500/40' },
}

const REQ_BADGE: Record<RenewalRequirement['status'], { glyph: string; class: string }> = {
  satisfied: { glyph: '✓', class: 'text-emerald-400' },
  missing:   { glyph: '✗', class: 'text-rose-400' },
  expiring:  { glyph: '!', class: 'text-amber-400' },
  unknown:   { glyph: '?', class: 'text-[#6b7594]' },
}


export function RenewalCoPilotCard({ credentialId }: { credentialId: string }) {
  const [analysis, setAnalysis] = useState<RenewalReadiness | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function analyze() {
    setLoading(true)
    setError(null)
    try {
      const result = await apiRequest<RenewalReadiness>(
        `/me/renewal-readiness/${credentialId}`,
      )
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  // Initial state — show the trigger button.
  if (!analysis && !loading && !error) {
    return (
      <div className="mt-3 pt-3 border-t border-white/8">
        <button
          onClick={() => void analyze()}
          className="w-full font-mono text-xs text-[#2dd4bf]
            border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 hover:bg-[#2dd4bf]/10
            rounded-lg py-2 px-3 transition-colors flex items-center
            justify-center gap-2"
          title="Personalized readiness analysis grounded in CFR + your record"
        >
          <span className="text-[#fbbf24]">✨</span>
          Analyze renewal readiness
        </button>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="mt-3 pt-3 border-t border-white/8">
        <AILoadingState
          variant="inline"
          messages={[
            'Reading your stored record…',
            'Retrieving controlling CFR sections…',
            'Cross-checking required supporting documents…',
            'Synthesizing your readiness verdict…',
          ]}
        />
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-3 pt-3 border-t border-white/8">
        <div className="font-mono text-xs text-rose-400 mb-2">{error}</div>
        <button
          onClick={() => void analyze()}
          className="font-mono text-[10px] text-[#2dd4bf] hover:underline"
        >
          Try again
        </button>
      </div>
    )
  }

  if (!analysis) return null

  const statusInfo = STATUS_BADGE[analysis.overall_status]

  return (
    <div className="mt-3 pt-3 border-t border-white/8 flex flex-col gap-3">
      {/* Header — overall verdict */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-[#fbbf24]">✨</span>
          <span className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
            Renewal Co-Pilot
          </span>
        </div>
        <span className={`font-mono text-[10px] px-2 py-0.5 rounded border uppercase tracking-wider ${statusInfo.class}`}>
          {statusInfo.label}
        </span>
      </div>

      {/* Narrative */}
      {analysis.narrative && (
        <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
          {analysis.narrative}
        </p>
      )}

      {/* Requirements checklist */}
      {analysis.requirements.length > 0 && (
        <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
          <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-2">
            Requirements
          </p>
          <ul className="space-y-1.5">
            {analysis.requirements.map((r, i) => {
              const badge = REQ_BADGE[r.status]
              return (
                <li key={i} className="flex items-start gap-2">
                  <span className={`font-mono text-sm font-bold flex-shrink-0 mt-0.5 ${badge.class}`}>
                    {badge.glyph}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="font-mono text-xs text-[#f0ece4]">{r.label}</p>
                    <p className="font-mono text-[11px] text-[#6b7594] leading-relaxed mt-0.5">
                      {r.detail}
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* Suggested actions */}
      {analysis.suggested_actions.length > 0 && (
        <div>
          <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1.5">
            Suggested actions
          </p>
          <ol className="space-y-1 list-decimal list-inside">
            {analysis.suggested_actions.map((a, i) => (
              <li key={i} className="font-mono text-xs text-[#f0ece4]/90 leading-relaxed">
                {a}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Citations */}
      {analysis.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {analysis.citations.map((c, i) => (
            <span
              key={i}
              className="font-mono text-[10px] px-2 py-0.5 rounded
                bg-white/5 border border-white/10 text-[#2dd4bf]"
            >
              {c}
            </span>
          ))}
        </div>
      )}

      <p className="font-mono text-[10px] text-[#6b7594] italic">
        AI-assisted analysis grounded in your stored record + RegKnots&apos; CFR corpus.
        Verify against the actual regulation before filing.
      </p>
    </div>
  )
}
