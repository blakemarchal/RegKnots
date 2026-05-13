'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { CorpusBadges } from '@/components/CorpusBadges'
import {
  SeeItInActionSection,
  WhyNotChatGPTSection,
  HallucinationProofSection,
  HowItWorksSection,
  MarinerVaultSection,
} from '@/components/marketing/MarketingSections'
import { LandingFooter } from '@/components/marketing/LandingFooter'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// Sprint D6.3 — Women Offshore donor-recipient landing page.
//
// Routes the visitor to one of two PROMO Stripe prices (25% off the
// standard monthly rate). Annual is shown as a secondary option for
// users who want to commit further. 10% of every subscription that
// originates from this page is donated to Women Offshore — captured
// via the `referral_source` field on the user record (set in
// localStorage here, persisted at checkout, written to DB by the
// billing router). Note: we describe Women Offshore as a non-profit
// we donate to, not as a "partner" — there is no formal partnership
// agreement; we are donors. Same convention applies to all charity-
// linked landing pages (/captainkarynn, /ass, etc.).

// Sprint D6.91 — Cadet ($7.49/mo promo, 25-msg cap) added as the
// entry-level tier on promo pages. Same feature parity as Mate aside
// from the chat-message cap.
type PromoPlan =
  | 'cadet_promo' | 'cadet_annual'
  | 'mate_promo'  | 'mate_annual'
  | 'captain_promo' | 'captain_annual'

const REFERRAL_KEY = 'regknot_referral_source'
const REFERRAL_VALUE = 'womenoffshore'

const PRICING = {
  cadet_promo: {
    label: 'Cadet',
    price: '$7.49',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      '25 messages per month',
      'Full reg corpus (see below)',
      'Vessel profile + chat history',
      'Credential vault with auto-OCR',
      'Renewal alerts (90 / 30 / 7 days)',
      'Study Tools — quiz + study guide generators',
      'All AI Co-Pilots included',
    ],
  },
  mate_promo: {
    label: 'Mate',
    price: '$14.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      'Everything in Cadet, plus:',
      '100 messages per month',
      'AI Renewal Co-Pilot + Career Path',
      'Vessel Analysis + Compliance Changelog',
      'Priority support',
    ],
  },
  captain_promo: {
    label: 'Captain',
    price: '$29.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      'Everything in Mate',
      'Unlimited messages',
      'PSC Co-Pilot + Audit Readiness',
      'USCG sea-service letter generator',
      'Audit-ready chat logs',
    ],
  },
} as const

const ANNUAL_DESCRIPTORS = {
  cadet_annual: {
    label: 'Cadet',
    monthlyEq: '$7.49',
    annualTotal: '$89.88',
    standardMonthly: '$9.99/mo',
  },
  mate_annual: {
    label: 'Mate',
    monthlyEq: '$14.99',
    annualTotal: '$179.88',
    standardMonthly: '$19.99/mo',
  },
  captain_annual: {
    label: 'Captain',
    monthlyEq: '$29.99',
    annualTotal: '$359.88',
    standardMonthly: '$39.99/mo',
  },
} as const

export default function WomenOffshorePage() {
  const { isAuthenticated } = useAuthStore()
  const [loading, setLoading] = useState<PromoPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Capture referral source as soon as the page mounts. We persist this
  // both to localStorage (survives signup detour) and — once authed — to
  // the user record (survives device changes via the backend).
  useEffect(() => {
    try {
      localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
    } catch {
      // localStorage unavailable (private browsing / SSR fallback) — fine.
    }
  }, [])

  async function handleSubscribe(plan: PromoPlan) {
    if (!isAuthenticated) {
      // Persist plan + referral so they survive signup → return-to-checkout.
      try {
        localStorage.setItem('pending_checkout_plan', plan)
        localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
      } catch {}
      window.location.href = '/register?ref=womenoffshore'
      return
    }
    setLoading(plan)
    setError(null)
    try {
      const data = await apiRequest<{ checkout_url: string }>('/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan, referral_source: REFERRAL_VALUE }),
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

  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">
      {/* ── Nav ───────────────────────────────────────────────────────────── */}
      <nav className="fixed top-0 inset-x-0 z-40 flex items-center justify-between
        px-5 md:px-10 py-4 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
        <Link href="/landing" className="flex items-center gap-2">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
            RegKnot
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <Link href="/giving"
            className="hidden md:inline font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Giving Back
          </Link>
          <Link href="/login"
            className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Sign In
          </Link>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative flex flex-col items-center justify-center
        px-5 text-center pt-24 pb-10 md:pb-14 overflow-hidden">

        <div className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: `
              repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px),
              repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px)
            `,
          }}
        />

        <div className="relative z-10 max-w-3xl">
          {/* Women Offshore logo placeholder — drop the asset into
              public/images/womenoffshore-logo.png and swap this. */}
          <div className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-full
            bg-[#2dd4bf]/10 border border-[#2dd4bf]/30">
            <svg className="w-3.5 h-3.5 text-[#2dd4bf]" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 0a8 8 0 100 16A8 8 0 008 0zM4.5 8.5l2.5 2.5 4.5-5L12 7l-5 5.5-3-3 .5-1z"/>
            </svg>
            <span className="font-mono text-xs uppercase tracking-wider text-[#2dd4bf]">
              Supporting Women Offshore
            </span>
          </div>

          <h1 className="font-display font-black text-[#f0ece4] leading-tight
            text-[clamp(36px,7vw,64px)] mb-5">
            Built by mariners.<br/>
            <span className="text-[#2dd4bf]">Backed by community.</span>
          </h1>
          <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed mb-6">
            RegKnot is co-founded by Karynn Marchal (Master Unlimited, active containership Captain)
            and her brother Blake (CTO and engineer) — maritime expertise and engineering, under
            one roof. Every subscription that starts on this page sends 10% directly to{' '}
            <a href="https://womenoffshore.org" target="_blank" rel="noopener noreferrer"
              className="text-[#f0ece4] underline decoration-[#2dd4bf]/40 hover:decoration-[#2dd4bf] transition-colors">
              Women Offshore
            </a>.
          </p>

          <div className="inline-flex items-center gap-2 mb-2 px-3 py-2 rounded-lg
            bg-amber-950/30 border border-amber-800/30">
            <span className="font-mono text-xs uppercase tracking-wider text-amber-400">
              Limited time · 25% off monthly
            </span>
          </div>
        </div>
      </section>

      {/* ── Plans ────────────────────────────────────────────────────────── */}
      <section className="px-5 pb-20">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] text-center mb-3 tracking-wide">
            Pick the plan that fits your watch
          </h2>
          <p className="font-mono text-sm text-[#6b7594] text-center mb-10 max-w-md mx-auto">
            Both promo prices are billed monthly. Cancel anytime.
          </p>

          {error && (
            <p className="font-mono text-xs text-red-400 mb-4 text-center">{error}</p>
          )}

          <div className="grid gap-5 md:grid-cols-3">
            {(['cadet_promo', 'mate_promo', 'captain_promo'] as const).map((plan) => {
              const data = PRICING[plan]
              const featured = plan === 'captain_promo'
              const isLoading = loading === plan
              return (
                <div key={plan} className={`flex flex-col rounded-2xl p-6 border transition-shadow
                  ${featured
                    ? 'bg-[#111827] border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]'
                    : 'bg-[#0d1225] border-white/8'
                  }`}>
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <div>
                      <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                        {data.label}
                      </p>
                      <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">{data.price}</p>
                      <p className="font-mono text-xs text-[#6b7594]">{data.sub}</p>
                      <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1.5 leading-snug">
                        Free trial · No credit card required
                      </p>
                    </div>
                    <span className="font-mono text-[10px] font-bold text-amber-400 bg-amber-950/40
                      border border-amber-800/30 rounded px-2 py-1 uppercase tracking-wider whitespace-nowrap">
                      {data.badge}
                    </span>
                  </div>
                  <ul className="flex flex-col gap-2 mb-6 flex-1">
                    {data.features.map((f) => (
                      <li key={f} className="flex items-start gap-2">
                        <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                        </svg>
                        <span className="font-mono text-sm text-[#f0ece4]/80">{f}</span>
                      </li>
                    ))}
                  </ul>
                  <button
                    onClick={() => handleSubscribe(plan)}
                    disabled={!!loading}
                    className={`w-full text-center font-mono font-bold text-sm uppercase tracking-wider
                      rounded-lg py-3 transition-[filter] duration-150
                      disabled:opacity-50 disabled:cursor-not-allowed
                      ${featured
                        ? 'bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110'
                        : 'border border-white/20 text-[#f0ece4]/70 hover:text-[#f0ece4] hover:border-white/40'
                      }`}
                  >
                    {isLoading ? 'Redirecting…' : `Start free trial · ${data.label}`}
                  </button>
                </div>
              )
            })}
          </div>

          {/* Annual fallback row — more visual weight than a flat row,
              less than the primary promo cards. Gives committed users a
              real choice without distracting from the monthly promo. */}
          <div className="mt-10">
            <p className="font-mono text-xs uppercase tracking-widest text-[#6b7594] text-center mb-4">
              Prefer to commit annually? Lock in the same rate, paid yearly.
            </p>
            <div className="grid gap-4 md:grid-cols-3 max-w-4xl mx-auto">
              {(['cadet_annual', 'mate_annual', 'captain_annual'] as const).map((plan) => {
                const data = ANNUAL_DESCRIPTORS[plan]
                const isLoading = loading === plan
                return (
                  <button
                    key={plan}
                    onClick={() => handleSubscribe(plan)}
                    disabled={!!loading}
                    className="group flex flex-col gap-2 rounded-xl px-5 py-4
                      border border-white/8 hover:border-[#2dd4bf]/40 bg-[#0d1225]
                      hover:bg-[#111827] transition-colors duration-150
                      disabled:opacity-50 disabled:cursor-not-allowed text-left"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide">
                          {data.label} · Annual
                        </p>
                        <p className="font-mono text-2xl font-bold text-[#f0ece4] mt-1">
                          {data.monthlyEq}
                          <span className="font-mono text-xs font-normal text-[#6b7594] ml-1">/mo</span>
                        </p>
                        <p className="font-mono text-xs text-[#6b7594] mt-0.5">
                          Billed {data.annualTotal} / year
                        </p>
                      </div>
                      <span className="font-mono text-[10px] font-bold text-[#2dd4bf] bg-[#2dd4bf]/10
                        border border-[#2dd4bf]/30 rounded px-2 py-1 uppercase tracking-wider whitespace-nowrap">
                        Save 25%
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-2 border-t border-white/5 mt-auto">
                      <span className="font-mono text-xs text-[#6b7594]">
                        vs {data.standardMonthly} standard
                      </span>
                      <span className="font-mono text-xs font-bold text-[#2dd4bf] uppercase tracking-wider
                        group-hover:translate-x-0.5 transition-transform duration-150">
                        {isLoading ? '…' : 'Choose →'}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ── Wheelhouse callout (Sprint D6.57) ──────────────────────────────
          Mentor-captains in the Women Offshore network often pay for crew
          access on their boats — a Wheelhouse covers that case directly.
          One subscription per vessel, up to 10 seats, 30-day free trial. */}
      <section className="px-5 pb-20">
        <div className="max-w-4xl mx-auto">
          <div className="rounded-2xl border border-[#2dd4bf]/30 bg-[#0d1225] p-6 md:p-8">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-5">
              <div className="flex-1">
                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-2">
                  For mentor captains — Wheelhouse
                </p>
                <p className="font-display text-xl md:text-2xl font-bold text-[#f0ece4] mb-2 leading-tight">
                  Cover your whole crew on one subscription.
                </p>
                <p className="font-mono text-xs md:text-sm text-[#6b7594] leading-relaxed">
                  If you&apos;re a mentor captain bringing women officers up
                  through the ranks, Wheelhouse gives your whole rotation
                  shared access — chat history, vessel dossier, and rotation
                  handoff notes that survive when the watch changes.
                  $99.99/month or $89.99/month annually. 30-day free trial,
                  no card required.
                </p>
              </div>
              <Link
                href="/pricing"
                className="font-mono font-bold text-sm uppercase tracking-wider whitespace-nowrap
                           bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                           rounded-lg py-2.5 px-5 transition-[filter] duration-150"
              >
                See Wheelhouse →
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── Sprint D6.72 — shared marketing sections ───────────────────────
          Same wow-factor surface as /landing. Single source of truth in
          @/components/marketing/MarketingSections so any future polish
          to the canonical narrative reaches every entry point. */}
      <SeeItInActionSection />
      <WhyNotChatGPTSection />
      <HallucinationProofSection />
      <HowItWorksSection />
      <MarinerVaultSection />

      {/* ── Corpus badges — what we know ────────────────────────────────── */}
      <section className="px-5 md:px-10 py-20 md:py-28 border-t border-white/5">
        <CorpusBadges
          heading="What we know"
          subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
        />
      </section>

      {/* ── Charity context ─────────────────────────────────────────────── */}
      <section className="px-5 pb-24 bg-[#0a0e1a]">
        <div className="max-w-2xl mx-auto rounded-2xl border border-[#2dd4bf]/30 bg-[#111827] p-7">
          <p className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-3">
            10% to Women Offshore — every subscription, every month
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
            We track every signup that originates from this page. At the close of each month,
            10% of the revenue collected from those subscriptions is sent directly to Women
            Offshore. No middleman, no marketing budget shell game.
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-5">
            RegKnot makes recurring donations to maritime-focused non-profits. Read the
            full giving model on our{' '}
            <Link href="/giving" className="text-[#2dd4bf] hover:underline">Giving Back page</Link>.
          </p>
          {/* Testimonial placeholder — Karynn or Ally to provide. */}
          <blockquote className="font-mono text-sm italic text-[#f0ece4]/70 border-l-2 border-[#2dd4bf]/40 pl-4">
            &ldquo;Testimonial slot — Karynn or Ally quote goes here once provided.&rdquo;
            <footer className="not-italic mt-2 text-xs text-[#6b7594]">— [Attribution]</footer>
          </blockquote>
        </div>
      </section>

      {/* ── Footer — Sprint D6.90 shared LandingFooter ──────────────── */}
      <LandingFooter />
    </div>
  )
}
