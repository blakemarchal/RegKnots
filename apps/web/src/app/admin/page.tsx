'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { useAuthStore } from '@/lib/auth'
import { apiRequest } from '@/lib/api'
import { PilotSurveyModal } from '@/components/PilotSurveyModal'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'

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
  subs_monthly: number
  subs_annual: number
  subs_paused: number
}

interface AdminUser {
  id: string
  email: string
  full_name: string | null
  role: string
  subscription_tier: string
  subscription_status: string
  billing_interval: string | null
  cancel_at_period_end: boolean
  current_period_end: string | null
  message_count: number
  vessel_count: number
  trial_ends_at: string | null
  created_at: string
  last_active_at: string | null
  is_admin: boolean
}

interface SentryIssue {
  id: string
  title: string
  level: string
  count: number
  first_seen: string | null
  last_seen: string
  permalink: string
  link: string  // legacy alias, same value as permalink
  project: string
}

interface CitationError {
  id: string
  conversation_id: string
  unverified_citation: string
  model_used: string | null
  message_preview: string
  created_at: string
}

interface SurveyResponse {
  id: string
  email: string
  full_name: string | null
  overall_rating: number
  usefulness: string | null
  favorite_feature: string | null
  missing_feature: string | null
  would_subscribe: boolean | null
  price_feedback: string | null
  vessel_type_used: string | null
  additional_comments: string | null
  created_at: string
}

interface SurveyAggregates {
  total_responses: number
  average_rating: number
  would_subscribe_pct: number
  top_missing_feature: string | null
  responses: SurveyResponse[]
}

interface DayMessageCount {
  day: string
  message_count: number
}

interface TopCitation {
  source: string
  section_number: string
  section_title: string | null
  cite_count: number
}

interface VesselTypeUsage {
  vessel_type: string
  message_count: number
  user_count: number
}

interface ModelUsageItem {
  model: string
  message_count: number
  total_input_tokens: number
  total_output_tokens: number
}

interface SupportTicket {
  id: string
  user_id: string
  user_email: string
  user_name: string | null
  subject: string
  message: string
  status: 'open' | 'replied' | 'closed'
  admin_reply: string | null
  replied_at: string | null
  created_at: string
}

interface FoundingEmailPreview {
  subject: string
  recipients: { email: string; name: string | null }[]
  total_count: number
  sample_html: string
}

interface AdminNotification {
  id: string
  title: string
  body: string
  notification_type: string
  source: string | null
  is_active: boolean
  created_at: string
}

type TicketFilter = 'all' | 'open' | 'replied' | 'closed'

type UserFilter =
  | 'all'
  | 'pro'
  | 'trial'
  | 'expired'
  | 'paused'
  | 'canceled'
  | 'monthly'
  | 'annual'
  | 'admin'

const USER_FILTERS: { value: UserFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pro', label: 'Pro' },
  { value: 'trial', label: 'Trial' },
  { value: 'expired', label: 'Expired' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'annual', label: 'Annual' },
  { value: 'paused', label: 'Paused' },
  { value: 'canceled', label: 'Canceled' },
  { value: 'admin', label: 'Admin' },
]

// Chart color ramp
const CHART_COLORS = ['#2dd4bf', '#1d9e75', '#0f6e56', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

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

function fmtRelative(iso: string | null): string {
  if (!iso) return '-'
  const then = new Date(iso).getTime()
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin} min ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  // Fall back to absolute for older items
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
  const [userSearch, setUserSearch] = useState('')
  const [userFilter, setUserFilter] = useState<UserFilter>('all')
  const [loading, setLoading] = useState(true)
  const [resetting, setResetting] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [expandedUser, setExpandedUser] = useState<string | null>(null)
  const [deletingUser, setDeletingUser] = useState<string | null>(null)
  const [emailSending, setEmailSending] = useState<string | null>(null)
  const [emailToast, setEmailToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const [sentryIssues, setSentryIssues] = useState<SentryIssue[]>([])
  const [sentryLoading, setSentryLoading] = useState(true)
  const [exporting, setExporting] = useState<string | null>(null)
  const [citationErrors, setCitationErrors] = useState<CitationError[]>([])
  const [citationLoading, setCitationLoading] = useState(true)
  const [expandedCitation, setExpandedCitation] = useState<string | null>(null)
  const [surveyData, setSurveyData] = useState<SurveyAggregates | null>(null)
  const [surveyLoading, setSurveyLoading] = useState(true)
  const [surveyPreview, setSurveyPreview] = useState(false)

  // Internal filtering toggle
  const [excludeInternal, setExcludeInternal] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('admin_exclude_internal') !== 'false'
    }
    return true
  })

  // Analytics state
  const [messagesPerDay, setMessagesPerDay] = useState<DayMessageCount[]>([])
  const [topCitations, setTopCitations] = useState<TopCitation[]>([])
  const [vesselUsage, setVesselUsage] = useState<VesselTypeUsage[]>([])
  const [modelUsage, setModelUsage] = useState<ModelUsageItem[]>([])
  const [analyticsLoading, setAnalyticsLoading] = useState(true)

  // Support tickets state
  const [tickets, setTickets] = useState<SupportTicket[]>([])
  const [ticketsLoading, setTicketsLoading] = useState(true)
  const [ticketFilter, setTicketFilter] = useState<TicketFilter>('all')
  const [expandedTicket, setExpandedTicket] = useState<string | null>(null)

  // Founding member email state
  const [foundingPreview, setFoundingPreview] = useState<FoundingEmailPreview | null>(null)
  const [foundingLoading, setFoundingLoading] = useState(true)
  const [foundingAction, setFoundingAction] = useState<'test' | 'send' | null>(null)
  const [foundingResult, setFoundingResult] = useState<{ msg: string; ok: boolean } | null>(null)

  // Notifications state
  const [notifications, setNotifications] = useState<AdminNotification[]>([])
  const [notifTitle, setNotifTitle] = useState('')
  const [notifBody, setNotifBody] = useState('')
  const [notifType, setNotifType] = useState<'regulation_update' | 'system' | 'announcement'>('regulation_update')
  const [notifSource, setNotifSource] = useState('')
  const [notifSending, setNotifSending] = useState(false)
  const [notifToast, setNotifToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({})
  const [ticketActionId, setTicketActionId] = useState<string | null>(null)
  const [ticketToast, setTicketToast] = useState<{ msg: string; ok: boolean } | null>(null)

  const ei = excludeInternal ? 'true' : 'false'

  const filteredUsers = useMemo(() => {
    const q = userSearch.trim().toLowerCase()
    const now = Date.now()
    return users.filter((u) => {
      if (q) {
        const hay = `${u.email} ${u.full_name ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      if (userFilter === 'all') return true
      const trialTs = u.trial_ends_at ? new Date(u.trial_ends_at).getTime() : null
      const isPro = u.subscription_tier === 'pro' && u.subscription_status === 'active'
      const isPaused = u.subscription_status === 'paused'
      const isCanceled = u.subscription_status === 'canceled' || u.subscription_status === 'canceling'
      const isTrial = !isPro && !isPaused && !isCanceled && trialTs !== null && trialTs > now
      const isExpired = !isPro && !isPaused && !isCanceled && (trialTs === null || trialTs <= now)
      switch (userFilter) {
        case 'pro': return isPro
        case 'trial': return isTrial
        case 'expired': return isExpired
        case 'paused': return isPaused
        case 'canceled': return isCanceled
        case 'monthly': return isPro && u.billing_interval === 'month'
        case 'annual': return isPro && u.billing_interval === 'year'
        case 'admin': return u.is_admin
        default: return true
      }
    })
  }, [users, userSearch, userFilter])

  const [statsError, setStatsError] = useState(false)

  const fetchStats = useCallback(() => {
    setStatsError(false)
    apiRequest<AdminStats>(`/admin/stats?exclude_internal=${ei}`)
      .then(setStats)
      .catch((err) => {
        console.error('Failed to fetch admin stats:', err)
        setStatsError(true)
      })
  }, [ei])

  const fetchUsers = useCallback((offset: number, append: boolean) => {
    apiRequest<AdminUser[]>(`/admin/users?limit=50&offset=${offset}&exclude_internal=${ei}`)
      .then((data) => {
        setUsers((prev) => append ? [...prev, ...data] : data)
        setHasMore(data.length === 50)
      })
      .catch(() => {})
  }, [ei])

  const fetchSentry = useCallback(() => {
    apiRequest<SentryIssue[]>('/admin/sentry-issues')
      .then(setSentryIssues)
      .catch(() => {})
      .finally(() => setSentryLoading(false))
  }, [])

  const fetchCitations = useCallback(() => {
    apiRequest<CitationError[]>(`/admin/citation-errors?limit=50&exclude_internal=${ei}`)
      .then(setCitationErrors)
      .catch(() => {})
      .finally(() => setCitationLoading(false))
  }, [ei])

  const fetchSurvey = useCallback(() => {
    apiRequest<SurveyAggregates>('/survey/admin/responses')
      .then(setSurveyData)
      .catch(() => {})
      .finally(() => setSurveyLoading(false))
  }, [])

  const fetchAnalytics = useCallback(() => {
    setAnalyticsLoading(true)
    Promise.all([
      apiRequest<DayMessageCount[]>(`/admin/analytics/messages-per-day?exclude_internal=${ei}`).catch(() => []),
      apiRequest<TopCitation[]>(`/admin/analytics/top-citations?exclude_internal=${ei}`).catch(() => []),
      apiRequest<VesselTypeUsage[]>(`/admin/analytics/usage-by-vessel-type?exclude_internal=${ei}`).catch(() => []),
      apiRequest<ModelUsageItem[]>('/admin/model-usage').catch(() => []),
    ]).then(([mpd, tc, vu, mu]) => {
      setMessagesPerDay(mpd)
      setTopCitations(tc)
      setVesselUsage(vu)
      setModelUsage(mu)
    }).finally(() => setAnalyticsLoading(false))
  }, [ei])

  const fetchTickets = useCallback(() => {
    apiRequest<SupportTicket[]>('/admin/support-tickets')
      .then(setTickets)
      .catch(() => {})
      .finally(() => setTicketsLoading(false))
  }, [])

  const fetchFoundingPreview = useCallback(() => {
    apiRequest<FoundingEmailPreview>('/admin/founding-email/preview')
      .then(setFoundingPreview)
      .catch(() => {})
      .finally(() => setFoundingLoading(false))
  }, [])

  const fetchNotifications = useCallback(() => {
    apiRequest<AdminNotification[]>('/admin/notifications')
      .then(setNotifications)
      .catch(() => {})
  }, [])

  async function createNotification() {
    if (!notifTitle.trim() || !notifBody.trim()) {
      setNotifToast({ msg: 'Title and body are required', ok: false })
      setTimeout(() => setNotifToast(null), 4000)
      return
    }
    setNotifSending(true)
    try {
      await apiRequest('/admin/notifications', {
        method: 'POST',
        body: JSON.stringify({
          title: notifTitle.trim(),
          body: notifBody.trim(),
          notification_type: notifType,
          source: notifSource.trim() || null,
        }),
      })
      setNotifTitle('')
      setNotifBody('')
      setNotifSource('')
      setNotifToast({ msg: 'Notification published', ok: true })
      fetchNotifications()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to publish'
      setNotifToast({ msg, ok: false })
    }
    setNotifSending(false)
    setTimeout(() => setNotifToast(null), 4000)
  }

  async function toggleNotification(id: string) {
    try {
      await apiRequest(`/admin/notifications/${id}`, { method: 'PATCH' })
      fetchNotifications()
    } catch {
      setNotifToast({ msg: 'Failed to toggle', ok: false })
      setTimeout(() => setNotifToast(null), 4000)
    }
  }

  useEffect(() => {
    if (hydrated && !isAdmin) {
      router.replace('/')
      return
    }
    if (!hydrated) return

    setLoading(true)
    fetchStats()
    fetchUsers(0, false)
    fetchSentry()
    fetchCitations()
    fetchSurvey()
    fetchAnalytics()
    fetchTickets()
    fetchFoundingPreview()
    fetchNotifications()

    const interval = setInterval(() => { fetchStats(); fetchSentry(); fetchCitations(); fetchSurvey(); fetchAnalytics(); fetchTickets() }, 60_000)
    return () => clearInterval(interval)
  }, [hydrated, isAdmin, router, fetchStats, fetchUsers, fetchSentry, fetchCitations, fetchSurvey, fetchAnalytics, fetchTickets, fetchFoundingPreview, fetchNotifications])

  function toggleExcludeInternal() {
    const next = !excludeInternal
    setExcludeInternal(next)
    setStats(null)
    localStorage.setItem('admin_exclude_internal', String(next))
  }

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

  async function deleteUser(userId: string, email: string) {
    if (!confirm(
      `Permanently delete ${email}? This removes all their conversations, vessels, and account data. This cannot be undone.`
    )) return
    setDeletingUser(userId)
    try {
      await apiRequest<{ deleted: boolean; email: string }>(
        `/admin/users/${userId}`,
        { method: 'DELETE' },
      )
      setExpandedUser((prev) => (prev === userId ? null : prev))
      fetchUsers(0, false)
      setUsersOffset(0)
      fetchStats()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to delete user'
      alert(msg)
    }
    setDeletingUser(null)
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

  async function simulateExpiry(userId: string, email: string) {
    if (!confirm(`Simulate trial expiry for ${email}? This sets their trial to yesterday.`)) return
    setActionLoading(`${userId}-simulate-expiry`)
    try {
      await apiRequest(`/admin/simulate-expiry/${userId}`, { method: 'POST' })
      fetchUsers(0, false)
      setUsersOffset(0)
      fetchStats()
    } catch { /* ignore */ }
    setActionLoading(null)
  }

  async function exportChats(userId: string, email: string) {
    setExporting(userId)
    try {
      const data = await apiRequest<Record<string, unknown>>(`/admin/export-chats/${userId}`)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `regknots_export_${email}_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
    setExporting(null)
  }

  async function sendTicketReply(ticketId: string) {
    const reply = (replyDrafts[ticketId] ?? '').trim()
    if (!reply) {
      setTicketToast({ msg: 'Reply text is required', ok: false })
      setTimeout(() => setTicketToast(null), 3000)
      return
    }
    setTicketActionId(`${ticketId}-reply`)
    try {
      await apiRequest(`/admin/support-tickets/${ticketId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply }),
      })
      setTickets((prev) => prev.map((t) =>
        t.id === ticketId
          ? { ...t, status: 'replied', admin_reply: reply, replied_at: new Date().toISOString() }
          : t,
      ))
      setReplyDrafts((prev) => {
        const next = { ...prev }
        delete next[ticketId]
        return next
      })
      setTicketToast({ msg: 'Reply sent', ok: true })
    } catch {
      setTicketToast({ msg: 'Failed to send reply', ok: false })
    }
    setTicketActionId(null)
    setTimeout(() => setTicketToast(null), 4000)
  }

  async function sendFoundingTest() {
    setFoundingAction('test')
    setFoundingResult(null)
    try {
      const res = await apiRequest<{ sent_to: string }>(
        '/admin/founding-email/test',
        { method: 'POST' },
      )
      setFoundingResult({ msg: `Test sent to ${res.sent_to}`, ok: true })
    } catch {
      setFoundingResult({ msg: 'Failed to send test email', ok: false })
    }
    setFoundingAction(null)
    setTimeout(() => setFoundingResult(null), 6000)
  }

  async function sendFoundingToAll() {
    if (!foundingPreview || foundingPreview.total_count === 0) return
    if (!confirm(`Send early-user thank-you email to ${foundingPreview.total_count} users?`)) return
    setFoundingAction('send')
    setFoundingResult(null)
    try {
      const res = await apiRequest<{
        sent: number
        failed: number
        failed_emails: string[]
      }>(
        '/admin/founding-email/send',
        { method: 'POST' },
      )
      const failedNote = res.failed > 0
        ? ` · ${res.failed} failed${res.failed_emails.length > 0 ? ` (${res.failed_emails.slice(0, 3).join(', ')}${res.failed_emails.length > 3 ? '…' : ''})` : ''}`
        : ''
      setFoundingResult({
        msg: `Sent to ${res.sent} users${failedNote}`,
        ok: res.failed === 0,
      })
      fetchFoundingPreview()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to send'
      setFoundingResult({ msg, ok: false })
    }
    setFoundingAction(null)
    setTimeout(() => setFoundingResult(null), 10000)
  }

  async function closeTicket(ticketId: string) {
    const ticket = tickets.find((t) => t.id === ticketId)
    const prompt = ticket?.status === 'replied'
      ? 'Close this ticket?'
      : 'Close this ticket without replying?'
    if (!confirm(prompt)) return
    setTicketActionId(`${ticketId}-close`)
    try {
      await apiRequest(`/admin/support-tickets/${ticketId}/close`, { method: 'POST' })
      setTickets((prev) => prev.map((t) =>
        t.id === ticketId ? { ...t, status: 'closed' } : t,
      ))
      setTicketToast({ msg: 'Ticket closed', ok: true })
    } catch {
      setTicketToast({ msg: 'Failed to close ticket', ok: false })
    }
    setTicketActionId(null)
    setTimeout(() => setTicketToast(null), 4000)
  }

  if (!hydrated || !isAdmin) return null

  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <AppHeader title="Admin" trailing={isReadOnly ? (
        <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded-full
          bg-amber-500/20 text-amber-400 border border-amber-500/30">
          Read Only
        </span>
      ) : undefined} />

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 py-6">

          {/* ── Internal filter toggle ────────────────────────────────── */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <button
                onClick={toggleExcludeInternal}
                className={`relative w-10 h-5 rounded-full transition-colors duration-200
                  ${excludeInternal ? 'bg-[#2dd4bf]' : 'bg-[#6b7594]/40'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full
                  transition-transform duration-200 ${excludeInternal ? 'translate-x-5' : 'translate-x-0'}`} />
              </button>
              <span className="font-mono text-xs text-[#f0ece4]/80">Hide internal data</span>
              {excludeInternal && (
                <span className="font-mono text-[9px] text-[#6b7594] bg-[#6b7594]/10
                  border border-[#6b7594]/20 rounded px-1.5 py-0.5">
                  Filtering: Blake, Karynn, test accounts
                </span>
              )}
            </div>
          </div>

          {/* ── Early-user thank-you email (legacy "founding member" flow) ── */}
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">
              Early-User Thank-You Email
            </h2>
            {foundingLoading ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 h-[88px] animate-pulse" />
            ) : !foundingPreview ? (
              <div className="bg-[#111827] rounded-xl border border-red-500/30 px-4 py-3">
                <p className="font-mono text-xs text-red-400">Failed to load preview</p>
              </div>
            ) : foundingPreview.total_count === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-[#2dd4bf]/30 px-4 py-4 flex items-center gap-3">
                <span className="text-[#2dd4bf] text-lg" aria-hidden="true">{'\u2713'}</span>
                <p className="font-mono text-sm text-[#f0ece4]/85">
                  All early-user thank-you emails have been sent.
                </p>
              </div>
            ) : (
              <div className="bg-[#111827] rounded-xl border border-[#2dd4bf]/20 px-5 py-4">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div>
                    <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                      Pending Recipients
                    </p>
                    <p className="font-mono text-3xl font-bold text-[#2dd4bf] mt-1">
                      {foundingPreview.total_count.toLocaleString()}
                    </p>
                    <p className="font-mono text-[11px] text-[#6b7594] mt-1">
                      Subject: <span className="text-[#f0ece4]/80">{foundingPreview.subject}</span>
                    </p>
                  </div>
                  {!isReadOnly && (
                    <div className="flex flex-col sm:flex-row gap-2">
                      <button
                        onClick={sendFoundingTest}
                        disabled={foundingAction !== null}
                        className="font-mono text-xs font-bold uppercase tracking-wider
                          border border-[#2dd4bf]/40 text-[#2dd4bf]
                          hover:bg-[#2dd4bf]/10 rounded-lg px-4 py-2.5
                          transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {foundingAction === 'test' ? 'Sending…' : 'Send Test to Me'}
                      </button>
                      <button
                        onClick={sendFoundingToAll}
                        disabled={foundingAction !== null}
                        className="font-mono text-xs font-bold uppercase tracking-wider
                          bg-[#2dd4bf] text-[#0a0e1a]
                          hover:brightness-110 rounded-lg px-4 py-2.5
                          transition-[filter] duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {foundingAction === 'send'
                          ? 'Sending…'
                          : `Send to All (${foundingPreview.total_count})`}
                      </button>
                    </div>
                  )}
                </div>
                {foundingResult && (
                  <div className={`mt-3 font-mono text-xs px-3 py-2 rounded
                    ${foundingResult.ok
                      ? 'bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/30'
                      : 'bg-red-500/10 text-red-400 border border-red-500/30'}`}>
                    {foundingResult.msg}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Notifications ────────────────────────────────────────── */}
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">
              In-App Notifications
            </h2>
            {!isReadOnly && (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-5 py-4 mb-3">
                <div className="flex flex-col gap-3">
                  <input
                    type="text"
                    value={notifTitle}
                    onChange={(e) => setNotifTitle(e.target.value)}
                    placeholder="Title (e.g. 'SOLAS January 2026 Amendments Available')"
                    className="w-full font-mono text-sm px-3 py-2 rounded-lg
                      bg-[#0a0e1a] border border-white/10 text-[#f0ece4]
                      placeholder:text-[#6b7594] focus:border-[#2dd4bf]/50 focus:outline-none"
                  />
                  <textarea
                    value={notifBody}
                    onChange={(e) => setNotifBody(e.target.value)}
                    placeholder="Body — short summary of the update"
                    rows={3}
                    className="w-full font-mono text-xs px-3 py-2 rounded-lg resize-y
                      bg-[#0a0e1a] border border-white/10 text-[#f0ece4]
                      placeholder:text-[#6b7594] focus:border-[#2dd4bf]/50 focus:outline-none"
                  />
                  <div className="flex flex-col sm:flex-row gap-3">
                    <select
                      value={notifType}
                      onChange={(e) => setNotifType(e.target.value as typeof notifType)}
                      className="font-mono text-xs px-3 py-2 rounded-lg
                        bg-[#0a0e1a] border border-white/10 text-[#f0ece4]
                        focus:border-[#2dd4bf]/50 focus:outline-none"
                    >
                      <option value="regulation_update">Regulation Update</option>
                      <option value="system">System</option>
                      <option value="announcement">Announcement</option>
                    </select>
                    <input
                      type="text"
                      value={notifSource}
                      onChange={(e) => setNotifSource(e.target.value)}
                      placeholder="Source (optional, e.g. 'solas_supplement')"
                      className="flex-1 font-mono text-xs px-3 py-2 rounded-lg
                        bg-[#0a0e1a] border border-white/10 text-[#f0ece4]
                        placeholder:text-[#6b7594] focus:border-[#2dd4bf]/50 focus:outline-none"
                    />
                    <button
                      onClick={createNotification}
                      disabled={notifSending}
                      className="font-mono text-xs font-bold uppercase tracking-wider
                        bg-[#2dd4bf] text-[#0a0e1a]
                        hover:brightness-110 rounded-lg px-4 py-2
                        transition-[filter] duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {notifSending ? 'Publishing…' : 'Send Notification'}
                    </button>
                  </div>
                  {notifToast && (
                    <div className={`font-mono text-xs px-3 py-2 rounded
                      ${notifToast.ok
                        ? 'bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/30'
                        : 'bg-red-500/10 text-red-400 border border-red-500/30'}`}>
                      {notifToast.msg}
                    </div>
                  )}
                </div>
              </div>
            )}
            {notifications.length === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
                <p className="font-mono text-xs text-[#6b7594]">No notifications yet.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    className="bg-[#111827] rounded-lg border border-white/8 px-4 py-3
                      flex items-start justify-between gap-3"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-display font-bold text-sm text-[#f0ece4] uppercase tracking-wide">
                          {n.title}
                        </p>
                        <span className={`inline-block text-[9px] font-bold px-1.5 py-0.5 rounded uppercase
                          ${n.is_active
                            ? 'bg-[#2dd4bf]/15 text-[#2dd4bf] border border-[#2dd4bf]/30'
                            : 'bg-white/5 text-[#6b7594] border border-white/10'}`}>
                          {n.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      <p className="font-mono text-xs text-[#6b7594] mt-1 line-clamp-2">
                        {n.body}
                      </p>
                      <p className="font-mono text-[10px] text-[#6b7594]/70 mt-1">
                        {n.notification_type}
                        {n.source ? ` · ${n.source}` : ''}
                        {` · ${fmtDate(n.created_at)}`}
                      </p>
                    </div>
                    {!isReadOnly && (
                      <button
                        onClick={() => toggleNotification(n.id)}
                        className="font-mono text-[10px] font-bold uppercase tracking-wider
                          border border-white/10 text-[#f0ece4]/80
                          hover:bg-white/5 rounded-md px-2.5 py-1.5 whitespace-nowrap
                          transition-colors"
                      >
                        {n.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Stats grid ───────────────────────────────────────────── */}
          {!stats && !statsError && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3 h-[72px] animate-pulse" />
              ))}
            </div>
          )}

          {statsError && !stats && (
            <div className="bg-[#111827] rounded-xl border border-red-500/30 px-6 py-5 mb-8 text-center">
              <p className="font-mono text-sm text-red-400 mb-3">Failed to load stats</p>
              <button
                onClick={fetchStats}
                className="font-mono text-xs font-bold uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-4 py-2
                  hover:brightness-110 transition-[filter] duration-150"
              >
                Retry
              </button>
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
              {/* Row 4 — subscription breakdown */}
              <div className="col-span-full bg-[#111827] rounded-xl border border-[#2dd4bf]/20 px-4 py-3">
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  Subscription Breakdown
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2">
                  <span className="font-mono text-xs text-[#f0ece4]/80">
                    <span className="text-[#2dd4bf]/70 uppercase tracking-wider text-[10px]">Monthly</span>{' '}
                    <span className="font-bold text-[#2dd4bf] text-base ml-1">{stats.subs_monthly}</span>
                  </span>
                  <span className="font-mono text-xs text-[#f0ece4]/80">
                    <span className="text-[#2dd4bf]/70 uppercase tracking-wider text-[10px]">Annual</span>{' '}
                    <span className="font-bold text-[#2dd4bf] text-base ml-1">{stats.subs_annual}</span>
                  </span>
                  <span className="font-mono text-xs text-[#f0ece4]/80">
                    <span className="text-amber-400/70 uppercase tracking-wider text-[10px]">Paused</span>{' '}
                    <span className="font-bold text-amber-400 text-base ml-1">{stats.subs_paused}</span>
                  </span>
                </div>
              </div>

              {/* Row 5 — wide card */}
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

          {/* ── System Errors (Sentry) ─────────────────────────────────── */}
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">System Errors</h2>
            {sentryLoading ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 h-[72px] animate-pulse" />
            ) : sentryIssues.length === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
                <p className="font-mono text-sm text-[#2dd4bf]">No recent issues</p>
              </div>
            ) : (
              <div className="rounded-xl border border-white/8">
                <table className="w-full table-fixed text-left font-mono text-xs">
                  <thead>
                    <tr className="bg-red-500/10 text-red-400">
                      <th className="px-3 py-2.5 font-medium w-[8%]">Sev</th>
                      <th className="px-3 py-2.5 font-medium w-[14%]">Project</th>
                      <th className="px-3 py-2.5 font-medium w-[48%]">Issue</th>
                      <th className="px-3 py-2.5 font-medium text-right w-[10%]">Count</th>
                      <th className="px-3 py-2.5 font-medium w-[20%]">Last Seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sentryIssues.map((issue, i) => {
                      const isFatal = issue.level === 'fatal' || issue.level === 'error'
                      return (
                        <tr key={issue.id}
                          className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                          <td className="px-3 py-2">
                            <span className={`inline-block text-[10px] font-bold px-1.5 py-0.5 rounded ${
                              isFatal
                                ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                                : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                            }`}>
                              {issue.level}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[#6b7594] truncate overflow-hidden">{issue.project}</td>
                          <td className="px-3 py-2 truncate overflow-hidden">
                            <a href={issue.link} target="_blank" rel="noopener noreferrer"
                              className="text-[#f0ece4]/90 hover:text-[#2dd4bf] transition-colors"
                              title={issue.title}>
                              {issue.title}
                            </a>
                          </td>
                          <td className="px-3 py-2 text-right text-[#f0ece4]/80">{issue.count.toLocaleString()}</td>
                          <td className="px-3 py-2 text-[#6b7594]" title={new Date(issue.last_seen).toLocaleString()}>
                            {fmtRelative(issue.last_seen)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ── Support Tickets ─────────────────────────────────────────── */}
          <div className="mb-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">
                Support Tickets
                {tickets.length > 0 && (
                  <span className="ml-2 font-mono text-xs text-[#6b7594] font-normal">
                    ({tickets.filter((t) => t.status === 'open').length} open)
                  </span>
                )}
              </h2>
              <div className="flex items-center gap-1">
                {(['all', 'open', 'replied', 'closed'] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setTicketFilter(f)}
                    className={`font-mono text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-md
                      transition-colors ${
                        ticketFilter === f
                          ? 'bg-[#2dd4bf]/15 text-[#2dd4bf] border border-[#2dd4bf]/30'
                          : 'text-[#6b7594] border border-transparent hover:text-[#f0ece4]/80'
                      }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            {ticketsLoading ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 h-[72px] animate-pulse" />
            ) : (() => {
              const filtered = ticketFilter === 'all'
                ? tickets
                : tickets.filter((t) => t.status === ticketFilter)
              if (filtered.length === 0) {
                return (
                  <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
                    <p className="font-mono text-sm text-[#6b7594]">
                      {ticketFilter === 'all' ? 'No support tickets yet' : `No ${ticketFilter} tickets`}
                    </p>
                  </div>
                )
              }
              return (
                <div className="space-y-2">
                  {filtered.map((t) => {
                    const isExpanded = expandedTicket === t.id
                    const statusStyles =
                      t.status === 'open'
                        ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                        : t.status === 'replied'
                        ? 'bg-[#2dd4bf]/15 text-[#2dd4bf] border-[#2dd4bf]/30'
                        : 'bg-[#6b7594]/15 text-[#6b7594] border-[#6b7594]/30'
                    return (
                      <div key={t.id} className="bg-[#111827] rounded-xl border border-white/8 overflow-hidden">
                        <button
                          onClick={() => setExpandedTicket(isExpanded ? null : t.id)}
                          className="w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className={`font-mono text-[9px] font-bold uppercase tracking-wider
                                  px-1.5 py-0.5 rounded border ${statusStyles}`}>
                                  {t.status}
                                </span>
                                <span className="font-mono text-[10px] text-[#6b7594] truncate">
                                  {t.user_email}
                                </span>
                              </div>
                              <p className="font-mono text-sm text-[#f0ece4]/90 truncate">{t.subject}</p>
                              {!isExpanded && (
                                <p className="font-mono text-xs text-[#6b7594] truncate mt-0.5">
                                  {t.message.slice(0, 120)}{t.message.length > 120 ? '…' : ''}
                                </p>
                              )}
                            </div>
                            <span className="font-mono text-[10px] text-[#6b7594] whitespace-nowrap pt-0.5">
                              {fmtDate(t.created_at)}
                            </span>
                          </div>
                        </button>

                        {isExpanded && (
                          <div className="border-t border-white/8 px-4 py-3 space-y-3">
                            <div>
                              <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                                Message
                              </p>
                              <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
                                {t.message}
                              </p>
                            </div>

                            {t.admin_reply && (
                              <div>
                                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-wider mb-1">
                                  Your reply{t.replied_at ? ` · ${fmtDate(t.replied_at)}` : ''}
                                </p>
                                <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap
                                  bg-[#0d1225] border-l-2 border-[#2dd4bf]/40 pl-3 py-2 rounded">
                                  {t.admin_reply}
                                </p>
                              </div>
                            )}

                            {!isReadOnly && t.status !== 'closed' && (
                              <div>
                                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                                  {t.status === 'replied' ? 'Send another reply' : 'Reply'}
                                </p>
                                <textarea
                                  value={replyDrafts[t.id] ?? ''}
                                  onChange={(e) => setReplyDrafts((prev) => ({ ...prev, [t.id]: e.target.value }))}
                                  placeholder="Write your reply…"
                                  rows={4}
                                  className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
                                    font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594]
                                    focus:outline-none focus:border-[#2dd4bf]/40 resize-y"
                                />
                                <div className="flex items-center gap-2 mt-2">
                                  <button
                                    onClick={() => sendTicketReply(t.id)}
                                    disabled={ticketActionId === `${t.id}-reply`}
                                    className="font-mono text-xs font-bold uppercase tracking-wider px-4 py-1.5
                                      rounded-lg bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                                      disabled:opacity-50 disabled:cursor-not-allowed transition-[filter] duration-150"
                                  >
                                    {ticketActionId === `${t.id}-reply` ? 'Sending…' : 'Send Reply'}
                                  </button>
                                  <button
                                    onClick={() => closeTicket(t.id)}
                                    disabled={ticketActionId === `${t.id}-close`}
                                    className="font-mono text-xs font-bold uppercase tracking-wider px-4 py-1.5
                                      rounded-lg border border-[#6b7594]/40 text-[#6b7594]
                                      hover:bg-[#6b7594]/10 disabled:opacity-50 transition-colors"
                                  >
                                    {ticketActionId === `${t.id}-close` ? 'Closing…' : 'Close'}
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )
            })()}

            {ticketToast && (
              <div className={`mt-3 font-mono text-xs px-3 py-2 rounded-lg border ${
                ticketToast.ok
                  ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/30 text-[#2dd4bf]'
                  : 'bg-red-500/10 border-red-500/30 text-red-400'
              }`}>
                {ticketToast.msg}
              </div>
            )}
          </div>

          {/* ── Survey Responses ────────────────────────────────────────── */}
          <div className="mb-8">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">Survey Responses</h2>
              {!isReadOnly && (
                <button
                  onClick={() => setSurveyPreview(true)}
                  className="font-mono text-xs px-3 py-1.5 rounded-lg border border-[#2dd4bf]/30
                    text-[#2dd4bf] hover:bg-[#2dd4bf]/10 transition-colors"
                >
                  Preview Survey
                </button>
              )}
            </div>

            {surveyLoading ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 h-[72px] animate-pulse" />
            ) : !surveyData || surveyData.total_responses === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
                <p className="font-mono text-sm text-[#6b7594]">No survey responses yet</p>
              </div>
            ) : (
              <>
                {/* Aggregate stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                  <StatCard label="Responses" value={surveyData.total_responses} />
                  <StatCard label="Avg Rating" value={`${surveyData.average_rating} / 5`} />
                  <StatCard label="Would Subscribe" value={`${surveyData.would_subscribe_pct}%`} />
                  <StatCard label="Top Request" value={surveyData.top_missing_feature ?? '-'} />
                </div>

                {/* Responses table */}
                <div className="rounded-xl border border-white/8 overflow-x-auto">
                  <table className="w-full text-left font-mono text-xs" style={{ minWidth: '800px' }}>
                    <thead>
                      <tr className="bg-[#2dd4bf]/10 text-[#2dd4bf]">
                        <th className="px-3 py-2.5 font-medium">User</th>
                        <th className="px-3 py-2.5 font-medium">Rating</th>
                        <th className="px-3 py-2.5 font-medium">Useful?</th>
                        <th className="px-3 py-2.5 font-medium">Favorite</th>
                        <th className="px-3 py-2.5 font-medium">Missing</th>
                        <th className="px-3 py-2.5 font-medium">Subscribe?</th>
                        <th className="px-3 py-2.5 font-medium">Comments</th>
                        <th className="px-3 py-2.5 font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {surveyData.responses.map((r, i) => (
                        <tr key={r.id}
                          className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                          <td className="px-3 py-2 text-[#f0ece4]/90 max-w-[160px] truncate" title={r.email}>
                            {r.full_name ?? r.email}
                          </td>
                          <td className="px-3 py-2 text-[#2dd4bf] whitespace-nowrap">
                            {'★'.repeat(r.overall_rating)}{'☆'.repeat(5 - r.overall_rating)}
                          </td>
                          <td className="px-3 py-2 text-[#f0ece4]/60 whitespace-nowrap">{r.usefulness ?? '-'}</td>
                          <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[120px] truncate" title={r.favorite_feature ?? ''}>
                            {r.favorite_feature ?? '-'}
                          </td>
                          <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[120px] truncate" title={r.missing_feature ?? ''}>
                            {r.missing_feature ?? '-'}
                          </td>
                          <td className="px-3 py-2 whitespace-nowrap">
                            <span className={r.would_subscribe === true ? 'text-[#2dd4bf]' : r.would_subscribe === false ? 'text-red-400/70' : 'text-[#6b7594]'}>
                              {r.would_subscribe === true ? 'Yes' : r.would_subscribe === false ? 'No' : '-'}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[160px] truncate"
                            title={[r.price_feedback, r.additional_comments].filter(Boolean).join(' | ')}>
                            {r.additional_comments || r.price_feedback || '-'}
                          </td>
                          <td className="px-3 py-2 text-[#6b7594] whitespace-nowrap">{fmtDate(r.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          {/* ── Citation Errors ──────────────────────────────────────────── */}
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">Citation Errors</h2>
            {citationLoading ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 h-[72px] animate-pulse" />
            ) : citationErrors.length === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
                <p className="font-mono text-sm text-[#2dd4bf]">No citation errors</p>
              </div>
            ) : (
              <div className="rounded-xl border border-white/8 overflow-auto max-h-[280px]">
                <table className="w-full text-left font-mono text-xs" style={{ minWidth: '600px' }}>
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-[#111827] text-amber-400">
                      <th className="px-3 py-2.5 font-medium bg-amber-500/10">Citation</th>
                      <th className="px-3 py-2.5 font-medium bg-amber-500/10">Model</th>
                      <th className="px-3 py-2.5 font-medium bg-amber-500/10">Preview</th>
                      <th className="px-3 py-2.5 font-medium bg-amber-500/10">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {citationErrors.map((ce, i) => {
                      const isExpanded = expandedCitation === ce.id
                      const rowBg = i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'
                      return (
                        <tr key={ce.id}
                          onClick={() => setExpandedCitation(isExpanded ? null : ce.id)}
                          className={`border-t border-white/5 ${rowBg} cursor-pointer
                            hover:bg-white/[0.03] transition-colors`}>
                          <td className="px-3 py-2 text-[#f0ece4]/90 whitespace-nowrap font-bold">
                            {ce.unverified_citation}
                          </td>
                          <td className="px-3 py-2 text-[#6b7594] whitespace-nowrap">
                            {ce.model_used ?? 'unknown'}
                          </td>
                          <td className="px-3 py-2 text-[#f0ece4]/60" colSpan={isExpanded ? 1 : 1}>
                            {isExpanded ? (
                              <div className="whitespace-pre-wrap break-words text-[#f0ece4]/80 leading-relaxed">
                                {ce.message_preview}
                              </div>
                            ) : (
                              <div className="truncate max-w-[300px]">
                                {ce.message_preview.slice(0, 120)}{ce.message_preview.length > 120 ? '...' : ''}
                                {ce.message_preview.length > 120 && (
                                  <span className="text-[#2dd4bf]/60 ml-1">tap to expand</span>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-[#6b7594] whitespace-nowrap align-top">
                            {fmtDate(ce.created_at)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ── Analytics Charts ─────────────────────────────────────── */}
          <div className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">Analytics</h2>

            {analyticsLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="bg-[#111827] rounded-xl border border-white/8 h-[280px] animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Chart 1: Messages per day */}
                <div className="bg-[#111827] rounded-xl border border-white/8 p-4">
                  <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-3">Messages per Day (30d)</p>
                  {messagesPerDay.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <LineChart data={messagesPerDay}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                        <XAxis
                          dataKey="day"
                          tick={{ fontSize: 10, fill: '#6b7594' }}
                          tickFormatter={(v: string) => new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                          interval="preserveStartEnd"
                        />
                        <YAxis tick={{ fontSize: 10, fill: '#6b7594' }} allowDecimals={false} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #2dd4bf33', borderRadius: '8px', fontSize: '11px', fontFamily: 'monospace' }}
                          labelStyle={{ color: '#6b7594' }}
                          itemStyle={{ color: '#2dd4bf' }}
                          labelFormatter={(v) => new Date(String(v)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                        />
                        <Line type="monotone" dataKey="message_count" stroke="#2dd4bf" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="font-mono text-xs text-[#6b7594] text-center py-16">No data yet</p>
                  )}
                </div>

                {/* Chart 2: Top cited regulations */}
                <div className="bg-[#111827] rounded-xl border border-white/8 p-4">
                  <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-3">Top Cited Regulations</p>
                  {topCitations.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={topCitations.slice(0, 10)} layout="vertical" margin={{ left: 80 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                        <XAxis type="number" tick={{ fontSize: 10, fill: '#6b7594' }} allowDecimals={false} />
                        <YAxis
                          type="category"
                          dataKey="section_number"
                          tick={{ fontSize: 9, fill: '#6b7594' }}
                          width={80}
                        />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #2dd4bf33', borderRadius: '8px', fontSize: '11px', fontFamily: 'monospace' }}
                          labelStyle={{ color: '#f0ece4' }}
                          itemStyle={{ color: '#2dd4bf' }}
                        />
                        <Bar dataKey="cite_count" fill="#2dd4bf" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="font-mono text-xs text-[#6b7594] text-center py-16">No data yet</p>
                  )}
                </div>

                {/* Chart 3: Usage by vessel type */}
                <div className="bg-[#111827] rounded-xl border border-white/8 p-4">
                  <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-3">Usage by Vessel Type</p>
                  {vesselUsage.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={vesselUsage}
                          dataKey="message_count"
                          nameKey="vessel_type"
                          cx="50%"
                          cy="50%"
                          innerRadius={50}
                          outerRadius={80}
                          paddingAngle={2}
                        >
                          {vesselUsage.map((_, i) => (
                            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #2dd4bf33', borderRadius: '8px', fontSize: '11px', fontFamily: 'monospace' }}
                        />
                        <Legend
                          wrapperStyle={{ fontSize: '10px', fontFamily: 'monospace' }}
                          formatter={(value) => <span style={{ color: '#6b7594' }}>{String(value)}</span>}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="font-mono text-xs text-[#6b7594] text-center py-16">No data yet</p>
                  )}
                </div>

                {/* Chart 4: Model usage distribution */}
                <div className="bg-[#111827] rounded-xl border border-white/8 p-4">
                  <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-3">Model Usage Distribution</p>
                  {modelUsage.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={modelUsage}
                          dataKey="message_count"
                          nameKey="model"
                          cx="50%"
                          cy="50%"
                          innerRadius={50}
                          outerRadius={80}
                          paddingAngle={2}
                        >
                          {modelUsage.map((_, i) => (
                            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #2dd4bf33', borderRadius: '8px', fontSize: '11px', fontFamily: 'monospace' }}
                          formatter={(value) => [Number(value).toLocaleString(), 'Messages']}
                        />
                        <Legend
                          wrapperStyle={{ fontSize: '10px', fontFamily: 'monospace' }}
                          formatter={(value) => <span style={{ color: '#6b7594' }}>{String(value)}</span>}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="font-mono text-xs text-[#6b7594] text-center py-16">No data yet</p>
                  )}
                </div>
              </div>
            )}
          </div>

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
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">
              Users
              <span className="ml-2 font-mono text-xs font-normal text-[#6b7594]">
                {filteredUsers.length === users.length
                  ? `(${users.length})`
                  : `(${filteredUsers.length} / ${users.length})`}
              </span>
            </h2>
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

          {/* Search + filter bar */}
          <div className="mb-3 space-y-2">
            <div className="relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#6b7594] pointer-events-none"
                viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="7" cy="7" r="5" />
                <path d="M11 11l3 3" strokeLinecap="round" />
              </svg>
              <input
                type="text"
                value={userSearch}
                onChange={(e) => setUserSearch(e.target.value)}
                placeholder="Search by email or name…"
                className="w-full bg-[#111827] border border-white/8 rounded-lg
                  pl-9 pr-9 py-2 font-mono text-sm text-[#f0ece4]
                  placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40
                  transition-colors"
              />
              {userSearch && (
                <button
                  onClick={() => setUserSearch('')}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center
                    justify-center rounded text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5"
                >
                  ×
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {USER_FILTERS.map((f) => {
                const active = userFilter === f.value
                return (
                  <button
                    key={f.value}
                    onClick={() => setUserFilter(f.value)}
                    className={`font-mono text-[10px] font-bold uppercase tracking-wider
                      px-2.5 py-1 rounded border transition-colors
                      ${active
                        ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                        : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                      }`}
                  >
                    {f.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div className={`space-y-2 ${filteredUsers.length > 10 ? 'max-h-[720px] overflow-y-auto pr-1' : ''}`}>
            {filteredUsers.length === 0 ? (
              <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-6 text-center">
                <p className="font-mono text-sm text-[#6b7594]">No users match your search</p>
              </div>
            ) : filteredUsers.map((u) => {
              const isExpanded = expandedUser === u.id
              const displayName = u.full_name?.trim() || u.email
              const now = Date.now()
              const trialTs = u.trial_ends_at ? new Date(u.trial_ends_at).getTime() : null

              // Derive status label
              let statusLabel: string
              let statusClass: string
              if (u.subscription_tier === 'pro' && u.subscription_status === 'active') {
                statusLabel = 'Pro'
                statusClass = 'bg-[#2dd4bf]/15 text-[#2dd4bf] border-[#2dd4bf]/30'
              } else if (u.subscription_status === 'paused') {
                statusLabel = 'Paused'
                statusClass = 'bg-amber-500/15 text-amber-400 border-amber-500/30'
              } else if (u.subscription_status === 'canceled' || u.subscription_status === 'canceling') {
                statusLabel = 'Canceled'
                statusClass = 'bg-[#6b7594]/15 text-[#6b7594] border-[#6b7594]/30'
              } else if (trialTs !== null && trialTs > now) {
                statusLabel = 'Trial'
                statusClass = 'bg-[#2dd4bf]/10 text-[#2dd4bf]/80 border-[#2dd4bf]/20'
              } else {
                statusLabel = 'Expired'
                statusClass = 'bg-red-500/10 text-red-400/80 border-red-500/30'
              }

              // Billing interval badge (only for pro)
              const intervalLabel =
                u.subscription_tier === 'pro' && u.subscription_status === 'active'
                  ? u.billing_interval === 'year'
                    ? 'Annual'
                    : u.billing_interval === 'month'
                    ? 'Monthly'
                    : null
                  : null

              return (
                <div key={u.id} className="bg-[#111827] rounded-xl border border-white/8 overflow-hidden">
                  <button
                    onClick={() => setExpandedUser(isExpanded ? null : u.id)}
                    className="w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`font-mono text-[9px] font-bold uppercase tracking-wider
                            px-1.5 py-0.5 rounded border ${statusClass}`}>
                            {statusLabel}
                          </span>
                          {intervalLabel && (
                            <span className="font-mono text-[9px] font-bold uppercase tracking-wider
                              px-1.5 py-0.5 rounded border border-[#2dd4bf]/30 text-[#2dd4bf]/80 bg-[#2dd4bf]/5">
                              {intervalLabel}
                            </span>
                          )}
                          {u.is_admin && (
                            <span className="font-mono text-[9px] font-bold uppercase tracking-wider
                              px-1.5 py-0.5 rounded border border-[#2dd4bf]/40 text-[#2dd4bf]">
                              Admin
                            </span>
                          )}
                          {u.cancel_at_period_end && (
                            <span className="font-mono text-[9px] font-bold uppercase tracking-wider
                              px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-400/80">
                              Cancels
                            </span>
                          )}
                        </div>
                        <p className="font-mono text-sm text-[#f0ece4]/90 truncate">{displayName}</p>
                      </div>
                      <div className="flex items-center gap-4 flex-shrink-0">
                        <div className="text-right">
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Last Active</p>
                          <p className="font-mono text-xs text-[#f0ece4]/70 whitespace-nowrap">
                            {fmtDate(u.last_active_at)}
                          </p>
                        </div>
                        <div className="text-right min-w-[44px]">
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Msgs</p>
                          <p className="font-mono text-xs text-[#f0ece4]/80">{u.message_count}</p>
                        </div>
                      </div>
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-white/8 px-4 py-4 space-y-4">
                      {/* Detail grid */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Email</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85 break-all">{u.email}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Role</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{u.role}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Registered</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{fmtDate(u.created_at)}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Trial Ends</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{fmtDate(u.trial_ends_at)}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Subscription</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">
                            {u.subscription_tier} / {u.subscription_status}
                            {intervalLabel ? ` · ${intervalLabel}` : ''}
                          </p>
                          {u.current_period_end && (
                            <p className="font-mono text-[10px] text-[#6b7594] mt-0.5">
                              Period ends {fmtDate(u.current_period_end)}
                            </p>
                          )}
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Last Active</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{fmtDate(u.last_active_at)}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Messages</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{u.message_count}</p>
                        </div>
                        <div>
                          <p className="font-mono text-[9px] text-[#6b7594] uppercase tracking-wider">Vessels</p>
                          <p className="font-mono text-xs text-[#f0ece4]/85">{u.vessel_count}</p>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-white/5">
                        <button
                          onClick={() => exportChats(u.id, u.email)}
                          disabled={exporting === u.id}
                          className="font-mono text-[10px] font-bold uppercase tracking-wider
                            px-2.5 py-1.5 rounded border border-[#2dd4bf]/30
                            text-[#2dd4bf]/80 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                            disabled:opacity-50 transition-colors"
                        >
                          {exporting === u.id ? 'Exporting…' : 'Export Chats'}
                        </button>
                        {!isReadOnly && !u.is_admin && (
                          <>
                            <button
                              onClick={() => adminAction(u.id, 'extend-trial', 'Extend trial 14 days')}
                              disabled={actionLoading === `${u.id}-extend-trial`}
                              className="font-mono text-[10px] font-bold uppercase tracking-wider
                                px-2.5 py-1.5 rounded border border-[#2dd4bf]/30
                                text-[#2dd4bf]/80 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                                disabled:opacity-50 transition-colors"
                            >
                              Extend Trial
                            </button>
                            {u.subscription_tier !== 'pro' ? (
                              <button
                                onClick={() => adminAction(u.id, 'grant-pro', 'Grant Pro')}
                                disabled={actionLoading === `${u.id}-grant-pro`}
                                className="font-mono text-[10px] font-bold uppercase tracking-wider
                                  px-2.5 py-1.5 rounded border border-[#2dd4bf]/30
                                  text-[#2dd4bf]/80 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                                  disabled:opacity-50 transition-colors"
                              >
                                Grant Pro
                              </button>
                            ) : (
                              <button
                                onClick={() => adminAction(u.id, 'revoke-pro', 'Revoke Pro')}
                                disabled={actionLoading === `${u.id}-revoke-pro`}
                                className="font-mono text-[10px] font-bold uppercase tracking-wider
                                  px-2.5 py-1.5 rounded border border-amber-500/30
                                  text-amber-400/80 hover:text-amber-400 hover:bg-amber-500/10
                                  disabled:opacity-50 transition-colors"
                              >
                                Revoke Pro
                              </button>
                            )}
                            <button
                              onClick={() => simulateExpiry(u.id, u.email)}
                              disabled={actionLoading === `${u.id}-simulate-expiry`}
                              className="font-mono text-[10px] font-bold uppercase tracking-wider
                                px-2.5 py-1.5 rounded border border-amber-500/30
                                text-amber-400/80 hover:text-amber-400 hover:bg-amber-500/10
                                disabled:opacity-50 transition-colors"
                            >
                              Simulate Expiry
                            </button>
                            <button
                              onClick={() => resetUser(u.id, u.email)}
                              disabled={resetting === u.id}
                              className="font-mono text-[10px] font-bold uppercase tracking-wider
                                px-2.5 py-1.5 rounded border border-amber-500/30
                                text-amber-400/80 hover:text-amber-400 hover:bg-amber-500/10
                                disabled:opacity-50 transition-colors"
                            >
                              {resetting === u.id ? 'Resetting…' : 'Reset'}
                            </button>
                            <button
                              onClick={() => deleteUser(u.id, u.email)}
                              disabled={deletingUser === u.id}
                              className="font-mono text-[10px] font-bold uppercase tracking-wider
                                px-2.5 py-1.5 rounded border border-red-500/40
                                text-red-400/80 hover:text-red-400 hover:bg-red-500/10
                                disabled:opacity-50 transition-colors ml-auto"
                            >
                              {deletingUser === u.id ? 'Deleting…' : 'Delete'}
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
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

      {/* Survey preview modal (admin-only, no save) */}
      {surveyPreview && (
        <PilotSurveyModal forceOpen preview onClose={() => setSurveyPreview(false)} />
      )}
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
