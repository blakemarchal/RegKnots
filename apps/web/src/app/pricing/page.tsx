'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { CorpusBadges } from '@/components/CorpusBadges'
import { LandingFooter } from '@/components/marketing/LandingFooter'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'

// Sprint D6.3b — three-tier pricing page: Free Trial, Mate, Captain.
// Paid tiers (Mate, Captain) are directly purchasable — no forced trial
// gate. The trial card exists as a friction-free on-ramp but is not the
// visual headline. Default toggle is Monthly.
//
// Referral-aware pricing: users with billing.referral_source set (e.g.
// they came in through /womenoffshore) see promo prices on the Monthly
// side — Mate drops to $14.99, Captain to $29.99. Annual is unaffected
// because there is no annual promo price. CTAs route to *_promo plan
// keys in that case so Stripe charges the right amount.

type Tier = 'mate' | 'captain'
type Interval = 'monthly' | 'annual'

type PlanKey =
  | 'mate_monthly' | 'mate_annual' | 'mate_promo'
  | 'captain_monthly' | 'captain_annual' | 'captain_promo'

function resolvePlanKey(tier: Tier, interval: Interval, referral: boolean): PlanKey {
  if (interval === 'annual') return `${tier}_annual` as PlanKey
  if (referral) return `${tier}_promo` as PlanKey
  return `${tier}_monthly` as PlanKey
}

const TIER_FEATURES: Record<Tier, { headline: string; perks: string[] }> = {
  mate: {
    headline: 'For mariners building their record and asking compliance questions.',
    perks: [
      '100 messages per month',
      'Full reg corpus (see below)',
      'Vessel profile + chat history',
      'Credential vault with auto-OCR',
      'Renewal alerts (90 / 30 / 7 days)',
      'AI Renewal Co-Pilot + Career Path',
      'Vessel Analysis + Compliance Changelog',
      'Cited regulation answers, not summaries',
    ],
  },
  captain: {
    headline: 'For working mariners using RegKnot daily.',
    perks: [
      'Everything in Mate, plus:',
      'Unlimited messages',
      'PSC Co-Pilot + Audit Readiness',
      'USCG sea-service letter generator',
      'Audit-ready chat logs',
      'Priority regulation update notifications',
    ],
  },
}

const TIER_DISPLAY: Record<Tier, {
  name: string
  monthly: number
  monthlyPromo: number
  annualEq: number
  annualTotal: number
}> = {
  mate:    { name: 'Mate',    monthly: 19.99, monthlyPromo: 14.99, annualEq: 14.99, annualTotal: 179.88 },
  captain: { name: 'Captain', monthly: 39.99, monthlyPromo: 29.99, annualEq: 29.99, annualTotal: 359.88 },
}

export default function PricingPage() {
  const [interval, setInterval] = useState<Interval>('monthly')
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { billing, setBilling, isAuthenticated } = useAuthStore()

  useEffect(() => {
    if (isAuthenticated && !billing) {
      apiRequest<BillingStatus>('/billing/status')
        .then(setBilling)
        .catch(() => {})
    }
  }, [isAuthenticated, billing, setBilling])

  // Referral-aware pricing. Any non-null referral_source grants lifetime
  // monthly promo pricing (Sprint D6.3b). Annual prices don't change.
  // Note: we describe these as donor-recipient relationships, not
  // partnerships — there is no formal partnership agreement; RegKnots
  // simply donates 10% of revenue from these signups to the named
  // non-profit. Pre-2026-05-09 copy used "Partner pricing" which
  // implied a formal partnership and was retired for legal clarity.
  const hasReferral = !!billing?.referral_source
  const referralNote = hasReferral
    ? `Supporter pricing — your subscription donates to ${billing!.referral_source!.replace(/_/g, ' ')}`
    : null

  async function handleSubscribeTier(tier: Tier) {
    const plan = resolvePlanKey(tier, interval, hasReferral)
    if (!isAuthenticated) {
      try { localStorage.setItem('pending_checkout_plan', plan) } catch {}
      window.location.href = '/register'
      return
    }
    // Honor any localStorage-saved referral source on checkout too —
    // covers the edge where billing.referral_source isn't yet populated
    // (e.g. just registered but billing/status cache hasn't refreshed).
    let referralSource: string | null = billing?.referral_source ?? null
    if (!referralSource) {
      try { referralSource = localStorage.getItem('regknot_referral_source') } catch {}
    }
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

  function handleStartTrial() {
    if (!isAuthenticated) {
      window.location.href = '/register'
      return
    }
    // Trial users are already free-tier users; send them into the app.
    window.location.href = '/'
  }

  const showSubscribed =
    billing && billing.subscription_status === 'active' &&
    (billing.tier === 'mate' || billing.tier === 'captain' || billing.tier === 'pro')

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col">
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
        <p className="font-mono text-sm text-[#6b7594] text-center max-w-md mb-4">
          {billing?.needs_subscription && billing.trial_active
            ? `You’ve used ${billing.message_count} of 50 free messages. Subscribe to continue.`
            : billing?.needs_subscription
            ? 'Your free trial has ended. Subscribe to continue.'
            : 'Start free or subscribe directly. Cancel anytime.'}
        </p>

        {referralNote && (
          <p className="font-mono text-xs text-[#2dd4bf] text-center mb-6 uppercase tracking-wider">
            {referralNote}
          </p>
        )}

        {/* Monthly / Annual toggle — default Monthly */}
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

        <div className="grid w-full max-w-5xl gap-5 md:grid-cols-3">
          {/* ── Free Trial (de-emphasized) ────────────────────────────── */}
          <div className="flex flex-col rounded-2xl p-6 border border-white/8 bg-[#0b1020]">
            <div className="mb-4">
              <p className="font-display text-xl font-bold text-[#f0ece4]/80 tracking-wide">
                Free Trial
              </p>
              <p className="font-mono text-3xl font-bold text-[#f0ece4]/80 mt-1">$0</p>
              <p className="font-mono text-xs text-[#6b7594]">7 days</p>
              <p className="font-mono text-xs text-[#6b7594] mt-1.5 leading-snug">
                No credit card required
              </p>
            </div>
            <p className="font-mono text-xs text-[#6b7594] mb-4 leading-relaxed">
              Try RegKnot risk-free before you commit. Upgrade any time during the trial.
            </p>
            <ul className="flex flex-col gap-2 mb-6 flex-1">
              {['50 messages during trial', 'Full feature access', 'Upgrade or cancel anytime'].map(p => (
                <li key={p} className="flex items-start gap-2">
                  <svg className="w-3.5 h-3.5 text-[#6b7594] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                  </svg>
                  <span className="font-mono text-sm text-[#f0ece4]/65">{p}</span>
                </li>
              ))}
            </ul>
            {billing?.trial_active ? (
              <div className="text-center">
                <p className="font-mono text-xs text-[#6b7594]">
                  Your free trial is active.
                </p>
              </div>
            ) : showSubscribed ? (
              <div className="text-center">
                <p className="font-mono text-xs text-[#6b7594]">
                  You’re already subscribed.
                </p>
              </div>
            ) : (
              <button
                onClick={handleStartTrial}
                className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                  border border-white/15 text-[#f0ece4]/70 rounded-lg py-3
                  hover:text-[#f0ece4] hover:border-white/30 transition-colors duration-150"
              >
                Start Free Trial
              </button>
            )}
          </div>

          {/* ── Mate ──────────────────────────────────────────────────── */}
          {(['mate', 'captain'] as Tier[]).map((tier) => {
            const display = TIER_DISPLAY[tier]
            const features = TIER_FEATURES[tier]
            const featured = tier === 'captain'
            const plan = resolvePlanKey(tier, interval, hasReferral)
            const isLoading = loading === plan
            const monthlyPrice = hasReferral ? display.monthlyPromo : display.monthly
            const priceShown = interval === 'monthly' ? monthlyPrice : display.annualEq
            const priceSub = interval === 'monthly'
              ? 'per month'
              : `per month, billed $${display.annualTotal.toFixed(2)}/year`
            const savings = hasReferral && interval === 'monthly'
              ? `vs $${display.monthly.toFixed(2)} standard`
              : null
            return (
              <div key={tier} className={`flex flex-col rounded-2xl p-6 border transition-shadow
                ${featured
                  ? 'bg-[#111827] border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]'
                  : 'bg-[#0d1225] border-white/10'
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
                    {savings && (
                      <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1">
                        {savings}
                      </p>
                    )}
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

                {showSubscribed && billing?.tier === tier ? (
                  <div className="text-center">
                    <p className="font-mono text-sm text-[#2dd4bf] font-bold mb-2">
                      You’re on {display.name}
                    </p>
                    <p className="font-mono text-xs text-[#6b7594]">
                      Manage in{' '}
                      <a href="/account" className="text-[#2dd4bf] hover:underline">Account settings</a>.
                    </p>
                  </div>
                ) : (
                  <button
                    onClick={() => handleSubscribeTier(tier)}
                    disabled={!!loading}
                    className={`w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                      rounded-lg py-3 transition-[filter] duration-150
                      disabled:opacity-50 disabled:cursor-not-allowed
                      ${featured
                        ? 'bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110'
                        : 'bg-[#1a2238] text-[#f0ece4] hover:bg-[#232d47] border border-white/10'
                      }`}
                  >
                    {isLoading ? 'Redirecting…' : `Subscribe to ${display.name}`}
                  </button>
                )}
              </div>
            )
          })}
        </div>

        <p className="font-mono text-xs text-[#6b7594] text-center mt-10 max-w-md leading-relaxed">
          Powered by Stripe. Cancel anytime. 10% of every subscription supports
          maritime charities — see{' '}
          <Link href="/giving" className="text-[#2dd4bf] hover:underline">our giving page</Link>.
        </p>

        {/* D6.61 — trust strip, mirroring landing. Security mentioned
            so the buyer scanning for it is satisfied; framing makes
            clear we don't think it deserves a billboard. */}
        <div className="mt-8 max-w-3xl w-full">
          <div className="rounded-xl border border-white/8 bg-[#0a0e1a]/60 px-5 py-4">
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2
              font-mono text-[10px] text-[#6b7594] uppercase tracking-[0.15em]">
              <span>TLS 1.3 in transit</span>
              <span className="text-white/15">·</span>
              <span>AES-256 at rest</span>
              <span className="text-white/15">·</span>
              <span>Zero third-party tracking</span>
              <span className="text-white/15">·</span>
              <span>Your data, your delete button</span>
            </div>
            <p className="font-mono text-[11px] text-[#6b7594] text-center mt-2 italic">
              Security is the floor, not the feature.
            </p>
          </div>
        </div>

        {/* ════════════════════════════════════════════════════════════════════
            Wheelhouse (Sprint D6.57) — separate visual block. Conceptually
            different product (per-vessel, multi-seat) so it lives below the
            individual tiers rather than crammed into the same row.
        ════════════════════════════════════════════════════════════════════ */}
        <div className="w-full max-w-5xl mt-20 md:mt-24">
          <div className="text-center mb-10">
            <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-3">
              For crews
            </p>
            <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
                           text-[clamp(28px,5vw,40px)] mb-3">
              Wheelhouse
            </h2>
            <p className="font-mono text-[#6b7594] text-sm md:text-base max-w-2xl mx-auto leading-relaxed">
              Vessel-anchored workspaces for rotation crews. One subscription per vessel.
              Shared chat, shared dossier, shared rotation handoff notes. Up to 10 seats.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 max-w-3xl mx-auto">
            {/* Monthly */}
            <div className="flex flex-col rounded-2xl p-6 border border-white/10 bg-[#0d1225]">
              <div className="mb-4">
                <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                  Monthly
                </p>
                <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">
                  $99.99
                </p>
                <p className="font-mono text-xs text-[#6b7594]">per month, per vessel</p>
              </div>
              <p className="font-mono text-xs text-[#6b7594] mb-4 leading-relaxed">
                Pay month-to-month. 30-day free trial, no card required.
              </p>
              <ul className="flex flex-col gap-2 mb-6 flex-1">
                {[
                  '10 crew seats',
                  'Shared chat history & vessel dossier',
                  'Rotation handoff notes',
                  'Captain stays Owner; can transfer',
                ].map((perk) => (
                  <li key={perk} className="flex items-start gap-2">
                    <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                    </svg>
                    <span className="font-mono text-sm text-[#f0ece4]/80">{perk}</span>
                  </li>
                ))}
              </ul>
              <a
                href="/workspaces"
                className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                           bg-[#1a2238] text-[#f0ece4] hover:bg-[#232d47]
                           border border-white/10 rounded-lg py-3 transition-colors duration-150"
              >
                Start Free Trial
              </a>
            </div>

            {/* Annual */}
            <div className="flex flex-col rounded-2xl p-6 border bg-[#111827]
                            border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]">
              <div className="flex items-start justify-between gap-3 mb-4">
                <div>
                  <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                    Annual
                  </p>
                  <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">
                    $89.99
                  </p>
                  <p className="font-mono text-xs text-[#6b7594]">
                    per month, billed $1,079.88/yr
                  </p>
                  <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1">
                    Save $120 vs monthly
                  </p>
                </div>
                <span className="font-mono text-[10px] font-bold text-[#2dd4bf] bg-[#2dd4bf]/10
                                 border border-[#2dd4bf]/30 rounded px-2 py-1
                                 uppercase tracking-wider whitespace-nowrap">
                  Best value
                </span>
              </div>
              <p className="font-mono text-xs text-[#6b7594] mb-4 leading-relaxed">
                Best for vessels operating year-round. 30-day free trial, no card required.
              </p>
              <ul className="flex flex-col gap-2 mb-6 flex-1">
                {[
                  '10 crew seats',
                  'Shared chat history & vessel dossier',
                  'Rotation handoff notes',
                  'Captain stays Owner; can transfer',
                ].map((perk) => (
                  <li key={perk} className="flex items-start gap-2">
                    <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                    </svg>
                    <span className="font-mono text-sm text-[#f0ece4]/80">{perk}</span>
                  </li>
                ))}
              </ul>
              <a
                href="/workspaces"
                className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                           bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                           rounded-lg py-3 transition-[filter] duration-150"
              >
                Start Free Trial
              </a>
            </div>
          </div>

          <p className="font-mono text-xs text-[#6b7594] text-center mt-6 max-w-xl mx-auto leading-relaxed">
            Trial gives your crew full access for 30 days. Add a payment method
            anytime; otherwise the workspace becomes read-only on day 31 (90-day
            recovery window before archival).
          </p>
        </div>

        <div className="mt-16 mb-8">
          <CorpusBadges
            heading="What we know"
            subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
          />
        </div>
      </main>

      {/* ── Footer — Sprint D6.90 shared LandingFooter ──────────────── */}
      <LandingFooter />
    </div>
  )
}
