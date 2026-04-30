'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

const mdComponents: Components = {
  h1: ({ children }) => <h1 className="font-display text-base font-bold text-[#f0ece4] mt-3 mb-1 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="font-display text-sm font-bold text-[#f0ece4] mt-2.5 mb-1 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="font-display text-xs font-bold text-[#f0ece4] mt-2 mb-0.5 first:mt-0">{children}</h3>,
  p: ({ children }) => <p className="mb-1.5 last:mb-0 leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-[#2dd4bf]">{children}</strong>,
  em: ({ children }) => <em className="italic text-[#f0ece4]/80">{children}</em>,
  ul: ({ children }) => <ul className="list-disc list-outside pl-3.5 mb-1.5 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-outside pl-3.5 mb-1.5 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed text-[#f0ece4]/90">{children}</li>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#2dd4bf] hover:underline">{children}</a>,
  code: ({ children, className }) => {
    if (className?.startsWith('language-')) {
      return <code className="block bg-[#0a0e1a] border border-white/8 rounded-lg px-2 py-1.5 text-[10px] font-mono text-[#f0ece4]/80 overflow-x-auto my-1.5">{children}</code>
    }
    return <code className="bg-[#0a0e1a] border border-white/8 rounded px-1 py-0.5 text-[10px] font-mono text-[#2dd4bf]">{children}</code>
  },
  blockquote: ({ children }) => <blockquote className="border-l-2 border-[#2dd4bf]/40 pl-2 my-1.5 text-[#f0ece4]/70 italic">{children}</blockquote>,
  hr: () => <hr className="border-white/10 my-2" />,
}

// ── FAQ Data ────────────────────────────────────────────────────────────────────

interface FaqItem {
  q: string
  a: string
  category: string
}

const FAQ_ITEMS: FaqItem[] = [
  // Using RegKnot
  {
    category: 'Using RegKnot',
    q: 'What regulations does RegKnot cover?',
    a: 'RegKnot covers U.S. Code of Federal Regulations Titles 33 (Navigation and Navigable Waters), 46 (Shipping), and 49 (Transportation) \u2014 plus the International Regulations for Preventing Collisions at Sea (COLREGs), U.S. Coast Guard Navigation and Vessel Inspection Circulars (NVICs), the SOLAS 2024 Consolidated Edition with the January 2026 Supplement, the STCW 2017 Consolidated Edition with the January 2025 Supplement, and the ISM Code (International Safety Management Code). We\u2019re actively expanding our knowledge base \u2014 MARPOL is next on the roadmap.',
  },
  {
    category: 'Using RegKnot',
    q: 'How do citations work?',
    a: 'When RegKnot answers a question, it cites the specific regulation sections inline \u2014 like (46 CFR 133.45), (SOLAS Ch. II-2, Reg. 10), (STCW Reg. II/1), or (ISM 1.2.3). Tap any teal citation chip to see more details about that regulation. For CFR regulations, you can view the full text. For SOLAS, STCW, COLREGs, and the ISM Code, we show a summary due to IMO copyright \u2014 you can access official text through IMO publications.',
  },
  {
    category: 'Using RegKnot',
    q: 'What are the vessel profiles for?',
    a: 'Your vessel profile helps RegKnot tailor answers to your specific situation. Requirements vary significantly by vessel type, tonnage, route (inland/coastal/international), and cargo. Adding your vessel details means answers automatically account for which regulations apply to you.',
  },
  {
    category: 'Using RegKnot',
    q: 'How accurate are the answers?',
    a: 'RegKnot pulls directly from official regulation sources \u2014 eCFR for CFR titles, official USCG publications for NVICs, and IMO-published editions of SOLAS 2024, STCW 2017 (with amendments), and the ISM Code. Every answer cites its sources. However, RegKnot is a navigation aid, not legal advice. Always verify critical compliance decisions with your company\u2019s designated person ashore (DPA) or legal counsel.',
  },
  // Account & billing
  {
    category: 'Account & Billing',
    q: 'What does the free trial include?',
    a: 'The 7-day free trial gives you 50 messages to test RegKnot with your real compliance questions. All regulation sources and features are available during the trial. No credit card required to start.',
  },
  {
    category: 'Account & Billing',
    q: 'How much does RegKnot Pro cost?',
    a: 'RegKnot Pro is $39/month, or $29/month on the annual plan (billed $348/year \u2014 a 26% savings). Both plans include unlimited questions and cancel anytime.',
  },
  {
    category: 'Account & Billing',
    q: 'How do I cancel my subscription?',
    a: 'You can cancel anytime from your billing portal. Go to [Account \u2192 Manage Subscription](/account) to open the Stripe-hosted portal, where you can cancel, switch between monthly and annual, or update your payment method. Your access continues until the end of your current billing period.',
  },
  {
    category: 'Account & Billing',
    q: 'What is the Certificates tab?',
    a: 'The Certificates tab provides printable reference templates of SOLAS certificate forms, including the Cargo Ship Safety Equipment Certificate as amended through January 2026. These are convention-prescribed form layouts that you can print or save as PDF for reference.',
  },
  // Technical
  {
    category: 'Technical',
    q: 'Can I use RegKnot offline?',
    a: 'RegKnot works as a Progressive Web App (PWA) \u2014 install it on your phone\u2019s home screen for an app-like experience. Currently, an internet connection is required for all queries. Offline cached answers are planned for a future update.',
  },
  {
    category: 'Technical',
    q: 'Which browsers are supported?',
    a: 'RegKnot works best on Chrome, Safari, Edge, and Firefox \u2014 both mobile and desktop. For the best experience on iPhone, use Safari and install the PWA to your home screen.',
  },
  {
    category: 'Technical',
    q: "RegKnot won\u2019t load on my ship\u2019s Wi-Fi",
    a: "Many ship networks restrict web applications by default. If RegKnot works on your personal mobile data but not on ship Wi-Fi, your vessel\u2019s network is likely blocking the connection. You can request your IT department to whitelist RegKnot \u2014 we\u2019ve prepared a ready-to-forward request document at [regknots.com/whitelisting](/whitelisting). As a workaround, you can use RegKnot on personal mobile data while in cellular range.",
  },
]

// ── FAQ Accordion ───────────────────────────────────────────────────────────────

const faqMdComponents: Components = {
  p: ({ children }) => <span>{children}</span>,
  a: ({ href, children }) => (
    <a
      href={href}
      onClick={(e) => e.stopPropagation()}
      className="text-[#2dd4bf] hover:underline"
    >
      {children}
    </a>
  ),
}

function FaqAccordion({ item, open, onToggle }: { item: FaqItem; open: boolean; onToggle: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}
      className="w-full text-left bg-[#111827] border border-white/8 rounded-xl px-4 py-3
        hover:border-[#2dd4bf]/30 transition-colors duration-150 cursor-pointer"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-mono text-sm text-[#f0ece4] leading-snug">{item.q}</p>
        <span className={`flex-shrink-0 text-[#6b7594] text-xs transition-transform duration-200 mt-0.5
          ${open ? 'rotate-180' : ''}`}>
          ▾
        </span>
      </div>
      {open && (
        <div className="font-mono text-xs text-[#f0ece4]/70 mt-3 leading-relaxed border-t border-white/5 pt-3">
          <ReactMarkdown components={faqMdComponents}>{item.a}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}

// ── Support Chat ────────────────────────────────────────────────────────────────

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

function SupportChat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')

    const userMsg: ChatMsg = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    try {
      const data = await apiRequest<{ response: string }>('/support/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: text,
          history: messages,
        }),
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: data.response }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, something went wrong. Please try again or email support@regknots.com.' }])
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <div className="bg-[#111827] border border-white/8 rounded-xl px-5 py-4">
        <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide">Still need help?</p>
        <p className="font-mono text-xs text-[#6b7594] mt-1 mb-3">Chat with our AI support assistant for account, billing, or technical questions.</p>
        <button
          onClick={() => setOpen(true)}
          className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
            hover:brightness-110 rounded-lg px-4 py-2 transition-[filter]"
        >
          Chat with Support
        </button>
      </div>
    )
  }

  return (
    <div className="bg-[#111827] border border-white/8 rounded-xl overflow-hidden">
      {/* Chat header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/8">
        <p className="font-display text-sm font-bold text-[#f0ece4] tracking-wide">Support Chat</p>
        <button onClick={() => setOpen(false)} className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]">
          Close
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="h-64 overflow-y-auto px-4 py-3 flex flex-col gap-3 chat-thread">
        {messages.length === 0 && (
          <p className="font-mono text-xs text-[#6b7594] italic">
            Ask about account, billing, or how to use RegKnot features.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 font-mono text-xs leading-relaxed
              ${m.role === 'user'
                ? 'bg-[#1a3254] text-[#f0ece4]'
                : 'bg-[#0d1225] text-[#f0ece4]/80 border border-white/5'
              }`}>
              {m.role === 'assistant' ? (
                <ReactMarkdown components={mdComponents}>{m.content}</ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-[#0d1225] border border-white/5 rounded-xl px-3 py-2">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-[bounceDot_1.2s_ease-in-out_infinite]" />
                <span className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-[bounceDot_1.2s_ease-in-out_0.2s_infinite]" />
                <span className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-[bounceDot_1.2s_ease-in-out_0.4s_infinite]" />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-white/8 px-3 py-2.5 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Type your question..."
          className="flex-1 bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
            font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594]/60
            focus:outline-none focus:border-[#2dd4bf]/40"
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
            hover:brightness-110 rounded-lg px-3 py-2 transition-[filter]
            disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </div>
  )
}

// ── Email Escalation ────────────────────────────────────────────────────────────

function EmailEscalation() {
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend() {
    if (!subject.trim() || !message.trim()) return
    setSending(true)
    setError(null)

    try {
      await apiRequest('/support/email', {
        method: 'POST',
        body: JSON.stringify({ subject: subject.trim(), message: message.trim() }),
      })
      setSent(true)
    } catch {
      setError('Failed to send. Please try emailing support@regknots.com directly.')
    } finally {
      setSending(false)
    }
  }

  if (sent) {
    return (
      <div className="bg-[#111827] border border-[#2dd4bf]/20 rounded-xl px-5 py-4">
        <p className="font-display text-base font-bold text-[#2dd4bf] tracking-wide">Message sent</p>
        <p className="font-mono text-xs text-[#f0ece4]/70 mt-1">
          We&apos;ll get back to you at your account email. Most issues are resolved within 24 hours.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-[#111827] border border-white/8 rounded-xl px-5 py-4">
      <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide">Contact Us</p>
      <p className="font-mono text-xs text-[#6b7594] mt-1 mb-3">
        Need to talk to a human? Send us a message and we&apos;ll reply by email.
      </p>

      <div className="space-y-3">
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
            font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594]/60
            focus:outline-none focus:border-[#2dd4bf]/40"
        />
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Describe your issue..."
          rows={4}
          className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
            font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594]/60
            focus:outline-none focus:border-[#2dd4bf]/40 resize-none"
        />

        {error && <p className="font-mono text-xs text-red-400">{error}</p>}

        <button
          onClick={handleSend}
          disabled={sending || !subject.trim() || !message.trim()}
          className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
            hover:brightness-110 rounded-lg px-4 py-2 transition-[filter]
            disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {sending ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  )
}

// ── Support Page ────────────────────────────────────────────────────────────────

function SupportContent() {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [openIdx, setOpenIdx] = useState<number | null>(null)

  const filtered = search.trim()
    ? FAQ_ITEMS.filter(
        (item) =>
          item.q.toLowerCase().includes(search.toLowerCase()) ||
          item.a.toLowerCase().includes(search.toLowerCase())
      )
    : FAQ_ITEMS

  // Group by category
  const categories = [...new Set(filtered.map((f) => f.category))]

  return (
    <div className="flex flex-col min-h-dvh bg-[#0a0e1a]">
      <AppHeader title="Help & Support" />

      <main className="flex-1 overflow-y-auto chat-thread">
        <div className="max-w-2xl mx-auto px-4 py-5 flex flex-col gap-6">

          {/* Search */}
          <div>
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setOpenIdx(null) }}
              placeholder="Search FAQ..."
              className="w-full bg-[#111827] border border-white/10 rounded-xl px-4 py-3
                font-mono text-sm text-[#f0ece4] placeholder:text-[#6b7594]/60
                focus:outline-none focus:border-[#2dd4bf]/40"
            />
          </div>

          {/* FAQ */}
          {categories.map((cat) => (
            <div key={cat}>
              <p className="font-display text-sm font-bold text-[#2dd4bf] uppercase tracking-wider mb-2">
                {cat}
              </p>
              <div className="flex flex-col gap-2">
                {filtered
                  .map((item, globalIdx) => ({ item, globalIdx }))
                  .filter(({ item }) => item.category === cat)
                  .map(({ item, globalIdx }) => (
                    <FaqAccordion
                      key={globalIdx}
                      item={item}
                      open={openIdx === globalIdx}
                      onToggle={() => setOpenIdx(openIdx === globalIdx ? null : globalIdx)}
                    />
                  ))}
              </div>
            </div>
          ))}

          {filtered.length === 0 && search.trim() && (
            <p className="font-mono text-sm text-[#6b7594] text-center py-8">
              No matching questions found. Try the support chat below.
            </p>
          )}

          {/* Support chat */}
          <SupportChat />

          {/* Email escalation */}
          <EmailEscalation />

          {/* Footer note */}
          <p className="font-mono text-[10px] text-[#6b7594] text-center pb-4">
            RegKnot is a navigation aid only and does not constitute legal advice.
          </p>
        </div>
      </main>
    </div>
  )
}

export default function SupportPage() {
  return (
    <AuthGuard>
      <SupportContent />
    </AuthGuard>
  )
}
