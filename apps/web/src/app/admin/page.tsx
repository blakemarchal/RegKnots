'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { useAuthStore } from '@/lib/auth'
import { apiRequest } from '@/lib/api'

// ── Types ───────────────────────────────────────────────────────────────────────

interface AdminStats {
  total_users: number
  active_users_24h: number
  active_users_7d: number
  total_conversations: number
  total_messages: number
  messages_today: number
  messages_7d: number
  pro_subscribers: number
  trial_active: number
  trial_expired: number
  message_limit_reached: number
  total_chunks: number
  chunks_by_source: Record<string, number>
  citation_errors_7d: number
}

interface AdminUser {
  id: string
  email: string
  full_name: string | null
  role: string
  subscription_tier: string
  subscription_status: string
  message_count: number
  trial_ends_at: string | null
  created_at: string
  is_admin: boolean
}

// Read-only admin emails — mirrors backend READONLY_ADMIN_EMAILS
const READONLY_ADMIN_EMAILS = new Set(['kdmarchal@gmail.com'])

// ── Stat card ───────────────────────────────────────────────────────────────────

function StatCard({ label, value, wide }: { label: string; value: string | number; wide?: boolean }) {
  return (
    <div className={`bg-[#111827] rounded-xl border border-white/8 px-4 py-3 ${wide ? 'col-span-full' : ''}`}>
      <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">{label}</p>
      <p className="font-mono text-2xl font-bold text-[#2dd4bf] mt-1">{typeof value === 'number' ? value.toLocaleString() : value}</p>
    </div>
  )
}

// ── Date formatting ─────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
}

// ── Admin content ───────────────────────────────────────────────────────────────

function AdminContent() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.is_admin ?? false
  const isReadOnly = READONLY_ADMIN_EMAILS.has(user?.email ?? '')
  const hydrated = useAuthStore((s) => s.hydrated)

  const [stats, setStats] = useState<AdminStats | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usersOffset, setUsersOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(true)
  const [resetting, setResetting] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [emailSending, setEmailSending] = useState<string | null>(null)
  const [emailToast, setEmailToast] = useState<{ msg: string; ok: boolean } | null>(null)

  const fetchStats = useCallback(() => {
    apiRequest<AdminStats>('/admin/stats').then(setStats).catch(() => {})
  }, [])

  const fetchUsers = useCallback((offset: number, append: boolean) => {
    apiRequest<AdminUser[]>(`/admin/users?limit=50&offset=${offset}`)
      .then((data) => {
        setUsers((prev) => append ? [...prev, ...data] : data)
        setHasMore(data.length === 50)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (hydrated && !isAdmin) {
      router.replace('/')
      return
    }
    if (!hydrated) return

    fetchStats()
    fetchUsers(0, false)
    setLoading(false)

    const interval = setInterval(fetchStats, 60_000)
    return () => clearInterval(interval)
  }, [hydrated, isAdmin, router, fetchStats, fetchUsers])

  function loadMore() {
    const next = usersOffset + 50
    setUsersOffset(next)
    fetchUsers(next, true)
  }

  async function resetUser(userId: string, email: string) {
    if (!confirm(`Reset pilot account for ${email}? This deletes all their conversations and restarts their trial.`)) return
    setResetting(userId)
    try {
      await apiRequest(`/admin/reset-user/${userId}`, { method: 'POST' })
      fetchUsers(0, false)
      setUsersOffset(0)
      fetchStats()
    } catch { /* ignore */ }
    setResetting(null)
  }

  async function resetAllPilots() {
    if (!confirm('Reset ALL non-admin pilot accounts? This deletes all their conversations and restarts their trials.')) return
    setResetting('all')
    try {
      const res = await apiRequest<{ reset_count: number }>('/admin/reset-all-pilots', { method: 'POST' })
      alert(`Reset ${res.reset_count} pilot accounts.`)
      fetchUsers(0, false)
      setUsersOffset(0)
      fetchStats()
    } catch { /* ignore */ }
    setResetting(null)
  }

  async function adminAction(userId: string, action: string, label: string) {
    if (!confirm(`${label} for this user?`)) return
    setActionLoading(`${userId}-${action}`)
    try {
      await apiRequest(`/admin/${action}/${userId}`, { method: 'POST' })
      fetchUsers(0, false)
      setUsersOffset(0)
      fetchStats()
    } catch { /* ignore */ }
    setActionLoading(null)
  }

  async function sendTestEmail(type: string) {
    setEmailSending(type)
    setEmailToast(null)
    try {
      const res = await apiRequest<{ success: boolean; type: string; recipient: string }>(
        '/admin/test-email',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type }) },
      )
      setEmailToast({ msg: `Sent ${res.type} email to ${res.recipient}`, ok: true })
    } catch {
      setEmailToast({ msg: `Failed to send ${type} email`, ok: false })
    }
    setEmailSending(null)
    setTimeout(() => setEmailToast(null), 4000)
  }

  if (!hydrated || !isAdmin) return null

  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <button onClick={() => router.back()}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors"
          aria-label="Back">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
          Admin Dashboard
        </h1>
        {isReadOnly && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded-full
            bg-amber-500/20 text-amber-400 border border-amber-500/30">
            Read Only
          </span>
        )}
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 py-6">

          {/* ── Stats grid ───────────────────────────────────────────── */}
          {loading && !stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3 h-[72px] animate-pulse" />
              ))}
            </div>
          )}

          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              {/* Row 1 */}
              <StatCard label="Total Users" value={stats.total_users} />
              <StatCard label="Active (24h)" value={stats.active_users_24h} />
              <StatCard label="Active (7d)" value={stats.active_users_7d} />
              <StatCard label="Pro Subscribers" value={stats.pro_subscribers} />
              {/* Row 2 */}
              <StatCard label="Trial Active" value={stats.trial_active} />
              <StatCard label="Trial Expired" value={stats.trial_expired} />
              <StatCard label="Limit Reached" value={stats.message_limit_reached} />
              <StatCard label="Citation Errors (7d)" value={stats.citation_errors_7d} />
              {/* Row 3 */}
              <StatCard label="Total Conversations" value={stats.total_conversations} />
              <StatCard label="Total Messages" value={stats.total_messages} />
              <StatCard label="Messages Today" value={stats.messages_today} />
              <StatCard label="Messages (7d)" value={stats.messages_7d} />
              {/* Row 4 — wide card */}
              <div className="col-span-full bg-[#111827] rounded-xl border border-white/8 px-4 py-3">
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  Regulation Chunks
                </p>
                <p className="font-mono text-2xl font-bold text-[#2dd4bf] mt-1">
                  {stats.total_chunks.toLocaleString()}
                </p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                  {Object.entries(stats.chunks_by_source).map(([src, cnt]) => (
                    <span key={src} className="font-mono text-xs text-[#f0ece4]/60">
                      <span className="text-[#2dd4bf]/70">{src}</span>: {cnt.toLocaleString()}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Email Testing ─────────────────────────────────────────── */}
          {!isReadOnly && (
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">Email Testing</h2>
            <p className="font-mono text-xs text-[#6b7594] mb-3">Send test emails to your admin address.</p>
            <div className="flex flex-wrap gap-2">
              {([
                ['welcome', 'Welcome Email'],
                ['password_reset', 'Password Reset'],
                ['trial_expiry', 'Trial Expiry'],
                ['pilot_ended', 'Pilot Ended'],
                ['waitlist_confirmed', 'Waitlist Confirmed'],
              ] as const).map(([type, label]) => (
                <button
                  key={type}
                  onClick={() => sendTestEmail(type)}
                  disabled={emailSending === type}
                  className="font-mono text-xs font-bold px-4 py-2 rounded-lg border border-[#2dd4bf]/30
                    text-[#2dd4bf] hover:bg-[#2dd4bf]/10 disabled:opacity-50
                    disabled:cursor-not-allowed transition-colors"
                >
                  {emailSending === type ? 'Sending...' : label}
                </button>
              ))}
            </div>
            {emailToast && (
              <div className={`mt-3 font-mono text-xs px-3 py-2 rounded-lg border ${
                emailToast.ok
                  ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/30 text-[#2dd4bf]'
                  : 'bg-red-500/10 border-red-500/30 text-red-400'
              }`}>
                {emailToast.msg}
              </div>
            )}
          </div>
          )}

          {/* ── Users table ──────────────────────────────────────────── */}
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">Users</h2>
            {!isReadOnly && (
            <button
              onClick={resetAllPilots}
              disabled={resetting === 'all'}
              className="font-mono text-xs px-3 py-1.5 rounded-lg border border-red-500/40
                text-red-400 hover:bg-red-500/10 disabled:opacity-50 transition-colors"
            >
              {resetting === 'all' ? 'Resetting...' : 'Reset All Pilots'}
            </button>
            )}
          </div>

          <div className="rounded-xl border border-white/8">
            <table className="w-full table-fixed text-left font-mono text-xs">
              <thead>
                <tr className="bg-[#2dd4bf]/10 text-[#2dd4bf]">
                  <th className="px-3 py-2.5 font-medium w-[22%]">Email</th>
                  <th className="px-3 py-2.5 font-medium w-[14%]">Name</th>
                  <th className="px-3 py-2.5 font-medium w-[8%]">Role</th>
                  <th className="px-3 py-2.5 font-medium w-[6%]">Tier</th>
                  <th className="px-3 py-2.5 font-medium w-[8%]">Status</th>
                  <th className="px-3 py-2.5 font-medium text-right w-[6%]">Msgs</th>
                  <th className="px-3 py-2.5 font-medium w-[10%]">Trial Ends</th>
                  <th className="px-3 py-2.5 font-medium w-[10%]">Joined</th>
                  {!isReadOnly && <th className="px-3 py-2.5 font-medium w-[16%]"></th>}
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={u.id}
                    className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                    <td className="px-3 py-2 text-[#f0ece4]/90 truncate overflow-hidden" title={u.email}>
                      {u.email}
                      {u.is_admin && <span className="ml-1.5 text-[#2dd4bf] text-[10px]">ADMIN</span>}
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/60 truncate overflow-hidden" title={u.full_name ?? ''}>{u.full_name ?? '-'}</td>
                    <td className="px-3 py-2 text-[#f0ece4]/60">{u.role}</td>
                    <td className="px-3 py-2">
                      <span className={u.subscription_tier === 'pro' ? 'text-[#2dd4bf]' : 'text-[#6b7594]'}>
                        {u.subscription_tier}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/60">{u.subscription_status}</td>
                    <td className="px-3 py-2 text-right text-[#f0ece4]/80">{u.message_count}</td>
                    <td className="px-3 py-2 text-[#6b7594]">{fmtDate(u.trial_ends_at)}</td>
                    <td className="px-3 py-2 text-[#6b7594]">{fmtDate(u.created_at)}</td>
                    {!isReadOnly && (
                    <td className="px-3 py-2">
                      {!u.is_admin && (
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => adminAction(u.id, 'extend-trial', 'Extend trial 14 days')}
                            disabled={actionLoading === `${u.id}-extend-trial`}
                            className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-[#2dd4bf]/30
                              text-[#2dd4bf]/70 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                              disabled:opacity-50 transition-colors whitespace-nowrap"
                          >
                            +Trial
                          </button>
                          {u.subscription_tier !== 'pro' ? (
                            <button
                              onClick={() => adminAction(u.id, 'grant-pro', 'Grant Pro')}
                              disabled={actionLoading === `${u.id}-grant-pro`}
                              className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-[#2dd4bf]/30
                                text-[#2dd4bf]/70 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                                disabled:opacity-50 transition-colors whitespace-nowrap"
                            >
                              +Pro
                            </button>
                          ) : (
                            <button
                              onClick={() => adminAction(u.id, 'revoke-pro', 'Revoke Pro')}
                              disabled={actionLoading === `${u.id}-revoke-pro`}
                              className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-amber-500/30
                                text-amber-400/70 hover:text-amber-400 hover:bg-amber-500/10
                                disabled:opacity-50 transition-colors whitespace-nowrap"
                            >
                              -Pro
                            </button>
                          )}
                          <button
                            onClick={() => resetUser(u.id, u.email)}
                            disabled={resetting === u.id}
                            className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-red-500/30
                              text-red-400/70 hover:text-red-400 hover:bg-red-500/10
                              disabled:opacity-50 transition-colors"
                          >
                            {resetting === u.id ? '...' : 'Reset'}
                          </button>
                        </div>
                      )}
                    </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {hasMore && users.length > 0 && (
            <div className="flex justify-center mt-4 mb-8">
              <button onClick={loadMore}
                className="font-mono text-xs text-[#2dd4bf] hover:underline">
                Load more
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  return (
    <AuthGuard>
      <AdminContent />
    </AuthGuard>
  )
}
