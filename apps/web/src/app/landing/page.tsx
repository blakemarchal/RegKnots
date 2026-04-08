'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'

// ── Static citation chip (non-interactive, landing page only) ─────────────────
function StaticChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
      bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none align-baseline mx-0.5">
      {label}
    </span>
  )
}

// ── Step card ──────────────────────────────────────────────────────────────────
function StepCard({ n, title, desc }: { n: string; title: string; desc: string }) {
  return (
    <div className="flex flex-col gap-3">
      <span className="font-display text-5xl font-black text-[#2dd4bf] leading-none">{n}</span>
      <div>
        <p className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">{title}</p>
        <p className="font-mono text-sm text-[#6b7594] mt-1 leading-relaxed">{desc}</p>
      </div>
    </div>
  )
}

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
          Titles 33, 46 &amp; 49 + COLREGs, NVICs, SOLAS 2024, STCW &amp; ISM Code — current, vessel-specific, and plain English.
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
          14-day free trial · 50 messages · No credit card required
        </p>

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

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 2 — BUILT BY MARINERS
      ══════════════════════════════════════════════════════════════════════ */}
      <section id="why-regknots" className="bg-[#111827] px-5 md:px-10 py-20 md:py-28">
        <div className="max-w-3xl mx-auto">
          {/* Compass accent */}
          <CompassRose className="w-6 h-6 text-[#2dd4bf] mb-5" />

          {/* Label */}
          <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-4">
            Why RegKnot
          </p>

          {/* Headline */}
          <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
            text-[clamp(32px,6vw,56px)] mb-8">
            CFRs are complex.<br />Getting cited shouldn&apos;t be.
          </h2>

          {/* Body */}
          <div className="flex flex-col gap-5">
            <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
              U.S. commercial mariners navigate an overlapping web of Titles 33, 46, and 49 — plus COLREGs, NVICs, SOLAS, STCW, and the ISM Code —
              thousands of sections that cross-reference each other, change without warning,
              and vary by vessel type, tonnage, route, and cargo. One missed detail during a
              Coast Guard inspection means deficiency citations, vessel detention, or costly
              litigation.
            </p>
            <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
              RegKnot was built by an Unlimited Licensed Captain and her engineer brother.
              We know these regulations because we live them. This is the tool we wished existed.
            </p>
            <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
              General-purpose AI doesn&apos;t have access to the SOLAS Consolidated Edition, the STCW Convention,
              or the ISM Code — and it can&apos;t tell the difference between what applies to your towing vessel
              versus a containership. RegKnot is built on the purchased source texts and your vessel profile,
              so every answer is specific to your ship and cites the exact section you can verify.
            </p>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 3 — SAMPLE ANSWER
      ══════════════════════════════════════════════════════════════════════ */}
      <section id="in-action" className="px-5 md:px-10 py-20 md:py-28">
        <div className="max-w-2xl mx-auto">
          {/* Heading */}
          <div className="text-center mb-12">
            <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
              text-[clamp(28px,5vw,48px)]">
              See It In Action
            </h2>
            <p className="font-mono text-[#6b7594] mt-3 text-sm md:text-base">
              Ask a real compliance question — CFR, COLREGs, NVICs, STCW, or ISM. Get a real cited answer.
            </p>
          </div>

          {/* Mock chat — chart grid background matching real app */}
          <div className="rounded-2xl overflow-hidden border border-white/8"
            style={{
              backgroundImage: `
                repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.018) 47px, rgba(45,212,191,0.018) 48px),
                repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.018) 47px, rgba(45,212,191,0.018) 48px)
              `,
              backgroundColor: '#0a0e1a',
            }}>

            {/* Chat header bar */}
            <div className="flex items-center gap-2.5 px-4 py-3 bg-[#111827]/95 border-b border-white/8">
              <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
                <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
              </svg>
              <span className="font-display text-base font-bold text-[#f0ece4] tracking-wide">RegKnot</span>
              <span className="font-mono text-[9px] text-[#6b7594] tracking-[0.2em] uppercase ml-0.5">Maritime Compliance Co-Pilot</span>
            </div>

            <div className="flex flex-col gap-0.5 py-3">
              {/* User message */}
              <div className="flex justify-end px-4 py-1.5">
                <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm
                  bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed font-mono">
                  What are the lifeboat inspection requirements for my vessel?
                </div>
              </div>

              {/* Assistant message */}
              <div className="flex items-start gap-3 px-4 py-3">
                <div className="w-0.5 self-stretch bg-[#2dd4bf]/40 rounded-full flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
                  {/* Markdown-style content, rendered statically */}
                  <p className="font-display text-lg font-bold text-[#f0ece4] mb-3">
                    Lifeboat Inspection Requirements
                  </p>

                  <p className="font-mono text-sm mb-3 leading-relaxed">
                    Under <StaticChip label="46 CFR 199.190" />, your vessel must conduct inspections
                    on the following schedule:
                  </p>

                  <p className="font-mono text-sm font-semibold text-[#2dd4bf] mb-1">Weekly:</p>
                  <p className="font-mono text-sm mb-3 text-[#f0ece4]/80 leading-relaxed">
                    Visual inspection of survival craft, rescue boats, and launching appliances
                    for readiness.
                  </p>

                  <p className="font-mono text-sm font-semibold text-[#2dd4bf] mb-1">Monthly:</p>
                  <p className="font-mono text-sm mb-3 text-[#f0ece4]/80 leading-relaxed">
                    Each lifesaving appliance must be verified complete and in good working order,
                    with results recorded in the vessel&apos;s official logbook{' '}
                    <StaticChip label="46 CFR 199.190(e)" />.
                  </p>

                  <p className="font-mono text-sm font-semibold text-[#2dd4bf] mb-1">Annually:</p>
                  <p className="font-mono text-sm mb-3 text-[#f0ece4]/80 leading-relaxed">
                    Full operational tests including launching appliances at loads from light to
                    full load <StaticChip label="46 CFR 133.45(b)" />.
                  </p>

                  <p className="font-mono text-xs text-[#6b7594] italic border-l-2 border-[#2dd4bf]/30 pl-3">
                    Note: SOLAS Chapter III applies to vessels on international routes in addition
                    to these CFR requirements.
                  </p>

                  {/* Footer chips */}
                  <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-1.5">
                    <StaticChip label="46 CFR 199.190" />
                    <StaticChip label="46 CFR 133.45" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <p className="font-mono text-xs text-[#6b7594] text-center mt-4">
            Answers cite exact CFR sections. Tap any citation to read the full regulation text.
          </p>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 4 — HOW IT WORKS
      ══════════════════════════════════════════════════════════════════════ */}
      <section className="bg-[#111827] px-5 md:px-10 py-20 md:py-28">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
              text-[clamp(28px,5vw,48px)]">
              Ready in minutes.
            </h2>
          </div>

          {/* Steps */}
          <div className="relative grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
            {/* Connecting line — desktop only */}
            <div className="hidden md:block absolute top-7 left-[calc(16.67%+12px)] right-[calc(16.67%+12px)]
              h-px bg-gradient-to-r from-[#2dd4bf]/30 via-[#2dd4bf]/60 to-[#2dd4bf]/30" />

            <StepCard
              n="01"
              title="Create your account"
              desc="Register and tell us your role onboard. Captain, mate, engineer — we tailor guidance to your position."
            />
            <StepCard
              n="02"
              title="Set up your vessel"
              desc="Enter your vessel type, route, and cargo profile. Tonnage thresholds and SOLAS applicability resolved automatically."
            />
            <StepCard
              n="03"
              title="Ask anything"
              desc="Get instant cited answers, 24/7. Every response references exact CFR sections, NVICs, SOLAS, STCW, and ISM Code regulations you can verify."
            />
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          SECTION 5 — PRICING
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
                    Save 26%
                  </span>
                </button>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <PricingCard
              name="Free Trial"
              price="$0"
              priceSub="for 14 days"
              features={[
                '14-day free trial',
                '50 messages during trial',
                'No credit card required',
              ]}
              smallPrint="One trial per account. No credit card required to start."
              cta="Start Free Trial"
            />
            <PricingCard
              name="Pro"
              price={plan === 'monthly' ? '$39' : '$29'}
              priceSub={plan === 'monthly' ? 'per month' : 'per month, billed $348/year'}
              features={[
                'Unlimited questions',
                'CFR Titles 33, 46 & 49 + COLREGs, NVICs, SOLAS 2024, STCW & ISM Code',
                'Vessel profile + history',
                'Priority regulation updates',
                'Audit-ready chat logs',
              ]}
              cta="Start Free Trial"
              featured
            />
          </div>

          <p className="font-mono text-xs text-[#6b7594] text-center mt-6">
            Fleet pricing available. Contact us at{' '}
            <a href="mailto:hello@regknots.com" className="text-[#2dd4bf] hover:underline">
              hello@regknots.com
            </a>
          </p>
          <p className="font-mono text-xs text-[#6b7594] text-center mt-2">
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
            Learn more about our partners &rarr;
          </Link>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════════════
          FOOTER
      ══════════════════════════════════════════════════════════════════════ */}
      <footer className="border-t border-white/8 px-5 md:px-10 py-8">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center
          justify-between gap-4 text-center md:text-left">
          <div className="flex items-center gap-2">
            <CompassRose className="w-4 h-4 text-[#2dd4bf]/60" />
            <span className="font-display text-base font-bold text-[#f0ece4]/60 tracking-widest uppercase">
              RegKnot
            </span>
          </div>
          <p className="font-mono text-xs text-[#6b7594]">
            Navigation aid only — not legal advice
          </p>
          <div className="flex items-center gap-4">
            <a href="/terms" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Terms
            </a>
            <a href="/privacy" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Privacy
            </a>
            <a href="/giving" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Giving Back
            </a>
            <a href="/whitelisting" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Ship network issues?
            </a>
            <p className="font-mono text-xs text-[#6b7594]">
              © 2026 RegKnot
            </p>
          </div>
        </div>
      </footer>

    </div>
  )
}
