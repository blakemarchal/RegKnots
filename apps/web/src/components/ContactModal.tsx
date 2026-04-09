'use client'

import { useEffect, useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface ContactModalProps {
  open: boolean
  onClose: () => void
}

const INPUT_CLS =
  'w-full font-mono text-sm bg-[#0a0e1a] border border-white/10 rounded-lg ' +
  'px-3 py-2 text-[#f0ece4] placeholder:text-[#6b7594]/70 ' +
  'focus:border-[#2dd4bf] focus:outline-none transition-colors duration-150 ' +
  'disabled:opacity-50'

export function ContactModal({ open, onClose }: ContactModalProps) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [company, setCompany] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  // Reset form when the modal closes so re-opening is a clean slate.
  useEffect(() => {
    if (open) return
    setName('')
    setEmail('')
    setCompany('')
    setMessage('')
    setSending(false)
    setError(null)
    setSent(false)
  }, [open])

  // Auto-close 3s after a successful send.
  useEffect(() => {
    if (!sent) return
    const id = setTimeout(onClose, 3000)
    return () => clearTimeout(id)
  }, [sent, onClose])

  // Lock body scroll while open.
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (sending) return

    const trimmedName = name.trim()
    const trimmedEmail = email.trim()
    const trimmedMessage = message.trim()

    if (trimmedName.length < 2) {
      setError('Please enter your name.')
      return
    }
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      setError('Please enter a valid email.')
      return
    }
    if (trimmedMessage.length < 10) {
      setError('Please enter a message (at least 10 characters).')
      return
    }

    setSending(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/contact/inquiry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: trimmedName,
          email: trimmedEmail,
          company: company.trim() || null,
          message: trimmedMessage,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSent(true)
    } catch {
      setError('Something went wrong. Email us directly at hello@regknots.com')
    } finally {
      setSending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center
        bg-black/70 backdrop-blur-sm p-5"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Contact us"
    >
      <div
        className="w-full max-w-md rounded-2xl bg-[#111827] border border-white/10
          shadow-xl relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-3 right-3 w-8 h-8 flex items-center justify-center
            rounded-lg text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/8
            transition-colors duration-150"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>

        <div className="px-6 pt-6 pb-6">
          {sent ? (
            <div className="flex flex-col items-center text-center py-6">
              <div className="w-12 h-12 rounded-full bg-[#2dd4bf]/15 border border-[#2dd4bf]/40
                flex items-center justify-center mb-4">
                <svg className="w-6 h-6 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <h2 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-2">
                Message Sent
              </h2>
              <p className="font-mono text-sm text-[#6b7594]">
                We&rsquo;ll be in touch shortly.
              </p>
            </div>
          ) : (
            <>
              <h2 className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                Get in <span className="text-[#2dd4bf]">Touch</span>
              </h2>
              <p className="font-mono text-xs text-[#6b7594] mt-1 mb-5 leading-relaxed">
                Fleet pricing, enterprise access, or general questions &mdash; we read every message.
              </p>

              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  required
                  disabled={sending}
                  autoComplete="name"
                  className={INPUT_CLS}
                />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  required
                  disabled={sending}
                  autoComplete="email"
                  className={INPUT_CLS}
                />
                <input
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Company or vessel operator (optional)"
                  disabled={sending}
                  autoComplete="organization"
                  className={INPUT_CLS}
                />
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Tell us about your fleet, use case, or question..."
                  required
                  rows={4}
                  disabled={sending}
                  className={`${INPUT_CLS} resize-y`}
                />

                <button
                  type="submit"
                  disabled={sending}
                  className="w-full font-mono text-sm font-bold uppercase tracking-wider
                    bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-3 mt-1
                    hover:brightness-110 transition-[filter] duration-150
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {sending ? 'Sending…' : 'Send Message'}
                </button>

                {error && (
                  <p className="font-mono text-xs text-red-400 leading-relaxed">
                    Something went wrong. Email us directly at{' '}
                    <a
                      href="mailto:hello@regknots.com"
                      className="underline hover:text-red-300"
                    >
                      hello@regknots.com
                    </a>
                  </p>
                )}
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
