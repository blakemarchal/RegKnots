'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'
import { apiRequest } from '@/lib/api'
import {
  formatExportAsText,
  triggerDownload,
  type ExportAllResponse,
} from '@/lib/export'

const ROLE_OPTIONS = [
  { value: 'captain', label: 'Captain / Master' },
  { value: 'mate', label: 'Chief Mate / Officer' },
  { value: 'engineer', label: 'Engineer' },
  { value: 'chief_engineer', label: 'Chief Engineer' },
  { value: 'other', label: 'Other / Shore-side' },
]

const ROLE_LABELS: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map((r) => [r.value, r.label]),
)

const ROUTE_LABEL: Record<string, string> = {
  inland: 'Inland',
  coastal: 'Coastal',
  international: 'Intl',
}

interface VesselItem {
  id: string
  name: string
  vessel_type: string
  route_types: string[]
  cargo_types: string[]
  gross_tonnage: number | null
}

function AccountContent() {
  const router = useRouter()
  const { user, logout, updateUserFromToken, removeVessel, billing, setBilling } = useAuthStore()

  // ── Profile editing ────────────────────────────────────────────
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [role, setRole] = useState(user?.role ?? 'other')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileMsg, setProfileMsg] = useState<string | null>(null)

  // ── Password ───────────────────────────────────────────────────
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState<{ text: string; ok: boolean } | null>(null)

  // ─�� Subscription ────────��────────────────────────���──────────────
  const [portalLoading, setPortalLoading] = useState(false)
  const [portalError, setPortalError] = useState<string | null>(null)
  const [billingLoading, setBillingLoading] = useState(true)
  const [billingError, setBillingError] = useState(false)

  // ── Vessels ────────────────────────────────────────────────────
  const [vessels, setVessels] = useState<VesselItem[]>([])
  const [vesselsLoading, setVesselsLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // ── Notification preferences ────────────────────────────────────
  const [notifPrefs, setNotifPrefs] = useState<{
    cert_expiry_reminders: boolean
    cert_expiry_days: number[]
    reg_change_digest: boolean
    reg_digest_frequency: string
    reg_alert_sources: string[]
  } | null>(null)
  const [notifLoading, setNotifLoading] = useState(true)
  const [notifSaving, setNotifSaving] = useState(false)
  const [notifMsg, setNotifMsg] = useState<string | null>(null)

  // ── Chat history export ────────────────────────────────────────
  const [exporting, setExporting] = useState<'json' | 'text' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<VesselItem[]>('/vessels')
      .then(setVessels)
      .catch(() => {})
      .finally(() => setVesselsLoading(false))
    setBillingLoading(true)
    setBillingError(false)
    apiRequest<BillingStatus>('/billing/status')
      .then(setBilling)
      .catch(() => setBillingError(true))
      .finally(() => setBillingLoading(false))
    apiRequest<typeof notifPrefs>('/preferences/notifications')
      .then(setNotifPrefs)
      .catch(() => {})
      .finally(() => setNotifLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveNotifPrefs() {
    if (!notifPrefs) return
    setNotifSaving(true)
    setNotifMsg(null)
    try {
      const saved = await apiRequest<typeof notifPrefs>('/preferences/notifications', {
        method: 'PUT',
        body: JSON.stringify(notifPrefs),
      })
      setNotifPrefs(saved)
      setNotifMsg('Saved')
      setTimeout(() => setNotifMsg(null), 2000)
    } catch (e) {
      setNotifMsg(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setNotifSaving(false)
    }
  }

  function toggleExpiryDay(day: number) {
    if (!notifPrefs) return
    const days = notifPrefs.cert_expiry_days.includes(day)
      ? notifPrefs.cert_expiry_days.filter((d) => d !== day)
      : [...notifPrefs.cert_expiry_days, day].sort((a, b) => b - a)
    setNotifPrefs({ ...notifPrefs, cert_expiry_days: days })
  }

  function toggleAlertSource(source: string) {
    if (!notifPrefs) return
    const sources = (notifPrefs.reg_alert_sources || []).includes(source)
      ? notifPrefs.reg_alert_sources.filter((s) => s !== source)
      : [...(notifPrefs.reg_alert_sources || []), source]
    setNotifPrefs({ ...notifPrefs, reg_alert_sources: sources })
  }

  async function saveProfile() {
    setProfileSaving(true)
    setProfileMsg(null)
    try {
      const res = await apiRequest<{ access_token: string }>('/auth/profile', {
        method: 'PUT',
        body: JSON.stringify({ full_name: fullName.trim(), role }),
      })
      updateUserFromToken(res.access_token)
      setProfileMsg('Saved')
      setTimeout(() => setProfileMsg(null), 2000)
    } catch (e) {
      setProfileMsg(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setProfileSaving(false)
    }
  }

  async function changePassword() {
    setPwMsg(null)
    if (newPw !== confirmPw) {
      setPwMsg({ text: 'Passwords do not match', ok: false })
      return
    }
    if (newPw.length < 8) {
      setPwMsg({ text: 'New password must be at least 8 characters', ok: false })
      return
    }
    setPwSaving(true)
    try {
      await apiRequest('/auth/password', {
        method: 'PUT',
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      })
      setPwMsg({ text: 'Password changed', ok: true })
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (e) {
      setPwMsg({ text: e instanceof Error ? e.message : 'Failed to change password', ok: false })
    } finally {
      setPwSaving(false)
    }
  }

  async function deleteVessel(id: string) {
    setDeletingId(id)
    try {
      await apiRequest(`/vessels/${id}`, { method: 'DELETE' })
      setVessels((prev) => prev.filter((v) => v.id !== id))
      removeVessel(id)
    } catch {
      // ignore
    } finally {
      setDeletingId(null)
      setConfirmDeleteId(null)
    }
  }

  async function openBillingPortal() {
    setPortalLoading(true)
    setPortalError(null)
    try {
      const data = await apiRequest<{ portal_url: string }>('/billing/portal', { method: 'POST' })

      const isStandalone = window.matchMedia('(display-mode: standalone)').matches
        || (window.navigator as any).standalone === true

      if (isStandalone) {
        window.open(data.portal_url, '_blank')
        setPortalLoading(false)
        const handleVisibility = () => {
          if (document.visibilityState === 'visible') {
            apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
            document.removeEventListener('visibilitychange', handleVisibility)
          }
        }
        document.addEventListener('visibilitychange', handleVisibility)
        return
      }

      window.location.href = data.portal_url
    } catch {
      setPortalLoading(false)
      setPortalError('Unable to open billing portal. Please try again.')
    }
  }

  async function handleExportAll(format: 'json' | 'text') {
    setExporting(format)
    setExportError(null)
    try {
      const data = await apiRequest<ExportAllResponse>('/conversations/export-all')
      const stamp = new Date().toISOString().slice(0, 10)
      const isText = format === 'text'
      const blob = isText
        ? new Blob([formatExportAsText(data)], { type: 'text/plain;charset=utf-8' })
        : new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const filename = `regknot_export_${stamp}.${isText ? 'txt' : 'json'}`
      triggerDownload(blob, filename)
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Export failed')
    } finally {
      setExporting(null)
    }
  }

  async function handleSignOut() {
    await logout()
    router.replace('/login')
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Account" />

      {/* Content */}
      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-sm mx-auto flex flex-col gap-5">

          {/* ── Profile section ──────────────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Profile</p>

            {/* Email (read-only) */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Email</label>
              <p className="font-mono text-sm text-[#f0ece4]/60">{user?.email ?? '—'}</p>
            </div>

            {/* Full name */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Full Name</label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                  text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
              />
            </div>

            {/* Role */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                {ROLE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={saveProfile}
                disabled={profileSaving}
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                  disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
              >
                {profileSaving ? 'Saving...' : 'Save'}
              </button>
              {profileMsg && (
                <p className="font-mono text-xs text-[#2dd4bf]">{profileMsg}</p>
              )}
            </div>
          </section>

          {/* ── Subscription ───────────────────────────────────��──── */}
          {billingLoading && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <div className="h-5 bg-white/5 rounded animate-pulse mt-3" />
              <div className="h-10 bg-white/5 rounded-lg animate-pulse mt-3" />
            </section>
          )}

          {!billingLoading && billingError && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <p className="font-mono text-sm text-red-400">Unable to load subscription info.</p>
              <button
                onClick={() => {
                  setBillingError(false)
                  setBillingLoading(true)
                  apiRequest<BillingStatus>('/billing/status')
                    .then(setBilling)
                    .catch(() => setBillingError(true))
                    .finally(() => setBillingLoading(false))
                }}
                className="font-mono text-xs text-[#2dd4bf] hover:underline"
              >
                Retry
              </button>
            </section>
          )}

          {!billingLoading && !billingError && billing && billing.tier !== 'free' && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <p className="font-mono text-sm text-[#f0ece4]/80">
                <span className="text-[#2dd4bf] font-bold">Pro</span>
                {' — '}
                {billing.price_amount
                  ? billing.billing_interval === 'year'
                    ? `$${Math.round(billing.price_amount / 100 / 12)}/month (Annual)`
                    : `$${billing.price_amount / 100}/month`
                  : 'Active'}
              </p>

              {billing.cancel_at_period_end && billing.current_period_end && (
                <div className="bg-amber-400/10 border border-amber-400/30 rounded-lg p-3">
                  <p className="font-mono text-xs text-amber-400">
                    Your subscription will end on {new Date(billing.current_period_end).toLocaleDateString()}.
                    You have full access until then.
                  </p>
                </div>
              )}

              {billing.subscription_status === 'past_due' && (
                <div className="bg-red-400/10 border border-red-400/30 rounded-lg p-3">
                  <p className="font-mono text-xs text-red-400">
                    Your last payment failed. Please update your payment method to keep your subscription active.
                  </p>
                </div>
              )}

              {billing.subscription_status === 'paused' && (
                <div className="bg-amber-400/10 border border-amber-400/30 rounded-lg p-3">
                  <p className="font-mono text-xs text-amber-400">
                    Your subscription is paused. Resume it to regain access.
                  </p>
                </div>
              )}

              <button
                onClick={openBillingPortal}
                disabled={portalLoading}
                className="w-full font-mono text-sm font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  disabled:opacity-50 rounded-lg py-2.5 transition-colors duration-150"
              >
                {portalLoading ? 'Loading...' : 'Manage Subscription'}
              </button>
              {portalError && (
                <p className="font-mono text-xs text-red-400 text-center">{portalError}</p>
              )}
              <p className="font-mono text-[10px] text-[#6b7594] text-center">Powered by Stripe</p>
            </section>
          )}

          {!billingLoading && !billingError && billing && billing.tier === 'free' && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <p className="font-mono text-sm text-[#f0ece4]/80">
                {billing.trial_active
                  ? `Free trial — ${billing.messages_remaining ?? 0} messages remaining`
                  : 'No active subscription'}
              </p>
              <a
                href="/pricing"
                className="w-full text-center font-mono text-sm font-bold text-[#0a0e1a]
                  bg-[#2dd4bf] hover:brightness-110 rounded-lg py-2.5
                  transition-[filter] duration-150 block"
              >
                Upgrade to Pro
              </a>
            </section>
          )}

          {/* ── Notification Preferences ─────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Notifications</p>

            {notifLoading && (
              <div className="h-20 bg-white/5 rounded-lg animate-pulse" />
            )}

            {!notifLoading && notifPrefs && (
              <>
                {/* Cert expiry reminders toggle */}
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-0.5">
                    <p className="font-mono text-sm text-[#f0ece4]">Certificate expiry reminders</p>
                    <p className="font-mono text-xs text-[#6b7594]">Get emailed when credentials are expiring</p>
                  </div>
                  <button
                    onClick={() => setNotifPrefs({ ...notifPrefs, cert_expiry_reminders: !notifPrefs.cert_expiry_reminders })}
                    className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${
                      notifPrefs.cert_expiry_reminders ? 'bg-[#2dd4bf]' : 'bg-white/15'
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform duration-200 ${
                      notifPrefs.cert_expiry_reminders ? 'translate-x-5' : ''
                    }`} />
                  </button>
                </div>

                {/* Expiry day selectors */}
                {notifPrefs.cert_expiry_reminders && (
                  <div className="flex items-center gap-2 ml-0.5">
                    <p className="font-mono text-xs text-[#6b7594] shrink-0">Remind at:</p>
                    {[90, 30, 7].map((day) => (
                      <button
                        key={day}
                        onClick={() => toggleExpiryDay(day)}
                        className={`font-mono text-xs px-2.5 py-1 rounded-md border transition-colors duration-150 ${
                          notifPrefs.cert_expiry_days.includes(day)
                            ? 'border-[#2dd4bf]/50 bg-[#2dd4bf]/10 text-[#2dd4bf]'
                            : 'border-white/10 text-[#6b7594] hover:border-white/20'
                        }`}
                      >
                        {day}d
                      </button>
                    ))}
                  </div>
                )}

                <hr className="border-white/8" />

                {/* Reg change digest toggle */}
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-0.5">
                    <p className="font-mono text-sm text-[#f0ece4]">Regulation change digest</p>
                    <p className="font-mono text-xs text-[#6b7594]">Summary of updated regulations</p>
                  </div>
                  <button
                    onClick={() => setNotifPrefs({ ...notifPrefs, reg_change_digest: !notifPrefs.reg_change_digest })}
                    className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${
                      notifPrefs.reg_change_digest ? 'bg-[#2dd4bf]' : 'bg-white/15'
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform duration-200 ${
                      notifPrefs.reg_change_digest ? 'translate-x-5' : ''
                    }`} />
                  </button>
                </div>

                {/* Digest frequency */}
                {notifPrefs.reg_change_digest && (
                  <div className="flex items-center gap-2 ml-0.5">
                    <p className="font-mono text-xs text-[#6b7594] shrink-0">Frequency:</p>
                    {(['weekly', 'biweekly'] as const).map((freq) => (
                      <button
                        key={freq}
                        onClick={() => setNotifPrefs({ ...notifPrefs, reg_digest_frequency: freq })}
                        className={`font-mono text-xs px-2.5 py-1 rounded-md border transition-colors duration-150 ${
                          notifPrefs.reg_digest_frequency === freq
                            ? 'border-[#2dd4bf]/50 bg-[#2dd4bf]/10 text-[#2dd4bf]'
                            : 'border-white/10 text-[#6b7594] hover:border-white/20'
                        }`}
                      >
                        {freq === 'weekly' ? 'Weekly' : 'Biweekly'}
                      </button>
                    ))}
                  </div>
                )}

                <hr className="border-white/8" />

                {/* Per-source immediate alerts */}
                <div className="flex flex-col gap-2">
                  <p className="font-mono text-sm text-[#f0ece4]">Immediate regulation alerts</p>
                  <p className="font-mono text-xs text-[#6b7594]">Get emailed as soon as a source is updated</p>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {[
                      { key: 'cfr_33', label: 'CFR 33' },
                      { key: 'cfr_46', label: 'CFR 46' },
                      { key: 'cfr_49', label: 'CFR 49' },
                      { key: 'nvic', label: 'NVIC' },
                      { key: 'colregs', label: 'COLREGs' },
                      { key: 'solas', label: 'SOLAS' },
                      { key: 'stcw', label: 'STCW' },
                      { key: 'ism', label: 'ISM' },
                    ].map((s) => (
                      <button
                        key={s.key}
                        onClick={() => toggleAlertSource(s.key)}
                        className={`font-mono text-xs px-2.5 py-1 rounded-md border transition-colors duration-150 ${
                          (notifPrefs.reg_alert_sources || []).includes(s.key)
                            ? 'border-[#2dd4bf]/50 bg-[#2dd4bf]/10 text-[#2dd4bf]'
                            : 'border-white/10 text-[#6b7594] hover:border-white/20'
                        }`}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={saveNotifPrefs}
                    disabled={notifSaving}
                    className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                      disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
                  >
                    {notifSaving ? 'Saving...' : 'Save'}
                  </button>
                  {notifMsg && (
                    <p className="font-mono text-xs text-[#2dd4bf]">{notifMsg}</p>
                  )}
                </div>
              </>
            )}
          </section>

          {/* ── Change password ──────────────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Change Password</p>

            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Current Password</label>
              <input
                type="password"
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                  text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">New Password</label>
              <input
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                  text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Confirm New Password</label>
              <input
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                  text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors"
              />
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={changePassword}
                disabled={pwSaving || !currentPw || !newPw}
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                  disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
              >
                {pwSaving ? 'Changing...' : 'Change Password'}
              </button>
              {pwMsg && (
                <p className={`font-mono text-xs ${pwMsg.ok ? 'text-[#2dd4bf]' : 'text-red-400'}`}>
                  {pwMsg.text}
                </p>
              )}
            </div>
          </section>

          {/* ── My Vessels ───────────────────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">My Vessels</p>
              <button
                onClick={() => router.push('/onboarding?add=true')}
                className="font-mono text-xs text-[#2dd4bf] border border-[#2dd4bf]/40
                  hover:bg-[#2dd4bf]/10 rounded-lg px-3 py-1.5 transition-colors duration-150"
              >
                + Add Vessel
              </button>
            </div>

            {vesselsLoading && (
              <div className="flex flex-col gap-2">
                {[1, 2].map((i) => (
                  <div key={i} className="h-12 bg-white/5 rounded-lg animate-pulse" />
                ))}
              </div>
            )}

            {!vesselsLoading && vessels.length === 0 && (
              <p className="font-mono text-sm text-[#6b7594]">No vessels yet.</p>
            )}

            {!vesselsLoading && vessels.map((v) => (
              <div key={v.id} className="flex items-center gap-3 bg-[#0d1225] border border-white/8 rounded-lg p-3">
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-sm text-[#f0ece4] truncate">{v.name}</p>
                  <p className="font-mono text-xs text-[#6b7594] mt-0.5">
                    {v.vessel_type}
                    {v.route_types.length > 0 && (
                      <> · {v.route_types.length === 1
                        ? (ROUTE_LABEL[v.route_types[0]] ?? v.route_types[0])
                        : 'Multiple routes'}</>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => router.push(`/account/vessel/${v.id}`)}
                    className="font-mono text-xs text-[#2dd4bf] hover:underline"
                  >
                    Edit
                  </button>
                  {confirmDeleteId === v.id ? (
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => deleteVessel(v.id)}
                        disabled={deletingId === v.id}
                        className="font-mono text-xs text-red-400 hover:underline disabled:opacity-50"
                      >
                        {deletingId === v.id ? '...' : 'Confirm'}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="font-mono text-xs text-[#6b7594] hover:underline"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDeleteId(v.id)}
                      className="font-mono text-xs text-red-400/70 hover:text-red-400"
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </section>

          {/* ── My Credentials shortcut ────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">My Credentials</p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Track your MMC, STCW endorsements, medical certificate, TWIC, and other credentials with expiry reminders.
            </p>
            <a
              href="/credentials"
              className="w-full text-center font-mono text-sm font-bold text-[#2dd4bf]
                border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                rounded-lg py-2.5 transition-colors duration-150 block"
            >
              Manage Credentials
            </a>
          </section>

          {/* ── Chat History export ──────────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Chat History</p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Download your conversations with all cited regulations.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleExportAll('json')}
                disabled={exporting !== null}
                className="flex-1 font-mono text-xs font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  disabled:opacity-50 rounded-lg py-2.5 transition-colors duration-150"
              >
                {exporting === 'json' ? 'Exporting...' : 'Export All Chats'}
              </button>
              <button
                onClick={() => handleExportAll('text')}
                disabled={exporting !== null}
                className="flex-1 font-mono text-xs font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  disabled:opacity-50 rounded-lg py-2.5 transition-colors duration-150"
              >
                {exporting === 'text' ? 'Exporting...' : 'Export as Text'}
              </button>
            </div>
            {exportError && (
              <p className="font-mono text-xs text-red-400">{exportError}</p>
            )}
          </section>

          {/* ── Sign Out ─────────────────────────────────────────── */}
          <button
            onClick={handleSignOut}
            className="w-full font-mono text-sm text-red-400/70 hover:text-red-400
              border border-red-400/20 hover:border-red-400/40
              rounded-xl py-3 transition-colors duration-150"
          >
            Sign Out
          </button>

        </div>
      </main>
    </div>
  )
}

export default function AccountPage() {
  return (
    <AuthGuard>
      <AccountContent />
    </AuthGuard>
  )
}
