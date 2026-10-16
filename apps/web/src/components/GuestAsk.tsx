'use client'

// 2026-10-14 — one free answer before signup (growth plan step 2). A visitor
// asks one question from a public page; the answer streams from
// POST /public/ask/stream (apps/api/app/routers/guest_chat.py). The stream's
// first event carries a claim secret that the register page sends with the new
// account, so the question and answer are waiting in chat after signup.
//
// Shows its children (the plain sign-up CTA) instead when the feature is off:
// no NEXT_PUBLIC_TURNSTILE_SITE_KEY at build time, or the API says disabled.
//
// 2026-10-16 UI pass — the answer renders through AnswerBody, the same
// renderer as chat (headings, chips, the verified badge). A chip opens our
// public page for that section, else eCFR, else says the full text opens in
// an account (GET /public/regs/links). The Turnstile hint asks for the tick
// when Cloudflare wants one.

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { AnswerBody } from '@/components/AnswerBody'
import { extractFooterCitations } from '@/lib/parseMessage'
import type { CitedRegulation, WebSourceRef } from '@/types/chat'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? ''
const DEVICE_KEY = 'rk_device'
export const GUEST_CLAIM_KEY = 'rk_guest_claim'

// The answer prompt adds this when it saves vessel details; for a visitor the
// details only stay if they create an account, which the CTA below offers.
const VESSEL_NOTE = /\s*I[’']ve noted these details about your vessel and will remember them for future questions\.?/g

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string
  reset: (id?: string) => void
  remove: (id?: string) => void
}
declare global {
  interface Window { turnstile?: TurnstileApi }
}

type Phase = 'checking' | 'off' | 'ready' | 'asking' | 'answered' | 'used' | 'error'
type ReadLink = { slug: string | null; url: string | null }

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
  const [asked, setAsked] = useState('')
  const [statusText, setStatusText] = useState('')
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState<CitedRegulation[]>([])
  const [webSources, setWebSources] = useState<WebSourceRef[]>([])
  const [links, setLinks] = useState<Record<string, ReadLink>>({})
  const [chipNote, setChipNote] = useState('')
  const [message, setMessage] = useState('')
  const [token, setToken] = useState('')
  const [needsTick, setNeedsTick] = useState(false)
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
          callback: (t: string) => { setToken(t); setNeedsTick(false) },
          'expired-callback': () => setToken(''),
          'error-callback': () => setToken(''),
          'before-interactive-callback': () => setNeedsTick(true),
          'after-interactive-callback': () => setNeedsTick(false),
        })
      })
      .catch(() => setPhase('off'))
  }, [phase])

  // Where each cited section can be read without an account.
  async function loadLinks(text: string, cited: CitedRegulation[]) {
    const map = new Map(cited.map((c) => [c.section_number, { source: c.source, title: c.section_title }]))
    const sections = extractFooterCitations(text, map)
      .filter((c) => c.source !== 'web')
      .map((c) => c.sectionNumber)
      .slice(0, 20)
    if (sections.length === 0) return
    try {
      const qs = sections.map((s) => `s=${encodeURIComponent(s)}`).join('&')
      const res = await fetch(`${API_URL}/public/regs/links?${qs}`)
      if (!res.ok) return
      const rows: Array<{ section_number: string } & ReadLink> = await res.json()
      setLinks(Object.fromEntries(rows.map((r) => [r.section_number, { slug: r.slug, url: r.url }])))
    } catch { /* chips fall back to the note */ }
  }

  function openCitation(_source: string, sectionNumber: string) {
    const link = links[sectionNumber]
    const href = link?.slug ? `/regs/${link.slug}` : link?.url
    if (href) {
      window.open(href, '_blank', 'noopener,noreferrer')
      setChipNote('')
    } else {
      setChipNote(sectionNumber)
    }
  }

  async function ask(e: React.FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (q.length < 3 || phase !== 'ready') return
    setPhase('asking')
    setAsked(q)
    setStatusText('Reading the regulations…')
    setAnswer('')
    setCitations([])
    setWebSources([])
    setMessage('')
    setChipNote('')
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
        setAsked('')
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
            const final = parsed as { answer?: string; cited_regulations?: CitedRegulation[]; web_sources?: WebSourceRef[] }
            if (final?.answer) {
              text = final.answer
              setAnswer(final.answer)
            }
            const cited = final?.cited_regulations ?? []
            setCitations(cited)
            setWebSources(final?.web_sources ?? [])
            setPhase('answered')
            void loadLinks(text.replace(VESSEL_NOTE, ''), cited)
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

  const shown = answer.replace(VESSEL_NOTE, '')
  const streaming = phase === 'asking'

  const cta = (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
      <Link href={signupHref}
        className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-5 py-2.5 hover:brightness-110 transition-[filter] duration-150">
        {phase === 'answered' ? 'Save this answer and keep asking' : 'Create a free account'}
      </Link>
      <span className="font-mono text-xs text-[#6b7594]">Free to start, no card. Your question moves to your account.</span>
    </div>
  )

  const widget = (
    <section className="rounded-2xl border border-[#2dd4bf]/30 bg-[#0d1225] p-5 md:p-7 shadow-[0_0_60px_rgba(45,212,191,0.06)]">
      <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-2">Free · no sign-up</p>
      <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] leading-tight mb-2">{heading}</h2>
      {phase === 'used' && !answer ? (
        <>
          <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed">
            {message || 'You’ve asked your free question. Create a free account to see your answer in chat and keep asking.'}
          </p>
          {cta}
        </>
      ) : (
        <>
          {!asked && (
            <p className="font-mono text-sm text-[#f0ece4]/70 leading-relaxed mb-4">
              Pick your vessel type and ask in plain English. RegKnot answers from the regulation text and cites
              every requirement.
            </p>
          )}
          {(phase === 'ready' || (phase === 'asking' && !answer)) && !asked && (
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
                aria-label="Your question"
                placeholder={placeholder ?? 'Ask a compliance question for your vessel'}
                className="w-full rounded-xl bg-[#0a0e1a] border border-white/15 focus:border-[#2dd4bf]/60 outline-none
                  px-3 py-2.5 font-mono text-base md:text-sm text-[#f0ece4] placeholder:text-[#6b7594] resize-y" />
              <div ref={widgetRef} className="mt-2 empty:mt-0" />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button type="submit" disabled={query.trim().length < 3 || !token}
                  className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-2.5
                    disabled:opacity-50 hover:brightness-110 transition-[filter] duration-150">
                  Ask
                </button>
                {!token && query.trim().length >= 3 && (
                  <span className="font-mono text-xs text-[#6b7594]" aria-live="polite">
                    {needsTick ? 'Tick “Verify you are human” above to ask.' : 'Checking your browser…'}
                  </span>
                )}
              </div>
              {message && <p className="mt-2 font-mono text-xs text-amber-300">{message}</p>}
            </form>
          )}

          {asked && (
            <div className="mt-2" aria-live="polite" aria-busy={streaming || undefined}>
              <div className="flex justify-end mb-3">
                <div className="max-w-[88%] px-4 py-3 rounded-2xl rounded-tr-sm bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed">
                  {asked}
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-0.5 self-stretch bg-[#2dd4bf]/40 rounded-full flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
                  {shown ? (
                    <AnswerBody content={shown} citations={citations} webSources={webSources}
                      onCitationTap={openCitation} isStreaming={streaming} />
                  ) : (
                    <p className="font-mono text-xs text-[#6b7594]">{statusText || 'Reading the regulations…'}</p>
                  )}
                  {streaming && shown && <p className="mt-2 font-mono text-xs text-[#6b7594]">{statusText}</p>}
                </div>
              </div>
            </div>
          )}

          {chipNote && (
            <p className="mt-4 rounded-lg border border-white/10 bg-[#0a0e1a] px-3 py-2 font-mono text-xs text-[#f0ece4]/75">
              The full text of {chipNote} opens in RegKnot once you create a free account.
            </p>
          )}
          {(phase === 'answered' || phase === 'error') && (
            <>
              {message && <p className="mt-3 font-mono text-xs text-amber-300">{message}</p>}
              {cta}
            </>
          )}
        </>
      )}
    </section>
  )
  return outerClassName ? <div className={outerClassName}>{widget}</div> : widget
}
