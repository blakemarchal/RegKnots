'use client'

// 2026-09-29 — admin dashboard. Replaces the Overview tab of the old
// single-page admin (16 same-looking counters, 4 charts, no trends) with:
// what needs attention, four KPIs with 26-week trends, growth and the
// signup funnel, answer quality, money, and recent activity.
// Data: /admin/stats (shared via AdminContext) + /admin/dashboard.
// Old deep links (/admin?tab=chats&conversation_id=…) forward to the
// section's own route.

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { apiRequest } from '@/lib/api'
import { useAdmin } from './_lib/AdminContext'
import { fmtMoney, fmtRelative, fmtWeek, pct, plural } from './_lib/format'
import type { DashboardData, RoleUsage, TopCitation } from './_lib/types'
import { Card, Kpi, MeterBar, Page, Pill, Skeleton, TEXT_MUTED, btn } from './_components/ui'

const LEGACY_TABS: Record<string, string> = {
  overview: '/admin',
  users: '/admin/users',
  chats: '/admin/chats',
  partners: '/admin/partners',
  features: '/admin/features',
  data: '/admin/data',
  jobs: '/admin/jobs',
  email: '/admin/email',
  system: '/admin/system',
  content: '/admin/support',
}

const JUDGE_LABELS: Record<string, string> = {
  complete_miss: 'complete miss',
  partial_miss: 'partial miss',
  precision_callout: 'precision callout',
  false_hedge: 'false hedge',
  unjudged: 'not judged yet',
}

const CAUSE_LABELS: Record<string, string> = {
  CORPUS_GAP: 'corpus gap',
  INTENT: 'intent',
  VOCAB: 'vocabulary',
  JURISDICTION: 'jurisdiction',
  RANKING: 'ranking',
  COSINE: 'similarity',
}

const MODEL_LABELS: Record<string, string> = {
  opus: 'Opus',
  sonnet: 'Sonnet',
  haiku: 'Haiku',
  fallback_gpt4o: 'GPT-4o fallback',
  unknown: 'unrecorded',
}

const TIER_LABELS: Record<string, string> = { cadet: 'Cadet', mate: 'Mate', captain: 'Captain', pro: 'Captain (legacy)' }

function useLegacyTabRedirect() {
  const router = useRouter()
  const params = useSearchParams()
  useEffect(() => {
    const tab = params.get('tab')
    if (!tab || !(tab in LEGACY_TABS) || tab === 'overview') return
    const cid = params.get('conversation_id')
    router.replace(cid ? `${LEGACY_TABS[tab]}?conversation_id=${encodeURIComponent(cid)}` : LEGACY_TABS[tab])
  }, [params, router])
}

interface AttentionItem {
  key: string
  text: string
  href: string
  tone: 'amber' | 'red'
}

export default function AdminDashboard() {
  useLegacyTabRedirect()
  const { stats, sentry, ei, excludeInternal, refresh, updatedAt } = useAdmin()
  const [dash, setDash] = useState<DashboardData | null>(null)
  const [dashError, setDashError] = useState(false)
  const [topCitations, setTopCitations] = useState<TopCitation[]>([])
  const [roles, setRoles] = useState<RoleUsage[]>([])

  const load = useCallback(() => {
    setDashError(false)
    apiRequest<DashboardData>(`/admin/dashboard?exclude_internal=${ei}&weeks=26`)
      .then(setDash)
      .catch(() => setDashError(true))
    apiRequest<TopCitation[]>(`/admin/analytics/top-citations?exclude_internal=${ei}`).then(setTopCitations).catch(() => {})
    apiRequest<RoleUsage[]>(`/admin/analytics/usage-by-role?exclude_internal=${ei}`).then(setRoles).catch(() => {})
  }, [ei])

  useEffect(() => { setDash(null); load() }, [load])

  const weeks = dash?.weeks ?? []
  const last4 = weeks.slice(-4)
  const signups30 = last4.reduce((n, w) => n + w.signups, 0)
  const paying = stats
    ? (stats.subs_active.cadet ?? 0) + stats.subs_active.mate + stats.subs_active.captain + stats.subs_active.pro_legacy
    : null

  const attention = useMemo<AttentionItem[]>(() => {
    if (!stats) return []
    const items: AttentionItem[] = []
    const tickets = stats.support_tickets_open ?? 0
    if (tickets) items.push({ key: 'tickets', text: `${plural(tickets, 'support ticket')} waiting for a reply`, href: '/admin/support', tone: 'amber' })
    const surveys = stats.survey_responses_7d ?? 0
    if (surveys) items.push({ key: 'surveys', text: `${plural(surveys, 'new survey response')} this week`, href: '/admin/support#surveys', tone: 'amber' })
    if (sentry?.length) items.push({ key: 'sentry', text: `${plural(sentry.length, 'unresolved app error')} in Sentry`, href: '/admin/system#errors', tone: 'red' })
    if (stats.citation_errors_7d) items.push({ key: 'cites', text: `${plural(stats.citation_errors_7d, 'unverified citation')} this week`, href: '/admin/citations', tone: 'red' })
    if (dash && dash.quality.hedged_7d) {
      items.push({
        key: 'hedged',
        text: `${dash.quality.hedged_7d} of ${plural(dash.quality.answers_7d, 'answer')} hedged this week`,
        href: '/admin/hedge-audit',
        tone: 'amber',
      })
    }
    // 2026-09-29 — Claude unavailable (credits ran out on 08-09 and 09-26): the
    // engine answers with GPT-4o instead, which only shows up in model_used.
    const fallback = dash?.quality.models_7d?.fallback_gpt4o ?? 0
    if (fallback) {
      items.push({ key: 'fallback', text: `${plural(fallback, 'answer')} came from the GPT-4o fallback this week (Claude unavailable)`, href: '/admin/system', tone: 'red' })
    }
    const pastDue = stats.subs_past_due + stats.subs_paused
    if (pastDue) items.push({ key: 'pastdue', text: `${plural(pastDue, 'subscription')} past due or paused`, href: '/admin/users?filter=paused', tone: 'red' })
    // 2026-10-02 — the free plan's monthly pool is the Claude spend guard for free users.
    const growth = dash?.growth
    if (growth && growth.free_plan_cap_month > 0 && growth.free_plan_answers_month >= growth.free_plan_cap_month * 0.8) {
      const paused = growth.free_plan_answers_month >= growth.free_plan_cap_month
      items.push({
        key: 'freeplan',
        text: paused
          ? `Free plan paused for the rest of the month (${growth.free_plan_answers_month} of ${growth.free_plan_cap_month} answers used)`
          : `Free plan at ${growth.free_plan_answers_month} of ${growth.free_plan_cap_month} answers this month; it pauses at the cap`,
        href: '/admin',
        tone: paused ? 'red' : 'amber',
      })
    }
    if (dash?.attention.trials_ending_7d) {
      items.push({ key: 'trials', text: `${plural(dash.attention.trials_ending_7d, 'trial')} ending in the next 7 days`, href: '/admin/users?filter=trial', tone: 'amber' })
    }
    if (stats.web_fallback_thumbs_down_7d) {
      items.push({ key: 'wf', text: `${plural(stats.web_fallback_thumbs_down_7d, 'thumbs-down')} on web answers this week`, href: '/admin/web-fallback', tone: 'amber' })
    }
    return items
  }, [stats, sentry, dash])

  return (
    <Page
      title="Dashboard"
      description={
        <>
          {excludeInternal ? 'Real users only: admin, internal and test accounts are left out.' : 'Including internal and test accounts.'}
          {updatedAt ? ` Updated ${fmtRelative(new Date(updatedAt).toISOString())}.` : ''}
        </>
      }
      actions={<button className={btn.quiet} onClick={() => { refresh(); load() }}>Refresh</button>}
    >
      {/* ── Needs attention ─────────────────────────────────────────── */}
      <section aria-label="Needs attention" className="mb-6">
        {!stats ? (
          <Skeleton className="h-[64px]" />
        ) : attention.length === 0 ? (
          <div className="flex items-center gap-3 rounded-xl border border-[#2dd4bf]/25 bg-[#2dd4bf]/[0.06] px-4 py-3.5">
            <span className="w-2 h-2 rounded-full bg-[#2dd4bf]" aria-hidden="true" />
            <p className="font-mono text-sm text-[#f0ece4]/90">Nothing needs you right now. No open tickets, errors or unverified citations.</p>
          </div>
        ) : (
          <div className="rounded-xl border border-amber-400/25 bg-amber-400/[0.05] px-4 py-3">
            <p className="font-mono text-[11px] uppercase tracking-wider text-amber-300/90 mb-2">Needs attention</p>
            <ul className="flex flex-col sm:flex-row sm:flex-wrap gap-x-6 gap-y-2">
              {attention.map((a) => (
                <li key={a.key}>
                  <Link href={a.href} className="group inline-flex items-center gap-2 font-mono text-sm text-[#f0ece4]/90 hover:text-[#f0ece4]">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${a.tone === 'red' ? 'bg-red-400' : 'bg-amber-400'}`} aria-hidden="true" />
                    <span className="group-hover:underline underline-offset-4">{a.text}</span>
                    <span aria-hidden="true" className="text-[#8b93ad]">→</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* ── KPIs ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 md:gap-4 mb-6">
        {!stats || !dash ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[168px]" />)
        ) : (
          <>
            <Kpi
              label="Paying customers"
              value={paying}
              href="/admin/users?filter=pro"
              sub={
                <>
                  <span className="text-[#2dd4bf] font-bold">{fmtMoney(dash.revenue.mrr_cents)}</span> MRR
                  {' · '}
                  {[['Cadet', stats.subs_active.cadet ?? 0], ['Mate', stats.subs_active.mate], ['Captain', stats.subs_active.captain + stats.subs_active.pro_legacy]]
                    .filter(([, n]) => Number(n) > 0).map(([l, n]) => `${l} ${n}`).join(' · ') || 'none yet'}
                </>
              }
              series={weeks.map((w) => w.new_paying)}
              seriesLabel="New paying customers per week, 26 weeks"
            />
            <Kpi
              label="Active users · 7 days"
              value={stats.active_users_7d}
              href="/admin/users"
              sub={<>30 days: {dash.funnel.active_30d} · {pct(stats.active_users_7d, stats.total_users)}% of {stats.total_users.toLocaleString()} signed up</>}
              series={weeks.map((w) => w.active_users)}
              seriesLabel="Users who asked a question, per week"
            />
            <Kpi
              label="Questions · 7 days"
              value={stats.questions_7d}
              href="/admin/chats"
              sub={<>{stats.total_questions.toLocaleString()} all time · {stats.total_conversations.toLocaleString()} conversations</>}
              series={weeks.map((w) => w.questions)}
              seriesLabel="Questions per week"
            />
            <Kpi
              label="Signups · last 4 weeks"
              value={signups30}
              href="/admin/traffic"
              sub={<>This week: {weeks.at(-1)?.signups ?? 0} · {stats.total_users.toLocaleString()} all time</>}
              series={weeks.map((w) => w.signups)}
              seriesLabel="Signups per week"
            />
          </>
        )}
      </div>

      {dashError && (
        <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 flex items-center justify-between gap-3">
          <p className="font-mono text-xs text-red-300">Couldn&apos;t load the trends and funnel.</p>
          <button className={btn.secondary} onClick={load}>Retry</button>
        </div>
      )}

      {/* ── Growth + funnel ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 md:gap-4 mb-6">
        <Card title="Signups and active users" subtitle="Per week, last 26 weeks" className="xl:col-span-2">
          {!dash ? <Skeleton className="h-[260px] border-0" /> : weeks.length === 0 ? (
            <p className={`font-mono text-xs ${TEXT_MUTED} py-24 text-center`}>No weekly data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={weeks} margin={{ top: 8, right: -10, bottom: 0, left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="week_start" tickFormatter={fmtWeek} tick={{ fontSize: 10, fill: '#8b93ad' }} interval="preserveStartEnd" minTickGap={24} />
                {/* Questions run 10x the other two, so they get their own axis on the right. */}
                <YAxis yAxisId="people" allowDecimals={false} tick={{ fontSize: 10, fill: '#8b93ad' }} />
                <YAxis yAxisId="questions" orientation="right" allowDecimals={false} tick={{ fontSize: 10, fill: '#e69f00' }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #2dd4bf33', borderRadius: 8, fontSize: 11, fontFamily: 'monospace' }}
                  labelStyle={{ color: '#8b93ad' }}
                  labelFormatter={(v) => `Week of ${fmtWeek(String(v))}`}
                  cursor={{ fill: 'rgba(45,212,191,0.06)' }}
                />
                <Legend wrapperStyle={{ fontSize: 11, fontFamily: 'monospace' }} formatter={(v) => <span style={{ color: '#8b93ad' }}>{String(v)}</span>} />
                <Bar yAxisId="people" dataKey="signups" name="Signups" fill="#56b4e9" fillOpacity={0.7} radius={[3, 3, 0, 0]} maxBarSize={18} />
                <Line yAxisId="people" dataKey="active_users" name="Active users" stroke="#2dd4bf" strokeWidth={2} dot={false} type="monotone" />
                <Line yAxisId="questions" dataKey="questions" name="Questions (right axis)" stroke="#e69f00" strokeWidth={1.5} strokeDasharray="4 3" dot={false} type="monotone" />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Signup funnel" subtitle="Everyone who has signed up, all time">
          {!dash ? <Skeleton className="h-[260px] border-0" /> : (
            <ol className="flex flex-col gap-3.5 mt-1">
              {([
                ['Signed up', dash.funnel.signed_up, null],
                ['Asked a question', dash.funnel.asked, 'at least once'],
                ['Came back', dash.funnel.returned, 'asked on 2+ different days'],
                ['Active in the last 30 days', dash.funnel.active_30d, null],
                ['Paying now', dash.funnel.paying, null],
              ] as const).map(([label, n, note], i) => (
                <li key={label}>
                  <div className="flex items-baseline justify-between gap-3 mb-1">
                    <span className="font-mono text-xs text-[#f0ece4]/85">
                      {label}
                      {note && <span className={`ml-1.5 text-[10px] ${TEXT_MUTED}`}>{note}</span>}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-[#f0ece4]">
                      <span className="font-bold">{n.toLocaleString()}</span>
                      {i > 0 && <span className={`ml-1.5 ${TEXT_MUTED}`}>{pct(n, dash.funnel.signed_up)}%</span>}
                    </span>
                  </div>
                  <MeterBar value={n} max={dash.funnel.signed_up} color={i === 4 ? '#2dd4bf' : '#56b4e9'} />
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {/* ── Quality · citations · roles ────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4 mb-6">
        <Card title="Answer quality · 7 days" action={<Link href="/admin/hedge-audit" className="font-mono text-[11px] text-[#2dd4bf] hover:underline">Hedge audit →</Link>}>
          {!dash || !stats ? <Skeleton className="h-[220px] border-0" /> : (
            <div className="flex flex-col gap-4">
              <div>
                <p className="font-display text-3xl font-bold text-[#f0ece4] leading-none">
                  {dash.quality.hedged_7d}
                  <span className="font-mono text-sm font-normal text-[#f0ece4]/60"> of {plural(dash.quality.answers_7d, 'answer')} hedged</span>
                </p>
                <div className="mt-2"><MeterBar value={dash.quality.hedged_7d} max={Math.max(1, dash.quality.answers_7d)} color="#e69f00" /></div>
                {Object.keys(dash.quality.judge_7d).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2.5">
                    {Object.entries(dash.quality.judge_7d).map(([v, n]) => (
                      <Pill key={v} tone={v === 'complete_miss' ? 'red' : v === 'false_hedge' ? 'gray' : 'amber'}>{n} {JUDGE_LABELS[v] ?? v}</Pill>
                    ))}
                  </div>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 font-mono text-xs">
                <div>
                  <dt className={TEXT_MUTED}>Unverified citations</dt>
                  <dd className={`text-lg font-bold ${stats.citation_errors_7d ? 'text-red-400' : 'text-[#f0ece4]'}`}>{stats.citation_errors_7d}</dd>
                </div>
                <div>
                  <dt className={TEXT_MUTED}>Web answers shown</dt>
                  <dd className="text-lg font-bold text-[#f0ece4]">
                    {stats.web_fallback_surfaced_7d ?? 0}
                    <span className={`text-xs font-normal ${TEXT_MUTED}`}> of {stats.web_fallback_attempts_7d ?? 0} tried</span>
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className={TEXT_MUTED}>Answered by</dt>
                  <dd className="text-[#f0ece4]/85">
                    {Object.keys(dash.quality.models_7d ?? {}).length === 0 ? (
                      <span className={TEXT_MUTED}>no answers yet</span>
                    ) : (
                      Object.entries(dash.quality.models_7d ?? {}).map(([m, n], i) => (
                        <span key={m} className={m === 'fallback_gpt4o' ? 'text-red-400' : undefined}>
                          {i > 0 && ' · '}{MODEL_LABELS[m] ?? m} {n}
                        </span>
                      ))
                    )}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className={TEXT_MUTED}>Open hedge audits</dt>
                  <dd className="text-[#f0ece4]">
                    <span className="text-lg font-bold">{dash.quality.hedge_audits_open}</span>
                    <span className={`ml-2 ${TEXT_MUTED}`}>
                      {Object.entries(dash.quality.open_audit_causes).slice(0, 3)
                        .map(([c, n]) => `${n} ${CAUSE_LABELS[c] ?? c.toLowerCase()}`).join(' · ')}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>
          )}
        </Card>

        <Card title="Most cited regulations" subtitle="All time">
          {topCitations.length === 0 ? (
            <p className={`font-mono text-xs ${TEXT_MUTED} py-8 text-center`}>No citations yet</p>
          ) : (
            <ol className="flex flex-col gap-2.5">
              {topCitations.slice(0, 8).map((c) => (
                <li key={`${c.source}-${c.section_number}`} title={c.section_title ?? undefined}>
                  <div className="flex items-baseline justify-between gap-3 mb-1">
                    <span className="font-mono text-xs text-[#f0ece4]/85 truncate">{c.section_number}</span>
                    <span className="font-mono text-xs tabular-nums text-[#f0ece4]/70">{c.cite_count}</span>
                  </div>
                  <MeterBar value={c.cite_count} max={topCitations[0].cite_count} />
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Questions by role" subtitle="All time">
          {roles.length === 0 ? (
            <p className={`font-mono text-xs ${TEXT_MUTED} py-8 text-center`}>No data yet</p>
          ) : (
            <ol className="flex flex-col gap-2.5">
              {[...roles].sort((a, b) => b.message_count - a.message_count).slice(0, 8).map((r) => (
                <li key={r.role}>
                  <div className="flex items-baseline justify-between gap-3 mb-1">
                    <span className="font-mono text-xs text-[#f0ece4]/85 truncate">{r.role.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-xs tabular-nums text-[#f0ece4]/70">
                      {r.message_count}<span className={`ml-1.5 ${TEXT_MUTED}`}>{plural(r.user_count, 'user')}</span>
                    </span>
                  </div>
                  <MeterBar value={r.message_count} max={Math.max(...roles.map((x) => x.message_count))} color="#cc79a7" />
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {/* ── Recent activity + money ────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 md:gap-4 mb-6">
        <Card title="Latest questions" className="xl:col-span-2" action={<Link href="/admin/chats" className="font-mono text-[11px] text-[#2dd4bf] hover:underline">All conversations →</Link>}>
          {!dash ? <Skeleton className="h-[240px] border-0" /> : dash.recent_questions.length === 0 ? (
            <p className={`font-mono text-xs ${TEXT_MUTED} py-8 text-center`}>No questions yet</p>
          ) : (
            <ul className="divide-y divide-white/5 -my-2">
              {dash.recent_questions.map((q, i) => (
                <li key={`${q.conversation_id}-${i}`}>
                  <Link href={`/admin/chats?conversation_id=${q.conversation_id}`} className="block py-2.5 group">
                    <p className="font-mono text-[13px] text-[#f0ece4]/90 line-clamp-2 group-hover:text-[#2dd4bf] transition-colors">{q.preview}</p>
                    <p className={`font-mono text-[11px] ${TEXT_MUTED} mt-0.5 truncate`}>
                      {q.user_name?.trim() || q.user_email} · {fmtRelative(q.created_at)}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="flex flex-col gap-3 md:gap-4">
          <Card title="Revenue" action={<Link href="/admin/users?filter=pro" className="font-mono text-[11px] text-[#2dd4bf] hover:underline">Paying users →</Link>}>
            {!dash ? <Skeleton className="h-[120px] border-0" /> : (
              <>
                <dl className="grid grid-cols-3 gap-3 font-mono">
                  <div>
                    <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>MRR</dt>
                    <dd className="text-lg font-bold text-[#2dd4bf]">{fmtMoney(dash.revenue.mrr_cents)}</dd>
                  </div>
                  <div>
                    <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>30 days</dt>
                    <dd className="text-lg font-bold text-[#f0ece4]">{fmtMoney(dash.revenue.paid_30d_cents)}</dd>
                  </div>
                  <div>
                    <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>All time</dt>
                    <dd className="text-lg font-bold text-[#f0ece4]">{fmtMoney(dash.revenue.paid_alltime_cents)}</dd>
                  </div>
                </dl>
                {dash.recent_payments.length > 0 && (
                  <ul className="mt-3 pt-3 border-t border-white/5 flex flex-col gap-1.5">
                    {dash.recent_payments.slice(0, 4).map((p, i) => (
                      <li key={i} className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
                        <span className="text-[#f0ece4]/80 truncate">{p.user_email ?? 'Deleted account'}</span>
                        <span className="whitespace-nowrap text-[#f0ece4]/70">
                          {fmtMoney(p.amount_cents)} {TIER_LABELS[p.subscription_tier ?? ''] ?? p.subscription_tier ?? ''}
                          <span className={`ml-1.5 ${TEXT_MUTED}`}>{fmtRelative(p.paid_at)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </Card>

          {/* 2026-10-02 — the free practice page and the free plan */}
          {(!dash || dash.growth) && (
            <Card title="Free practice · free plan" action={<Link href="/practice" className="font-mono text-[11px] text-[#2dd4bf] hover:underline">Open /practice →</Link>}>
              {!dash?.growth ? <Skeleton className="h-[110px] border-0" /> : (
                <>
                  <dl className="grid grid-cols-3 gap-3 font-mono">
                    <div>
                      <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>Quizzes 7d</dt>
                      <dd className="text-lg font-bold text-[#f0ece4]">{dash.growth.practice_quizzes_7d.toLocaleString()}</dd>
                    </div>
                    <div>
                      <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>Quizzes 30d</dt>
                      <dd className="text-lg font-bold text-[#f0ece4]">{dash.growth.practice_quizzes_30d.toLocaleString()}</dd>
                    </div>
                    <div>
                      <dt className={`text-[10px] uppercase tracking-wider ${TEXT_MUTED}`}>Signups 30d</dt>
                      <dd className="text-lg font-bold text-[#2dd4bf]">{dash.growth.practice_signups_30d.toLocaleString()}</dd>
                    </div>
                  </dl>
                  <div className="mt-3 pt-3 border-t border-white/5">
                    <div className="flex items-baseline justify-between gap-2 font-mono text-[11px] mb-1.5">
                      <span className="text-[#f0ece4]/80">Free-plan answers this month</span>
                      <span className="tabular-nums text-[#f0ece4]/70">
                        {dash.growth.free_plan_answers_month.toLocaleString()} / {dash.growth.free_plan_cap_month.toLocaleString()}
                      </span>
                    </div>
                    <MeterBar value={dash.growth.free_plan_answers_month} max={dash.growth.free_plan_cap_month}
                      color={dash.growth.free_plan_answers_month >= dash.growth.free_plan_cap_month ? '#f87171' : '#2dd4bf'} />
                  </div>
                </>
              )}
            </Card>
          )}

          <Card title="Newest signups" action={<Link href="/admin/users" className="font-mono text-[11px] text-[#2dd4bf] hover:underline">Users →</Link>}>
            {!dash ? <Skeleton className="h-[160px] border-0" /> : dash.recent_signups.length === 0 ? (
              <p className={`font-mono text-xs ${TEXT_MUTED} py-6 text-center`}>No signups yet</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {dash.recent_signups.slice(0, 5).map((s) => (
                  <li key={s.id} className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
                    <span className="min-w-0">
                      <span className="block text-[#f0ece4]/85 truncate">{s.full_name?.trim() || s.email}</span>
                      <span className={`block ${TEXT_MUTED} truncate`}>
                        {s.role?.replace(/_/g, ' ') ?? 'no role'} · {s.signup_source ?? 'source not recorded'}
                      </span>
                    </span>
                    <span className="text-right whitespace-nowrap">
                      <span className="block text-[#f0ece4]/70">{fmtRelative(s.created_at)}</span>
                      <span className={`block ${s.questions ? 'text-[#2dd4bf]' : TEXT_MUTED}`}>{plural(s.questions, 'question')}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {/* ── Corpus ──────────────────────────────────────────────────── */}
      {stats && (
        <Link href="/admin/corpus" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/8 bg-[#111827] px-4 md:px-5 py-3.5 hover:border-[#2dd4bf]/30 transition-colors">
          <p className="font-mono text-xs text-[#f0ece4]/80">
            <span className={`uppercase tracking-wider text-[11px] ${TEXT_MUTED} mr-3`}>Corpus</span>
            <span className="font-bold text-[#f0ece4]">{stats.total_chunks.toLocaleString()}</span> passages from{' '}
            <span className="font-bold text-[#f0ece4]">{Object.keys(stats.chunks_by_source).length}</span> sources
          </p>
          <span className="font-mono text-[11px] text-[#2dd4bf]">By source →</span>
        </Link>
      )}
    </Page>
  )
}
