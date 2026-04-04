'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'
import { apiRequest } from '@/lib/api'

const ROLE_OPTIONS = [
  { value: 'captain', label: 'Captain / Master' },
  { value: 'mate', label: 'Chief Mate / Officer' },
  { value: 'engineer', label: 'Engineer' },
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

  // ── Subscription ────────────────────────────────────────────────
  const [portalLoading, setPortalLoading] = useState(false)

  // ── Vessels ────────────────────────────────────────────────────
  const [vessels, setVessels] = useState<VesselItem[]>([])
  const [vesselsLoading, setVesselsLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  useEffect(() => {
    apiRequest<VesselItem[]>('/vessels')
      .then(setVessels)
      .catch(() => {})
      .finally(() => setVesselsLoading(false))
    if (!billing) {
      apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
    try {
      const data = await apiRequest<{ portal_url: string }>('/billing/portal', { method: 'POST' })
      window.location.href = data.portal_url
    } catch {
      setPortalLoading(false)
    }
  }

  async function handleSignOut() {
    await logout()
    router.replace('/login')
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150"
          aria-label="Back"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
          Account
        </h1>
      </header>

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

          {/* ── Subscription ──────────────────────────────────────── */}
          {billing && billing.tier === 'pro' && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">Subscription</p>
              <p className="font-mono text-sm text-[#f0ece4]/80">
                <span className="text-[#2dd4bf] font-bold">Pro</span> — $49/month
              </p>
              <button
                onClick={openBillingPortal}
                disabled={portalLoading}
                className="w-full font-mono text-sm font-bold text-[#2dd4bf]
                  border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
                  disabled:opacity-50 rounded-lg py-2.5 transition-colors duration-150"
              >
                {portalLoading ? 'Loading...' : 'Manage Subscription'}
              </button>
              <p className="font-mono text-[10px] text-[#6b7594] text-center">Powered by Stripe</p>
            </section>
          )}

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
            <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">My Vessels</p>

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
