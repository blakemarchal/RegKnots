'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'

export default function PricingPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState<'monthly' | 'annual'>('monthly')
  const { billing, setBilling } = useAuthStore()

  useEffect(() => {
    if (!billing) {
      apiRequest<BillingStatus>('/billing/status')
        .then(setBilling)
        .catch(() => {})
    }
  }, [billing, setBilling])

  async function handleSubscribe() {
    setLoading(true)
    setError(null)
    try {
      const data = await apiRequest<{ checkout_url: string }>('/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan }),
      })
      window.location.href = data.checkout_url
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Something went wrong'
      if (msg.includes('503')) {
        setError('Payment system is not yet configured. Please try again later.')
      } else {
        setError('Unable to start checkout. Please try again.')
      }
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col">
      {/* Nav */}
      <nav className="flex items-center justify-between px-5 md:px-10 py-4 border-b border-white/5">
        <Link href="/" className="flex items-center gap-2">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
            RegKnot
          </span>
        </Link>
        <Link href="/" className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors">
          Back to app
        </Link>
      </nav>

      <main className="flex-1 flex flex-col items-center justify-center px-5 py-16">
        <h1 className="font-display font-black text-[#f0ece4] text-center leading-tight
          text-[clamp(32px,6vw,56px)] mb-4">
          Upgrade to Pro
        </h1>

        {billing?.needs_subscription && (
          <p className="font-mono text-sm text-amber-400 mb-6 text-center max-w-md">
            {billing.trial_active
              ? `You've used ${billing.message_count} of 50 free messages.`
              : 'Your free trial has ended.'}
            {' '}Subscribe to continue using RegKnot.
          </p>
        )}

        {/* Monthly / Annual toggle */}
        <div className="flex items-center gap-1 bg-[#111827] rounded-full p-1 border border-white/8 mb-8">
          <button
            onClick={() => setPlan('monthly')}
            className={`font-mono text-sm font-bold px-5 py-2 rounded-full transition-colors duration-150
              ${plan === 'monthly'
                ? 'bg-[#2dd4bf] text-[#0a0e1a]'
                : 'text-[#6b7594] hover:text-[#f0ece4]'
              }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setPlan('annual')}
            className={`font-mono text-sm font-bold px-5 py-2 rounded-full transition-colors duration-150
              ${plan === 'annual'
                ? 'bg-[#2dd4bf] text-[#0a0e1a]'
                : 'text-[#6b7594] hover:text-[#f0ece4]'
              }`}
          >
            Annual
            <span className="ml-1.5 text-[10px] font-bold uppercase tracking-wider
              bg-[#2dd4bf]/15 text-[#2dd4bf] px-1.5 py-0.5 rounded">
              Save 26%
            </span>
          </button>
        </div>

        <div className="w-full max-w-sm">
          <div className="rounded-2xl p-6 border border-[#2dd4bf]/50
            bg-[#111827] shadow-[0_0_40px_rgba(45,212,191,0.08)]">
            <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">Pro</p>
            <p className="font-mono text-4xl font-bold text-[#f0ece4] mt-2">
              {plan === 'monthly' ? '$39' : '$29'}
            </p>
            <p className="font-mono text-xs text-[#6b7594]">
              {plan === 'monthly' ? 'per month' : 'per month, billed $348/year'}
            </p>
            <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1.5 leading-snug">
              14-day free trial · 50 messages · No credit card required
            </p>

            <ul className="flex flex-col gap-2 mt-6 mb-6">
              {[
                'Unlimited questions',
                'CFR Titles 33, 46 & 49 + COLREGs, NVICs, SOLAS 2024, STCW, ISM Code & ERG',
                'Vessel profile + history',
                'Priority regulation updates',
                'Audit-ready chat logs',
              ].map(f => (
                <li key={f} className="flex items-start gap-2">
                  <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                  </svg>
                  <span className="font-mono text-sm text-[#f0ece4]/80">{f}</span>
                </li>
              ))}
            </ul>

            {error && (
              <p className="font-mono text-xs text-red-400 mb-3 text-center">{error}</p>
            )}

            {billing && billing.tier === 'pro' && billing.subscription_status === 'active' ? (
              <div className="text-center">
                <p className="font-mono text-sm text-[#2dd4bf] font-bold mb-2">
                  You&apos;re subscribed!
                </p>
                <p className="font-mono text-xs text-[#6b7594]">
                  Manage your subscription in{' '}
                  <a href="/account" className="text-[#2dd4bf] hover:underline">Account settings</a>.
                </p>
              </div>
            ) : (
              <button
                onClick={handleSubscribe}
                disabled={loading}
                className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-3
                  hover:brightness-110 transition-[filter] duration-150
                  disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? 'Redirecting...' : 'Start Free Trial'}
              </button>
            )}
          </div>

          <p className="font-mono text-xs text-[#6b7594] text-center mt-6">
            Powered by Stripe. Cancel anytime.
          </p>
        </div>
      </main>
    </div>
  )
}
