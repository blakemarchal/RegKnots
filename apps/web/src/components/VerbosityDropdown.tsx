'use client'

import { useEffect, useRef, useState } from 'react'
import type { VerbosityOverride } from './InputBar'

// Sprint D6.77 — verbosity surfaced as a compact dropdown next to the
// VesselPill and Quick-Log button instead of three chips above the
// textarea. Karynn's morning UX list called out the chip row as
// real-estate waste; this collapses three chips into one pill that
// expands to a small menu only when the user wants to change the
// setting.
//
// Visual parity with the Log pill: same compact height, same border /
// hover treatment, same font sizing. So the row reads as a single
// horizontal control strip rather than mixed-style elements stacked.

const LABELS: Record<VerbosityOverride, string> = {
  brief: 'Brief',
  standard: 'Standard',
  detailed: 'Deep dive',
}

// One-line description per option — shown only inside the open menu so
// new users understand what each option means without committing to a
// full tooltip / help affordance.
const DESCRIPTIONS: Record<VerbosityOverride, string> = {
  brief: 'Short answer. The key citation, no extra context.',
  standard: 'Balanced. Cited answer with the reasoning that matters.',
  detailed: 'Long-form. Multi-section synthesis when complexity warrants.',
}

interface Props {
  value: VerbosityOverride
  onChange: (v: VerbosityOverride) => void
  /** When true, render in a slightly more constrained mode for narrow
   *  parent rows (e.g. when wrapped under the VesselPill on mobile).
   *  Currently only affects label visibility — the trigger still shows
   *  the level icon and the abbreviated current label. */
  compact?: boolean
}

export function VerbosityDropdown({ value, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function pick(v: VerbosityOverride) {
    onChange(v)
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Answer length: ${LABELS[value]} (click to change)`}
        className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs
          border border-white/10 bg-white/5 hover:bg-[#2dd4bf]/10 hover:border-[#2dd4bf]/30
          transition-colors duration-150 whitespace-nowrap"
      >
        <svg
          className="w-3 h-3 text-[#2dd4bf]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          {/* Three horizontal lines — visual cue for "answer length" */}
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="14" y2="12" />
          <line x1="4" y1="18" x2="9" y2="18" />
        </svg>
        <span className="font-mono text-[10px] font-bold text-[#2dd4bf]">
          {LABELS[value]}
        </span>
        <svg
          className={`w-2.5 h-2.5 text-[#2dd4bf] transition-transform duration-150
            ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 bottom-full mb-2 w-56 rounded-xl
            border border-white/10 bg-[#0d1225] shadow-[0_8px_24px_rgba(0,0,0,0.4)]
            overflow-hidden z-20 animate-[fadeSlideIn_0.15s_ease-out]"
        >
          {(Object.keys(LABELS) as VerbosityOverride[]).map((opt) => (
            <button
              key={opt}
              role="menuitemradio"
              aria-checked={value === opt}
              onClick={() => pick(opt)}
              className={`flex w-full items-start gap-2 px-3 py-2.5 text-left
                transition-colors duration-100
                ${value === opt
                  ? 'bg-[#2dd4bf]/10'
                  : 'hover:bg-white/5'
                }`}
            >
              {/* Active radio dot */}
              <span
                className={`mt-1 w-1.5 h-1.5 flex-shrink-0 rounded-full
                  ${value === opt ? 'bg-[#2dd4bf]' : 'bg-white/15'}`}
                aria-hidden="true"
              />
              <span className="flex-1 min-w-0">
                <span className={`font-mono text-xs font-bold block
                  ${value === opt ? 'text-[#2dd4bf]' : 'text-[#f0ece4]'}`}>
                  {LABELS[opt]}
                </span>
                <span className="font-mono text-[10px] text-[#6b7594] block leading-snug mt-0.5">
                  {DESCRIPTIONS[opt]}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
