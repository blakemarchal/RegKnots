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
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// Sprint D6.13 — "atseastories" personal landing page (route /ass).
//
// @atseastories is a maritime meme Instagram (~21k mariner followers)
// that plugged RegKnot in late April 2026, generating the traffic
// bump that signed our first wave of paid users. The channel operator
// is intentionally anonymous to his followers; this page therefore
// only references the "atseastories" handle and never the operator's
// real name. We're paying him 10% via a private service agreement
// (not advertised on this page).
//
// The URL itself is the running joke (atseastories → /ass). We
// acknowledge it once in the hero and then move on; the body stays in
// the same tone as /captainkarynn but a bit saltier to match the
// channel's meme energy.
//
// Same Stripe promo prices + referral attribution flow as
// /womenoffshore and /captainkarynn. referral_source = 'atseastories'
// so signups from this URL roll up cleanly in the admin partner-tithe
// view.

type PromoPlan = 'mate_promo' | 'captain_promo' | 'mate_annual' | 'captain_annual'

const REFERRAL_KEY = 'regknot_referral_source'
const REFERRAL_VALUE = 'atseastories'

const PRICING = {
  mate_promo: {
    label: 'Mate',
    price: '$14.99',
    sub: 'per month · billed monthly',
    badge: '25% off',
    features: [
      '100 messages per month',
      'Full reg corpus (see below)',
      'Vessel profile + chat history',
      'Credential vault with auto-OCR',
      'Renewal alerts (90 / 30 / 7 days)',
      'AI Renewal Co-Pilot + Career Path',
      'Vessel Analysis + Compliance Changelog',
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

export default function AtSeaStoriesPage() {
  const { isAuthenticated } = useAuthStore()
  const [loading, setLoading] = useState<PromoPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
    } catch {
      // private browsing / SSR — fine
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
          <div className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-full
            bg-[#2dd4bf]/10 border border-[#2dd4bf]/30">
            <svg className="w-3.5 h-3.5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5.5 6.5c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5S15.17 7 16 7s1.5.67 1.5 1.5zM12 17c-2.33 0-4.31-1.46-5.11-3.5h10.22c-.8 2.04-2.78 3.5-5.11 3.5z"/>
            </svg>
            <span className="font-mono text-xs uppercase tracking-wider text-[#2dd4bf]">
              From @atseastories
            </span>
          </div>

          <h1 className="font-display font-black text-[#f0ece4] leading-tight
            text-[clamp(36px,7vw,64px)] mb-5">
            Yeah, the URL is dumb.<br/>
            <span className="text-[#2dd4bf]">The tool isn’t.</span>
          </h1>
          <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed mb-6">
            @atseastories sent you. They run the memes; we run the regulations.
            RegKnot is a chat tool that answers compliance questions with cited paragraphs from
            the whole stack a working mariner actually has to keep straight — IMO conventions,
            U.S. federal regs, USCG circulars, the ERG. No fluff, no fake guarantees.
          </p>

          <div className="inline-flex items-center gap-2 mb-2 px-3 py-2 rounded-lg
            bg-amber-950/30 border border-amber-800/30">
            <span className="font-mono text-xs uppercase tracking-wider text-amber-400">
              atseastories rate · 25% off monthly
            </span>
          </div>
        </div>
      </section>

      {/* ── Personal note ────────────────────────────────────────────────── */}
      <section className="px-5 pb-12">
        <div className="max-w-2xl mx-auto rounded-2xl border border-white/10 bg-[#0d1225] p-7">
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0 w-12 h-12 rounded-full bg-[#2dd4bf]/15
              border border-[#2dd4bf]/30 flex items-center justify-center">
              <span className="font-display text-lg font-bold text-[#2dd4bf]">K</span>
            </div>
            <div className="flex-1">
              <p className="font-display text-sm font-bold text-[#f0ece4] tracking-wide">
                Karynn Marchal
              </p>
              <p className="font-mono text-xs text-[#6b7594] mb-3">
                Master Unlimited · Active Containership Captain · RegKnot Co-founder
              </p>
              <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed mb-3">
                If you’re here from atseastories, hi. They gave us a plug a couple weeks back
                and it brought a wave of you in, which is honestly why this page exists.
                We figured we’d give the crowd a real discount instead of just saying thanks.
              </p>
              <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
                I built RegKnot with my brother because I’m the one who has to actually
                answer when a PSC inspector asks a CFR question I can’t Google fast enough.
                If you’ve ever spent forty minutes finding a regulation paragraph you knew
                existed, give it a try. Free trial, no card up front.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Plans ────────────────────────────────────────────────────────── */}
      <section className="px-5 pb-20">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] text-center mb-3 tracking-wide">
            Pick your watch
          </h2>
          <p className="font-mono text-sm text-[#6b7594] text-center mb-10 max-w-md mx-auto">
            Free trial. No card up front. Cancel anytime.
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

          <div className="mt-10">
            <p className="font-mono text-xs uppercase tracking-widest text-[#6b7594] text-center mb-4">
              Going annual? Same rate, paid yearly.
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

      {/* ── Sprint D6.72 — shared marketing sections ───────────────────────
          Same wow-factor surface as /landing. Single source of truth in
          @/components/marketing/MarketingSections — the meme-page audience
          gets the same proof-of-rigor as everyone else. */}
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

      {/* ── Closing pitch ─────────────────────────────────────────────────
          Lighter close than /captainkarynn — this audience came in via a
          meme page; they don’t need a serious sign-off, just a "we’re
          real, here’s how to find us if it breaks." */}
      <section className="px-5 pb-24 bg-[#0a0e1a]">
        <div className="max-w-2xl mx-auto rounded-2xl border border-[#2dd4bf]/20 bg-[#111827] p-7">
          <p className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-3">
            One more thing
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
            If something doesn’t work the way you expect, tell us. We read every support
            ticket because there are two of us and that’s the entire customer service
            department. Email us through the in-app support page and we’ll see it.
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
            And to whoever runs atseastories — thanks for the plug. Next round’s on us.
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
            — Karynn & Blake
          </p>
        </div>
      </section>
    </div>
  )
}
