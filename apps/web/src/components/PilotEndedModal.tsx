'use client'

import { useState } from 'react'
import { CompassRose } from './CompassRose'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface Props {
  message: string
  onClose: () => void
}

export function PilotEndedModal({ message, onClose }: Props) {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    if (!email.trim()) return
    try {
      const res = await fetch(`${API_URL}/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })
      if (!res.ok) throw new Error()
      setSubmitted(true)
    } catch {
      setError('Something went wrong. Please try again.')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-5">
      <div className="w-full max-w-sm rounded-2xl bg-[#111827] border border-white/10 p-6 shadow-xl">
        <div className="flex flex-col items-center text-center mb-6">
          <CompassRose className="w-10 h-10 text-[#2dd4bf] mb-4" />
          <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-3">
            Trial Ended
          </h2>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
            {message}
          </p>
        </div>

        {!submitted ? (
          <>
            <p className="font-mono text-xs text-[#f0ece4]/70 mb-3">
              Want to be notified when we launch? Enter your email:
            </p>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full px-3 py-2.5 rounded-lg bg-[#0a0e1a] border border-white/10
                font-mono text-sm text-[#f0ece4] placeholder-[#6b7594]
                focus:outline-none focus:border-[#2dd4bf]/50 mb-3"
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            />
            {error && (
              <p className="font-mono text-xs text-red-400 mb-2">{error}</p>
            )}
            <button
              onClick={handleSubmit}
              className="w-full font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-2.5
                hover:brightness-110 transition-[filter] duration-150 mb-2"
            >
              Notify Me
            </button>
          </>
        ) : (
          <p className="font-mono text-sm text-[#2dd4bf] text-center mb-3">
            You&apos;re on the list! We&apos;ll let you know when RegKnot launches.
          </p>
        )}

        <button
          onClick={onClose}
          className="w-full font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
            transition-colors duration-150 py-2"
        >
          Close
        </button>
      </div>
    </div>
  )
}
