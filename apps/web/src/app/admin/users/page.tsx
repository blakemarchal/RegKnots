'use client'

// 2026-09-29 — Users, moved out of the single-page admin. Same actions as
// before, plus: linkable filters (?filter=paused), counts on each filter, a
// sort, and signup source on the row. "Reset All Pilots" is gone (it wiped
// every non-admin account, paying customers included); Grant Pro is no
// longer offered on rows that already pay; "Load more" steps by the page size.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate, fmtRelative } from '../_lib/format'
import type { AdminUser } from '../_lib/types'
import { Empty, FilterPills, Page, Pill, type PillTone, Skeleton, TEXT_MUTED, btn } from '../_components/ui'

const PAGE_SIZE = 200

type UserFilter =
  | 'all' | 'pro' | 'cadet' | 'mate' | 'captain' | 'trial' | 'expired'
  | 'paused' | 'canceled' | 'monthly' | 'annual' | 'admin'

// 'pro' keeps its key for old links but means "any paid tier".
const USER_FILTERS: { value: UserFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pro', label: 'Paid' },
  { value: 'cadet', label: 'Cadet' },
  { value: 'mate', label: 'Mate' },
  { value: 'captain', label: 'Captain' },
  { value: 'trial', label: 'Trial' },
  { value: 'expired', label: 'Trial ended' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'annual', label: 'Annual' },
  { value: 'paused', label: 'Paused / past due' },
  { value: 'canceled', label: 'Canceled' },
  { value: 'admin', label: 'Admin' },
]

type SortKey = 'newest' | 'active' | 'questions'
const SORTS: { value: SortKey; label: string }[] = [
  { value: 'newest', label: 'Newest' },
  { value: 'active', label: 'Last active' },
  { value: 'questions', label: 'Most questions' },
]

const PAID_TIER_LABEL: Record<string, string> = {
  cadet: 'Cadet', mate: 'Mate', captain: 'Captain', pro: 'Captain', solo: 'Captain',
}

function classify(u: AdminUser, now: number) {
  const trialTs = u.trial_ends_at ? new Date(u.trial_ends_at).getTime() : null
  const isPaid = u.subscription_status === 'active' && PAID_TIER_LABEL[u.subscription_tier] !== undefined
  const isPaused = u.subscription_status === 'paused' || u.subscription_status === 'past_due'
  const isCanceled = u.subscription_status === 'canceled' || u.subscription_status === 'canceling'
  const isTrial = !isPaid && !isPaused && !isCanceled && trialTs !== null && trialTs > now
  const isExpired = !isPaid && !isPaused && !isCanceled && !isTrial
  return { isPaid, isPaused, isCanceled, isTrial, isExpired }
}

function matches(u: AdminUser, f: UserFilter, now: number): boolean {
  const c = classify(u, now)
  switch (f) {
    case 'all': return true
    case 'pro': return c.isPaid
    case 'cadet': return u.subscription_tier === 'cadet' && u.subscription_status === 'active'
    case 'mate': return u.subscription_tier === 'mate' && u.subscription_status === 'active'
    case 'captain': return (u.subscription_tier === 'captain' || u.subscription_tier === 'pro') && u.subscription_status === 'active'
    case 'trial': return c.isTrial
    case 'expired': return c.isExpired
    case 'paused': return c.isPaused
    case 'canceled': return c.isCanceled
    case 'monthly': return c.isPaid && u.billing_interval === 'month'
    case 'annual': return c.isPaid && u.billing_interval === 'year'
    case 'admin': return u.is_admin
  }
}

function status(u: AdminUser, now: number): { label: string; tone: PillTone } {
  const c = classify(u, now)
  if (c.isPaid) return { label: PAID_TIER_LABEL[u.subscription_tier], tone: 'teal' }
  // Red is kept for money at risk. An ended trial is the normal resting state
  // for most accounts, so it stays gray.
  if (c.isPaused) return u.subscription_status === 'past_due' ? { label: 'Past due', tone: 'red' } : { label: 'Paused', tone: 'amber' }
  if (c.isCanceled) return { label: 'Canceled', tone: 'gray' }
  if (c.isTrial) return { label: 'Trial', tone: 'teal' }
  return { label: 'Trial ended', tone: 'gray' }
}

export default function AdminUsersPage() {
  const params = useSearchParams()
  const { ei, isOwner, isReadOnly, refresh } = useAdmin()
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<UserFilter>(() => {
    const f = params.get('filter') as UserFilter | null
    return f && USER_FILTERS.some((o) => o.value === f) ? f : 'all'
  })
  const [sort, setSort] = useState<SortKey>('newest')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const fetchUsers = useCallback((off: number, append: boolean) => {
    apiRequest<AdminUser[]>(`/admin/users?limit=${PAGE_SIZE}&offset=${off}&exclude_internal=${ei}`)
      .then((data) => {
        setUsers((prev) => (append && prev ? [...prev, ...data] : data))
        setHasMore(data.length === PAGE_SIZE)
      })
      .catch(() => setUsers((prev) => prev ?? []))
  }, [ei])

  useEffect(() => { setOffset(0); fetchUsers(0, false) }, [fetchUsers])

  function reload() {
    setOffset(0)
    fetchUsers(0, false)
    refresh()
  }

  const now = Date.now()
  const counts = useMemo(() => {
    const out: Partial<Record<UserFilter, number>> = {}
    for (const f of USER_FILTERS) out[f.value] = (users ?? []).filter((u) => matches(u, f.value, now)).length
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [users])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = (users ?? []).filter((u) => {
      if (q && !`${u.email} ${u.full_name ?? ''} ${u.signup_source ?? ''}`.toLowerCase().includes(q)) return false
      return matches(u, filter, now)
    })
    const t = (s: string | null) => (s ? new Date(s).getTime() : 0)
    if (sort === 'active') list.sort((a, b) => t(b.last_active_at) - t(a.last_active_at))
    else if (sort === 'questions') list.sort((a, b) => b.message_count - a.message_count)
    else list.sort((a, b) => t(b.created_at) - t(a.created_at))
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [users, search, filter, sort])

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key)
    try { await fn(); reload() } catch (err) {
      alert(err instanceof Error ? err.message : 'Action failed')
    }
    setBusy(null)
  }

  function adminAction(u: AdminUser, action: string, label: string) {
    if (!confirm(`${label} for ${u.email}?`)) return
    void act(`${u.id}-${action}`, () => apiRequest(`/admin/${action}/${u.id}`, { method: 'POST' }))
  }

  function simulateExpiry(u: AdminUser) {
    if (!confirm(`Simulate trial expiry for ${u.email}? This sets their trial to yesterday.`)) return
    void act(`${u.id}-simulate-expiry`, () => apiRequest(`/admin/simulate-expiry/${u.id}`, { method: 'POST' }))
  }

  function resetUser(u: AdminUser) {
    if (!confirm(`Reset ${u.email}? This deletes all their conversations and restarts their trial.`)) return
    void act(`${u.id}-reset`, () => apiRequest(`/admin/reset-user/${u.id}`, { method: 'POST' }))
  }

  function deleteUser(u: AdminUser) {
    if (!confirm(`Permanently delete ${u.email}? This removes all their conversations, vessels and account data. This cannot be undone.`)) return
    void act(`${u.id}-delete`, async () => {
      await apiRequest(`/admin/users/${u.id}`, { method: 'DELETE' })
      setExpanded(null)
    })
  }

  // Sprint D6.3c — Owner can set/clear referral_source on a user.
  function setReferral(u: AdminUser) {
    const next = window.prompt(
      `Set referral source for ${u.email}.\n\nExamples: womenoffshore, mercyships, mission-to-seafarers\nLeave blank to clear.`,
    )
    if (next === null) return
    void act(`${u.id}-referral`, () => apiRequest(`/admin/users/${u.id}/referral-source`, {
      method: 'POST',
      body: JSON.stringify({ referral_source: next.trim() || null }),
    }))
  }

  async function exportChats(u: AdminUser) {
    setBusy(`${u.id}-export`)
    try {
      const data = await apiRequest<Record<string, unknown>>(`/admin/export-chats/${u.id}`)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `regknot_export_${u.email}_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
    setBusy(null)
  }

  const small = 'font-mono text-[11px] font-bold uppercase tracking-wider px-2.5 py-1.5 rounded border transition-colors disabled:opacity-50'
  const tealBtn = `${small} border-[#2dd4bf]/30 text-[#2dd4bf]/85 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10`
  const amberBtn = `${small} border-amber-500/30 text-amber-400/85 hover:text-amber-400 hover:bg-amber-500/10`
  const redBtn = `${small} border-red-500/40 text-red-400/85 hover:text-red-400 hover:bg-red-500/10`

  return (
    <Page
      title="Users"
      description={users ? `${visible.length === users.length ? users.length : `${visible.length} of ${users.length}`} accounts. Click a row for details and actions.` : 'Loading accounts…'}
    >
      <div className="flex flex-col gap-3 mb-4">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#6b7594] pointer-events-none"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <circle cx="7" cy="7" r="5" /><path d="M11 11l3 3" strokeLinecap="round" />
            </svg>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, email or signup source…"
              aria-label="Search users"
              className="w-full bg-[#111827] border border-white/8 rounded-lg pl-9 pr-3 py-2 font-mono text-sm text-[#f0ece4]
                placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40"
            />
          </div>
          <label className="flex items-center gap-2 font-mono text-xs text-[#8b93ad]">
            Sort
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="bg-[#111827] border border-white/8 rounded-lg px-3 py-2 font-mono text-xs text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/40"
            >
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
        </div>
        <FilterPills options={USER_FILTERS} value={filter} onChange={setFilter} counts={users ? counts : undefined} />
      </div>

      {!users ? (
        <div className="flex flex-col gap-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[64px]" />)}</div>
      ) : visible.length === 0 ? (
        <Empty>No users match.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {visible.map((u) => {
            const open = expanded === u.id
            const st = status(u, now)
            const paid = classify(u, now).isPaid
            const interval = paid ? (u.billing_interval === 'year' ? 'Annual' : u.billing_interval === 'month' ? 'Monthly' : null) : null
            return (
              <li key={u.id} className="bg-[#111827] rounded-xl border border-white/8 overflow-hidden">
                <button
                  onClick={() => setExpanded(open ? null : u.id)}
                  aria-expanded={open}
                  className="w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                        <Pill tone={st.tone}>{st.label}</Pill>
                        {interval && <Pill tone="teal">{interval}</Pill>}
                        {u.is_admin && <Pill tone="purple">Admin</Pill>}
                        {u.cancel_at_period_end && <Pill tone="amber">Cancels</Pill>}
                      </div>
                      <p className="font-mono text-sm text-[#f0ece4]/90 truncate">{u.full_name?.trim() || u.email}</p>
                      <p className={`font-mono text-[11px] ${TEXT_MUTED} truncate`}>
                        {u.full_name?.trim() ? `${u.email} · ` : ''}{u.role?.replace(/_/g, ' ')}{u.signup_source ? ` · ${u.signup_source}` : ''}
                      </p>
                    </div>
                    <div className="flex items-center gap-5 flex-shrink-0 text-right">
                      <div className="hidden sm:block">
                        <p className={`font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>Signed up</p>
                        <p className="font-mono text-xs text-[#f0ece4]/70 whitespace-nowrap">{fmtDate(u.created_at)}</p>
                      </div>
                      <div>
                        <p className={`font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>Last active</p>
                        <p className="font-mono text-xs text-[#f0ece4]/70 whitespace-nowrap" title={u.last_active_at ? new Date(u.last_active_at).toLocaleString() : undefined}>
                          {u.last_active_at ? fmtRelative(u.last_active_at) : 'never'}
                        </p>
                      </div>
                      <div className="min-w-[44px]">
                        <p className={`font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>Msgs</p>
                        <p className="font-mono text-xs text-[#f0ece4]/80">{u.message_count}</p>
                      </div>
                    </div>
                  </div>
                </button>

                {open && (
                  <div className="border-t border-white/8 px-4 py-4 flex flex-col gap-4">
                    <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5 font-mono text-xs">
                      {([
                        ['Email', u.email],
                        ['Role', u.role],
                        ['Registered', fmtDate(u.created_at)],
                        ['Trial ends', fmtDate(u.trial_ends_at)],
                        ['Subscription', `${u.subscription_tier} / ${u.subscription_status}${interval ? ` · ${interval}` : ''}${u.current_period_end ? ` · period ends ${fmtDate(u.current_period_end)}` : ''}`],
                        ['Last active', u.last_active_at ? new Date(u.last_active_at).toLocaleString() : 'never'],
                        ['Messages', String(u.message_count)],
                        ['Vessels', String(u.vessel_count)],
                        ['Signup source', u.signup_source ?? 'not recorded'],
                      ] as const).map(([k, v]) => (
                        <div key={k} className="min-w-0">
                          <dt className={`text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>{k}</dt>
                          <dd className="text-[#f0ece4]/85 break-all">{v}</dd>
                        </div>
                      ))}
                    </dl>

                    <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-white/5">
                      <button onClick={() => exportChats(u)} disabled={busy === `${u.id}-export`} className={tealBtn}>
                        {busy === `${u.id}-export` ? 'Exporting…' : 'Export chats'}
                      </button>
                      {!isReadOnly && !u.is_admin && isOwner && (
                        <>
                          <button onClick={() => adminAction(u, 'extend-trial', 'Extend trial 14 days')} disabled={busy === `${u.id}-extend-trial`} className={tealBtn}>
                            Extend trial
                          </button>
                          {u.subscription_tier === 'pro' ? (
                            <button onClick={() => adminAction(u, 'revoke-pro', 'Revoke Pro')} disabled={busy === `${u.id}-revoke-pro`} className={amberBtn}>
                              Revoke Pro
                            </button>
                          ) : !paid && (
                            <button onClick={() => adminAction(u, 'grant-pro', 'Grant Pro (comp, no Stripe)')} disabled={busy === `${u.id}-grant-pro`} className={tealBtn}
                              title="Sets the legacy Pro tier in our database only; nothing in Stripe changes">
                              Grant Pro (comp)
                            </button>
                          )}
                          <button onClick={() => simulateExpiry(u)} disabled={busy === `${u.id}-simulate-expiry`} className={amberBtn}>
                            Simulate expiry
                          </button>
                          <button onClick={() => setReferral(u)} disabled={busy === `${u.id}-referral`} className={tealBtn}
                            title="Set or clear charity-partner referral_source">
                            Referral
                          </button>
                          <button onClick={() => resetUser(u)} disabled={busy === `${u.id}-reset`} className={amberBtn}>
                            {busy === `${u.id}-reset` ? 'Resetting…' : 'Reset'}
                          </button>
                          <button onClick={() => deleteUser(u)} disabled={busy === `${u.id}-delete`} className={`${redBtn} ml-auto`}>
                            {busy === `${u.id}-delete` ? 'Deleting…' : 'Delete'}
                          </button>
                        </>
                      )}
                      {!isOwner && !u.is_admin && <span className={`font-mono text-[11px] ${TEXT_MUTED}`}>Account actions are owner-only</span>}
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {hasMore && users && users.length > 0 && (
        <div className="flex justify-center mt-4">
          <button
            className={btn.quiet}
            onClick={() => { const next = offset + PAGE_SIZE; setOffset(next); fetchUsers(next, true) }}
          >
            Load more
          </button>
        </div>
      )}
    </Page>
  )
}
