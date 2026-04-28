'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { ContactModal } from '@/components/ContactModal'
import { CorpusBadges } from '@/components/CorpusBadges'

// ── Static citation chip (non-interactive, landing page only) ─────────────────
function StaticChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
      bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none align-baseline mx-0.5">
      {label}
    </span>
  )
}

// ── In-action demo data ─────────────────────────────────────────────────────
//
// Sprint D6.23c — rotate 4 sample chats in the "See It In Action" section
// to surface the breadth of coverage (US CFR, UK MCA, ERG/IMDG, IMO BWM).
// Each demo is a (question, response) pair with markdown-style sections.

interface DemoSection { label: string; body: string; chip?: string }
interface Demo {
  vesselContext: string         // small grey label above the user message
  question: string
  title: string
  intro: string                 // first paragraph, often with an inline chip
  introChip?: string
  sections: DemoSection[]
  note?: string                 // italic footnote
  footerChips: string[]         // citation pills below the answer
}

const DEMOS: Demo[] = [
  {
    vesselContext: 'U.S.-flag passenger vessel · 200 GT · coastwise',
    question: 'What are the lifeboat inspection requirements for my vessel?',
    title: 'Lifeboat Inspection Requirements',
    intro: 'your vessel must conduct inspections on the following schedule:',
    introChip: '46 CFR 199.190',
    sections: [
      { label: 'Weekly:', body: 'Visual inspection of survival craft, rescue boats, and launching appliances for readiness.' },
      { label: 'Monthly:', body: "Each lifesaving appliance must be verified complete and in good working order, with results recorded in the vessel's official logbook", chip: '46 CFR 199.190(e)' },
      { label: 'Annually:', body: 'Full operational tests including launching appliances at loads from light to full load', chip: '46 CFR 133.45(b)' },
    ],
    note: 'SOLAS Chapter III applies to vessels on international routes in addition to these CFR requirements.',
    footerChips: ['46 CFR 199.190', '46 CFR 133.45'],
  },
  {
    vesselContext: 'UK-flag ro-pax ferry · Dunkerque–Dover',
    question: 'What weekly drills must my vessel log?',
    title: 'Weekly Drill Logging — UK Channel Ferry',
    intro: 'For your UK-flagged ro-pax ferry, the binding framework is SOLAS Ch.III as implemented by the MCA.',
    introChip: 'SOLAS Ch.III Reg.19',
    sections: [
      { label: 'Abandon-ship drill (weekly):', body: 'Muster of crew, lifeboat lowering on alternating sides, emergency lighting test.', chip: 'MGN 71 (M+F)' },
      { label: 'Fire drill (weekly):', body: 'Manning of fire parties, fire-pump start with two jets, watertight doors and dampers operated.', chip: 'MGN 71 (M+F)' },
      { label: 'Logbook entries:', body: 'Date/time, drill type, crew participation, equipment faults, and any corrective action.', chip: 'MSN 1676 (M)' },
    ],
    note: 'Contains public sector information licensed under the Open Government Licence v3.0.',
    footerChips: ['MGN 71 (M+F)', 'MSN 1676 (M)', 'SOLAS Ch.III'],
  },
  {
    vesselContext: 'Containership · international voyage',
    question: 'A tank container of UN 2734 caught fire on deck — what do I do?',
    title: 'UN 2734 — Fire Response',
    intro: 'UN 2734 is Amines, liquid, corrosive, flammable, n.o.s. (Class 8 + 3, packing groups I or II).',
    introChip: '49 CFR 172.101',
    sections: [
      { label: 'ERG Guide:', body: 'Use Guide 132 — flammable corrosive liquids. Eliminate ignition sources. Stop leak if safe. Prevent runoff to waterways.', chip: 'ERG Guide 132' },
      { label: 'Suppression:', body: 'Water spray, foam, dry chemical, or CO₂. Cool exposed containers with flooding water. Withdraw if safety-valve discoloration or rising vent sound.', chip: 'ERG Guide 132' },
      { label: 'Isolation:', body: 'At least 50 meters in all directions for spill or leak; far larger for tank involvement. Consult ERG Table 1 for downwind.', chip: 'ERG Table 1' },
    ],
    note: 'IMDG 3.2 lists UN 2734 with class 8 / subsidiary 3, EmS F-E / S-C, and stowage code SGG18.',
    footerChips: ['UN 2734', 'ERG Guide 132', '49 CFR 172.101', 'IMDG 3.2'],
  },
  {
    vesselContext: 'Liberian-flag bulk carrier · 80,000 GT',
    question: 'What does the Ballast Water Management Convention require for record-keeping?',
    title: 'BWM Recordkeeping — Liberian Flag',
    intro: 'For a Liberian-flag bulker on international voyages, BWM record-keeping is governed by the BWM Convention via LISCR Marine Notice POL-005.',
    introChip: 'LISCR POL-005',
    sections: [
      { label: 'Ballast Water Record Book:', body: 'Each ballast operation logged within 24 hours: source, volume, location, treatment used. Entries signed by the officer in charge.', chip: 'MEPC.369(80)' },
      { label: 'Ballast Water Management Plan:', body: 'Plan approved by flag administration, on board, accessible to crew, in working language and English.', chip: 'LISCR POL-005' },
      { label: 'Crew familiarization:', body: 'Master and officers must be familiar with safety implications of ballast operations and treatment system operation.', chip: 'BWM Convention Reg.B-3' },
    ],
    note: 'Same answer applies to RMI/IRI flag via MN-2-014-1 with similar form requirements.',
    footerChips: ['LISCR POL-005', 'MEPC.369(80)', 'BWM Convention'],
  },
]

// ── Demo carousel — rotates through the DEMOS array ─────────────────────────

function DemoCarousel() {
  const [idx, setIdx] = useState(0)
  const [paused, setPaused] = useState(false)

  // Auto-advance every 9s unless the user has interacted recently.
  useEffect(() => {
    if (paused) return
    const t = setInterval(() => setIdx((i) => (i + 1) % DEMOS.length), 9000)
    return () => clearInterval(t)
  }, [paused])

  const demo = DEMOS[idx]

  return (
    <div onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      {/* Mock chat — same chrome as the real app */}
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
          <span className="ml-auto font-mono text-[10px] text-[#6b7594]">{demo.vesselContext}</span>
        </div>

        <div className="flex flex-col gap-0.5 py-3 min-h-[420px]">
          {/* User message */}
          <div className="flex justify-end px-4 py-1.5">
            <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm
              bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed font-mono">
              {demo.question}
            </div>
          </div>

          {/* Assistant message */}
          <div className="flex items-start gap-3 px-4 py-3">
            <div className="w-0.5 self-stretch bg-[#2dd4bf]/40 rounded-full flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
              <p className="font-display text-lg font-bold text-[#f0ece4] mb-3">{demo.title}</p>
              <p className="font-mono text-sm mb-3 leading-relaxed">
                {demo.introChip && <><StaticChip label={demo.introChip} />{' '}</>}
                {demo.intro}
              </p>
              {demo.sections.map((s) => (
                <div key={s.label}>
                  <p className="font-mono text-sm font-semibold text-[#2dd4bf] mb-1">{s.label}</p>
                  <p className="font-mono text-sm mb-3 text-[#f0ece4]/80 leading-relaxed">
                    {s.body}
                    {s.chip && <> <StaticChip label={s.chip} />.</>}
                  </p>
                </div>
              ))}
              {demo.note && (
                <p className="font-mono text-xs text-[#6b7594] italic border-l-2 border-[#2dd4bf]/30 pl-3 mt-2">
                  Note: {demo.note}
                </p>
              )}
              <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-1.5">
                {demo.footerChips.map((c) => <StaticChip key={c} label={c} />)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Pagination dots */}
      <div className="flex justify-center gap-2 mt-4" role="tablist" aria-label="Demo selector">
        {DEMOS.map((d, i) => (
          <button
            key={d.title}
            role="tab"
            aria-selected={i === idx}
            aria-label={`Demo ${i + 1}: ${d.title}`}
            onClick={() => { setIdx(i); setPaused(true) }}
            className={`h-1.5 rounded-full transition-all duration-200 ${
              i === idx ? 'w-8 bg-[#2dd4bf]' : 'w-1.5 bg-white/15 hover:bg-white/30'
            }`}
          />
        ))}
      </div>
    </div>
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
            The regs are complex.<br />Getting cited shouldn&apos;t be.
          </h2>

          {/* Body */}
          <div className="flex flex-col gap-5">
            <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
              Commercial mariners navigate an overlapping web of regs — the IMO conventions
              (SOLAS, MARPOL, IMDG, COLREGs, STCW, ISM, plus the IGC, IBC, HSC and Load Lines codes),
              the U.S. CFR Titles 33/46/49 and USCG guidance, and a growing set of flag-state
              regulators (UK MCA, AMSA Australia, Singapore MPA, Hong Kong, Norway NMA, Liberia,
              Marshall Islands, Bahamas). Thousands of sections that cross-reference each other,
              change without warning, and vary by vessel type, tonnage, flag, route, and cargo.
              One missed detail during an inspection means deficiency citations, vessel detention,
              or costly litigation.
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
              U.S. Captain. Channel ferry. Hazmat fire. Liberian bulker. Real cited answers, every time.
            </p>
          </div>

          <DemoCarousel />

          <p className="font-mono text-xs text-[#6b7594] text-center mt-4">
            Answers cite exact regulation sections. Tap any citation to read the full text.
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
              desc="Get instant cited answers, 24/7. Every response references exact CFR sections, IMO convention paragraphs (SOLAS, MARPOL, IMDG, COLREGs, STCW, ISM), USCG circulars, ERG entries — anything you can verify."
            />
          </div>
        </div>
      </section>

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
                'PSC checklist builder & sea-service letters',
              ]}
              cta="Subscribe to Captain"
              featured
            />
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
            <a href="mailto:hello@regknots.com" className="text-[#2dd4bf] hover:underline">
              hello@regknots.com
            </a>
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
          <div className="flex items-center gap-4 flex-wrap justify-center">
            <button
              type="button"
              onClick={() => setContactOpen(true)}
              className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors"
            >
              Contact Us
            </button>
            <a href="/coverage" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Coverage
            </a>
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

      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  )
}
