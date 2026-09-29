'use client'

// 2026-09-29 — in-app notifications, moved from the old "Content" tab and
// renamed for what they are: notices shown to users in the app.
// Regulation-update notices also go out in the weekly digest email.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate } from '../_lib/format'
import type { AdminNotification, Toast } from '../_lib/types'
import { Card, Empty, FilterPills, Page, Pill, Skeleton, TEXT_MUTED, ToastBanner, btn } from '../_components/ui'

type NotifType = 'regulation_update' | 'system' | 'announcement'
const TYPE_LABEL: Record<string, string> = { regulation_update: 'Regulation update', system: 'System', announcement: 'Announcement' }

const input = 'w-full font-mono text-sm px-3 py-2 rounded-lg bg-[#0a0e1a] border border-white/10 text-[#f0ece4] placeholder:text-[#6b7594] focus:border-[#2dd4bf]/50 focus:outline-none'

export default function AdminAnnouncementsPage() {
  const { isOwner } = useAdmin()
  const [rows, setRows] = useState<AdminNotification[] | null>(null)
  const [filter, setFilter] = useState<'active' | 'all'>('active')
  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [type, setType] = useState<NotifType>('regulation_update')
  const [source, setSource] = useState('')
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState<Toast>(null)

  const load = useCallback(() => {
    apiRequest<AdminNotification[]>('/admin/notifications').then(setRows).catch(() => setRows([]))
  }, [])
  useEffect(load, [load])

  function flash(t: Toast) {
    setToast(t)
    setTimeout(() => setToast(null), 4000)
  }

  async function publish() {
    if (!title.trim() || !body.trim()) { flash({ msg: 'Title and body are required', ok: false }); return }
    setSending(true)
    try {
      await apiRequest('/admin/notifications', {
        method: 'POST',
        body: JSON.stringify({ title: title.trim(), body: body.trim(), notification_type: type, source: source.trim() || null }),
      })
      setTitle(''); setBody(''); setSource('')
      flash({ msg: 'Published', ok: true })
      load()
    } catch (err) {
      flash({ msg: err instanceof Error ? err.message : 'Failed to publish', ok: false })
    }
    setSending(false)
  }

  async function toggle(id: string) {
    try {
      await apiRequest(`/admin/notifications/${id}`, { method: 'PATCH' })
      load()
    } catch {
      flash({ msg: 'Failed to toggle', ok: false })
    }
  }

  const shown = (rows ?? []).filter((n) => filter === 'all' || n.is_active)

  return (
    <Page
      title="Announcements"
      description="Notices shown to users inside the app. Regulation-update notices are also included in the weekly digest email."
      actions={isOwner && <button onClick={() => setFormOpen((v) => !v)} className={btn.secondary}>{formOpen ? 'Close' : 'New announcement'}</button>}
    >
      {isOwner && formOpen && (
        <Card className="mb-6">
          <div className="flex flex-col gap-3">
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} className={input}
              placeholder="Title (e.g. 'SOLAS January 2026 amendments available')" aria-label="Title" />
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} className={`${input} text-xs resize-y`}
              placeholder="Body: a short summary of the update" aria-label="Body" />
            <div className="flex flex-col sm:flex-row gap-3">
              <select value={type} onChange={(e) => setType(e.target.value as NotifType)} className={`${input} sm:w-auto text-xs`} aria-label="Type">
                <option value="regulation_update">Regulation update</option>
                <option value="system">System</option>
                <option value="announcement">Announcement</option>
              </select>
              <input type="text" value={source} onChange={(e) => setSource(e.target.value)} className={`${input} flex-1 text-xs`}
                placeholder="Source (optional, e.g. 'solas_supplement')" aria-label="Source" />
              <button onClick={publish} disabled={sending} className={btn.primary}>{sending ? 'Publishing…' : 'Publish'}</button>
            </div>
            <ToastBanner toast={toast} />
          </div>
        </Card>
      )}

      <div className="mb-3">
        <FilterPills options={[{ value: 'active', label: 'Active' }, { value: 'all', label: 'All' }] as const} value={filter} onChange={setFilter} />
      </div>

      {!rows ? <Skeleton /> : shown.length === 0 ? (
        <Empty>{filter === 'active' ? 'No active announcements.' : 'No announcements yet.'}</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((n) => (
            <li key={n.id} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-display font-bold text-base text-[#f0ece4] tracking-wide">{n.title}</p>
                  <Pill tone={n.is_active ? 'teal' : 'gray'}>{n.is_active ? 'Active' : 'Inactive'}</Pill>
                </div>
                <p className="font-mono text-xs text-[#f0ece4]/70 mt-1 line-clamp-2">{n.body}</p>
                <p className={`font-mono text-[11px] ${TEXT_MUTED} mt-1`}>
                  {TYPE_LABEL[n.notification_type] ?? n.notification_type}{n.source ? ` · ${n.source}` : ''} · {fmtDate(n.created_at)}
                </p>
              </div>
              {isOwner && (
                <button onClick={() => toggle(n.id)} className={`${btn.quiet} whitespace-nowrap`}>{n.is_active ? 'Deactivate' : 'Activate'}</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!formOpen && <ToastBanner toast={toast} className="mt-3" />}
    </Page>
  )
}
