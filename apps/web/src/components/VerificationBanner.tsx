'use client'

import { useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useAuthStore, type BillingStatus } from '@/lib/auth'

/**
 * Persistent banner shown above the chat thread while the current user's
 * email is not verified. Dismissable for the current page visit only —
 * re-appears on reload.
 */
export function VerificationBanner() {
  const user = useAuthStore((s) => s.user)
  const billing = useAuthStore((s) => s.billing)
  const [dismissed, setDismissed] = useState(false)
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  if (!user || user.email_verified || dismissed) return null

  const used = billing?.message_count ?? 0
  const usedDisplay = Math.min(used, 5)

  async function handleResend() {
    setSending(true)
    setStatus(null)
    try {
      await apiRequest('/auth/resend-verification', { method: 'POST' })
      setStatus('Verification email sent — check your inbox.')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to send email'
      if (msg.includes('429')) {
        setStatus('Please wait a moment before requesting another email.')
      } else {
        setStatus('Failed to send verification email. Try again shortly.')
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <div
      className="flex-shrink-0 flex items-center justify-between gap-3 px-4 py-2
        bg-teal-950/40 border-b border-[#2dd4bf]/20"
    >
      <div className="flex flex-col min-w-0">
        <p className="font-mono text-xs text-[#2dd4bf] leading-snug">
          Verify your email to unlock full access
          <span className="text-[#6b7594]"> ({usedDisplay}/5 messages used)</span>
        </p>
        {status && (
          <p className="font-mono text-[10px] text-[#f0ece4]/80 mt-0.5">{status}</p>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <button
          onClick={handleResend}
          disabled={sending}
          className="font-mono text-xs font-bold text-[#2dd4bf] hover:underline
            disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
        >
          {sending ? 'Sending…' : 'Resend email'}
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="w-6 h-6 flex items-center justify-center rounded
            text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
          aria-label="Dismiss"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// Keep TS happy when this module is imported somewhere that also expects
// a default BillingStatus reference even though we don't re-export.
export type { BillingStatus }
