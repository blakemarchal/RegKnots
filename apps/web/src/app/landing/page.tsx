'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { ContactModal } from '@/components/ContactModal'
import { CorpusBadges } from '@/components/CorpusBadges'
import { EmailComposeButton } from '@/components/EmailComposeButton'
import { GuestAsk } from '@/components/GuestAsk'
import {
  DemoCarousel,
  BuiltByMarinersSection,
  WhyNotChatGPTSection,
  HallucinationProofSection,
  MarinerVaultSection,
} from '@/components/marketing/MarketingSections'
import { LandingFooter } from '@/components/marketing/LandingFooter'
import { SiteNav, START_FREE_LABEL } from '@/components/marketing/SiteNav'

// Sprint D6.76 — DemoCarousel + DEMOS data + the four wow-factor section
// components (BuiltByMariners, WhyNotChatGPT, HallucinationProof,
// HowItWorks, MarinerVault) plus the StaticChip primitive all moved to
// @/components/marketing/MarketingSections in D6.72 so the three referral
// pages (/captainkarynn, /womenoffshore, /ass) could share them. /landing
// kept inline copies as a duplication smell. This commit closes that —
// landing now imports from the same module, eliminating drift risk and
// shrinking this file by ~700 lines. PricingCard is retained inline
// because it's landing-specific (the referral pages have their own
// promo-pricing variant).

// ── Pricing card ──────────────────────────────────────────────────────────────
function PricingCard({
  name, price, priceSub, badge, features, smallPrint, subNote, cta, featured,
}: {
  name: string
  price: string
  priceSub: string
  badge?: string
  features: string[]
  smallPrint?: string
  subNote?: string
  cta: string
  featured?: boolean
}) {
  return (
    <div className={`relative flex flex-col rounded-2xl p-6 border transition-shadow
      ${featured
        ? 'bg-[#111827] border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]'
        : 'bg-[#0d1225] border-white/8'
      }`}>
      {/* 2026-10-16 UI pass — the badge sits on the card's top border, so it can't
          overflow a narrow card (it used to share a row with the price). */}
      {badge && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 font-mono text-[10px] font-bold
          text-[#2dd4bf] bg-[#0a0e1a] border border-[#2dd4bf]/50 rounded-full px-3 py-1
          uppercase tracking-wider whitespace-nowrap">
          {badge}
        </span>
      )}
      <div className="mb-4">
        <div>
          <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">{name}</p>
          <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">{price}</p>
          <p className="font-mono text-xs text-[#6b7594]">{priceSub}</p>
          {subNote && (
            <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1 leading-snug">{subNote}</p>
          )}
        </div>
      </div>

      <ul className="flex flex-col gap-2 mb-6 flex-1">
        {features.map(f => (
          <li key={f} className="flex items-start gap-2">
            <svg className="w-3.5 h-3.5 text-[#2dd4bf] mt-0.5 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor">
              <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
            </svg>
            <span className="font-mono text-sm text-[#f0ece4]/80">{f}</span>
          </li>
        ))}
      </ul>

      {smallPrint && (
        <p className="font-mono text-[11px] text-[#6b7594] mb-4 leading-relaxed">{smallPrint}</p>
      )}

      <Link
        href="/register"
        className={`block text-center font-mono font-bold text-sm uppercase tracking-wider
          rounded-lg py-3 transition-[filter] duration-150
          ${featured
            ? 'bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110'
            : 'border border-white/20 text-[#f0ece4]/70 hover:text-[#f0ece4] hover:border-white/40'
          }`}
      >
        {cta}
      </Link>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
// 2026-10-16 UI pass — hero rebuilt: the headline renders at once (it faded in
// over 1.5 s), the demo answer sits beside it as the product visual (it was the
// fourth section down), and the free question follows in its own row. The old
// hero ran past the screen on laptops, so its tagline and scroll arrow
// overlapped the free-question card. A strip of checkable facts follows;
// "How it works" and the second demo section are gone from this page.

const PROOF: { big: string; small: string; href?: string }[] = [
  { big: 'Master Unlimited', small: 'Co-founded by a USCG-licensed containership captain' },
  { big: '77 sources', small: 'CFR, NVICs, Coast Guard policy, IMO conventions and resolutions' },
  { big: '14 flag states', small: 'UK, Liberia, Marshall Islands, Singapore, Norway and more' },
  { big: '1,100+ pages', small: 'Free plain-English guides to the most-asked regulations', href: '/regs' },
]

export default function LandingPage() {
  const [plan, setPlan] = useState<'monthly' | 'annual'>('monthly')
  const [contactOpen, setContactOpen] = useState(false)

  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">

      <SiteNav />

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 1 — HERO: promise + demo answer, then the free question
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="relative px-5 md:px-10 pt-24 md:pt-28 pb-16 md:pb-24 overflow-hidden">

        {/* Chart grid background */}
        <div className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: `
              repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px),
              repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px)
            `,
          }}
        />
        <div className="absolute -top-24 -left-24 w-[520px] h-[520px] rounded-full pointer-events-none"
          style={{ background: 'radial-gradient(circle, rgba(45,212,191,0.07) 0%, transparent 70%)' }}
        />

        <div className="relative max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-x-14 gap-y-12 items-center">
          <div className="order-1 text-center lg:text-left">
            <p className="inline-flex items-center gap-2 font-mono text-[11px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-5">
              <CompassRose className="w-4 h-4 animate-[compassSpin_60s_linear_infinite]" />
              Built by a USCG Master Unlimited
            </p>
            <h1 className="font-display font-black text-[#f0ece4] leading-[0.95] tracking-tight
              text-[clamp(46px,6.4vw,80px)]">
              {/* nowrap: phones split "Co-" / "Pilot." */}
              Your Compliance <span className="whitespace-nowrap">Co-Pilot.</span><br />Always On Watch.
            </h1>
            <p className="font-mono text-[#8a94ad] mt-6 max-w-xl mx-auto lg:mx-0 leading-relaxed text-base md:text-lg">
              Answers from the regulation text itself: the CFR and Coast Guard guidance, the IMO conventions
              and 14 flag states. Scoped to your vessel, with every requirement cited.
            </p>
            <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-3 mt-8">
              <Link href="/register"
                className="w-full max-w-xs sm:w-auto text-center font-mono font-bold text-sm uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3 hover:brightness-110 transition-[filter] duration-150">
                {START_FREE_LABEL}
              </Link>
              <a href="#ask"
                className="w-full max-w-xs sm:w-auto text-center font-mono font-bold text-sm uppercase tracking-wider
                  border border-[#2dd4bf]/50 text-[#2dd4bf] rounded-xl px-6 py-3
                  hover:border-[#2dd4bf] hover:bg-[#2dd4bf]/5 transition-colors duration-150">
                Ask a question free
              </a>
            </div>
            <p className="font-mono text-[11px] text-[#6b7594] mt-4 tracking-wide">
              7-day trial, then 10 free questions every 30 days · No credit card
            </p>
          </div>

          <div className="order-3 lg:order-2 animate-[heroFadeUp_0.6s_ease-out_0.1s]" style={{ animationFillMode: 'both' }}>
            <DemoCarousel />
          </div>

          {/* 2026-10-14 — one free question before signup (components/GuestAsk.tsx).
              Renders nothing until Turnstile keys and the API flag are on. */}
          <div id="ask" className="order-2 lg:order-3 lg:col-span-2 scroll-mt-20">
            <GuestAsk page="landing" heading="Ask your first question"
              placeholder="For example: Does my towing vessel need a TSMS, and what goes in it?"
              outerClassName="max-w-3xl mx-auto w-full" />
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 2 — PROOF: facts a visitor can check
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="border-y border-white/5 bg-[#0d1225]/60 px-5 md:px-10 py-10 md:py-12">
        <dl className="max-w-6xl mx-auto grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-8 text-center lg:text-left">
          {PROOF.map((p) => {
            const body = (
              <>
                <dt className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] tracking-wide">{p.big}</dt>
                <dd className="font-mono text-xs text-[#6b7594] mt-1.5 leading-relaxed">
                  {p.small}{p.href && <span className="text-[#2dd4bf]"> →</span>}
                </dd>
              </>
            )
            return p.href ? (
              <Link key={p.big} href={p.href} className="block rounded-lg hover:bg-white/[0.02] transition-colors">{body}</Link>
            ) : (
              <div key={p.big}>{body}</div>
            )
          })}
        </dl>
      </section>

      <WhyNotChatGPTSection />

      <HallucinationProofSection />

      <BuiltByMarinersSection />

      <MarinerVaultSection />

{/* ══════════════════════════════════════════════════════════════════════
          SECTION 5 — CORPUS BADGES — what's in the index
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="px-5 md:px-10 py-20 md:py-28 border-t border-white/5">
        <CorpusBadges
          heading="What we know"
          subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
        />
      </section>

{/* ══════════════════════════════════════════════════════════════════════
          SECTION 6 — PRICING
      ══════════════════════════════════════════════════════════════════════ */}
      <section id="pricing" className="px-5 md:px-10 py-20 md:py-28 scroll-mt-16">
        {/* 2026-10-16 UI pass — max-w-6xl (was 3xl): four cards in 768 px left
            ~180 px each, so every line wrapped and the badges overflowed. */}
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
              text-[clamp(28px,5vw,48px)]">
              Simple pricing. No surprises.
            </h2>
            <p className="font-mono text-[#6b7594] mt-3 text-sm md:text-base">
              Built for working mariners, not corporate procurement.
            </p>

            {/* Monthly / Annual toggle */}
            <div className="flex items-center justify-center mt-6">
              <div className="flex items-center gap-1 bg-[#111827] rounded-full p-1 border border-white/8">
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
                    Save 25%
                  </span>
                </button>
              </div>
            </div>
          </div>

          {/* Sprint D6.91 — Cadet ($9.99/mo, 25-msg cap) inserted as the
              entry-level paid option. Grid bumped from 3 to 4 columns on
              lg+ screens; 2-up on md; stacked on mobile so each card
              keeps breathing room. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-x-5 gap-y-8 pt-3">
            <PricingCard
              name="Free"
              price="$0"
              priceSub="7-day trial, then free"
              features={[
                '7-day trial: 50 messages, full access',
                'Then 10 free questions every 30 days',
                'Free USCG exam practice',
                'Upgrade or cancel anytime',
              ]}
              smallPrint="No credit card required to start."
              cta={START_FREE_LABEL}
            />
            <PricingCard
              name="Cadet"
              price={plan === 'monthly' ? '$9.99' : '$7.49'}
              priceSub={plan === 'monthly' ? 'per month' : 'per month, billed $89.88/year'}
              badge="New"
              features={[
                '25 messages per month',
                'Full reg corpus (see above)',
                'Vessel profile + chat history',
                'Credential vault with auto-OCR',
                'Renewal alerts (90 / 30 / 7 days)',
                'Study Tools — quiz + study guide generators',
              ]}
              cta="Subscribe to Cadet"
            />
            <PricingCard
              name="Mate"
              price={plan === 'monthly' ? '$19.99' : '$14.99'}
              priceSub={plan === 'monthly' ? 'per month' : 'per month, billed $179.88/year'}
              features={[
                '100 messages per month',
                'Everything in Cadet',
                'AI Renewal Co-Pilot + Career Path',
                'Vessel Analysis + Compliance Changelog',
                'Priority support',
                'Cited regulation answers, not summaries',
              ]}
              cta="Subscribe to Mate"
            />
            <PricingCard
              name="Captain"
              price={plan === 'monthly' ? '$39.99' : '$29.99'}
              priceSub={plan === 'monthly' ? 'per month' : 'per month, billed $359.88/year'}
              badge="Most popular"
              features={[
                'Unlimited messages',
                'Everything in Mate',
                'Priority regulation update notifications',
                'Audit-ready chat logs',
                'USCG sea-service letter generator',
                'PSC checklist builder',
              ]}
              cta="Subscribe to Captain"
              featured
            />
          </div>

          {/* D6.61 — trust strip. Security is table stakes; we mention the
              controls so the buyer who scans for them is satisfied, then frame
              security as the floor, not the brochure.
              2026-10-16 UI pass — "AES-256 at rest" came out: DigitalOcean
              documents at-rest encryption for Volumes and Spaces, not for the
              Droplet disk the database lives on. Every item here is true. */}
          <div className="mt-10 max-w-3xl mx-auto">
            <div className="rounded-xl border border-white/8 bg-[#0a0e1a]/60 px-5 py-4">
              <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2
                font-mono text-[10px] text-[#6b7594] uppercase tracking-[0.15em]">
                <span>Encrypted in transit</span>
                <span className="text-white/15">·</span>
                <span>Argon2-hashed passwords</span>
                <span className="text-white/15">·</span>
                <span>No tracking cookies</span>
                <span className="text-white/15">·</span>
                <span>Your data, your delete button</span>
              </div>
              <p className="font-mono text-[11px] text-[#6b7594] text-center mt-2 italic">
                Security is the floor, not the feature.
              </p>
            </div>
          </div>

          {/* D6.57 — Wheelhouse callout. Conceptually different (per-vessel,
              multi-seat, 30-day no-card trial) so it lives below the personal
              tiers as a "for crews" upsell rather than crammed into the
              same row. Links to /pricing for the detailed Wheelhouse cards. */}
          <div className="mt-8 max-w-3xl mx-auto rounded-2xl border border-[#2dd4bf]/30 bg-[#0d1225] p-6 md:p-7">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-5">
              <div className="flex-1">
                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-2">
                  For crews — Wheelhouse
                </p>
                <p className="font-display text-xl md:text-2xl font-bold text-[#f0ece4] mb-2 leading-tight">
                  One vessel. Up to 10 crew. Shared chat, dossier, and rotation handoff.
                </p>
                <p className="font-mono text-xs md:text-sm text-[#6b7594] leading-relaxed">
                  $99.99/month or $89.99/month billed annually ($1,079.88/yr).
                  30-day free trial — no card required.
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

          <p className="font-mono text-xs text-[#6b7594] text-center mt-6">
            Fleet pricing available.{' '}
            <button
              type="button"
              onClick={() => setContactOpen(true)}
              className="text-[#2dd4bf] hover:underline font-mono"
            >
              Contact us
            </button>
            {' '}or email{' '}
            <EmailComposeButton
              mode="address"
              recipient="hello@regknots.com"
              buttonClassName="text-[#2dd4bf] hover:underline"
              buttonChildren="hello@regknots.com"
            />
          </p>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 6 — GIVING BACK
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="py-16 px-5 md:px-10 border-t border-white/5">
        <div className="max-w-3xl mx-auto text-center">
          <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-widest mb-3">
            Giving Back
          </p>
          <h2 className="font-display font-black text-[#f0ece4] text-2xl md:text-3xl mb-4">
            10% of Every Dollar Goes to Charity
          </h2>
          <p className="font-mono text-sm text-[#6b7594] mb-6 max-w-lg mx-auto">
            Your subscription supports Mercy Ships, Waves of Impact, and Elijah Rising &mdash;
            organizations making a real difference in maritime communities and beyond.
          </p>
          <Link
            href="/giving"
            className="font-mono text-sm text-[#2dd4bf] hover:underline"
          >
            Learn more about our giving &rarr;
          </Link>
        </div>
      </section>

      {/* 2026-10-16 UI pass — closing call to action, so the long page ends
          on the two things a visitor can do. */}
      <section className="px-5 md:px-10 py-16 md:py-20 border-t border-white/5">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight text-[clamp(28px,5vw,44px)]">
            Your first cited answer is a minute away.
          </h2>
          <p className="font-mono text-sm md:text-base text-[#6b7594] mt-3">
            Free to start, no card. Your vessel, your regulations, every requirement cited.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3 mt-7">
            <Link href="/register"
              className="font-mono font-bold text-sm uppercase tracking-wider bg-[#2dd4bf] text-[#0a0e1a]
                rounded-xl px-6 py-3 hover:brightness-110 transition-[filter] duration-150">
              {START_FREE_LABEL}
            </Link>
            <a href="#ask"
              className="font-mono font-bold text-sm uppercase tracking-wider border border-[#2dd4bf]/50 text-[#2dd4bf]
                rounded-xl px-6 py-3 hover:border-[#2dd4bf] hover:bg-[#2dd4bf]/5 transition-colors duration-150">
              Ask a question free
            </a>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          FOOTER — Sprint D6.90: shared LandingFooter with social row.
          Page-specific extras (Coverage, Ship network issues?) ride in
          via the extraLinks slot.
      ══════════════════════════════════════════════════════════════════════ */}
      <LandingFooter
        onContactClick={() => setContactOpen(true)}
        extraLinks={[
          { href: '/coverage', label: 'Coverage' },
          { href: '/whitelisting', label: 'Ship network issues?' },
        ]}
      />

      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  )
}
