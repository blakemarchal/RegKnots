'use client'

// Sprint B — /education landing page.
//
// A persona-targeted landing surface for USCG exam candidates and
// the instructors / training programs that prep them. Leads with
// the Study Tools product (quiz + study guide generators anchored
// on the curated NMC exam pool + the regulations corpus), priced
// at the permanent $14.99 promo Mate rate.
//
// "Permanent promo" mechanics:
//   - This page uses the SAME mate_promo Stripe price ID the charity
//     landing pages use (settings.stripe_price_mate_promo). That price
//     has no expiration on the Stripe side; it's just a separate price
//     object at $14.99/mo. No coupon, no discount code, no clock.
//   - There is no "limited time" badge. The card just shows $14.99/mo.
//
// Persona-targeted UX:
//   - The two CTA buttons split the audience: "I'm a cadet/student"
//     sets pending_persona='cadet_student'; "I'm a teacher/instructor"
//     sets pending_persona='teacher_instructor'. Both subscribe to the
//     same Mate promo plan.
//   - The pending_persona key flows through registration → /onboarding/persona
//     POST so the welcome wizard pre-fills step 0, and the post-onboarding
//     redirect lands them on /study (per the persona-default redirect
//     wired in A5 step 4).
//
// Page is hidden from primary nav; reach via direct link or QR code.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { CorpusBadges } from '@/components/CorpusBadges'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

type EduPersona = 'cadet_student' | 'teacher_instructor'
type EduPlan = 'mate_promo' | 'mate_annual'

const REFERRAL_KEY = 'regknot_referral_source'
const REFERRAL_VALUE = 'education'
const PENDING_PERSONA_KEY = 'pending_persona'

const PERSONA_BLURB: Record<EduPersona, string> = {
  cadet_student:
    'For mariners studying for an MMC, STCW, or upgrade exam. Generate quizzes ' +
    'on the topic you are weak on; review explanations grounded on the CFR.',
  teacher_instructor:
    'For mariner instructors and training program staff. Build quizzes for class, ' +
    'export print-ready PDFs, and let students self-grade with answer keys.',
}

const FEATURES = [
  {
    title: 'USCG-format quizzes',
    body:
      '10 multiple-choice questions per quiz. Vessel-scenario stems, ' +
      'plausible distractors, difficulty mix (3 easy / 5 medium / 2 hard) ' +
      'matching the actual exam-pool format.',
  },
  {
    title: 'Citation-verified answers',
    body:
      'Every correct answer cites a real regulation section. We verify each ' +
      'citation against the corpus before saving — see the green check chips ' +
      'in the answer key.',
  },
  {
    title: 'Study guides with markdown',
    body:
      'Free-text any topic ("MMC renewal", "stability principles") and get ' +
      'a 4-7 section guide with bold key terms, bullet lists, and a ' +
      '"Key Citations" footer.',
  },
  {
    title: 'Take-the-quiz mode',
    body:
      'All 10 questions on one page (USCG paper-exam style). Per-pick autosave ' +
      'so refresh / phone-lock won’t lose progress. Scored on submit; ' +
      '70%+ passing band, color-coded.',
  },
  {
    title: 'Print / Save as PDF',
    body:
      'One click opens a clean print view of any quiz or guide — strip down ' +
      'the colors, add answer key + explanations inline, ready for the printer ' +
      'or Save-as-PDF. Hand out to a class.',
  },
  {
    title: 'Anchored on real corpus',
    body:
      '46 CFR, 33 CFR, COLREGs, SOLAS, STCW, MARPOL, ISM — all loaded into ' +
      'pgvector with semantic + keyword retrieval. Plus the curated NMC exam ' +
      'pool of 244 sections / 2,938 chunks.',
  },
] as const

export default function EducationLanding() {
  const { isAuthenticated } = useAuthStore()
  const [loading, setLoading] = useState<EduPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Capture referral_source on mount so it survives any signup detour.
  useEffect(() => {
    try {
      localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
    } catch {
      // localStorage unavailable (private browsing / SSR fallback) — fine.
    }
  }, [])

  async function handleSubscribe(plan: EduPlan, persona: EduPersona) {
    if (!isAuthenticated) {
      // Persist plan + persona + referral so they survive signup.
      try {
        localStorage.setItem('pending_checkout_plan', plan)
        localStorage.setItem(REFERRAL_KEY, REFERRAL_VALUE)
        localStorage.setItem(PENDING_PERSONA_KEY, persona)
      } catch { /* private browsing — best effort */ }
      window.location.href = '/register?ref=education'
      return
    }
    setLoading(plan)
    setError(null)
    // For authed users, set persona before checkout so post-checkout
    // redirects + the menu visibility rule pick it up.
    try {
      await apiRequest('/onboarding/persona', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona }),
      })
    } catch {
      // Persona update is a soft profile edit — ignore failures so we
      // don't block a paying user from completing checkout.
    }
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
        px-5 text-center pt-28 pb-12 md:pt-32 md:pb-16 overflow-hidden">

        {/* Faint nautical grid backdrop, same vibe as /womenoffshore */}
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
            <svg className="w-3.5 h-3.5 text-[#2dd4bf]" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 1l-7 4 7 4 7-4-7-4zM1 9l7 4 7-4M1 13l7 4 7-4" stroke="currentColor" strokeWidth="1" fill="none"/>
            </svg>
            <span className="font-mono text-xs uppercase tracking-wider text-[#2dd4bf]">
              For mariner students &amp; instructors
            </span>
          </div>

          <h1 className="font-display font-black text-[#f0ece4] leading-tight
            text-[clamp(36px,7vw,64px)] mb-5">
            Pass your USCG exam.<br/>
            <span className="text-[#2dd4bf]">Anchored on the real CFR.</span>
          </h1>

          <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed mb-7">
            Generate USCG-format quizzes and study guides on demand. Every answer
            cites a real regulation. Every citation is verified against our
            46 CFR / 33 CFR / COLREGs / SOLAS / STCW corpus before it lands in
            your library.
          </p>

          {/* Persona-split primary CTAs */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-3">
            <button
              onClick={() => handleSubscribe('mate_promo', 'cadet_student')}
              disabled={!!loading}
              className="font-mono font-bold text-sm uppercase tracking-wider whitespace-nowrap
                bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                rounded-lg py-3 px-6 transition-[filter] duration-150
                disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto"
            >
              I&apos;m a cadet / student &rarr;
            </button>
            <button
              onClick={() => handleSubscribe('mate_promo', 'teacher_instructor')}
              disabled={!!loading}
              className="font-mono font-bold text-sm uppercase tracking-wider whitespace-nowrap
                border border-[#2dd4bf]/40 text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                rounded-lg py-3 px-6 transition-colors duration-150
                disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto"
            >
              I&apos;m a teacher / instructor &rarr;
            </button>
          </div>

          <p className="font-mono text-xs text-[#6b7594]/80 mb-2">
            $14.99 / month, billed monthly. Cancel anytime. Free trial &mdash; no card required.
          </p>
        </div>
      </section>

      {/* ── Feature grid ───────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 pb-16 md:pb-20">
        <div className="max-w-5xl mx-auto">
          <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] text-center mb-10 tracking-wide">
            What&apos;s in the box
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <article key={f.title}
                className="rounded-xl border border-white/8 bg-[#111827] p-5
                  hover:border-[#2dd4bf]/30 transition-colors duration-150">
                <h3 className="font-display text-base font-bold text-[#2dd4bf] tracking-wide mb-2">
                  {f.title}
                </h3>
                <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed">
                  {f.body}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ── Plan card ──────────────────────────────────────────────────── */}
      <section className="px-5 pb-16 md:pb-20">
        <div className="max-w-3xl mx-auto">
          <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] text-center mb-3 tracking-wide">
            One plan. Permanent price.
          </h2>
          <p className="font-mono text-sm text-[#6b7594] text-center mb-10 max-w-md mx-auto">
            $14.99 / month is the rate, full stop. No countdown timer, no expiring
            promo code. Cancel anytime.
          </p>

          {error && (
            <p className="font-mono text-xs text-red-400 mb-4 text-center">{error}</p>
          )}

          {/* Primary monthly card */}
          <div className="rounded-2xl bg-[#111827] border border-[#2dd4bf]/50
            shadow-[0_0_40px_rgba(45,212,191,0.08)] p-6 md:p-8 mb-6">
            <div className="flex items-start justify-between gap-3 mb-5">
              <div>
                <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">
                  Mate &mdash; Education
                </p>
                <p className="font-mono text-4xl font-bold text-[#f0ece4] mt-1">
                  $14.99
                  <span className="font-mono text-base font-normal text-[#6b7594] ml-2">/ month</span>
                </p>
                <p className="font-mono text-xs text-[#6b7594]">Billed monthly</p>
                <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1.5 leading-snug">
                  Free trial &middot; No credit card required
                </p>
              </div>
            </div>
            <ul className="flex flex-col gap-2 mb-6">
              {[
                '200 quiz/guide generations per month',
                'Full Study Tools — quizzes, guides, take-the-quiz mode, PDF export',
                'Citation-verified answers (CFR / SOLAS / COLREGs / STCW)',
                '100 chat messages per month against the full reg corpus',
                'Vessel profile + chat history',
                'Credentials Tracker (MMC, STCW, medical, TWIC) with renewal alerts',
              ].map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                  </svg>
                  <span className="font-mono text-sm text-[#f0ece4]/85">{f}</span>
                </li>
              ))}
            </ul>

            <div className="grid gap-3 sm:grid-cols-2">
              {(['cadet_student', 'teacher_instructor'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => handleSubscribe('mate_promo', p)}
                  disabled={!!loading}
                  className="font-mono font-bold text-sm uppercase tracking-wider
                    bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                    rounded-lg py-3 px-4 transition-[filter] duration-150
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading === 'mate_promo'
                    ? 'Redirecting…'
                    : p === 'cadet_student'
                      ? 'Start as a student'
                      : 'Start as a teacher'}
                </button>
              ))}
            </div>
            <p className="font-mono text-[10px] text-[#6b7594] text-center mt-3 leading-relaxed">
              Same plan either way; the persona just personalizes which tools are
              defaulted in your menu and which post-onboarding home you land on.
            </p>
          </div>

          {/* Annual fallback */}
          <div className="rounded-xl border border-white/8 bg-[#0d1225] p-5">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
              <div>
                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-1">
                  Prefer annual?
                </p>
                <p className="font-display text-lg font-bold text-[#f0ece4]">
                  $14.99 / month, paid yearly
                </p>
                <p className="font-mono text-xs text-[#6b7594] mt-0.5">
                  $179.88 / year &middot; same monthly rate, no surprises
                </p>
              </div>
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => handleSubscribe('mate_annual', 'cadet_student')}
                  disabled={!!loading}
                  className="font-mono text-xs font-bold uppercase tracking-wider
                    border border-white/15 text-[#f0ece4]/80
                    hover:text-[#f0ece4] hover:border-[#2dd4bf]/40
                    rounded-lg py-2 px-4 transition-colors duration-150
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Annual &middot; Student
                </button>
                <button
                  onClick={() => handleSubscribe('mate_annual', 'teacher_instructor')}
                  disabled={!!loading}
                  className="font-mono text-xs font-bold uppercase tracking-wider
                    border border-white/15 text-[#f0ece4]/80
                    hover:text-[#f0ece4] hover:border-[#2dd4bf]/40
                    rounded-lg py-2 px-4 transition-colors duration-150
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Annual &middot; Teacher
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Persona blurbs ─────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 pb-16 md:pb-20 border-t border-white/5">
        <div className="max-w-4xl mx-auto pt-12">
          <div className="grid gap-5 md:grid-cols-2">
            {(Object.keys(PERSONA_BLURB) as EduPersona[]).map((p) => (
              <div key={p}
                className="rounded-xl border border-white/8 bg-[#111827] p-5">
                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-2">
                  {p === 'cadet_student' ? 'For students' : 'For instructors'}
                </p>
                <p className="font-mono text-sm text-[#f0ece4]/85 leading-relaxed">
                  {PERSONA_BLURB[p]}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Sample topics strip ────────────────────────────────────────── */}
      <section className="px-5 md:px-10 pb-16 md:pb-20">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display text-xl md:text-2xl font-bold text-[#f0ece4] text-center mb-3 tracking-wide">
            Topics you can drop in tonight
          </h2>
          <p className="font-mono text-sm text-[#6b7594] text-center mb-8 max-w-lg mx-auto">
            Free-text any topic; these are just starting points.
          </p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[
              'Lifeboat inspection requirements',
              'COLREGs Rule 13 overtaking',
              'Fire pump capacity small passenger vessel',
              'MARPOL Annex VI sulfur ECA',
              'Subchapter M TSMS',
              'Tankerman-PIC endorsement',
              'Engine room watch standing',
              'STCW basic safety training',
              'MMC renewal — what to gather',
              'Stability principles for small passenger vessels',
              'Ballast water management',
              'Hazmat segregation tables (IMDG)',
              'Polar Code crew qualifications',
              'Engineer license endorsement ladder',
              'Sea-service letter — what counts',
            ].map((t) => (
              <span key={t}
                className="font-mono text-xs text-[#6b7594] border border-white/10
                  bg-[#0d1225] rounded-full px-3 py-1.5">
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── Corpus badges ──────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 py-16 md:py-20 border-t border-white/5">
        <CorpusBadges
          heading="What we cite"
          subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
        />
      </section>

      {/* ── Bottom CTA ─────────────────────────────────────────────────── */}
      <section className="px-5 pb-20">
        <div className="max-w-2xl mx-auto rounded-2xl border border-[#2dd4bf]/30 bg-[#111827] p-7 text-center">
          <p className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-2">
            Ready to start?
          </p>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-5">
            $14.99 / month. Free trial. No card required to try the chat;
            you only pay when you subscribe to unlock Study Tools.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={() => handleSubscribe('mate_promo', 'cadet_student')}
              disabled={!!loading}
              className="font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                rounded-lg py-3 px-6 transition-[filter] duration-150
                disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto"
            >
              Start as a student
            </button>
            <button
              onClick={() => handleSubscribe('mate_promo', 'teacher_instructor')}
              disabled={!!loading}
              className="font-mono font-bold text-sm uppercase tracking-wider
                border border-[#2dd4bf]/40 text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                rounded-lg py-3 px-6 transition-colors duration-150
                disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto"
            >
              Start as a teacher
            </button>
          </div>
          <p className="font-mono text-[11px] text-[#6b7594] mt-4">
            Already have an account?{' '}
            <Link href="/login" className="text-[#2dd4bf] hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </div>
  )
}
