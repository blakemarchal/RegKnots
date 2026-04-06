'use client'

import { useEffect, useState, useCallback } from 'react'
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

interface SentryIssue {
  id: string
  title: string
  level: string
  count: number
  last_seen: string
  link: string
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

  const ei = excludeInternal ? 'true' : 'false'

  const fetchStats = useCallback(() => {
    apiRequest<AdminStats>(`/admin/stats?exclude_internal=${ei}`).then(setStats).catch(() => {})
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

    const interval = setInterval(() => { fetchStats(); fetchSentry(); fetchCitations(); fetchSurvey(); fetchAnalytics() }, 60_000)
    return () => clearInterval(interval)
  }, [hydrated, isAdmin, router, fetchStats, fetchUsers, fetchSentry, fetchCitations, fetchSurvey, fetchAnalytics])

  function toggleExcludeInternal() {
    const next = !excludeInternal
    setExcludeInternal(next)
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

          {/* ── Stats grid ───────────────────────────────────────────── */}
          {!stats && (
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
                          <td className="px-3 py-2 text-[#6b7594]">{fmtDate(issue.last_seen)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
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
              <div className="rounded-xl border border-white/8 overflow-x-auto">
                <table className="w-full text-left font-mono text-xs" style={{ minWidth: '600px' }}>
                  <thead>
                    <tr className="bg-amber-500/10 text-amber-400">
                      <th className="px-3 py-2.5 font-medium">Citation</th>
                      <th className="px-3 py-2.5 font-medium">Model</th>
                      <th className="px-3 py-2.5 font-medium">Preview</th>
                      <th className="px-3 py-2.5 font-medium">Date</th>
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

          <div className="rounded-xl border border-white/8 overflow-x-auto">
            <table className="w-full text-left font-mono text-xs" style={{ minWidth: '860px' }}>
              <thead>
                <tr className="bg-[#2dd4bf]/10 text-[#2dd4bf]">
                  <th className="px-2 py-2 font-medium">Email</th>
                  <th className="px-2 py-2 font-medium">Name</th>
                  <th className="px-2 py-2 font-medium">Tier</th>
                  <th className="px-2 py-2 font-medium">Status</th>
                  <th className="px-2 py-2 font-medium text-right">Msgs</th>
                  <th className="px-2 py-2 font-medium">Trial Ends</th>
                  <th className="px-2 py-2 font-medium">Joined</th>
                  <th className="px-2 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={u.id}
                    className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                    <td className="px-2 py-1.5 text-[#f0ece4]/90" title={u.email}>
                      <span className="block max-w-[180px] truncate">{u.email}</span>
                      {u.is_admin && <span className="text-[#2dd4bf] text-[9px]">ADMIN</span>}
                    </td>
                    <td className="px-2 py-1.5 text-[#f0ece4]/60" title={u.full_name ?? ''}>
                      <span className="block max-w-[110px] truncate">{u.full_name ?? '-'}</span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={u.subscription_tier === 'pro' ? 'text-[#2dd4bf]' : 'text-[#6b7594]'}>
                        {u.subscription_tier}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-[#f0ece4]/60">{u.subscription_status}</td>
                    <td className="px-2 py-1.5 text-right text-[#f0ece4]/80">{u.message_count}</td>
                    <td className="px-2 py-1.5 text-[#6b7594] whitespace-nowrap">{fmtDate(u.trial_ends_at)}</td>
                    <td className="px-2 py-1.5 text-[#6b7594] whitespace-nowrap">{fmtDate(u.created_at)}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => exportChats(u.id, u.email)}
                          disabled={exporting === u.id}
                          title="Export chat logs"
                          className="font-mono text-[9px] px-1 py-px rounded border border-[#2dd4bf]/30
                            text-[#2dd4bf]/70 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                            disabled:opacity-50 transition-colors"
                        >
                          {exporting === u.id ? '..' : 'Exp'}
                        </button>
                        {!isReadOnly && !u.is_admin && (
                          <>
                            <button
                              onClick={() => adminAction(u.id, 'extend-trial', 'Extend trial 14 days')}
                              disabled={actionLoading === `${u.id}-extend-trial`}
                              title="Extend trial 14 days"
                              className="font-mono text-[9px] px-1 py-px rounded border border-[#2dd4bf]/30
                                text-[#2dd4bf]/70 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                                disabled:opacity-50 transition-colors"
                            >
                              +T
                            </button>
                            <button
                              onClick={() => simulateExpiry(u.id, u.email)}
                              disabled={actionLoading === `${u.id}-simulate-expiry`}
                              title="Simulate trial expiry"
                              className="font-mono text-[9px] px-1 py-px rounded border border-amber-500/30
                                text-amber-400/70 hover:text-amber-400 hover:bg-amber-500/10
                                disabled:opacity-50 transition-colors"
                            >
                              Sim
                            </button>
                            {u.subscription_tier !== 'pro' ? (
                              <button
                                onClick={() => adminAction(u.id, 'grant-pro', 'Grant Pro')}
                                disabled={actionLoading === `${u.id}-grant-pro`}
                                title="Grant Pro"
                                className="font-mono text-[9px] px-1 py-px rounded border border-[#2dd4bf]/30
                                  text-[#2dd4bf]/70 hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                                  disabled:opacity-50 transition-colors"
                              >
                                +P
                              </button>
                            ) : (
                              <button
                                onClick={() => adminAction(u.id, 'revoke-pro', 'Revoke Pro')}
                                disabled={actionLoading === `${u.id}-revoke-pro`}
                                title="Revoke Pro"
                                className="font-mono text-[9px] px-1 py-px rounded border border-amber-500/30
                                  text-amber-400/70 hover:text-amber-400 hover:bg-amber-500/10
                                  disabled:opacity-50 transition-colors"
                              >
                                -P
                              </button>
                            )}
                            <button
                              onClick={() => resetUser(u.id, u.email)}
                              disabled={resetting === u.id}
                              title="Reset pilot account"
                              className="font-mono text-[9px] px-1 py-px rounded border border-red-500/30
                                text-red-400/70 hover:text-red-400 hover:bg-red-500/10
                                disabled:opacity-50 transition-colors"
                            >
                              {resetting === u.id ? '..' : 'Rst'}
                            </button>
                          </>
                        )}
                      </div>
                    </td>
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
