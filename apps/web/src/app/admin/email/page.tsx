'use client'

// 2026-09-29 — email tools, moved from the old Email tab. The "pro" audience
// is gone (it targeted the 2026-04 'solo' tier, which nobody has).
// Transactional only: cold outreach never goes through Resend (CLAUDE.md).

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useAdmin } from '../_lib/AdminContext'
import type { Toast } from '../_lib/types'
import { EmailCatalogSection } from '../_components/EmailCatalog'
import { Card, FilterPills, Page, Section, TEXT_MUTED, ToastBanner, btn } from '../_components/ui'

type Audience = 'all' | 'trial' | 'expired' | 'cadet' | 'mate' | 'captain' | 'wheelhouse' | 'custom'
const AUDIENCES: { value: Audience; label: string }[] = [
  { value: 'all', label: 'Everyone' },
  { value: 'trial', label: 'On trial' },
  { value: 'expired', label: 'Trial expired' },
  { value: 'cadet', label: 'Cadet' },
  { value: 'mate', label: 'Mate' },
  { value: 'captain', label: 'Captain' },
  { value: 'wheelhouse', label: 'Fleet owners' },
  { value: 'custom', label: 'Custom list' },
]

const input = 'w-full font-mono text-sm px-3 py-2 rounded-lg bg-[#0a0e1a] border border-white/10 text-[#f0ece4] placeholder:text-[#6b7594] focus:border-[#2dd4bf]/50 focus:outline-none'

function CustomEmail() {
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [audience, setAudience] = useState<Audience>('all')
  const [emails, setEmails] = useState('')
  const [count, setCount] = useState<number | null>(null)
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState<Toast>(null)

  useEffect(() => {
    if (audience === 'custom') { setCount(null); return }
    apiRequest<{ count: number }>(`/admin/custom-email-count?filter=${audience}`)
      .then((r) => setCount(r.count))
      .catch(() => setCount(null))
  }, [audience])

  function flash(t: Toast, ms = 6000) {
    setToast(t)
    setTimeout(() => setToast(null), ms)
  }

  async function send() {
    if (!subject.trim() || !body.trim()) { flash({ msg: 'Subject and body are required', ok: false }); return }
    const list = audience === 'custom' ? emails.split(/[,\n]+/).map((e) => e.trim()).filter(Boolean) : undefined
    if (audience === 'custom' && (!list || list.length === 0)) { flash({ msg: 'Enter at least one email address', ok: false }); return }
    const n = audience === 'custom' ? list!.length : count
    if (!confirm(`Send "${subject.trim()}" to ${n ?? 'the selected'} recipient${n === 1 ? '' : 's'}?`)) return
    setSending(true)
    try {
      const r = await apiRequest<{ sent: number; failed: number; failed_emails: string[] }>('/admin/send-custom-email', {
        method: 'POST',
        body: JSON.stringify({ subject: subject.trim(), body_text: body.trim(), recipient_filter: audience, custom_emails: list }),
      })
      flash({ msg: `Sent to ${r.sent} user${r.sent !== 1 ? 's' : ''}${r.failed ? ` (${r.failed} failed)` : ''}`, ok: r.failed === 0 })
      if (r.failed === 0) { setSubject(''); setBody(''); setEmails('') }
    } catch (e) {
      flash({ msg: e instanceof Error ? e.message : 'Send failed', ok: false })
    }
    setSending(false)
  }

  return (
    <Section title="Send an email to users" description="Plain text; line breaks are kept. Sent from the transactional address, so keep it to product and account news.">
      <Card>
        <div className="flex flex-col gap-3">
          <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} className={input} placeholder="Subject line" aria-label="Subject" />
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} className={`${input} text-xs resize-y`} placeholder="Email body" aria-label="Body" />
          <div className="flex flex-col gap-2">
            <p className={`font-mono text-[11px] ${TEXT_MUTED}`}>
              Recipients{audience !== 'custom' && count !== null ? `: ${count}` : ''}
            </p>
            <FilterPills options={AUDIENCES} value={audience} onChange={setAudience} />
          </div>
          {audience === 'custom' && (
            <textarea value={emails} onChange={(e) => setEmails(e.target.value)} rows={2} className={`${input} text-xs resize-y`}
              placeholder="Email addresses, comma or newline separated" aria-label="Recipient emails" />
          )}
          <div className="flex items-center gap-3 flex-wrap">
            <button onClick={send} disabled={sending} className={btn.primary}>{sending ? 'Sending…' : 'Send email'}</button>
            <ToastBanner toast={toast} />
          </div>
        </div>
      </Card>
    </Section>
  )
}

export default function AdminEmailPage() {
  const { isOwner, isReadOnly } = useAdmin()
  const [sending, setSending] = useState<string | null>(null)
  const [toast, setToast] = useState<Toast>(null)

  async function sendTestEmail(type: string) {
    setSending(type)
    setToast(null)
    try {
      const r = await apiRequest<{ success: boolean; type: string; recipient: string }>('/admin/test-email', {
        method: 'POST',
        body: JSON.stringify({ type }),
      })
      setToast({ msg: `Sent ${r.type} email to ${r.recipient}`, ok: true })
    } catch {
      setToast({ msg: `Failed to send ${type} email`, ok: false })
    }
    setSending(null)
    setTimeout(() => setToast(null), 4000)
  }

  return (
    <Page title="Email" description="Preview any transactional template in your own inbox, and send announcements to groups of users.">
      {isOwner && <CustomEmail />}
      {!isReadOnly && <EmailCatalogSection emailSending={sending} emailToast={toast} sendTestEmail={sendTestEmail} />}
    </Page>
  )
}
