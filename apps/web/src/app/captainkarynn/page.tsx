'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { CorpusBadges } from '@/components/CorpusBadges'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// Sprint D6.9 — "Captain Karynn's invite" personal landing page.
//
// Same promo Stripe prices as /womenoffshore but reframed as a private
// invite from Karynn. No charity tithe — this is Karynn's personal share
// link to give to her network. Psychology: lower the price barrier AND
// make recipients feel chosen. The page is intentionally distributable
// (the URL itself is the only gate); the warm framing does the work.
//
// Referral attribution flows the same way as /womenoffshore:
//   - localStorage `regknot_referral_source` set on mount
//   - register page reads it, sends to backend on signup
//   - billing/checkout passes it through to the user record
// Admin can later filter MRR / signup volume by referral_source =
// 'captainkarynn' to gauge how this channel performs.

type PromoPlan = 'mate_promo' | 'captain_promo' | 'mate_annual' | 'captain_annual'

const REFERRAL_KEY = 'regknot_referral_source'
const REFERRAL_VALUE = 'captainkarynn'

const PRICING = {
  mate_promo: {
    label: 'Mate',
    price: '$14.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      '100 messages per month',
      'Full reg corpus — IMO conventions, U.S. CFR + USC, USCG circulars, ERG (see below)',
      '46 USC + WHO IHR (port health & seamen’s law)',
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

// Same sample-answer carousel as /womenoffshore — keep the demo identical
// so we don't fragment the "show the product" content. If we update the
// canonical demo later, both pages should track together; consider
// extracting to a shared component when a third page wants the same.
const SAMPLE_ANSWERS: Array<{
  sourceTag: string
  question: string
  answer: string
}> = [
  {
    sourceTag: 'COLREGs Rule 13',
    question: 'I’m overtaking another vessel at night — what light configuration tells me they’re a power-driven vessel longer than 50 meters underway?',
    answer: 'A power-driven vessel of 50 meters or more underway shall exhibit a forward masthead light, a second masthead light abaft of and higher than the forward one, sidelights, and a sternlight {citation: COLREGs Rule 23(a)}. As the overtaking vessel under {citation: COLREGs Rule 13}, you are the give-way vessel and must keep clear.',
  },
  {
    sourceTag: '46 CFR 199.175',
    question: 'How many parachute flares does my lifeboat need to carry?',
    answer: 'For a containership operating internationally, each lifeboat must carry 4 rocket parachute flares per {citation: 46 CFR 199.175}. SOLAS-equipped vessels follow the equivalent {citation: SOLAS Ch.III LSA Code 4.4} which mandates the same 4 rocket parachute flares per lifeboat.',
  },
  {
    sourceTag: 'NVIC 04-08',
    question: 'My MMC medical certificate expires in two weeks but I’m stuck overseas — what are my options?',
    answer: 'Per {citation: NVIC 04-08 Ch-2}, a mariner whose medical certificate expires while at sea may continue to serve until reaching the next port where renewal is practical, provided you apply through the {citation: NMC} as soon as you’re able. Document the circumstances in your logbook for any subsequent inspection.',
  },
  {
    sourceTag: 'WHO IHR Annex 3',
    question: 'When does my Ship Sanitation Control Certificate need to be renewed?',
    answer: 'Per {citation: WHO IHR Annex 3}, the Ship Sanitation Control Certificate is valid for six months from the date of issue. Renewal must occur at any port equipped to issue SSCCs — typically a designated port of entry of a State Party to the IHR. The certificate is the modern replacement for the legacy "deratting certificate."',
  },
  {
    sourceTag: '46 USC 11103',
    question: 'Is a vessel on a foreign voyage required to have a slop chest, and what does it need to contain?',
    answer: 'Per {citation: 46 USC 11103}, a vessel on a voyage of more than 78 hours from a U.S. port to a foreign port (other than to Canada or the West Indies) must carry a slop chest containing sufficient clothing, including boots/shoes, hats, underclothing, outer clothing, foul-weather gear, and tobacco — sufficient for the intended voyage of each seaman.',
  },
]

function renderAnswerWithChips(text: string): React.ReactNode {
  const parts = text.split(/\{citation: ([^}]+)\}/)
  return parts.map((part, i) => {
    if (i % 2 === 0) return <span key={i}>{part}</span>
    return (
      <span
        key={i}
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
          bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none mx-0.5"
      >
        {part}
      </span>
    )
  })
}

function SampleAnswerCarousel() {
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused) return
    const handle = window.setInterval(() => {
      setIndex(i => (i + 1) % SAMPLE_ANSWERS.length)
    }, 7000)
    return () => window.clearInterval(handle)
  }, [paused])

  const current = SAMPLE_ANSWERS[index]

  return (
    <section className="px-5 pb-20 bg-[#0a0e1a]">
      <div className="max-w-3xl mx-auto">
        <h2 className="font-display text-2xl font-bold text-[#f0ece4] text-center mb-2 tracking-wide">
          Cited answers, not summaries
        </h2>
        <p className="font-mono text-sm text-[#6b7594] text-center mb-8 max-w-md mx-auto">
          Every answer references the specific regulation paragraph it came from — so you can
          verify before you act.
        </p>

        <div
          className="rounded-2xl border border-white/8 bg-[#0d1225] p-6 transition-opacity duration-300 min-h-[260px]"
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
        >
          <p className="font-mono text-xs text-[#6b7594] mb-3 uppercase tracking-wider">
            Question · {current.sourceTag}
          </p>
          <p className="font-mono text-sm text-[#f0ece4]/90 leading-relaxed mb-4">
            “{current.question}”
          </p>
          <div className="border-t border-white/8 pt-4">
            <p className="font-mono text-xs text-[#6b7594] mb-3 uppercase tracking-wider">
              RegKnot answer
            </p>
            <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
              {renderAnswerWithChips(current.answer)}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-center gap-2 mt-5">
          {SAMPLE_ANSWERS.map((_, i) => (
            <button
              key={i}
              onClick={() => { setIndex(i); setPaused(true) }}
              aria-label={`Show example ${i + 1}`}
              className={`h-1.5 rounded-full transition-all duration-200
                ${i === index
                  ? 'w-8 bg-[#2dd4bf]'
                  : 'w-1.5 bg-white/15 hover:bg-white/30'
                }`}
            />
          ))}
        </div>
        <p className="font-mono text-[10px] uppercase tracking-widest text-[#6b7594] text-center mt-3">
          {index + 1} of {SAMPLE_ANSWERS.length}
          {paused && <span className="ml-2 text-[#2dd4bf]/60">paused</span>}
        </p>
      </div>
    </section>
  )
}

const ANNUAL_DESCRIPTORS = {
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

export default function CaptainKarynnPage() {
  const { isAuthenticated } = useAuthStore()
  const [loading, setLoading] = useState<PromoPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Capture referral on mount — survives signup detour via localStorage,
  // gets persisted to user record at first checkout.
  useEffect(() => {
    try {
      localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
    } catch {
      // Private browsing / SSR — fine.
    }
  }, [])

  async function handleSubscribe(plan: PromoPlan) {
    if (!isAuthenticated) {
      try {
        localStorage.setItem('pending_checkout_plan', plan)
        localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
      } catch {}
      window.location.href = `/register?ref=${REFERRAL_VALUE}`
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
          {/* "From Captain Karynn" badge — personal, warm, distinct from
              the WomenOffshore charity badge. */}
          <div className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-full
            bg-[#2dd4bf]/10 border border-[#2dd4bf]/30">
            <svg className="w-3.5 h-3.5 text-[#2dd4bf]" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 0L9.8 5.5h5.7l-4.6 3.4 1.8 5.6L8 11l-4.7 3.5 1.8-5.6L0.5 5.5h5.7L8 0z"/>
            </svg>
            <span className="font-mono text-xs uppercase tracking-wider text-[#2dd4bf]">
              From Captain Karynn
            </span>
          </div>

          <h1 className="font-display font-black text-[#f0ece4] leading-tight
            text-[clamp(36px,7vw,64px)] mb-5">
            You’re in.<br/>
            <span className="text-[#2dd4bf]">Welcome aboard.</span>
          </h1>
          <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed mb-6">
            Karynn shared this with you for a reason — RegKnot is the regulatory co-pilot
            she actually uses on her containership. The link you got is a private invite with
            her promo pricing baked in. No promo code to remember, no expiration to track.
          </p>

          <div className="inline-flex items-center gap-2 mb-2 px-3 py-2 rounded-lg
            bg-amber-950/30 border border-amber-800/30">
            <span className="font-mono text-xs uppercase tracking-wider text-amber-400">
              Karynn’s rate · 25% off monthly
            </span>
          </div>
        </div>
      </section>

      {/* ── Karynn's note ─────────────────────────────────────────────────
          Personal voice — lowers the friction of "is this another SaaS
          pitch?" and makes the reader feel like they're getting a real
          recommendation from a real captain. Copy is editable inline; if
          Karynn wants to refine it, swap the string here. */}
      <section className="px-5 pb-12">
        <div className="max-w-2xl mx-auto rounded-2xl border border-white/10 bg-[#0d1225] p-7">
          <div className="flex items-start gap-4">
            {/* Avatar slot — drop public/images/karynn-avatar.jpg in and
                this becomes a real headshot. Until then, an initial. */}
            <div className="flex-shrink-0 w-12 h-12 rounded-full bg-[#2dd4bf]/15
              border border-[#2dd4bf]/30 flex items-center justify-center">
              <span className="font-display text-lg font-bold text-[#2dd4bf]">K</span>
            </div>
            <div className="flex-1">
              <p className="font-display text-sm font-bold text-[#f0ece4] tracking-wide">
                Karynn Marchal
              </p>
              <p className="font-mono text-xs text-[#6b7594] mb-3">
                Master Unlimited · Active Containership Captain
              </p>
              <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
                I built RegKnot with my brother because I was tired of CFR-diving on a deadline.
                If I shared this link with you, it’s because I think it’ll make your job
                easier too. The promo pricing is my way of saying thanks for trying it.
              </p>
            </div>
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
            Free trial. No credit card up front. Cancel anytime.
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

          {/* Annual fallback row — committed users get the same monthly
              rate paid yearly. Keep the visual hierarchy below the
              primary monthly cards so it doesn't pull focus. */}
          <div className="mt-10">
            <p className="font-mono text-xs uppercase tracking-widest text-[#6b7594] text-center mb-4">
              Prefer to commit annually? Lock in the same rate, paid yearly.
            </p>
            <div className="grid gap-4 md:grid-cols-2 max-w-3xl mx-auto">
              {(['mate_annual', 'captain_annual'] as const).map((plan) => {
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

      {/* ── Sample answers carousel ───────────────────────────────────── */}
      <SampleAnswerCarousel />

      {/* ── Corpus badges — what we know ────────────────────────────────── */}
      <section className="px-5 pb-20 bg-[#0a0e1a]">
        <CorpusBadges
          heading="What we know"
          subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
        />
      </section>

      {/* ── Closing personal pitch ─────────────────────────────────────────
          Replaces the WomenOffshore tithe section. Soft close — reinforces
          the personal angle without being saccharine. */}
      <section className="px-5 pb-24 bg-[#0a0e1a]">
        <div className="max-w-2xl mx-auto rounded-2xl border border-[#2dd4bf]/20 bg-[#111827] p-7">
          <p className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-3">
            One last thing
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
            If you sign up and something doesn’t work the way you expect, tell me. The
            product gets better when mariners actually use it. Email me directly through the
            in-app support page and I’ll see it.
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
            — Karynn
          </p>
        </div>
      </section>
    </div>
  )
}
