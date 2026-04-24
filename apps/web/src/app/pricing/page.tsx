'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'

// Sprint D6.3 — two-tier pricing page. Mate ($19.99 / $14.99 annual eq.)
// is the capped plan; Captain ($39.99 / $29.99 annual eq.) is unlimited.
// Annual toggle is the default because (a) it's better cash flow / lower
// churn for us and (b) the stated savings are real for the user.

type Plan = 'mate_monthly' | 'mate_annual' | 'captain_monthly' | 'captain_annual'

type Tier = 'mate' | 'captain'
type Interval = 'monthly' | 'annual'

function planKey(tier: Tier, interval: Interval): Plan {
  return `${tier}_${interval}` as Plan
}

const TIER_FEATURES: Record<Tier, { headline: string; perks: string[] }> = {
  mate: {
    headline: 'For mariners with occasional compliance questions.',
    perks: [
      '100 messages per month',
      'CFR Titles 33 / 46 / 49 + SOLAS, COLREGs, NVICs, STCW, ISM, ERG',
      '46 USC + WHO IHR (port health & seamen\u2019s law)',
      'Vessel profile + chat history',
      'Cited regulation answers, not summaries',
    ],
  },
  captain: {
    headline: 'For working mariners using RegKnot daily.',
    perks: [
      'Unlimited messages',
      'Everything in Mate, plus:',
      'Priority regulation update notifications',
      'Audit-ready chat logs',
      'PSC checklist builder & sea-service letters',
    ],
  },
}

const TIER_DISPLAY: Record<Tier, { name: string; monthly: number; annualEq: number; annualTotal: number }> = {
  mate:    { name: 'Mate',    monthly: 19.99, annualEq: 14.99, annualTotal: 179.88 },
  captain: { name: 'Captain', monthly: 39.99, annualEq: 29.99, annualTotal: 359.88 },
}

export default function PricingPage() {
  const [interval, setInterval] = useState<Interval>('annual')
  const [loading, setLoading] = useState<Plan | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { billing, setBilling, isAuthenticated } = useAuthStore()

  useEffect(() => {
    if (isAuthenticated && !billing) {
      apiRequest<BillingStatus>('/billing/status')
        .then(setBilling)
        .catch(() => {})
    }
  }, [isAuthenticated, billing, setBilling])

  async function handleSubscribe(tier: Tier) {
    const plan = planKey(tier, interval)
    if (!isAuthenticated) {
      // Persist plan intent so we can resume after login.
      try { localStorage.setItem('pending_checkout_plan', plan) } catch {}
      window.location.href = '/register'
      return
    }
    // If the user came in via a charity landing page (e.g. /womenoffshore),
    // that page wrote a referral_source to localStorage. Honor it on any
    // checkout — even if the user wandered through /pricing afterwards —
    // so the charity gets credited consistently.
    let referralSource: string | null = null
    try { referralSource = localStorage.getItem('regknot_referral_source') } catch {}
    setLoading(plan)
    setError(null)
    try {
      const data = await apiRequest<{ checkout_url: string }>('/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan,
          ...(referralSource && { referral_source: referralSource }),
        }),
      })
      window.location.href = data.checkout_url
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Something went wrong'
      if (msg.includes('503')) {
        setError('Payment system is not yet configured. Please try again later.')
      } else if (msg.includes('409')) {
        setError('You already have an active subscription. Manage it from Account settings.')
      } else {
        setError('Unable to start checkout. Please try again.')
      }
      setLoading(null)
    }
  }

  const showSubscribed =
    billing && billing.subscription_status === 'active' &&
    (billing.tier === 'mate' || billing.tier === 'captain' || billing.tier === 'pro')

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

      <main className="flex-1 flex flex-col items-center px-5 py-14 md:py-20">
        <h1 className="font-display font-black text-[#f0ece4] text-center leading-tight
          text-[clamp(32px,6vw,52px)] mb-3">
          Pick your plan
        </h1>
        <p className="font-mono text-sm text-[#6b7594] text-center max-w-md mb-8">
          {billing?.needs_subscription && billing.trial_active
            ? `You\u2019ve used ${billing.message_count} of 50 free messages. Subscribe to continue.`
            : billing?.needs_subscription
            ? 'Your free trial has ended. Subscribe to continue.'
            : 'Two tiers, monthly or annual. Cancel anytime.'}
        </p>

        {/* Monthly / Annual toggle — defaults to annual */}
        <div className="flex items-center gap-1 bg-[#111827] rounded-full p-1 border border-white/8 mb-10">
          <button
            onClick={() => setInterval('monthly')}
            className={`font-mono text-sm font-bold px-5 py-2 rounded-full transition-colors duration-150
              ${interval === 'monthly'
                ? 'bg-[#2dd4bf] text-[#0a0e1a]'
                : 'text-[#6b7594] hover:text-[#f0ece4]'
              }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setInterval('annual')}
            className={`font-mono text-sm font-bold px-5 py-2 rounded-full transition-colors duration-150
              ${interval === 'annual'
                ? 'bg-[#2dd4bf] text-[#0a0e1a]'
                : 'text-[#6b7594] hover:text-[#f0ece4]'
              }`}
          >
            Annual
            <span className="ml-1.5 text-[10px] font-bold uppercase tracking-wider
              bg-[#2dd4bf]/15 text-[#2dd4bf] px-1.5 py-0.5 rounded">
              Save 25%
            </span>
          </button>
        </div>

        {error && (
          <p className="font-mono text-xs text-red-400 mb-4 text-center">{error}</p>
        )}

        <div className="grid w-full max-w-4xl gap-5 md:grid-cols-2">
          {(['mate', 'captain'] as Tier[]).map((tier) => {
            const display = TIER_DISPLAY[tier]
            const features = TIER_FEATURES[tier]
            const featured = tier === 'captain'
            const plan = planKey(tier, interval)
            const isLoading = loading === plan
            const priceShown = interval === 'monthly' ? display.monthly : display.annualEq
            const priceSub = interval === 'monthly'
              ? 'per month'
              : `per month, billed $${display.annualTotal.toFixed(2)}/year`
            return (
              <div key={tier} className={`flex flex-col rounded-2xl p-6 border transition-shadow
                ${featured
                  ? 'bg-[#111827] border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]'
                  : 'bg-[#0d1225] border-white/8'
                }`}>
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div>
                    <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                      {display.name}
                    </p>
                    <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">
                      ${priceShown.toFixed(2)}
                    </p>
                    <p className="font-mono text-xs text-[#6b7594]">{priceSub}</p>
                    <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1.5 leading-snug">
                      Free trial · No credit card required
                    </p>
                  </div>
                  {featured && (
                    <span className="font-mono text-[10px] font-bold text-[#2dd4bf] bg-[#2dd4bf]/10
                      border border-[#2dd4bf]/30 rounded px-2 py-1 uppercase tracking-wider whitespace-nowrap">
                      Most popular
                    </span>
                  )}
                </div>

                <p className="font-mono text-xs text-[#6b7594] mb-4 leading-relaxed">
                  {features.headline}
                </p>

                <ul className="flex flex-col gap-2 mb-6 flex-1">
                  {features.perks.map((perk) => (
                    <li key={perk} className="flex items-start gap-2">
                      <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                      </svg>
                      <span className="font-mono text-sm text-[#f0ece4]/80">{perk}</span>
                    </li>
                  ))}
                </ul>

                {showSubscribed ? (
                  <div className="text-center">
                    <p className="font-mono text-sm text-[#2dd4bf] font-bold mb-2">
                      You&apos;re subscribed!
                    </p>
                    <p className="font-mono text-xs text-[#6b7594]">
                      Manage in{' '}
                      <a href="/account" className="text-[#2dd4bf] hover:underline">Account settings</a>.
                    </p>
                  </div>
                ) : (
                  <button
                    onClick={() => handleSubscribe(tier)}
                    disabled={!!loading}
                    className={`w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                      rounded-lg py-3 transition-[filter] duration-150
                      disabled:opacity-50 disabled:cursor-not-allowed
                      ${featured
                        ? 'bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110'
                        : 'border border-white/20 text-[#f0ece4]/70 hover:text-[#f0ece4] hover:border-white/40'
                      }`}
                  >
                    {isLoading ? 'Redirecting…' : `Start free trial · ${display.name}`}
                  </button>
                )}
              </div>
            )
          })}
        </div>

        <p className="font-mono text-xs text-[#6b7594] text-center mt-8 max-w-md leading-relaxed">
          Powered by Stripe. Cancel anytime. 10% of every subscription supports
          maritime charities — see{' '}
          <Link href="/giving" className="text-[#2dd4bf] hover:underline">our giving page</Link>.
        </p>
      </main>
    </div>
  )
}
