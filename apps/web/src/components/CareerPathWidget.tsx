'use client'

// Sprint D6.63 Move C — Career Path widget.
//
// Reads the user's stored credentials + sea-time, retrieves the
// 11.x-series CFR via RAG, and asks Sonnet: "What upgrades is this
// mariner cap-eligible for right now? What's within reach with a
// quantified gap?"
//
// Renders at the bottom of the credentials page. Lazy — only fires
// when the user clicks "Analyze upgrade options."
//
// This is the move competitors fundamentally can't replicate:
// vault apps don't have a regulation corpus to ground "what's the
// next step" against the actual CFR ladder.

import { useState } from 'react'
import { apiRequest } from '@/lib/api'

interface CareerUpgrade {
  title: string
  status: 'cap_eligible' | 'within_reach' | 'requires_training'
  summary: string
  gap: string | null
  estimated_timeline: string | null
  citations: string[]
}

interface CareerProgression {
  current_credentials: string[]
  cap_eligible_now: CareerUpgrade[]
  within_reach: CareerUpgrade[]
  narrative: string
  citations: string[]
  model_used: string
}


function UpgradeCard({ u, accent }: { u: CareerUpgrade; accent: 'cap' | 'reach' }) {
  const accentClass =
    accent === 'cap'
      ? 'border-emerald-500/30 bg-emerald-500/5'
      : 'border-amber-500/30 bg-amber-500/5'
  const accentText =
    accent === 'cap' ? 'text-emerald-300' : 'text-amber-300'
  return (
    <div className={`rounded-lg border p-3 flex flex-col gap-2 ${accentClass}`}>
      <div className="flex items-start justify-between gap-2">
        <p className={`font-mono text-sm font-bold ${accentText}`}>{u.title}</p>
        {u.estimated_timeline && (
          <span className="font-mono text-[10px] text-[#6b7594] flex-shrink-0">
            {u.estimated_timeline}
          </span>
        )}
      </div>
      {u.summary && (
        <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed">{u.summary}</p>
      )}
      {u.gap && (
        <p className="font-mono text-xs text-amber-300">
          Gap: <span className="text-[#f0ece4]">{u.gap}</span>
        </p>
      )}
      {u.citations.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {u.citations.map((c, i) => (
            <span
              key={i}
              className="font-mono text-[9px] px-1.5 py-0.5 rounded
                bg-white/5 border border-white/10 text-[#2dd4bf]"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}


export function CareerPathWidget() {
  const [analysis, setAnalysis] = useState<CareerProgression | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function analyze() {
    setLoading(true)
    setError(null)
    try {
      const result = await apiRequest<CareerProgression>('/me/career-progression')
      setAnalysis(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="mt-6 bg-[#111827] border border-[#2dd4bf]/20 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-1">
            Career Path
          </p>
          <p className="font-display font-bold text-[#f0ece4] text-base">
            What&apos;s your next upgrade?
          </p>
          <p className="font-mono text-xs text-[#6b7594] mt-1 max-w-md">
            We read your stored credentials + sea-time, then look at the
            actual CFR ladder to see what you qualify for now and what&apos;s
            close.
          </p>
        </div>
        {!analysis && !loading && (
          <button
            onClick={() => void analyze()}
            className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 rounded-lg px-3 py-2 transition-[filter]
              flex items-center gap-2 flex-shrink-0"
          >
            <span>✨</span>
            Analyze upgrade options
          </button>
        )}
        {analysis && (
          <button
            onClick={() => void analyze()}
            className="font-mono text-[10px] text-[#2dd4bf] hover:underline flex-shrink-0"
            title="Re-run with current data"
          >
            Refresh
          </button>
        )}
      </div>

      {loading && (
        <div className="font-mono text-xs text-[#6b7594] py-3 text-center">
          Reading your record + the CFR officer-endorsement ladder…
        </div>
      )}

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3
          font-mono text-xs text-rose-400">
          {error}
        </div>
      )}

      {analysis && (
        <>
          {/* Current credentials snapshot */}
          {analysis.current_credentials.length > 0 && (
            <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
              <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1.5">
                Where you are
              </p>
              <ul className="space-y-1">
                {analysis.current_credentials.map((c, i) => (
                  <li key={i} className="font-mono text-xs text-[#f0ece4]/85">
                    · {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Narrative */}
          {analysis.narrative && (
            <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
              {analysis.narrative}
            </p>
          )}

          {/* Cap-eligible-now */}
          {analysis.cap_eligible_now.length > 0 && (
            <div>
              <p className="font-mono text-[10px] text-emerald-300 uppercase tracking-wider mb-2">
                Cap-eligible right now
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {analysis.cap_eligible_now.map((u, i) => (
                  <UpgradeCard key={i} u={u} accent="cap" />
                ))}
              </div>
            </div>
          )}

          {/* Within reach */}
          {analysis.within_reach.length > 0 && (
            <div>
              <p className="font-mono text-[10px] text-amber-300 uppercase tracking-wider mb-2">
                Within reach
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {analysis.within_reach.map((u, i) => (
                  <UpgradeCard key={i} u={u} accent="reach" />
                ))}
              </div>
            </div>
          )}

          {/* Empty path */}
          {analysis.cap_eligible_now.length === 0 && analysis.within_reach.length === 0 && (
            <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-3">
              <p className="font-mono text-xs text-[#6b7594]">
                No specific upgrades surfaced yet — keep logging sea-time and
                adding credentials. Re-run when you have new data.
              </p>
            </div>
          )}

          <p className="font-mono text-[10px] text-[#6b7594] italic mt-1">
            AI-assisted analysis grounded in your stored record + RegKnots&apos; CFR corpus.
            Verify against the actual regulation before applying.
          </p>
        </>
      )}
    </section>
  )
}
