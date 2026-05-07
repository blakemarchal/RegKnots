'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'
import { apiRequest } from '@/lib/api'
import { useViewMode } from '@/lib/useViewMode'
import {
  formatExportAsText,
  triggerDownload,
  type ExportAllResponse,
} from '@/lib/export'
// Sprint D6.81 — unified persona options. The legacy ROLE_OPTIONS list
// (captain/mate/engineer) was removed from this page; the maritime job
// title now lives per-vessel as vessel.crew_role. The persona dropdown
// in the "How we scope answers" section is the single source of truth
// for "who you are" at the user level.
import { PERSONA_OPTIONS } from '@/lib/personaOptions'

// Sprint D6.27 — translate the database `subscription_tier` value into
// the user-facing tier name. Legacy 'pro' subscribers (early users from
// before the Mate/Captain split) get mapped to 'Captain' since that's
// the closest current equivalent. Falls back to a Title-Case of the raw
// tier for any unknown future tier rather than rendering blank.
function tierLabel(tier: string): string {
  const map: Record<string, string> = {
    pro: 'Captain',
    captain: 'Captain',
    mate: 'Mate',
  }
  if (map[tier]) return map[tier]
  return tier.charAt(0).toUpperCase() + tier.slice(1)
}

function AccountContent() {
  const router = useRouter()
  // Sprint D6.5 — vessel list/edit/delete moved to the My Vessels sheet
  // (single source of truth). Account page no longer touches vessels.
  const { user, logout, updateUserFromToken, billing, setBilling } = useAuthStore()
  // D6.55 — view mode shapes the upgrade messaging. Wheelhouse-only
  // members already have access via their captain's workspace; the
  // upgrade pitch should acknowledge that rather than implying they
  // have no access at all.
  const { viewMode } = useViewMode()
  const isWheelhouseOnly = viewMode?.mode === 'wheelhouse_only'
  const hasWorkspaces = (viewMode?.workspace_count ?? 0) > 0

  // ── Profile editing ────────────────────────────────────────────
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [role, setRole] = useState(user?.role ?? 'other')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileMsg, setProfileMsg] = useState<string | null>(null)

  // Sprint D6.31 — persona + jurisdiction_focus. Fetched lazily after
  // mount so existing users (NULL until they fill them) see the empty
  // state and can populate retroactively.
  // Sprint D6.33 — verbosity_preference now lives in the same panel
  // and persists with the same Save button.
  // Sprint D6.37 — theme_preference also lives in the same Save flow
  // but applies to the document-root immediately on save (so the user
  // sees the theme switch without reloading).
  const [persona, setPersona] = useState<string>('')
  const [jurisdictionFocus, setJurisdictionFocus] = useState<string>('')
  const [verbosityPreference, setVerbosityPreference] = useState<string>('')
  const [themePreference, setThemePreference] = useState<string>('')
  // Sprint D6.83 follow-up — Study Tools nav-visibility toggle.
  // Resolved server-side: defaults to true for cadet_student/teacher_instructor
  // personas, false for everyone else, until the user explicitly toggles.
  const [studyToolsEnabled, setStudyToolsEnabled] = useState<boolean>(false)
  const [personaSaving, setPersonaSaving] = useState(false)
  const [personaMsg, setPersonaMsg] = useState<string | null>(null)

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
    // Sprint D6.31/D6.33/D6.37 — pre-fill persona + jurisdiction + verbosity + theme.
    apiRequest<{
      persona: string | null
      jurisdiction_focus: string | null
      verbosity_preference: string | null
      theme_preference: string | null
      study_tools_enabled?: boolean
    }>('/onboarding/persona')
      .then((r) => {
        setPersona(r.persona ?? '')
        setJurisdictionFocus(r.jurisdiction_focus ?? '')
        setVerbosityPreference(r.verbosity_preference ?? '')
        setThemePreference(r.theme_preference ?? '')
        // Backend resolves NULL → persona-default; defensive fallback for
        // older API responses that don't include the field at all.
        setStudyToolsEnabled(r.study_tools_enabled ?? false)
      })
      .catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function savePersona() {
    setPersonaSaving(true)
    setPersonaMsg(null)
    try {
      await apiRequest('/onboarding/persona', {
        method: 'POST',
        body: JSON.stringify({
          persona: persona || null,
          jurisdiction_focus: jurisdictionFocus || null,
          verbosity_preference: verbosityPreference || null,
          theme_preference: themePreference || null,
          // Always send the explicit boolean (not null) so we capture
          // the user's intent even on first save — otherwise a student
          // who flipped off and saved would re-default back to true on
          // the next persona-change because the server-side seed only
          // fires when study_tools_enabled is NULL.
          study_tools_enabled: studyToolsEnabled,
        }),
      })
      // Bug fix: propagate the toggle to the HamburgerMenu without
      // requiring a page refresh. The menu listens for this event and
      // re-renders the nav row in/out of view immediately. Network-free
      // same-tab handoff; cross-tab cases get reconciled on next drawer
      // open via the menu's fetch-on-open path.
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('regknot:study-tools-changed', {
            detail: studyToolsEnabled,
          }),
        )
      }
      // Sprint D6.37 — apply theme immediately so the user sees the
      // change without reloading. localStorage cache + DOM attribute
      // both updated. Empty string = revert to "dark" default.
      if (typeof window !== 'undefined') {
        const themeToApply = themePreference || 'dark'
        localStorage.setItem('regknot_theme', themeToApply)
        const resolved =
          themeToApply === 'auto'
            ? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
            : themeToApply
        document.documentElement.setAttribute('data-theme', resolved)
      }
      setPersonaMsg('Saved')
      setTimeout(() => setPersonaMsg(null), 2000)
    } catch (e) {
      setPersonaMsg(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setPersonaSaving(false)
    }
  }

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

  // Sprint D6.5 — deleteVessel moved to VesselSheet (My Vessels tab).

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
        <div className="max-w-sm md:max-w-2xl mx-auto flex flex-col gap-5">

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

            {/* Sprint D6.81 — the standalone maritime job-title "Role"
                selector is removed here. The single source of truth for
                "who you are" is now the unified persona dropdown in the
                "How we scope answers" section below. Maritime job title
                lives per-vessel via vessel.crew_role (right scope —
                you can be Captain on one ship and Mate on another over
                your career). */}

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

          {/* ── How RegKnot scopes your answers (Sprint D6.31) ────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">How we scope answers</p>
              <p className="font-mono text-[11px] text-[#6b7594] leading-relaxed">
                Optional. Helps RegKnot tailor regulatory answers when you don&apos;t have a specific
                vessel selected.
              </p>
            </div>

            <div className="flex flex-col gap-1">
              {/* Sprint D6.81 — relabeled "What's your role?" → "Who you are"
                  to remove the ambiguity with the per-vessel maritime job
                  title (which used to share the same "Role" label and
                  lived in the Profile section above). Single source of
                  truth for user-level identity now lives here. */}
              <label className="font-mono text-xs text-[#6b7594]">Who you are</label>
              <select
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Not set</option>
                {PERSONA_OPTIONS.map((p) => (
                  <option
                    key={p.value}
                    value={p.value}
                    style={{ backgroundColor: '#111827', color: '#f0ece4' }}
                  >
                    {p.label}
                  </option>
                ))}
              </select>
              {/* Hint under the field for whichever option is selected,
                  mirroring the registration affordance. */}
              {(() => {
                const hint = PERSONA_OPTIONS.find((p) => p.value === persona)?.hint
                return hint ? (
                  <p className="font-mono text-[10px] text-[#6b7594] mt-0.5 leading-snug">
                    {hint}
                  </p>
                ) : null
              })()}
            </div>

            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Primary jurisdiction</label>
              <select
                value={jurisdictionFocus}
                onChange={(e) => setJurisdictionFocus(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Not set</option>
                <option value="us" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>United States</option>
                <option value="uk" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>United Kingdom</option>
                <option value="au" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Australia</option>
                <option value="no" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Norway</option>
                <option value="sg" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Singapore</option>
                <option value="hk" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Hong Kong</option>
                <option value="bs" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Bahamas</option>
                <option value="lr" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Liberia</option>
                <option value="mh" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Marshall Islands</option>
                <option value="international_mixed" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>International / mixed</option>
              </select>
            </div>

            {/* Sprint D6.33 — response style preference */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Response style</label>
              <select
                value={verbosityPreference}
                onChange={(e) => setVerbosityPreference(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Standard (default)</option>
                <option value="brief" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Brief &mdash; 2-3 paragraphs, lead citation</option>
                <option value="standard" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Standard &mdash; current default</option>
                <option value="detailed" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Detailed &mdash; sectioned, applicability tables</option>
              </select>
              <p className="font-mono text-[10px] text-[#6b7594] leading-relaxed mt-1">
                You can also override per-message using the chips below the chat input.
              </p>
            </div>

            {/* Sprint D6.37/D6.40 — theme preference. Empty value = "dark" by
                default; the empty option was removed to avoid showing two
                visually-identical "Dark" entries. */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Theme</label>
              <select
                value={themePreference || 'dark'}
                onChange={(e) => setThemePreference(e.target.value)}
                className="font-mono w-full border border-white/10 rounded-lg px-3 py-2 text-sm
                  outline-none focus:border-[#2dd4bf] transition-colors"
                style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
              >
                <option value="dark" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Dark (default)</option>
                <option value="light" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Light</option>
                <option value="auto" style={{ backgroundColor: '#111827', color: '#f0ece4' }}>Auto &mdash; follow system</option>
              </select>
              <p className="font-mono text-[10px] text-[#6b7594] leading-relaxed mt-1">
                Light mode is best for daylight reading. Saved to your account so it persists across devices.
              </p>
            </div>

            {/* Sprint D6.83 follow-up — Study Tools nav visibility toggle.
                Defaults on for cadet_student / teacher_instructor personas,
                off for everyone else; user can flip either way and the
                explicit choice wins over the persona default. */}
            <div className="flex flex-col gap-1">
              <label className="font-mono text-xs text-[#6b7594]">Study Tools</label>
              <button
                type="button"
                onClick={() => setStudyToolsEnabled((v) => !v)}
                role="switch"
                aria-checked={studyToolsEnabled}
                className={`flex items-center justify-between px-3 py-2 rounded-lg border transition-colors duration-150
                  ${studyToolsEnabled
                    ? 'border-[#2dd4bf]/40 bg-[#2dd4bf]/5'
                    : 'border-white/10 bg-[#0d1225] hover:border-white/20'
                  }`}
              >
                <span className={`font-mono text-sm ${studyToolsEnabled ? 'text-[#2dd4bf]' : 'text-[#f0ece4]/80'}`}>
                  Quizzes &amp; Guides {studyToolsEnabled ? 'enabled' : 'hidden'}
                </span>
                <span
                  aria-hidden="true"
                  className={`relative inline-block w-10 h-5 rounded-full transition-colors duration-150
                    ${studyToolsEnabled ? 'bg-[#2dd4bf]' : 'bg-white/15'}`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-[#0a0e1a] transition-all duration-150
                      ${studyToolsEnabled ? 'left-[1.375rem]' : 'left-0.5'}`}
                  />
                </span>
              </button>
              <p className="font-mono text-[10px] text-[#6b7594] leading-relaxed mt-1">
                Hides &ldquo;Quizzes &amp; Guides&rdquo; from the menu when off. The page is still
                reachable by direct link if you want it later. Defaulted on for students and teachers.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={savePersona}
                disabled={personaSaving}
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                  disabled:opacity-50 rounded-lg px-4 py-2 transition-[filter] duration-150"
              >
                {personaSaving ? 'Saving...' : 'Save'}
              </button>
              {personaMsg && (
                <p className="font-mono text-xs text-[#2dd4bf]">{personaMsg}</p>
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
                {/* Sprint D6.27 — fix three problems with the previous render:
                    (1) tier was hard-coded as "Pro" — legacy label that no
                        longer matches our pricing (Mate / Captain are current).
                    (2) when billing_interval was null but price_amount was set
                        (annual price stored as $348), it fell through to the
                        else branch and printed "$348/month" — terrifying for
                        any user. Now we only attach a /month suffix when we
                        explicitly know it's a monthly plan; otherwise we show
                        "Active" without a fabricated cadence.
                    (3) annual plans now show monthly equivalent + total. */}
                <span className="text-[#2dd4bf] font-bold">{tierLabel(billing.tier)}</span>
                {(() => {
                  const interval = billing.billing_interval
                  const amount = billing.price_amount
                  if (!amount) return ' — Active'
                  const dollars = amount / 100
                  if (interval === 'month') return ` — $${dollars.toFixed(0)}/month`
                  if (interval === 'year') {
                    const perMonth = Math.round(dollars / 12)
                    return ` — $${perMonth}/month (Annual, $${dollars.toFixed(0)}/year)`
                  }
                  // Unknown interval — show total without cadence rather than
                  // implying a per-month price we can't verify.
                  return ' — Active'
                })()}
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

          {!billingLoading && !billingError && billing && billing.tier === 'free' && billing.unlimited && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <p className="font-mono text-sm text-[#f0ece4]/80">
                <span className="text-[#2dd4bf] font-bold">Unlimited</span> — admin account
              </p>
              <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                All message limits and trial restrictions are bypassed for admin/internal accounts.
              </p>
            </section>
          )}

          {!billingLoading && !billingError && billing && billing.tier === 'free' && !billing.unlimited && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              {/* D6.55 — three messaging tracks based on view mode:
                   1. Wheelhouse-only member: acknowledge their workspace
                      seat; soft-pitch a personal account if they want one.
                   2. Free with active trial: show trial countdown.
                   3. Free with no trial: nudge to a paid plan.
                  CTA wording switched off legacy "Pro" since the live
                  tiers are Mate (limited) and Captain (unlimited). */}
              {isWheelhouseOnly ? (
                <>
                  <p className="font-mono text-sm text-[#f0ece4]/80">
                    You&apos;re using RegKnot through a Wheelhouse seat.
                    Your access is covered by the workspace owner.
                  </p>
                  <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                    If you want your own personal RegKnot account
                    (independent of any workspace), pick a plan below.
                  </p>
                  <a
                    href="/pricing"
                    className="w-full text-center font-mono text-sm font-bold text-[#f0ece4]
                      border border-white/10 hover:bg-white/5 rounded-lg py-2.5
                      transition-colors duration-150 block"
                  >
                    Get a personal account
                  </a>
                </>
              ) : (
                <>
                  <p className="font-mono text-sm text-[#f0ece4]/80">
                    {billing.trial_active
                      ? `Free trial — ${billing.messages_remaining ?? 0} messages remaining`
                      : 'No active subscription'}
                  </p>
                  {hasWorkspaces && (
                    <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
                      Note: your workspace seat covers your workspace
                      chat. A personal plan unlocks personal-tier
                      features (your own vessels, dossier, history).
                    </p>
                  )}
                  <a
                    href="/pricing"
                    className="w-full text-center font-mono text-sm font-bold text-[#0a0e1a]
                      bg-[#2dd4bf] hover:brightness-110 rounded-lg py-2.5
                      transition-[filter] duration-150 block"
                  >
                    Pick a plan &mdash; Mate or Captain
                  </a>
                </>
              )}
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
                      { key: 'erg', label: 'ERG' },
                      { key: 'nmc_memo', label: 'NMC' },
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

          {/* ── Re-run setup wizard ───────────────────────────────── */}
          <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Setup</p>
            <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
              Walk through the welcome wizard again to add a vessel, upload a COI,
              or track a new credential.
            </p>
            <button
              onClick={async () => {
                try {
                  await apiRequest('/onboarding/reset', { method: 'POST' })
                } catch {
                  /* harmless if it fails — wizard is still reachable directly */
                }
                router.push('/welcome')
              }}
              className="w-full text-center font-mono text-sm font-bold text-[#2dd4bf]
                border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                rounded-lg py-2.5 transition-colors duration-150"
            >
              Re-run Setup Wizard
            </button>
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
