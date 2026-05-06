'use client'

/**
 * Shared marketing-page sections — Sprint D6.72.
 *
 * The four marketing entry points (/landing, /captainkarynn, /womenoffshore,
 * /ass) used to share only the hero/pricing scaffolding. The "wow factor"
 * sections (polished demo carousel, ChatGPT comparison cards, hallucination
 * showcase, how-it-works steps, beyond-chat product surface) lived only on
 * /landing — so visitors arriving via referral pages got a thinner first
 * impression than visitors landing on the canonical page.
 *
 * Karynn's call-out: every page is a potential first-and-only impression;
 * they all need to wow.
 *
 * This module is the single source of truth for those shared sections.
 * Each export is a self-contained component the page templates compose
 * around their unique hero/pricing/closing bits.
 */

import { useEffect, useState } from 'react'
import { CompassRose } from '@/components/CompassRose'
import { HallucinationCarousel } from '@/components/HallucinationCarousel'

// ── Shared visual primitives ────────────────────────────────────────────────

/** Citation chip used inline within demo answers and section bodies. */
export function StaticChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
      bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none align-baseline mx-0.5">
      {label}
    </span>
  )
}

// ── DemoCarousel — chat-mock that rotates through 4 vessel-typed demos ─────

interface DemoSection { label: string; body: string; chip?: string }
interface Demo {
  vesselContext: string
  question: string
  title: string
  intro: string
  introChip?: string
  sections: DemoSection[]
  note?: string
  footerChips: string[]
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

/**
 * Animated chat-mock carousel cycling through 4 vessel-typed demos.
 *
 * Auto-advances every 9s; pauses on hover; tablist of dots underneath
 * for explicit selection. Visually mirrors the actual chat UI so the
 * marketing surface promises exactly what the product delivers.
 */
export function DemoCarousel() {
  const [idx, setIdx] = useState(0)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused) return
    const t = setInterval(() => setIdx((i) => (i + 1) % DEMOS.length), 9000)
    return () => clearInterval(t)
  }, [paused])

  const demo = DEMOS[idx]

  return (
    <div onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="rounded-2xl overflow-hidden border border-white/8"
        style={{
          backgroundImage: `
            repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.018) 47px, rgba(45,212,191,0.018) 48px),
            repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.018) 47px, rgba(45,212,191,0.018) 48px)
          `,
          backgroundColor: '#0a0e1a',
        }}>

        <div className="flex items-center gap-2.5 px-4 py-3 bg-[#111827]/95 border-b border-white/8">
          <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
            <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
          </svg>
          <span className="font-display text-base font-bold text-[#f0ece4] tracking-wide">RegKnot</span>
          <span className="font-mono text-[9px] text-[#6b7594] tracking-[0.2em] uppercase ml-0.5">Maritime Compliance Co-Pilot</span>
          <span className="ml-auto font-mono text-[10px] text-[#6b7594] hidden sm:inline">{demo.vesselContext}</span>
        </div>

        <div className="flex flex-col gap-0.5 py-3 min-h-[420px]">
          <div className="flex justify-end px-4 py-1.5">
            <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm
              bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed font-mono">
              {demo.question}
            </div>
          </div>

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

// ── DemoSection — wraps DemoCarousel with the standard section header ──────

/** Full "See It In Action" section (heading + DemoCarousel + footer). */
export function SeeItInActionSection({ id = 'in-action' }: { id?: string }) {
  return (
    <section id={id} className="px-5 md:px-10 py-20 md:py-28">
      <div className="max-w-2xl mx-auto">
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
  )
}

// ── BuiltByMariners — "Why RegKnot" trust section ──────────────────────────

export function BuiltByMarinersSection() {
  return (
    <section className="bg-[#111827] px-5 md:px-10 py-20 md:py-28">
      <div className="max-w-3xl mx-auto">
        <CompassRose className="w-6 h-6 text-[#2dd4bf] mb-5" />
        <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-4">
          Why RegKnot
        </p>
        <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
          text-[clamp(32px,6vw,56px)] mb-8">
          The regs are complex.<br />Getting cited shouldn&apos;t be.
        </h2>
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
  )
}

// ── WhyNotChatGPT — 4-card differentiator section ──────────────────────────

export function WhyNotChatGPTSection() {
  return (
    <section className="bg-[#0a0e1a] px-5 md:px-10 py-20 md:py-28">
      <div className="max-w-4xl mx-auto">
        <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-3">
          How we&apos;re different
        </p>
        <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
          text-[clamp(28px,5vw,44px)] mb-4">
          Why not just use ChatGPT?
        </h2>
        <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base mb-12 max-w-2xl">
          Honest answer: for casual maritime questions, you can. For compliance answers
          that need to hold up to a Coast Guard inspector or a port-state control deficiency
          report, here&apos;s what general-purpose AI doesn&apos;t do.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5">
          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              01 — Citation discipline
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              Every section we cite is verified against the actual text
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              ChatGPT and Gemini will cheerfully invent a CFR section that doesn&apos;t exist.
              RegKnot runs every citation through a verification pass before you see it.
              If we can&apos;t ground a claim in the retrieved regulation text, we hedge instead
              of guessing &mdash; and we tell you exactly what we couldn&apos;t verify.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              02 — Real source texts
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              IMDG Code 2024, SOLAS Consolidated, STCW with current supplements
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              IMO conventions are paywalled. General AI was trained on web summaries
              and outdated copies. We&apos;ve ingested the licensed editions &mdash; the
              IMDG Dangerous Goods List, the full SOLAS chapters, STCW with the latest
              MSC resolutions, the ISM Code, plus 9 flag-state regulators. When you ask
              about UN 3480 stowage, we have the actual row from Chapter 3.2.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              03 — Vessel-specific scoping
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              The answer changes based on your ship
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              Subchapter L OSV vs Subchapter K small passenger vessel vs U.K.-flag bulker
              in U.S. waters &mdash; the regulatory answer is different for each. RegKnot
              reads your vessel profile (flag, tonnage, route, subchapter, cargo) and scopes
              retrieval + answer accordingly. Generic LLMs give you the same one-size-fits-all
              response no matter what you operate.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              04 — Built by mariners, audited daily
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              A Master Unlimited captain runs the audits
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              Karynn holds an Unlimited Master license and reviews actual user answers
              every few days, flagging anything off. When she finds a gap &mdash; a missed
              Annex V exemption, a wrong jurisdictional cite &mdash; the prompt rules and
              ingest pipeline get fixed within the week. This isn&apos;t a wrapper around an
              API. It&apos;s a regulatory tool with a mariner in the loop.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── HallucinationProof — wraps the existing HallucinationCarousel ──────────

export function HallucinationProofSection() {
  return (
    <section id="hallucination-proof" className="bg-[#0a0e1a] px-5 md:px-10 py-20 md:py-28
                                                  border-t border-white/5">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12 md:mb-14">
          <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-3">
            We tested it
          </p>
          <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
                         text-[clamp(28px,5vw,44px)] mb-4">
            ChatGPT looks confident. <br className="hidden sm:block" />
            That&apos;s the problem.
          </h2>
          <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base
                        max-w-2xl mx-auto">
            We asked ChatGPT specific maritime questions. Every answer came back
            polished and authoritative. Some of them are wrong. The hard part
            isn&apos;t spotting hallucinations &mdash; it&apos;s noticing them
            before the inspector does.
          </p>
        </div>

        <HallucinationCarousel />

        <p className="font-mono text-[10px] text-[#6b7594] text-center mt-10
                      max-w-xl mx-auto leading-relaxed">
          Examples captured 2026-05-04 from ChatGPT with web browsing enabled.
          Verifiable against eCFR, the IMDG Code, and USCG NVIC archive.
        </p>
      </div>
    </section>
  )
}

// ── HowItWorks — 3-step explainer ──────────────────────────────────────────

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

export function HowItWorksSection() {
  return (
    <section className="bg-[#111827] px-5 md:px-10 py-20 md:py-28">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-14">
          <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
            text-[clamp(28px,5vw,48px)]">
            Ready in minutes.
          </h2>
        </div>

        <div className="relative grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
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
  )
}

// ── MarinerVault — "Beyond Chat" product showcase (D6.61) ──────────────────

export function MarinerVaultSection() {
  return (
    <section className="bg-[#111827] px-5 md:px-10 py-20 md:py-28 border-t border-white/5">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <p className="font-mono text-[11px] text-[#2dd4bf] uppercase tracking-[0.3em] mb-3">
            Beyond Chat
          </p>
          <h2 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
            text-[clamp(28px,5vw,48px)]">
            Your record, your career,<br />reasoned against the regulation.
          </h2>
          <p className="font-mono text-[#6b7594] mt-4 max-w-2xl mx-auto text-sm md:text-base">
            Snap a photo of your MMC, TWIC, or medical cert. We extract
            the data, track the expiry, and answer the regulatory questions
            only your stored record can trigger — including which
            credential upgrade you&apos;re closest to qualifying for.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
          <div className="bg-[#0d1225] rounded-2xl border border-white/8 p-6 md:p-7">
            <div className="w-10 h-10 rounded-lg bg-[#2dd4bf]/10 border border-[#2dd4bf]/20
              flex items-center justify-center mb-4">
              <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M3 9h18M9 21V9" />
              </svg>
            </div>
            <h3 className="font-display font-bold text-[#f0ece4] text-lg mb-2">
              Credential Vault
            </h3>
            <p className="font-mono text-xs text-[#6b7594] leading-relaxed mb-3">
              MMC, TWIC, medical, STCW, passports, course certs, sea-service letters,
              drug-test letters, vaccine records, union paperwork, pay stubs — all in one place.
            </p>
            <p className="font-mono text-[10px] text-[#2dd4bf]/70 uppercase tracking-wider">
              Snap → extract → done
            </p>
          </div>

          <div className="bg-[#0d1225] rounded-2xl border border-white/8 p-6 md:p-7">
            <div className="w-10 h-10 rounded-lg bg-[#2dd4bf]/10 border border-[#2dd4bf]/20
              flex items-center justify-center mb-4">
              <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="6" width="20" height="14" rx="2" />
                <path d="M22 6l-10 7L2 6M7 2v4M17 2v4" />
              </svg>
            </div>
            <h3 className="font-display font-bold text-[#f0ece4] text-lg mb-2">
              Snap + Understand
            </h3>
            <p className="font-mono text-xs text-[#6b7594] leading-relaxed mb-3">
              One photo, structured data + the regulation behind it.
              &ldquo;Your MMC says Master Inland 100 GT — here&apos;s what 46 CFR 11.422
              requires to upgrade to 200 GT.&rdquo;
            </p>
            <p className="font-mono text-[10px] text-[#2dd4bf]/70 uppercase tracking-wider">
              Other apps stop at the photo
            </p>
          </div>

          <div className="bg-[#0d1225] rounded-2xl border border-white/8 p-6 md:p-7">
            <div className="w-10 h-10 rounded-lg bg-[#2dd4bf]/10 border border-[#2dd4bf]/20
              flex items-center justify-center mb-4">
              <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 6v6l4 2" />
              </svg>
            </div>
            <h3 className="font-display font-bold text-[#f0ece4] text-lg mb-2">
              Renewal Co-Pilot
            </h3>
            <p className="font-mono text-xs text-[#6b7594] leading-relaxed mb-3">
              Personalized readiness for every credential. ✓ medical cert valid,
              ✗ drug-test letter missing per 46 CFR 16.230, ✓ sea-time exceeds
              threshold — not just &ldquo;your MMC expires in 47 days.&rdquo;
            </p>
            <p className="font-mono text-[10px] text-[#2dd4bf]/70 uppercase tracking-wider">
              Calendar + the rule + your record
            </p>
          </div>

          <div className="bg-[#0d1225] rounded-2xl border border-white/8 p-6 md:p-7">
            <div className="w-10 h-10 rounded-lg bg-[#2dd4bf]/10 border border-[#2dd4bf]/20
              flex items-center justify-center mb-4">
              <svg className="w-5 h-5 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 17l6-6 4 4 8-8" />
                <path d="M14 7h7v7" />
              </svg>
            </div>
            <h3 className="font-display font-bold text-[#f0ece4] text-lg mb-2">
              Career Path
            </h3>
            <p className="font-mono text-xs text-[#6b7594] leading-relaxed mb-3">
              We read your stored credentials + sea-time, then look at the actual
              CFR ladder. &ldquo;You&apos;re cap-eligible for Master Inland 200 GT now;
              Master Near-Coastal 200 GT is 180 days away under 46 CFR 11.422.&rdquo;
            </p>
            <p className="font-mono text-[10px] text-[#2dd4bf]/70 uppercase tracking-wider">
              What credentialing services charge for, free
            </p>
          </div>
        </div>

        <div className="mt-8 max-w-4xl mx-auto">
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] text-center mb-3">
            Plus four more AI co-pilots reasoning over your record
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-[#0d1225] border border-white/8 rounded-lg p-3">
              <p className="font-mono text-[11px] text-[#f0ece4] font-bold mb-1">Vessel Analysis</p>
              <p className="font-mono text-[10px] text-[#6b7594] leading-snug">
                Drop in a COI, get the regulatory implications mapped.
              </p>
            </div>
            <div className="bg-[#0d1225] border border-white/8 rounded-lg p-3">
              <p className="font-mono text-[11px] text-[#f0ece4] font-bold mb-1">PSC Co-Pilot</p>
              <p className="font-mono text-[10px] text-[#6b7594] leading-snug">
                Inspection prep tailored to vessel + flag + MOU region.
              </p>
            </div>
            <div className="bg-[#0d1225] border border-white/8 rounded-lg p-3">
              <p className="font-mono text-[11px] text-[#f0ece4] font-bold mb-1">Compliance Changelog</p>
              <p className="font-mono text-[10px] text-[#6b7594] leading-snug">
                What changed in the regs that affects your record.
              </p>
            </div>
            <div className="bg-[#0d1225] border border-white/8 rounded-lg p-3">
              <p className="font-mono text-[11px] text-[#f0ece4] font-bold mb-1">Audit Readiness</p>
              <p className="font-mono text-[10px] text-[#6b7594] leading-snug">
                Score, gaps, and what to fix first across credentials + vessels.
              </p>
            </div>
          </div>
        </div>

        <p className="font-mono text-xs text-[#6b7594] text-center mt-10 max-w-2xl mx-auto">
          Other mariner apps store the paperwork.{' '}
          <span className="text-[#f0ece4]/85">RegKnots stores it AND explains the rule the paperwork points to.</span>
        </p>
      </div>
    </section>
  )
}
