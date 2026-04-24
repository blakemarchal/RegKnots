'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// Sprint D6.3 — Women Offshore charity-partner landing page.
//
// Routes the visitor to one of two PROMO Stripe prices (25% off the
// standard monthly rate). Annual is shown as a secondary option for
// users who want to commit further. 10% of every subscription that
// originates from this page is owed to Women Offshore — captured via
// the `referral_source` field on the user record (set in localStorage
// here, persisted at checkout, written to DB by the billing router).

type PromoPlan = 'mate_promo' | 'captain_promo' | 'mate_annual' | 'captain_annual'

const REFERRAL_KEY = 'regknot_referral_source'
const REFERRAL_VALUE = 'womenoffshore'

const PRICING = {
  mate_promo: {
    label: 'Mate',
    price: '$14.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      '100 messages per month',
      'CFR 33 / 46 / 49, SOLAS, COLREGs, NVICs, STCW, ISM, ERG',
      '46 USC + WHO IHR (port health & seamen\u2019s law)',
      'Vessel profile + chat history',
    ],
  },
  captain_promo: {
    label: 'Captain',
    price: '$29.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      'Unlimited messages',
      'Everything in Mate',
      'Priority regulation update notifications',
      'Audit-ready chat logs',
      'PSC checklist builder & sea-service letters',
    ],
  },
} as const

const ANNUAL_DESCRIPTORS = {
  mate_annual:    { label: 'Mate (annual)',    sub: '$14.99/mo · billed $179.88/year' },
  captain_annual: { label: 'Captain (annual)', sub: '$29.99/mo · billed $359.88/year' },
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
      <section className="relative flex flex-col items-center justify-center min-h-[80vh]
        px-5 text-center pt-24 pb-16 overflow-hidden">

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
              Women Offshore Partner
            </span>
          </div>

          <h1 className="font-display font-black text-[#f0ece4] leading-tight
            text-[clamp(36px,7vw,64px)] mb-5">
            Built by mariners.<br/>
            <span className="text-[#2dd4bf]">Backed by community.</span>
          </h1>
          <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed mb-8">
            RegKnot is a maritime compliance co-pilot built by a containership Master and her engineer
            brother. Every subscription that starts on this page sends 10% directly to{' '}
            <a href="https://womenoffshore.org" target="_blank" rel="noopener noreferrer"
              className="text-[#f0ece4] underline decoration-[#2dd4bf]/40 hover:decoration-[#2dd4bf] transition-colors">
              Women Offshore
            </a>.
            Use the codeless link below — discount applies automatically.
          </p>

          <div className="inline-flex items-center gap-2 mb-8 px-3 py-2 rounded-lg
            bg-amber-950/30 border border-amber-800/30">
            <span className="font-mono text-xs uppercase tracking-wider text-amber-400">
              Limited time · 25% off monthly · 10% to Women Offshore
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

          <div className="grid gap-5 md:grid-cols-2">
            {(['mate_promo', 'captain_promo'] as const).map((plan) => {
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

          {/* Annual fallback row */}
          <div className="mt-8 grid gap-3 md:grid-cols-2 max-w-3xl mx-auto">
            {(['mate_annual', 'captain_annual'] as const).map((plan) => {
              const data = ANNUAL_DESCRIPTORS[plan]
              const isLoading = loading === plan
              return (
                <button
                  key={plan}
                  onClick={() => handleSubscribe(plan)}
                  disabled={!!loading}
                  className="flex items-center justify-between gap-3 px-4 py-3 rounded-lg
                    border border-white/8 hover:border-white/20 bg-[#0d1225] transition-colors duration-150
                    disabled:opacity-50 disabled:cursor-not-allowed text-left"
                >
                  <div>
                    <p className="font-mono text-sm font-bold text-[#f0ece4]">{data.label}</p>
                    <p className="font-mono text-xs text-[#6b7594] mt-0.5">{data.sub}</p>
                  </div>
                  <span className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider">
                    {isLoading ? '…' : 'Choose →'}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── Sample answer / proof ───────────────────────────────────────── */}
      <section className="px-5 pb-20 bg-[#0a0e1a]">
        <div className="max-w-3xl mx-auto">
          <h2 className="font-display text-2xl font-bold text-[#f0ece4] text-center mb-2 tracking-wide">
            Cited answers, not summaries
          </h2>
          <p className="font-mono text-sm text-[#6b7594] text-center mb-8 max-w-md mx-auto">
            Every answer references the specific regulation paragraph it came from — so you can
            verify before you act.
          </p>

          <div className="rounded-2xl border border-white/8 bg-[#0d1225] p-6">
            <p className="font-mono text-xs text-[#6b7594] mb-3 uppercase tracking-wider">
              Question · COLREGs Rule 13
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/90 leading-relaxed mb-4">
              \u201cI\u2019m overtaking another vessel at night — what light configuration tells me
              they\u2019re a power-driven vessel longer than 50 meters underway?\u201d
            </p>
            <div className="border-t border-white/8 pt-4">
              <p className="font-mono text-xs text-[#6b7594] mb-3 uppercase tracking-wider">
                RegKnot answer
              </p>
              <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
                A power-driven vessel of 50 meters or more underway shall exhibit a forward masthead
                light, a second masthead light abaft of and higher than the forward one, sidelights,
                and a sternlight{' '}
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
                  bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none">
                  COLREGs Rule 23(a)
                </span>
                . As the overtaking vessel under{' '}
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
                  bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none">
                  COLREGs Rule 13
                </span>
                , you are the give-way vessel and must keep clear.
              </p>
            </div>
          </div>
        </div>
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
            RegKnot also partners with maritime charities more broadly — Mercy Ships, Waves of
            Impact, and Elijah Rising. Read the full giving model on our{' '}
            <Link href="/giving" className="text-[#2dd4bf] hover:underline">Giving Back page</Link>.
          </p>
          {/* Testimonial placeholder — Karynn or Ally to provide. */}
          <blockquote className="font-mono text-sm italic text-[#f0ece4]/70 border-l-2 border-[#2dd4bf]/40 pl-4">
            &ldquo;Testimonial slot — Karynn or Ally quote goes here once provided.&rdquo;
            <footer className="not-italic mt-2 text-xs text-[#6b7594]">— [Attribution]</footer>
          </blockquote>
        </div>
      </section>
    </div>
  )
}
