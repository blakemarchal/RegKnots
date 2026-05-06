'use client'

// Sprint D6.63 hotfix — animated loading state for long-running AI
// reasoning calls (Renewal Co-Pilot + Career Path).
//
// Sonnet calls take 3–10 seconds. Static "Loading…" text tells the
// user nothing and starts looking like a hang at the 3-second mark.
// This component:
//   1. Shows a spinning compass-style indicator (consistent with the
//      hero) so there's continuous visual motion.
//   2. Cycles through a sequence of progress messages that describe
//      what's actually happening — reading record, retrieving CFR,
//      synthesizing — so the user knows the system is working AND
//      learns what the analysis is grounded in.
//
// Used by both RenewalCoPilotCard and CareerPathWidget.

import { useEffect, useState } from 'react'

interface Props {
  /**
   * Sequence of messages to rotate through during the analysis.
   * The first run advances 1→last linearly; once we hit the end,
   * we keep cycling through the FILLER_MESSAGES below so the user
   * never sees the same message stuck on screen for more than ~2s.
   */
  messages: string[]
  /** Visual variant: 'inline' for narrow card slots, 'card' for the wider widget. */
  variant?: 'inline' | 'card'
}

const ROTATION_MS = 1800

// Generic filler messages cycled after the caller's specific
// progress messages run out. Sonnet calls can take 8-12s in
// the worst case (heavy not_ready prose); without these the
// "Synthesizing…" message would freeze and look like a hang.
const FILLER_MESSAGES = [
  'Verifying citations…',
  'Tightening the wording…',
  'Cross-checking against the corpus once more…',
  'Drafting the final structured response…',
  'Almost there — finishing up…',
] as const

export function AILoadingState({ messages, variant = 'inline' }: Props) {
  const [i, setI] = useState(0)
  // Combined timeline: caller's messages first, then filler in a loop.
  // Filler loops indefinitely (modulo) so we never run out of
  // motion regardless of how long the call actually takes.
  const totalScripted = messages.length

  useEffect(() => {
    if (totalScripted <= 1 && FILLER_MESSAGES.length === 0) return
    const id = setInterval(() => {
      setI((prev) => prev + 1)
    }, ROTATION_MS)
    return () => clearInterval(id)
  }, [totalScripted])

  const currentMessage =
    i < totalScripted
      ? messages[i]
      : FILLER_MESSAGES[(i - totalScripted) % FILLER_MESSAGES.length]

  // Progress dots stop at the end of the scripted timeline; once we
  // start cycling filler we hide the dots so it's not misleading.
  const showDots = i < totalScripted && totalScripted > 1
  const padding = variant === 'card' ? 'py-6' : 'py-3'

  return (
    <div className={`flex items-center gap-3 ${padding}`}>
      <Spinner />
      <div className="flex-1 min-w-0">
        <p className="font-mono text-xs text-[#f0ece4]/85 truncate">
          {currentMessage}
        </p>
        {showDots && <Dots count={totalScripted} active={i} />}
      </div>
    </div>
  )
}


function Spinner() {
  // Uses Tailwind's animate-spin built-in. Stroke + dashing gives the
  // compass-rose feel without importing the full CompassRose component.
  return (
    <svg
      className="w-5 h-5 text-[#2dd4bf] animate-spin flex-shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <circle
        cx="12" cy="12" r="9"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="2"
      />
      <path
        d="M21 12a9 9 0 0 1-9 9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}


function Dots({ count, active }: { count: number; active: number }) {
  if (count <= 1) return null
  return (
    <div className="flex items-center gap-1 mt-1.5">
      {Array.from({ length: count }).map((_, i) => (
        <span
          key={i}
          className={`block h-1 rounded-full transition-all duration-300
            ${i <= active ? 'bg-[#2dd4bf] w-4' : 'bg-white/15 w-2'}`}
        />
      ))}
    </div>
  )
}
