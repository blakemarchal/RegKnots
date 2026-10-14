'use client'

// 2026-10-14 — one free answer before signup (growth plan step 2). A visitor
// asks one question from a public page; the answer streams from
// POST /public/ask/stream (apps/api/app/routers/guest_chat.py). The stream's
// first event carries a claim secret that the register page sends with the new
// account, so the question and answer are waiting in chat after signup.
//
// Shows its children (the plain sign-up CTA) instead when the feature is off:
// no NEXT_PUBLIC_TURNSTILE_SITE_KEY at build time, or the API says disabled.

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? ''
const DEVICE_KEY = 'rk_device'
export const GUEST_CLAIM_KEY = 'rk_guest_claim'

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string
  reset: (id?: string) => void
  remove: (id?: string) => void
}
declare global {
  interface Window { turnstile?: TurnstileApi }
}

type Phase = 'checking' | 'off' | 'ready' | 'asking' | 'answered' | 'used' | 'error'

interface Props {
  page: string
  heading: string
  placeholder?: string
  /** Classes for a wrapper drawn only while the widget is on (layout spacing). */
  outerClassName?: string
  children?: React.ReactNode
}

function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_KEY)
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem(DEVICE_KEY, id)
    }
    return id
  } catch {
    return crypto.randomUUID()
  }
}

function storedClaim(): { claim: string; conversation_id: string } | null {
  try {
    const raw = localStorage.getItem(GUEST_CLAIM_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

let turnstileScript: Promise<void> | null = null
function loadTurnstile(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  if (!turnstileScript) {
    turnstileScript = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      s.async = true
      s.onload = () => resolve()
      s.onerror = () => reject(new Error('turnstile'))
      document.head.appendChild(s)
    })
  }
  return turnstileScript
}

export function GuestAsk({ page, heading, placeholder, outerClassName, children }: Props) {
  const [phase, setPhase] = useState<Phase>(SITE_KEY ? 'checking' : 'off')
  const [vesselTypes, setVesselTypes] = useState<string[]>([])
  const [vesselType, setVesselType] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [statusText, setStatusText] = useState('')
  const [answer, setAnswer] = useState('')
  const [message, setMessage] = useState('')
  const [token, setToken] = useState('')
  const widgetRef = useRef<HTMLDivElement>(null)
  const widgetId = useRef<string | null>(null)
  const signupHref = `/register?src=guest&utm_content=${encodeURIComponent(page)}`

  useEffect(() => {
    if (!SITE_KEY) return
    if (storedClaim()) {
      setPhase('used')
      return
    }
    fetch(`${API_URL}/public/ask/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s: { enabled: boolean; vessel_types: string[] } | null) => {
        if (!s?.enabled) return setPhase('off')
        setVesselTypes(s.vessel_types)
        setPhase('ready')
      })
      .catch(() => setPhase('off'))
  }, [])

  useEffect(() => {
    if (phase !== 'ready' || !widgetRef.current || widgetId.current) return
    loadTurnstile()
      .then(() => {
        if (!widgetRef.current || !window.turnstile || widgetId.current) return
        widgetId.current = window.turnstile.render(widgetRef.current, {
          sitekey: SITE_KEY,
          appearance: 'interaction-only',
          callback: (t: string) => setToken(t),
          'expired-callback': () => setToken(''),
          'error-callback': () => setToken(''),
        })
      })
      .catch(() => setPhase('off'))
  }, [phase])

  async function ask(e: React.FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (q.length < 3 || phase !== 'ready') return
    setPhase('asking')
    setStatusText('Reading the regulations…')
    setAnswer('')
    setMessage('')
    try {
      const res = await fetch(`${API_URL}/public/ask/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, turnstile_token: token, device_id: deviceId(), vessel_type: vesselType, page }),
      })
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => null)
        const detail = err?.detail
        setMessage(typeof detail === 'object' && detail?.message ? detail.message : 'Something went wrong. Please try again.')
        if (detail?.code === 'guest_used' || detail?.code === 'guest_ip' || detail?.code === 'guest_paused') {
          setPhase('used')
        } else {
          setPhase('ready')
          if (widgetId.current) window.turnstile?.reset(widgetId.current)
          setToken('')
        }
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let text = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''
        for (const raw of events) {
          let type = ''
          let data = ''
          for (const line of raw.split('\n')) {
            if (line.startsWith('event: ')) type = line.slice(7).trim()
            else if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!type) continue
          let parsed: unknown = data
          try { parsed = JSON.parse(data) } catch { /* plain text */ }
          if (type === 'guest') {
            try { localStorage.setItem(GUEST_CLAIM_KEY, JSON.stringify(parsed)) } catch { /* private mode */ }
          } else if (type === 'status' && typeof parsed === 'string') {
            setStatusText(parsed)
          } else if (type === 'delta' && typeof parsed === 'string') {
            text += parsed
            setAnswer(text)
          } else if (type === 'delta_reset') {
            text = ''
            setAnswer('')
          } else if (type === 'done') {
            const final = (parsed as { answer?: string })?.answer
            if (final) setAnswer(final)
            setPhase('answered')
          } else if (type === 'error') {
            setMessage('The answer could not be finished. Create a free account and ask again in chat.')
            setPhase('error')
          }
        }
      }
      setPhase((p) => (p === 'asking' ? 'answered' : p))
    } catch {
      setMessage('Something went wrong. Please try again.')
      setPhase('error')
    }
  }

  if (phase === 'off' || phase === 'checking') return <>{children}</>

  const cta = (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <Link href={signupHref}
        className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-5 py-2.5 hover:brightness-110 transition-[filter] duration-150">
        {phase === 'answered' ? 'Save this answer and keep asking' : 'Create a free account'}
      </Link>
      <span className="font-mono text-xs text-[#6b7594]">Free trial, no card. Your question moves to your account.</span>
    </div>
  )

  const widget = (
    <section className="rounded-2xl border border-[#2dd4bf]/30 bg-[#2dd4bf]/[0.06] p-5 md:p-6">
      <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-1">{heading}</h2>
      {phase === 'used' && !answer ? (
        <>
          <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed">
            {message || 'You’ve asked your free question. Create a free account to see your answer in chat and keep asking.'}
          </p>
          {cta}
        </>
      ) : (
        <>
          <p className="font-mono text-sm text-[#f0ece4]/70 leading-relaxed mb-3">
            Ask one question free, no sign-up. RegKnot answers from the regulation text, with citations.
          </p>
          {(phase === 'ready' || (phase === 'asking' && !answer)) && (
            <form onSubmit={ask}>
              {vesselTypes.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3" role="group" aria-label="Your vessel type (optional)">
                  {vesselTypes.map((t) => (
                    <button key={t} type="button" onClick={() => setVesselType(vesselType === t ? null : t)}
                      aria-pressed={vesselType === t}
                      className={`font-mono text-[11px] rounded-full border px-2.5 py-1 transition-colors ${
                        vesselType === t
                          ? 'border-[#2dd4bf] bg-[#2dd4bf]/15 text-[#2dd4bf]'
                          : 'border-white/15 text-[#f0ece4]/60 hover:border-white/30'}`}>
                      {t}
                    </button>
                  ))}
                </div>
              )}
              <textarea value={query} onChange={(e) => setQuery(e.target.value)} maxLength={1500} rows={3}
                placeholder={placeholder ?? 'Ask a compliance question for your vessel'}
                disabled={phase === 'asking'}
                className="w-full rounded-xl bg-[#0a0e1a] border border-white/15 focus:border-[#2dd4bf]/60 outline-none
                  px-3 py-2.5 font-mono text-base md:text-sm text-[#f0ece4] placeholder:text-[#6b7594] resize-y" />
              <div ref={widgetRef} className="mt-2" />
              <div className="mt-3 flex items-center gap-3">
                <button type="submit" disabled={phase === 'asking' || query.trim().length < 3 || !token}
                  className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-5 py-2.5
                    disabled:opacity-50 hover:brightness-110 transition-[filter] duration-150">
                  {phase === 'asking' ? 'Answering…' : 'Ask'}
                </button>
                {phase === 'asking' && <span className="font-mono text-xs text-[#6b7594]" aria-live="polite">{statusText}</span>}
                {phase === 'ready' && !token && <span className="font-mono text-xs text-[#6b7594]">Checking your browser…</span>}
              </div>
              {message && <p className="mt-2 font-mono text-xs text-amber-300">{message}</p>}
            </form>
          )}
          {answer && (
            <div className="mt-2 rounded-xl border border-white/8 bg-[#0a0e1a] p-4" aria-live="polite">
              <div className="font-mono text-[14px] leading-relaxed text-[#f0ece4]/90 break-words
                [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3
                [&_li]:mb-1 [&_strong]:text-[#f0ece4] [&_a]:text-[#2dd4bf] [&_h1]:font-bold [&_h2]:font-bold
                [&_h3]:font-bold [&_h1]:mb-2 [&_h2]:mb-2 [&_h3]:mb-2 [&_table]:text-xs [&_table]:block
                [&_table]:overflow-x-auto [&_td]:border [&_td]:border-white/10 [&_td]:px-2 [&_th]:border
                [&_th]:border-white/10 [&_th]:px-2">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
              </div>
              {phase === 'asking' && <p className="mt-2 font-mono text-xs text-[#6b7594]">{statusText}</p>}
            </div>
          )}
          {(phase === 'answered' || phase === 'error') && (
            <>
              {message && <p className="mt-2 font-mono text-xs text-amber-300">{message}</p>}
              {cta}
            </>
          )}
        </>
      )}
    </section>
  )
  return outerClassName ? <div className={outerClassName}>{widget}</div> : widget
}
