'use client'

import { useState, FormEvent } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await apiRequest('/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
    } catch {
      // Always show success — don't leak whether email exists
    } finally {
      setLoading(false)
      setSubmitted(true)
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-navy px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center flex flex-col items-center gap-3">
          <CompassRose className="w-12 h-12 text-teal" />
          <div>
            <h1 className="font-display text-3xl font-black tracking-widest uppercase text-off-white">
              Reg<span className="text-teal">Knot</span>
            </h1>
            <p className="mt-1 text-xs text-muted tracking-wider uppercase font-mono">
              Maritime Compliance Co-pilot
            </p>
          </div>
        </div>

        {submitted ? (
          <div className="bg-surface-mid border border-white/8 rounded-xl p-6 flex flex-col gap-4 text-center">
            <svg className="w-10 h-10 text-teal mx-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="font-mono text-sm text-off-white leading-relaxed">
              If that email is registered, you&apos;ll receive a reset link shortly.
            </p>
            <p className="font-mono text-xs text-muted">
              Check your spam folder if it doesn&apos;t arrive within a few minutes.
            </p>
          </div>
        ) : (
          <form
            onSubmit={handleSubmit}
            className="bg-surface-mid border border-white/8 rounded-xl p-6 flex flex-col gap-4"
          >
            <div>
              <p className="font-mono text-sm text-off-white mb-1">Reset your password</p>
              <p className="font-mono text-xs text-muted">
                Enter your account email and we&apos;ll send you a reset link.
              </p>
            </div>

            <div className="flex flex-col gap-1">
              <label htmlFor="email" className="text-xs text-muted uppercase tracking-wider font-mono">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="font-mono bg-surface-dim border border-white/10 rounded-lg px-3 py-2 text-sm text-off-white outline-none focus:border-teal transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="bg-teal hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-navy font-bold text-sm uppercase tracking-wider rounded-lg py-2.5 transition-[filter] font-mono"
            >
              {loading ? 'Sending…' : 'Send Reset Link'}
            </button>
          </form>
        )}

        <p className="mt-4 text-center text-xs text-muted font-mono">
          <Link href="/login" className="text-teal hover:underline">
            ← Back to Sign In
          </Link>
        </p>
      </div>
    </main>
  )
}
