'use client'

import { useRef, useEffect, type KeyboardEvent, type ChangeEvent } from 'react'

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  loading: boolean
}

export function InputBar({ value, onChange, onSend, loading }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

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

  return (
    <div className="px-3 pb-3 pt-1">
      <div className="flex items-end gap-2 px-3 py-2 rounded-2xl
        bg-[#0d1225] border border-white/10
        focus-within:border-teal/40 transition-colors duration-150">

        <textarea
          ref={ref}
          value={value}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
          onKeyDown={onKey}
          disabled={loading}
          rows={1}
          placeholder="Ask a regulation question…"
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
