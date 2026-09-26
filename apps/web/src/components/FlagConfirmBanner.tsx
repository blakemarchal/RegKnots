'use client'

import { useState } from 'react'
import { apiRequest, ApiError } from '@/lib/api'
import { FLAG_OPTIONS } from '@/lib/flags'

interface Props {
  vesselId: string
  vesselName: string
  /** One-click choice, from the user's primary jurisdiction. */
  suggested: string | null
  onSaved: (flag: string) => void
  onDismiss: () => void
}

/**
 * 2026-09-26 — "confirm your flag". Shown in chat while the active vessel's
 * flag is Unknown. Retrieval scopes answers to the flag; without it, foreign
 * flag notices compete with the user's own regulations. Users were typing
 * their flag into the chat box, which cannot write the vessel profile.
 */
export function FlagConfirmBanner({ vesselId, vesselName, suggested, onSaved, onDismiss }: Props) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(flag: string) {
    if (!flag || saving) return
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/vessels/${vesselId}`, {
        method: 'PUT',
        body: JSON.stringify({ flag_state: flag }),
      })
      onSaved(flag)
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Only a workspace Owner or Admin can set the flag.'
          : 'Could not save the flag. Try again, or set it in the vessel editor.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      role="region"
      aria-label="Vessel flag"
      className="flex items-start justify-between gap-3 px-4 py-2
        bg-[#2dd4bf]/6 border-t border-[#2dd4bf]/15"
    >
      <div className="flex flex-col gap-1.5 min-w-0">
        <p className="font-mono text-[11px] text-[#6b7594] leading-snug">
          What flag does <span className="text-[#f0ece4]">{vesselName}</span> fly?
          Answers are scoped to your flag&apos;s regulations.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {suggested && (
            <button
              onClick={() => save(suggested)}
              disabled={saving}
              className="px-2.5 py-1 rounded-full font-mono text-[11px] font-bold text-[#2dd4bf]
                border border-[#2dd4bf]/40 bg-[#2dd4bf]/10 hover:bg-[#2dd4bf]/20
                disabled:opacity-50 transition-colors"
            >
              {suggested}
            </button>
          )}
          <select
            value=""
            disabled={saving}
            onChange={(e) => save(e.target.value)}
            aria-label="Choose the vessel's flag"
            className="font-mono text-[11px] border border-white/10 rounded-full px-2.5 py-1
              outline-none focus:border-[#2dd4bf] disabled:opacity-50"
            style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
          >
            <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
              {suggested ? 'Other flag…' : 'Choose flag…'}
            </option>
            {FLAG_OPTIONS.filter((f) => f !== suggested).map((f) => (
              <option key={f} value={f} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                {f}
              </option>
            ))}
          </select>
          {saving && <span className="font-mono text-[10px] text-[#6b7594]">Saving…</span>}
        </div>
        {error && <p className="font-mono text-[10px] text-amber-300">{error}</p>}
      </div>
      <button
        onClick={onDismiss}
        aria-label="Not now"
        title="Not now"
        className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded
          text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  )
}
