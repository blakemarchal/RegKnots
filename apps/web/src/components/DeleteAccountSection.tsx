'use client'

// 2026-09-29 — self-serve account deletion (POST /auth/delete-account). The
// landing and pricing pages promise "your data, your delete button"; until now
// only the owner could delete an account, from the admin. The API cancels any
// live subscription first and refuses while the user owns a Wheelhouse that
// other people use; see apps/api/app/account_deletion.py.

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAuthStore, type BillingStatus } from '@/lib/auth'

const TIER_LABELS: Record<string, string> = { cadet: 'Cadet', mate: 'Mate', captain: 'Captain', pro: 'Pro', solo: 'Pro' }
const LIVE_STATUSES = new Set(['active', 'canceling', 'past_due', 'trialing'])

export function DeleteAccountSection({ billing, isAdmin }: { billing: BillingStatus | null; isAdmin: boolean }) {
  const router = useRouter()
  const logout = useAuthStore((s) => s.logout)
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const liveSubscription =
    !!billing && billing.tier !== 'free' && !billing.unlimited && LIVE_STATUSES.has(billing.subscription_status)
  const canSubmit = confirm.trim().toUpperCase() === 'DELETE' && password.length > 0 && !busy

  async function handleDelete() {
    setBusy(true)
    setError(null)
    try {
      await apiRequest('/auth/delete-account', {
        method: 'POST',
        body: JSON.stringify({ password, confirm }),
      })
      await logout()
      router.replace('/login?deleted=1')
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete the account. Please try again.")
      setBusy(false)
    }
  }

  function close() {
    setOpen(false)
    setPassword('')
    setConfirm('')
    setError(null)
  }

  return (
    <section className="bg-[#111827] border border-red-400/20 rounded-xl p-5 flex flex-col gap-3">
      <p className="font-mono text-xs text-red-400/80 uppercase tracking-wider">Delete account</p>
      {isAdmin ? (
        <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
          Admin accounts can&rsquo;t be deleted from the app.
        </p>
      ) : !open ? (
        <>
          <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
            Permanently delete your account and everything in it.
          </p>
          <button
            onClick={() => setOpen(true)}
            className="w-full font-mono text-sm text-red-400/80 hover:text-red-400
              border border-red-400/25 hover:border-red-400/50 rounded-lg py-2.5 transition-colors duration-150"
          >
            Delete my account&hellip;
          </button>
        </>
      ) : (
        <>
          <ul className="font-mono text-xs text-[#f0ece4]/75 leading-relaxed flex flex-col gap-1.5 list-disc pl-4">
            <li>Deletes your conversations, vessels, uploaded documents, credentials, sea time, logs and checklists.</li>
            {liveSubscription && (
              <li>
                Your {TIER_LABELS[billing!.tier] ?? billing!.tier} subscription is canceled right away, so you
                won&rsquo;t be charged again.
              </li>
            )}
            <li>A Wheelhouse you own is deleted too. If other people use it, transfer ownership first.</li>
            <li>Payment records are kept for accounting.</li>
            <li className="text-red-300">This can&rsquo;t be undone. Want a copy? Export your chats first (above).</li>
          </ul>
          <div className="flex flex-col gap-1">
            <label htmlFor="delete-password" className="font-mono text-xs text-[#6b7594]">Password</label>
            <input
              id="delete-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-red-400/60 transition-colors"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="delete-confirm" className="font-mono text-xs text-[#6b7594]">
              Type <span className="text-[#f0ece4]">DELETE</span> to confirm
            </label>
            <input
              id="delete-confirm"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-red-400/60 transition-colors"
            />
          </div>
          {error && <p role="alert" className="font-mono text-xs text-red-400 leading-relaxed">{error}</p>}
          <div className="flex gap-2">
            <button
              onClick={close}
              disabled={busy}
              className="flex-1 font-mono text-sm text-[#f0ece4]/75 border border-white/15 hover:bg-white/5
                disabled:opacity-50 rounded-lg py-2.5 transition-colors duration-150"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={!canSubmit}
              className="flex-1 font-mono text-sm font-bold text-white bg-red-600 hover:bg-red-500
                disabled:opacity-40 disabled:cursor-not-allowed rounded-lg py-2.5 transition-colors duration-150"
            >
              {busy ? 'Deleting…' : 'Delete account'}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
