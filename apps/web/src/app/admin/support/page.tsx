'use client'

// 2026-09-29 — support tickets and survey responses, formerly two of the six
// unrelated sections under the old "Content" tab.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { PilotSurveyModal } from '@/components/PilotSurveyModal'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate } from '../_lib/format'
import type { SupportTicket, SurveyAggregates, Toast } from '../_lib/types'
import { Empty, FilterPills, Page, Pill, Section, Skeleton, StatCard, TEXT_MUTED, ToastBanner, btn } from '../_components/ui'

type TicketFilter = 'all' | 'open' | 'replied' | 'closed'
const TICKET_FILTERS: { value: TicketFilter; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'replied', label: 'Replied' },
  { value: 'closed', label: 'Closed' },
  { value: 'all', label: 'All' },
]

function Tickets() {
  const { isReadOnly, refresh } = useAdmin()
  const [tickets, setTickets] = useState<SupportTicket[] | null>(null)
  const [filter, setFilter] = useState<TicketFilter>('open')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<Toast>(null)

  const load = useCallback(() => {
    apiRequest<SupportTicket[]>('/admin/support-tickets').then(setTickets).catch(() => setTickets([]))
  }, [])
  useEffect(load, [load])

  function flash(t: Toast) {
    setToast(t)
    setTimeout(() => setToast(null), 4000)
  }

  async function reply(id: string) {
    const text = (drafts[id] ?? '').trim()
    if (!text) { flash({ msg: 'Reply text is required', ok: false }); return }
    setBusy(`${id}-reply`)
    try {
      await apiRequest(`/admin/support-tickets/${id}/reply`, { method: 'POST', body: JSON.stringify({ reply: text }) })
      setTickets((prev) => prev?.map((t) => t.id === id ? { ...t, status: 'replied', admin_reply: text, replied_at: new Date().toISOString() } : t) ?? null)
      setDrafts((prev) => { const n = { ...prev }; delete n[id]; return n })
      flash({ msg: 'Reply sent', ok: true })
      refresh()
    } catch {
      flash({ msg: 'Failed to send reply', ok: false })
    }
    setBusy(null)
  }

  async function close(id: string) {
    const t = tickets?.find((x) => x.id === id)
    if (!confirm(t?.status === 'replied' ? 'Close this ticket?' : 'Close this ticket without replying?')) return
    setBusy(`${id}-close`)
    try {
      await apiRequest(`/admin/support-tickets/${id}/close`, { method: 'POST' })
      setTickets((prev) => prev?.map((x) => x.id === id ? { ...x, status: 'closed' } : x) ?? null)
      flash({ msg: 'Ticket closed', ok: true })
      refresh()
    } catch {
      flash({ msg: 'Failed to close ticket', ok: false })
    }
    setBusy(null)
  }

  const counts = {
    all: tickets?.length ?? 0,
    open: tickets?.filter((t) => t.status === 'open').length ?? 0,
    replied: tickets?.filter((t) => t.status === 'replied').length ?? 0,
    closed: tickets?.filter((t) => t.status === 'closed').length ?? 0,
  }
  const shown = (tickets ?? []).filter((t) => filter === 'all' || t.status === filter)

  return (
    <Section title="Support tickets" description="Replies go to the user by email." action={<FilterPills options={TICKET_FILTERS} value={filter} onChange={setFilter} counts={tickets ? counts : undefined} />}>
      {!tickets ? <Skeleton /> : shown.length === 0 ? (
        <Empty tone={filter === 'open' ? 'good' : 'muted'}>{filter === 'open' ? 'No open tickets.' : filter === 'all' ? 'No support tickets yet.' : `No ${filter} tickets.`}</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((t) => {
            const open = expanded === t.id
            return (
              <li key={t.id} className="bg-[#111827] rounded-xl border border-white/8 overflow-hidden">
                <button onClick={() => setExpanded(open ? null : t.id)} aria-expanded={open} className="w-full px-4 py-3 text-left hover:bg-white/[0.02]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <Pill tone={t.status === 'open' ? 'amber' : t.status === 'replied' ? 'teal' : 'gray'}>{t.status}</Pill>
                        <span className={`font-mono text-[11px] ${TEXT_MUTED} truncate`}>{t.user_name ? `${t.user_name} · ` : ''}{t.user_email}</span>
                      </div>
                      <p className="font-mono text-sm text-[#f0ece4]/90 truncate">{t.subject}</p>
                      {!open && <p className={`font-mono text-xs ${TEXT_MUTED} truncate mt-0.5`}>{t.message.slice(0, 140)}</p>}
                    </div>
                    <span className={`font-mono text-[11px] ${TEXT_MUTED} whitespace-nowrap pt-0.5`}>{fmtDate(t.created_at)}</span>
                  </div>
                </button>
                {open && (
                  <div className="border-t border-white/8 px-4 py-3 flex flex-col gap-3">
                    <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">{t.message}</p>
                    {t.admin_reply && (
                      <div>
                        <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-wider mb-1">Your reply{t.replied_at ? ` · ${fmtDate(t.replied_at)}` : ''}</p>
                        <p className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap bg-[#0d1225] border-l-2 border-[#2dd4bf]/40 pl-3 py-2 rounded">{t.admin_reply}</p>
                      </div>
                    )}
                    {!isReadOnly && t.status !== 'closed' && (
                      <div>
                        <label className={`block font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider mb-1`} htmlFor={`reply-${t.id}`}>
                          {t.status === 'replied' ? 'Send another reply' : 'Reply'}
                        </label>
                        <textarea
                          id={`reply-${t.id}`}
                          value={drafts[t.id] ?? ''}
                          onChange={(e) => setDrafts((prev) => ({ ...prev, [t.id]: e.target.value }))}
                          placeholder="Write your reply…"
                          rows={4}
                          className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40 resize-y"
                        />
                        <div className="flex items-center gap-2 mt-2">
                          <button onClick={() => reply(t.id)} disabled={busy === `${t.id}-reply`} className={btn.primary}>
                            {busy === `${t.id}-reply` ? 'Sending…' : 'Send reply'}
                          </button>
                          <button onClick={() => close(t.id)} disabled={busy === `${t.id}-close`} className={btn.quiet}>
                            {busy === `${t.id}-close` ? 'Closing…' : 'Close ticket'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <ToastBanner toast={toast} className="mt-3" />
    </Section>
  )
}

function Surveys() {
  const { isReadOnly } = useAdmin()
  const [data, setData] = useState<SurveyAggregates | null | undefined>(undefined)
  const [preview, setPreview] = useState(false)

  useEffect(() => {
    apiRequest<SurveyAggregates>('/survey/admin/responses').then(setData).catch(() => setData(null))
  }, [])

  return (
    <Section
      id="surveys"
      title="Survey responses"
      description="The in-app product survey."
      action={!isReadOnly && <button onClick={() => setPreview(true)} className={btn.secondary}>Preview survey</button>}
    >
      {data === undefined ? <Skeleton /> : !data || data.total_responses === 0 ? (
        <Empty>No survey responses yet.</Empty>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <StatCard label="Responses" value={data.total_responses} />
            <StatCard label="Avg rating" value={`${data.average_rating} / 5`} />
            <StatCard label="Would subscribe" value={`${data.would_subscribe_pct}%`} />
            <StatCard label="Top request" value={data.top_missing_feature ?? '-'} />
          </div>
          <div className="rounded-xl border border-white/8 overflow-x-auto">
            <table className="w-full text-left font-mono text-xs" style={{ minWidth: 800 }}>
              <thead>
                <tr className="bg-[#2dd4bf]/10 text-[#2dd4bf]">
                  {['User', 'Rating', 'Useful?', 'Favorite', 'Missing', 'Subscribe?', 'Comments', 'Date'].map((h) => (
                    <th key={h} className="px-3 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.responses.map((r, i) => (
                  <tr key={r.id} className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                    <td className="px-3 py-2 text-[#f0ece4]/90 max-w-[160px] truncate" title={r.email}>{r.full_name ?? r.email}</td>
                    <td className="px-3 py-2 text-[#2dd4bf] whitespace-nowrap" aria-label={`${r.overall_rating} out of 5`}>{'★'.repeat(r.overall_rating)}{'☆'.repeat(5 - r.overall_rating)}</td>
                    <td className="px-3 py-2 text-[#f0ece4]/60 whitespace-nowrap">{r.usefulness ?? '-'}</td>
                    <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[140px] truncate" title={r.favorite_feature ?? ''}>{r.favorite_feature ?? '-'}</td>
                    <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[140px] truncate" title={r.missing_feature ?? ''}>{r.missing_feature ?? '-'}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className={r.would_subscribe === true ? 'text-[#2dd4bf]' : r.would_subscribe === false ? 'text-red-400/70' : 'text-[#6b7594]'}>
                        {r.would_subscribe === true ? 'Yes' : r.would_subscribe === false ? 'No' : '-'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/60 max-w-[180px] truncate" title={[r.price_feedback, r.additional_comments].filter(Boolean).join(' | ')}>
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
      {preview && <PilotSurveyModal forceOpen preview onClose={() => setPreview(false)} />}
    </Section>
  )
}

export default function AdminSupportPage() {
  return (
    <Page title="Tickets & surveys" description="What users are asking for help with, and what they think of the product.">
      <Tickets />
      <Surveys />
    </Page>
  )
}
