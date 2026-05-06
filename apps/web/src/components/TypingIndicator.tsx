'use client'

import { useEffect, useState } from 'react'

// Sprint D6.74 — Karynn report: chat "keeps stopping mid stream".
//
// Root cause: when streaming text completes but the server is still doing
// post-processing (citation verification, regeneration on hedge, citation-
// oracle intervention, web fallback dispatch), the client's last status
// message can sit static for 5-15s. The streamed text is in the bubble
// above; the static "Verifying citations…" sits below; nothing moves;
// users assume the system hung.
//
// Fix: when a status message stays the same for too long, this indicator
// auto-cycles nautical-themed filler so the user sees continuous motion.
// Whenever a NEW status arrives from the server (different string), we
// reset back to it. Bouncing-dots fallback unchanged for the dot-only
// "thinking" state before the first server status fires.
//
// The nautical filler set is the same vocabulary used in AILoadingState
// (D6.63). Curated for length parity so the line height doesn't reflow.

interface Props {
  /** Optional progress message — when set, replaces the bouncing dots with a
   *  single pulsing teal dot + the status text. Falls back to dots when null. */
  message?: string | null
}

const FILLER_AFTER_MS = 3500   // hold the server status this long, then start cycling
const FILLER_INTERVAL_MS = 2500
const NAUTICAL_FILLER = [
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
  const out = [...arr]
  for (let n = out.length - 1; n > 0; n--) {
    const j = Math.floor(Math.random() * (n + 1))
    ;[out[n], out[j]] = [out[j], out[n]]
  }
  return out
}

export function TypingIndicator({ message = null }: Props = {}) {
  // Filler cycle state: -1 = show the original message, 0..N = filler index.
  const [fillerIdx, setFillerIdx] = useState(-1)
  // Shuffle once per indicator mount so a chatty user doesn't see the same
  // opener line every time.
  const [fillers] = useState<readonly string[]>(() => shuffled(NAUTICAL_FILLER))

  // Reset to the original message whenever a new status arrives.
  useEffect(() => {
    setFillerIdx(-1)
  }, [message])

  // When sitting on the same message for too long, start cycling filler.
  useEffect(() => {
    if (!message) return                    // dots-only state — no cycling
    if (fillerIdx === -1) {
      // Initial wait — hold the server status, then advance into filler.
      const id = setTimeout(() => setFillerIdx(0), FILLER_AFTER_MS)
      return () => clearTimeout(id)
    }
    // Cycle through filler list, modulo so we never go blank.
    const id = setTimeout(
      () => setFillerIdx((i) => (i + 1) % fillers.length),
      FILLER_INTERVAL_MS,
    )
    return () => clearTimeout(id)
  }, [message, fillerIdx, fillers.length])

  const displayed =
    fillerIdx === -1 || !message
      ? message
      : fillers[fillerIdx]

  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]">
      {/* Teal accent bar matching assistant messages */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-1" />
      {displayed ? (
        <div className="flex items-center gap-2 py-1 min-w-[12rem]">
          <span
            className="w-1.5 h-1.5 rounded-full bg-teal animate-[progressPulse_1.5s_ease-in-out_infinite] flex-shrink-0"
            aria-hidden="true"
          />
          <span
            key={displayed}
            className="font-mono text-xs text-[#6b7594] animate-[fadeSlideIn_0.25s_ease-out]"
          >
            {displayed}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0s_infinite]" />
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.2s_infinite]" />
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.4s_infinite]" />
        </div>
      )}
    </div>
  )
}
