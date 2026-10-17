'use client'

// 2026-10-16 — "Report a problem" on Help & Support: what went wrong, an
// optional screenshot, and the page / browser the app fills in. It lands in
// Admin > Support as a problem report (apps/api/app/routers/support_reports.py).

import { useState } from 'react'
import { useAuthStore } from '@/lib/auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const MAX_SHOT = 8 * 1024 * 1024

function lastAppPage(): string {
  try {
    const ref = document.referrer
    if (ref && new URL(ref).origin === location.origin) {
      const u = new URL(ref)
      return u.pathname + (u.search.includes('conversation_id') ? u.search : '')
    }
  } catch { /* no referrer */ }
  return ''
}

export function ReportProblem() {
  const token = useAuthStore((s) => s.accessToken)
  const [page, setPage] = useState('')
  const [message, setMessage] = useState('')
  const [shot, setShot] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)

  if (!touched) {
    // Fill the page in once the user starts; document.referrer is the page they came from.
    const guess = lastAppPage()
    if (guess && !page) setPage(guess)
    setTouched(true)
  }

  async function send() {
    const text = message.trim()
    if (text.length < 10) { setError('Tell us a little more about what happened.'); return }
    if (shot && shot.size > MAX_SHOT) { setError('The screenshot is too large (8 MB max).'); return }
    setSending(true)
    setError(null)
    try {
      const form = new FormData()
      form.set('message', text)
      form.set('page', page.trim().slice(0, 300))
      let conversation_id = ''
      try { conversation_id = new URLSearchParams(page.split('?')[1] ?? '').get('conversation_id') ?? '' } catch { /* none */ }
      form.set('context', JSON.stringify({
        conversation_id,
        referrer: lastAppPage(),
        user_agent: navigator.userAgent,
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        language: navigator.language,
        online: navigator.onLine,
      }))
      if (shot) form.set('screenshot', shot, shot.name)
      const res = await fetch(`${API_URL}/support/report`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(typeof err?.detail === 'string' ? err.detail : 'Could not send the report.')
      }
      const out = (await res.json()) as { id: string }
      setDone(out.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send the report. Please email support@regknots.com.')
    } finally {
      setSending(false)
    }
  }

  if (done) {
    return (
      <div className="bg-[#111827] border border-[#2dd4bf]/20 rounded-xl px-5 py-4">
        <p className="font-display text-base font-bold text-[#2dd4bf] tracking-wide">Report received</p>
        <p className="font-mono text-xs text-[#f0ece4]/75 mt-1 leading-relaxed">
          Thank you. It&apos;s in our queue (reference {done.slice(0, 8)}). We&apos;ll write back at your account email if we need more.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-[#111827] border border-white/8 rounded-xl px-5 py-4">
      <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide">Report a problem</p>
      <p className="font-mono text-xs text-[#6b7594] mt-1 mb-3 leading-relaxed">
        Something wrong, missing or slow? Say what you did and what you saw. A screenshot helps.
      </p>
      <div className="space-y-3">
        <div>
          <label htmlFor="rp-page" className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Where</label>
          <input id="rp-page" value={page} onChange={(e) => setPage(e.target.value)} placeholder="e.g. /credentials or chat"
            className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 font-mono text-sm text-[#f0ece4]
              placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40" />
        </div>
        <div>
          <label htmlFor="rp-message" className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">What happened</label>
          <textarea id="rp-message" value={message} onChange={(e) => setMessage(e.target.value)} rows={4} maxLength={4000}
            placeholder="What you were doing, what you expected, what you got instead."
            className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 font-mono text-sm text-[#f0ece4]
              placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40 resize-y" />
        </div>
        <div>
          <label htmlFor="rp-shot" className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Screenshot (optional, JPEG / PNG / WebP)</label>
          <input id="rp-shot" type="file" accept="image/jpeg,image/png,image/webp"
            onChange={(e) => setShot(e.target.files?.[0] ?? null)}
            className="block w-full font-mono text-xs text-[#6b7594] file:mr-3 file:rounded-lg file:border-0 file:bg-white/10
              file:px-3 file:py-1.5 file:font-mono file:text-xs file:text-[#f0ece4] hover:file:bg-white/15" />
        </div>
        {error && <p className="font-mono text-xs text-amber-300">{error}</p>}
        <div className="flex items-center gap-3">
          <button onClick={send} disabled={sending || message.trim().length < 10}
            className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-5 py-2 disabled:opacity-50
              hover:brightness-110 transition-[filter] duration-150">
            {sending ? 'Sending…' : 'Send report'}
          </button>
          <span className="font-mono text-[11px] text-[#6b7594]">We attach your browser and screen size; nothing else.</span>
        </div>
      </div>
    </div>
  )
}
