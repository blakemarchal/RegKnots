'use client'

import { useEffect, useState } from 'react'
import { CompassRose } from './CompassRose'
import { getTailoredPrompts, type VesselProfileForPrompts } from '@/lib/vesselPrompts'
import { apiRequest } from '@/lib/api'

interface Props {
  onPrompt: (text: string) => void
  isNewConversation: boolean
  vessel?: VesselProfileForPrompts | null
}

// D6.63 Move A — light user-context shape needed only for personalized
// starters. Real chat requests use a richer GET /me/context payload.
interface MariniarContextLight {
  credentials: Array<{
    id: string
    credential_type: string
    title: string
    expiry_date: string | null
    days_until_expiry: number | null
  }>
  sea_time: { entry_count: number; total_days: number } | null
}

// Build mariner-aware prompts (D6.63). Returns prompts that reason
// against the user's actual record, prepended to the base set.
function buildMarinerPrompts(ctx: MariniarContextLight | null): string[] {
  if (!ctx) return []
  const out: string[] = []

  // Pick the soonest-expiring credential we have an expiry for.
  const expiring = (ctx.credentials || [])
    .filter((c) => c.days_until_expiry !== null && c.days_until_expiry !== undefined)
    .sort((a, b) => (a.days_until_expiry as number) - (b.days_until_expiry as number))
  const next = expiring[0]
  if (next) {
    const label = next.title || next.credential_type.toUpperCase()
    if ((next.days_until_expiry ?? 0) <= 180) {
      out.push(`What do I need to renew my ${label}?`)
    }
  }

  // Has at least one MMC + meaningful sea-time → upgrade question
  const hasMmc = (ctx.credentials || []).some((c) => c.credential_type === 'mmc')
  const hasSeaTime = (ctx.sea_time?.entry_count ?? 0) > 0
  if (hasMmc && hasSeaTime) {
    out.push("Based on my record, what's my next credential upgrade?")
  } else if (hasMmc) {
    out.push("What credential upgrades am I closest to qualifying for?")
  }

  // Fold-in: total record check
  if ((ctx.credentials || []).length > 0) {
    out.push("Are there any compliance gaps in my stored credentials?")
  }

  return out.slice(0, 3)
}

export function EmptyState({ onPrompt, isNewConversation, vessel = null }: Props) {
  const { prompts: vesselPrompts, tailored } = getTailoredPrompts(vessel)
  const [marinerCtx, setMarinerCtx] = useState<MariniarContextLight | null>(null)

  // D6.63 — fire a best-effort /me/context fetch on mount. If it
  // succeeds we can offer mariner-aware starters; if it fails we
  // silently fall back to the existing vessel-only suggestions.
  useEffect(() => {
    let cancelled = false
    apiRequest<MariniarContextLight>('/me/context')
      .then((data) => { if (!cancelled) setMarinerCtx(data) })
      .catch(() => { /* unauthenticated or no data — silent */ })
    return () => { cancelled = true }
  }, [])

  const marinerPrompts = buildMarinerPrompts(marinerCtx)
  const personalized = marinerPrompts.length > 0
  // Mariner prompts go first when present — they're the strongest
  // conversion signal (the user can immediately see the chat reasons
  // about their actual record).
  const merged = personalized
    ? [...marinerPrompts, ...vesselPrompts].slice(0, 4)
    : vesselPrompts
  const headlineLabel = personalized
    ? 'Tailored to your record'
    : (tailored && vessel ? `Tailored for ${vessel.name}` : null)

  return (
    <div className="flex flex-col items-center justify-center min-h-full px-6 py-12 text-center select-none">
      {/* Compass rose */}
      <div className="relative mb-8">
        <CompassRose className="w-28 h-28 text-teal opacity-20" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-6 h-6 rounded-full bg-teal/10 border border-teal/30" />
        </div>
      </div>

      {/* Logo wordmark */}
      <h1 className="font-display text-5xl font-bold tracking-wide text-[#f0ece4] mb-1">
        RegKnot
      </h1>
      <p className="text-[11px] text-[#6b7594] tracking-[0.25em] uppercase mb-2 font-semibold">
        Maritime Compliance Co-Pilot
      </p>
      <p className="text-sm text-[#6b7594] max-w-xs mb-10 leading-relaxed">
        Ask anything about maritime regulations. Cited answers from the IMO conventions,
        U.S. CFR, and flag-state regulators (UK, Australia, Singapore, Hong Kong,
        Norway, Liberia, Marshall Islands, Bahamas).
      </p>

      {/* Suggested prompts — only on a fresh new conversation */}
      {isNewConversation && (
        <div className="flex flex-col gap-2 w-full max-w-xs">
          {headlineLabel ? (
            <p className="text-[10px] text-teal uppercase tracking-widest mb-1 flex items-center gap-1.5 justify-center">
              <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {headlineLabel}
            </p>
          ) : (
            <p className="text-[10px] text-[#6b7594] uppercase tracking-widest mb-1">Try asking</p>
          )}
          {merged.map((prompt, i) => (
            <button
              key={prompt}
              onClick={() => onPrompt(prompt)}
              className={`px-4 py-2.5 rounded-xl text-sm text-left
                bg-white/5 border border-white/8 text-[#f0ece4]/80
                hover:bg-white/10 hover:border-teal/30 hover:text-[#f0ece4]
                transition-all duration-150
                ${i === 3 ? 'hidden md:block' : ''}`}
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
