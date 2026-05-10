'use client'

// Sprint D6.84 — Confidence tier chip + footnote rendering.
//
// Four visual states corresponding to the backend tier router:
//
//   verified           → green, "✓ RegKnot Verified"
//   industry_standard  → teal,  "⚓ Industry Standard"  (no citation; footnote disclosure)
//   relaxed_web        → amber, "🌐 Web Reference · Confidence N/5"  (disclaimer)
//   best_effort        → slate, "⚠ Best Effort"
//
// The chip is rendered ABOVE the answer body (header position), so the
// epistemic status is the first thing the user perceives. The Tier 2
// answer also carries an inline footnote at the bottom of the message
// (the synthesizer renders it via tier_router.render_industry_standard_answer).
// Tier 3 also gets a small disclaimer block right under the chip.

import type { TierMetadata } from '@/types/chat'

interface Props {
  metadata: TierMetadata
}

interface TierVisual {
  label: string
  icon: string
  className: string
  hint: string  // tooltip on hover
}

const VISUALS: Record<TierMetadata['label'], TierVisual> = {
  verified: {
    label: 'RegKnot Verified',
    icon: '✓',
    className:
      'bg-emerald-950/70 text-emerald-300 border border-emerald-700/60 ' +
      'hover:bg-emerald-900/70',
    hint: 'Answer cited to your regulations corpus and verified.',
  },
  industry_standard: {
    label: 'Industry Standard',
    icon: '⚓',
    className:
      'bg-teal-950/70 text-teal-300 border border-teal-700/60 ' +
      'hover:bg-teal-900/70',
    hint:
      'Settled maritime engineering / seamanship knowledge — not cited to ' +
      'a specific regulation. Verified for self-consistency before render.',
  },
  relaxed_web: {
    label: 'Web Reference',
    icon: '🌐',
    className:
      'bg-amber-950/70 text-amber-300 border border-amber-700/60 ' +
      'hover:bg-amber-900/70',
    hint:
      'Pulled from an external maritime source — please verify against ' +
      'the cited URL before relying on it.',
  },
  best_effort: {
    label: 'Best Effort',
    icon: '⚠',
    className:
      'bg-slate-800/70 text-slate-300 border border-slate-600/60 ' +
      'hover:bg-slate-700/70',
    hint:
      'We did not find this in the corpus or settled industry knowledge. ' +
      'Treat the response as a best-effort starting point.',
  },
}

export function TierChip({ metadata }: Props) {
  const visual = VISUALS[metadata.label] || VISUALS.best_effort
  const showConfidence = metadata.label === 'relaxed_web' && metadata.web_confidence != null

  return (
    <div className="mb-2 flex items-center gap-2">
      <span
        className={
          'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ' +
          'leading-none transition-colors duration-150 cursor-help ' +
          visual.className
        }
        title={visual.hint}
        aria-label={`Confidence tier: ${visual.label}`}
      >
        <span aria-hidden>{visual.icon}</span>
        <span>{visual.label}</span>
        {showConfidence && (
          <span className="opacity-80 ml-1">
            · Confidence {metadata.web_confidence}/5
          </span>
        )}
      </span>
    </div>
  )
}


// Tier 3 (relaxed web) renders a small disclaimer banner under the chip
// to make the epistemic status legible even on glance. Kept separate
// from the chip so it can be conditionally rendered without making the
// chip itself ugly.
export function TierWebDisclaimer({ confidence }: { confidence: number | null | undefined }) {
  return (
    <div className="mb-3 px-3 py-2 rounded-md border border-amber-700/40 bg-amber-950/30">
      <p className="text-[11px] font-mono text-amber-200/90 leading-relaxed">
        Pulled from a trusted maritime source on the web — not from your
        regulations corpus. Please verify against the linked source before
        relying on it for a compliance-critical decision.
        {confidence != null && (
          <span className="opacity-70"> Source confidence: {confidence}/5.</span>
        )}
      </p>
    </div>
  )
}
