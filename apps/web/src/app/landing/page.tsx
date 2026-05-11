'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { ContactModal } from '@/components/ContactModal'
import { CorpusBadges } from '@/components/CorpusBadges'
import { EmailComposeButton } from '@/components/EmailComposeButton'
import {
  SeeItInActionSection,
  BuiltByMarinersSection,
  WhyNotChatGPTSection,
  HallucinationProofSection,
  HowItWorksSection,
  MarinerVaultSection,
} from '@/components/marketing/MarketingSections'
import { LandingFooter } from '@/components/marketing/LandingFooter'

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
    <div className={`flex flex-col rounded-2xl p-6 border transition-shadow
      ${featured
        ? 'bg-[#111827] border-[#2dd4bf]/50 shadow-[0_0_40px_rgba(45,212,191,0.08)]'
        : 'bg-[#0d1225] border-white/8'
      }`}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide">{name}</p>
          <p className="font-mono text-3xl font-bold text-[#f0ece4] mt-1">{price}</p>
          <p className="font-mono text-xs text-[#6b7594]">{priceSub}</p>
          {subNote && (
            <p className="font-mono text-xs text-[#2dd4bf]/80 mt-1 leading-snug">{subNote}</p>
          )}
        </div>
        {badge && (
          <span className="font-mono text-[10px] font-bold text-[#2dd4bf] bg-[#2dd4bf]/10
            border border-[#2dd4bf]/30 rounded px-2 py-1 uppercase tracking-wider whitespace-nowrap">
            {badge}
          </span>
        )}
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
export default function LandingPage() {
  const [plan, setPlan] = useState<'monthly' | 'annual'>('monthly')
  const [contactOpen, setContactOpen] = useState(false)

  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">

      {/* ── Nav ─────────────────────────────────────────────────────────────── */}
      <nav className="fixed top-0 inset-x-0 z-40 flex items-center justify-between
        px-5 md:px-10 py-4 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
        <div className="flex items-center gap-2">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
            RegKnot
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/giving"
            className="hidden md:inline font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Giving Back
          </Link>
          <Link href="/login"
            className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Sign In
          </Link>
          <Link href="/register"
            className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 transition-[filter] duration-150
              rounded-lg px-4 py-1.5">
            Get Access
          </Link>
        </div>
      </nav>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 1 — HERO
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="relative flex flex-col items-center justify-center min-h-screen
        px-5 text-center overflow-hidden pt-16">

        {/* Chart grid background */}
        <div className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: `
              repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px),
              repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px)
            `,
          }}
        />

        {/* Radial glow behind compass */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          w-[480px] h-[480px] rounded-full pointer-events-none"
          style={{ background: 'radial-gradient(circle, rgba(45,212,191,0.06) 0%, transparent 70%)' }}
        />

        {/* Spinning compass rose */}
        <div className="relative mb-10 animate-[heroFadeUp_0.8s_ease-out]"
          style={{ animationFillMode: 'both' }}>
          <CompassRose className="w-40 h-40 text-[#2dd4bf]/30 animate-[compassSpin_60s_linear_infinite]" />
        </div>

        {/* Headline */}
        <h1
          className="font-display font-black text-[#f0ece4] leading-[0.95] tracking-tight
            text-[clamp(52px,12vw,96px)] max-w-4xl
            animate-[heroFadeUp_0.8s_ease-out_0.15s]"
          style={{ animationFillMode: 'both' }}
        >
          Your Compliance Co-Pilot.<br />Always On Watch.
        </h1>

        {/* Subheadline */}
        <p
          className="font-mono text-[#6b7594] mt-6 max-w-xl leading-relaxed
            text-base md:text-lg
            animate-[heroFadeUp_0.8s_ease-out_0.3s]"
          style={{ animationFillMode: 'both' }}
        >
          Cited answers from the actual regulation texts — not AI guesswork.
          The IMO conventions, U.S. CFR &amp; USCG guidance, plus flag-state regs from
          the UK, Australia, Singapore, Hong Kong, Norway, Liberia, Marshall Islands, and Bahamas —
          current, vessel-specific, and plain English.
        </p>

        {/* CTAs */}
        <div
          className="flex items-center gap-4 mt-10
            animate-[heroFadeUp_0.8s_ease-out_0.45s]"
          style={{ animationFillMode: 'both' }}
        >
          <Link
            href="/register"
            className="font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
              hover:brightness-110 transition-[filter] duration-150"
          >
            Start Free Trial
          </Link>
          <button
            onClick={() => document.getElementById('in-action')?.scrollIntoView({ behavior: 'smooth' })}
            className="font-mono font-bold text-sm uppercase tracking-wider
              border border-[#2dd4bf]/50 text-[#2dd4bf] rounded-xl px-6 py-3
              hover:border-[#2dd4bf] hover:bg-[#2dd4bf]/5 transition-colors duration-150"
          >
            See It In Action
          </button>
        </div>
        <p
          className="font-mono text-[11px] text-[#6b7594] mt-4 tracking-wide
            animate-[heroFadeUp_0.8s_ease-out_0.55s]"
          style={{ animationFillMode: 'both' }}
        >
          7-day free trial · 50 messages · No credit card required
        </p>

        {/* D6.61 — competitive wedge tagline. Single mariner-vault apps
            (MarinerDocs etc.) sell the bookkeeping; we sell that AND
            the regulatory reasoning behind it. */}
        <p
          className="font-mono text-[11px] text-[#f0ece4]/60 mt-3 tracking-wide max-w-md
            animate-[heroFadeUp_0.8s_ease-out_0.7s]"
          style={{ animationFillMode: 'both' }}
        >
          Track your credentials. Generate your USCG paperwork.{' '}
          <span className="text-[#2dd4bf]/80">And actually understand the regulations behind them.</span>
        </p>

        {/* Sprint D6.26 — flag strip moved out of hero into CorpusBadges
            "What we know" section so the hero stays uncluttered and
            jurisdictional signal lives right next to the actual sources. */}

        {/* Scroll indicator */}
        <button
          className="absolute bottom-8 flex flex-col items-center gap-1 cursor-pointer"
          aria-label="Scroll to demo"
          onClick={() => document.getElementById('why-regknots')?.scrollIntoView({ behavior: 'smooth' })}
        >
          <svg
            className="w-5 h-5 text-[#6b7594] animate-[chevronBounce_2s_ease-in-out_infinite]"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </section>

            <BuiltByMarinersSection />

      <WhyNotChatGPTSection />

      <HallucinationProofSection />

      <SeeItInActionSection />

      <HowItWorksSection />

{/* ══════════════════════════════════════════════════════════════════════
          SECTION 5 — CORPUS BADGES — what's in the index
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="px-5 md:px-10 py-20 md:py-28 border-t border-white/5">
        <CorpusBadges
          heading="What we know"
          subhead="Every reg in our index, sorted by where it comes from. Click any chip to open the source."
        />
      </section>

            <MarinerVaultSection />

{/* ══════════════════════════════════════════════════════════════════════
          SECTION 6 — PRICING
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="px-5 md:px-10 py-20 md:py-28">
        <div className="max-w-3xl mx-auto">
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

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <PricingCard
              name="Free Trial"
              price="$0"
              priceSub="for 7 days"
              features={[
                '7-day free trial',
                '50 messages during trial',
                'Full feature access',
                'Upgrade or cancel anytime',
              ]}
              smallPrint="No credit card required to start."
              cta="Start Free Trial"
            />
            <PricingCard
              name="Mate"
              price={plan === 'monthly' ? '$19.99' : '$14.99'}
              priceSub={plan === 'monthly' ? 'per month' : 'per month, billed $179.88/year'}
              features={[
                '100 messages per month',
                'Full reg corpus (see above)',
                'Vessel profile + chat history',
                'Credential vault with auto-OCR',
                'Renewal alerts (90 / 30 / 7 days)',
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

          {/* D6.61 — trust strip. Security is table stakes; competitors who
              market AES-256 as a feature are flagging that they don't have
              anything else to sell. We mention the controls so the buyer
              who scans for them is satisfied, then immediately frame
              security as the floor, not the brochure. */}
          <div className="mt-10 max-w-3xl mx-auto">
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

          {/* D6.57 — Wheelhouse callout. Conceptually different (per-vessel,
              multi-seat, 30-day no-card trial) so it lives below the personal
              tiers as a "for crews" upsell rather than crammed into the
              same row. Links to /pricing for the detailed Wheelhouse cards. */}
          <div className="mt-8 rounded-2xl border border-[#2dd4bf]/30 bg-[#0d1225] p-6 md:p-7">
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
          <p className="font-mono text-xs text-[#6b7594] text-center mt-2 text-balance break-words">
            Fleet operators: request a custom subdomain (
            <span className="text-[#f0ece4]/80">yourcompany.regknots.com</span>) for simplified
            fleet-wide deployment and firewall whitelisting.
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
