'use client'

import { useRef, useEffect, type KeyboardEvent, type ChangeEvent } from 'react'
import { useVoiceInput } from '@/lib/useVoiceInput'

// Sprint D6.34 — per-message verbosity override.
// undefined = use the user's saved default (users.verbosity_preference).
// "brief" / "standard" / "detailed" override for THIS turn only.
export type VerbosityOverride = 'brief' | 'standard' | 'detailed' | undefined

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  loading: boolean
  /** Optional verbosity override surfaced as 3 chips above the textarea.
   *  When undefined, no chip is selected and the user's saved preference
   *  governs. Selecting a chip applies for the next message only. */
  verbosity?: VerbosityOverride
  onVerbosityChange?: (v: VerbosityOverride) => void
}

export function InputBar({
  value, onChange, onSend, loading,
  verbosity, onVerbosityChange,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

  const { listening, supported, toggle } = useVoiceInput({
    onTranscript: (text) => {
      onChange(value ? `${value} ${text}` : text)
    },
  })

  // Auto-resize textarea
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!loading && value.trim()) onSend()
    }
  }

  const canSend = !loading && value.trim().length > 0

  // Sprint D6.34 — chip toggle. Clicking the active chip clears it
  // (back to user default); clicking another chip switches the override.
  function pickChip(next: VerbosityOverride) {
    if (!onVerbosityChange) return
    onVerbosityChange(verbosity === next ? undefined : next)
  }

  return (
    <div className="px-3 pb-3 pt-1">
      {onVerbosityChange && (
        <div className="flex items-center gap-1.5 mb-1.5 px-1">
          <VerbosityChip
            label="Brief"
            active={verbosity === 'brief'}
            onClick={() => pickChip('brief')}
          />
          <VerbosityChip
            label="Standard"
            active={verbosity === 'standard'}
            onClick={() => pickChip('standard')}
          />
          <VerbosityChip
            label="Deep dive"
            active={verbosity === 'detailed'}
            onClick={() => pickChip('detailed')}
          />
          {verbosity && (
            <button
              onClick={() => onVerbosityChange(undefined)}
              className="font-mono text-[10px] text-[#6b7594] hover:text-[#f0ece4] ml-1 transition-colors"
              aria-label="Clear verbosity override"
            >
              clear
            </button>
          )}
        </div>
      )}
      <div className="flex items-end gap-2 px-3 py-2 rounded-2xl
        bg-[#0d1225] border border-white/10
        focus-within:border-teal/40 transition-colors duration-150">

        {/* Voice input button */}
        {supported && (
          <button
            onClick={toggle}
            disabled={loading}
            aria-label={listening ? 'Stop recording' : 'Start voice input'}
            className={`flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
              transition-all duration-150
              ${listening
                ? 'bg-red-500/20 text-red-400 animate-pulse'
                : 'text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5'
              }
              disabled:opacity-30 disabled:cursor-not-allowed`}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="1" width="6" height="14" rx="3" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>
        )}

        <textarea
          ref={ref}
          value={value}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
          onKeyDown={onKey}
          disabled={loading}
          rows={1}
          placeholder={listening ? 'Listening...' : 'Ask a regulation question\u2026'}
          className="flex-1 bg-transparent text-sm text-[#f0ece4] placeholder:text-[#6b7594]/60
            resize-none outline-none leading-relaxed py-1
            disabled:opacity-50"
          style={{ minHeight: '28px' }}
        />

        {/* Send button */}
        <button
          onClick={onSend}
          disabled={!canSend}
          aria-label="Send message"
          className="flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
            bg-teal text-[#0a0e1a] font-bold
            disabled:opacity-30 disabled:cursor-not-allowed
            hover:enabled:bg-teal/90 active:enabled:scale-95
            transition-all duration-150"
        >
          {loading ? (
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          ) : (
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          )}
        </button>
      </div>

      <p className="text-center text-[10px] text-[#6b7594]/50 mt-1.5 leading-none">
        Navigation aid only — not legal advice
      </p>
    </div>
  )
}

// Sprint D6.34 — small toggle chip for per-message verbosity override.
function VerbosityChip({
  label, active, onClick,
}: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`font-mono text-[10px] px-2 py-0.5 rounded-full border transition-colors duration-150
        ${active
          ? 'border-teal/60 bg-teal/15 text-teal'
          : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/25'
        }`}
    >
      {label}
    </button>
  )
}
