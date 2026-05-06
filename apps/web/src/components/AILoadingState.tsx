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
   * Sequence of scripted progress messages, in order. Each shown
   * for SCRIPTED_INTERVAL_MS, except the last (which holds for
   * HOLD_LAST_MS — typically the "Synthesizing…" line where the
   * model is doing the actual work). After the scripted timeline
   * completes, we fire through the cheeky nautical-themed
   * NAUTICAL_MESSAGES below — these communicate "the system is
   * still working AND has personality" without the awkward
   * loop-of-the-same-three-lines pattern.
   */
  messages: string[]
  /** Visual variant: 'inline' for narrow card slots, 'card' for the wider widget. */
  variant?: 'inline' | 'card'
}

// Timing — three regimes.
//   1. Scripted progress messages: 1.8s each, advance linearly.
//   2. The LAST scripted message ("Synthesizing…"): held for 8s
//      because that's the slow Sonnet phase where the model is
//      actually generating. Static long enough to feel substantial,
//      not so long it looks like a hang (the spinner is visible).
//   3. Nautical filler messages: 2.5s each, fire through linearly.
//      If the call somehow runs past all 10, we modulo-loop so the
//      animation never goes blank.
const SCRIPTED_INTERVAL_MS = 1800
const HOLD_LAST_MS = 8000
const NAUTICAL_INTERVAL_MS = 2500

// Cheeky nautical filler. Reads as personality, not goofy. Curated
// for length parity so the line doesn't reflow the layout when it
// changes. Order randomized client-side so a chatty user doesn't see
// the same opener twice in two consecutive calls.
const NAUTICAL_MESSAGES = [
  'All hands on deck — finalizing your answer…',
  'Squaring away the citations…',
  'Heading to the bridge for a second opinion…',
  'Checking the chart for shoal water…',
  'The chief engineer is reviewing this one…',
  'Trimming the sails for accuracy…',
  'Coffee’s brewing while we finalize…',
  'Steady as she goes — almost there…',
  'Polishing the brass before delivery…',
  'Battening down the hatches on the final draft…',
] as const

function shuffled<T>(arr: readonly T[]): T[] {
  // Fisher-Yates. Cheap; we run it once per mount.
  const out = [...arr]
  for (let n = out.length - 1; n > 0; n--) {
    const j = Math.floor(Math.random() * (n + 1))
    ;[out[n], out[j]] = [out[j], out[n]]
  }
  return out
}

export function AILoadingState({ messages, variant = 'inline' }: Props) {
  const [i, setI] = useState(0)
  // Shuffle nautical lines once per mount so consecutive calls don't
  // surface the same opener.
  const [nautical] = useState<readonly string[]>(() => shuffled(NAUTICAL_MESSAGES))

  const totalScripted = messages.length
  const lastScriptedIndex = totalScripted - 1
  const inScripted = i < totalScripted
  const onLastScripted = i === lastScriptedIndex

  // Variable-delay timer: each setTimeout schedules the NEXT
  // advance based on which message is currently shown.
  useEffect(() => {
    let delay: number
    if (inScripted && onLastScripted) {
      delay = HOLD_LAST_MS
    } else if (inScripted) {
      delay = SCRIPTED_INTERVAL_MS
    } else {
      delay = NAUTICAL_INTERVAL_MS
    }
    const id = setTimeout(() => setI((prev) => prev + 1), delay)
    return () => clearTimeout(id)
  }, [i, inScripted, onLastScripted])

  const currentMessage =
    inScripted
      ? messages[i]
      : nautical[(i - totalScripted) % nautical.length]

  // Progress dots track the scripted timeline only. Once we cross
  // into nautical filler we drop them — there's no meaningful
  // progress to indicate at that point.
  const showDots = inScripted && totalScripted > 1
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
