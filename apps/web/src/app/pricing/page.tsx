'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

export default function PricingPage() {
  const [loading, setLoading] = useState(false)
  const billing = useAuthStore(s => s.billing)

  async function handleSubscribe() {
    setLoading(true)
    try {
      const { checkout_url } = await apiRequest<{ checkout_url: string }>('/billing/checkout', {
        method: 'POST',
      })
      window.location.href = checkout_url
    } catch {
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
            RegKnots
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
          <p className="font-mono text-sm text-amber-400 mb-8 text-center max-w-md">
            {billing.trial_active
              ? `You've used ${billing.message_count} of 50 free messages.`
              : 'Your 7-day free trial has ended.'}
            {' '}Subscribe to continue using RegKnots.
          </p>
        )}

        <div className="w-full max-w-sm">
          <div className="rounded-2xl p-6 border border-[#2dd4bf]/50
            bg-[#111827] shadow-[0_0_40px_rgba(45,212,191,0.08)]">
            <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">Pro</p>
            <p className="font-mono text-4xl font-bold text-[#f0ece4] mt-2">$49</p>
            <p className="font-mono text-xs text-[#6b7594]">per month</p>

            <ul className="flex flex-col gap-2 mt-6 mb-6">
              {[
                'Unlimited questions',
                'CFR Titles 33, 46 & 49 + COLREGs, NVICs & SOLAS 2024',
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

            <button
              onClick={handleSubscribe}
              disabled={loading}
              className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-3
                hover:brightness-110 transition-[filter] duration-150
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Redirecting...' : 'Subscribe Now'}
            </button>
          </div>

          <p className="font-mono text-xs text-[#6b7594] text-center mt-6">
            Powered by Stripe. Cancel anytime.
          </p>
        </div>
      </main>
    </div>
  )
}
