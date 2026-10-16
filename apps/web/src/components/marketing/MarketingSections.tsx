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

/** Citation chip used inline within demo answers and section bodies.
 *  2026-10-16 UI pass — teal, like the real chips (CitationChip); amber is
 *  the caution colour in the app, so amber demo chips promised the wrong thing. */
export function StaticChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
      bg-teal-950/70 text-teal-300 border border-teal-800/60 leading-none align-baseline mx-0.5">
      {label}
    </span>
  )
}

/** The "Corpus-verified · N citations" badge from a chat answer's footer. */
function VerifiedBadge({ count }: { count: number }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium
      bg-emerald-950/60 text-emerald-300 border border-emerald-800/50">
      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M20 6L9 17l-5-5" />
      </svg>
      Corpus-verified · {count} citation{count === 1 ? '' : 's'}
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
  // 2026-10-16 UI pass — from a real answer (the first free question asked on
  // the live site), each line checked against the cited text of 46 CFR
  // 141.305, 141.360, 141.370 and 141.375. It replaced a passenger-vessel demo
  // that cited 46 CFR 133.45, an OSV (Subchapter L) section.
  {
    vesselContext: 'U.S.-flag towboat · 7 crew · Mississippi River',
    question: 'What lifesaving gear does my towboat need on the Mississippi? We have 7 crew.',
    title: 'Lifesaving Equipment — Towboat on the Rivers',
    intro: 'Under Subchapter M, equipment depends on the area you operate in, not the route on your COI.',
    introChip: '46 CFR 141.370',
    sections: [
      { label: 'Survival craft:', body: 'None required on rivers, unless the OCMI or your TSMS calls for them', chip: '46 CFR 141.305' },
      { label: 'Lifebuoys (26 to 79 ft):', body: 'Two, at least 24 in, on opposite sides where crew are normally present; at least one with a 60 ft buoyant lifeline', chip: '46 CFR 141.360' },
      { label: 'Distress signals:', body: 'Three day and three night visual distress signals for the rivers area', chip: '46 CFR 141.375' },
    ],
    note: 'Head into coastwise or Gulf waters and the tables change: buoyant apparatus or liferafts come into play.',
    footerChips: ['46 CFR 141.305', '46 CFR 141.360', '46 CFR 141.370', '46 CFR 141.375'],
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
          <span className="font-mono text-[9px] text-[#6b7594] tracking-[0.2em] uppercase ml-0.5 hidden sm:inline">Maritime Compliance Co-Pilot</span>
        </div>

        <div className="flex flex-col gap-0.5 py-3 min-h-[460px]">
          {/* 2026-10-16 UI pass — the vessel, as the chat's vessel pill shows it
              (it sat in the header, where it overflowed narrow cards). */}
          <div className="px-4 pt-0.5 pb-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03]
              px-2.5 py-1 font-mono text-[10px] text-[#8a94ad]">
              <svg className="w-3 h-3 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="5" r="2" /><path d="M12 7v14M5 12H3a9 9 0 0 0 18 0h-2M8 10h8" />
              </svg>
              {demo.vesselContext}
            </span>
          </div>
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
              <div className="mt-3 pt-3 border-t border-white/5">
                <div className="mb-2"><VerifiedBadge count={demo.footerChips.length} /></div>
                <div className="flex flex-wrap gap-1.5">
                  {demo.footerChips.map((c) => <StaticChip key={c} label={c} />)}
                </div>
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
            River towboat. Channel ferry. Hazmat fire. Liberian bulker. Cited answers, every time.
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
        {/* 2026-10-16 UI pass — three paragraphs cut to three short ones; the
            "purchased source texts" line went (no claim about how texts were
            obtained). */}
        <div className="flex flex-col gap-5">
          <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
            A commercial vessel answers to the CFR, Coast Guard policy, the IMO conventions and its flag
            state at once, and the answer changes with vessel type, tonnage, route and cargo. One missed
            detail at an inspection means a deficiency, a detention or worse.
          </p>
          <p className="font-mono text-[#f0ece4]/80 leading-relaxed text-sm md:text-base">
            RegKnot was built by a USCG Master Unlimited and her engineer brother. We know these
            regulations because we live them. This is the tool we wished existed.
          </p>
          <p className="font-mono text-[#6b7594] leading-relaxed text-sm md:text-base">
            General-purpose AI answers from memory. RegKnot answers from the regulation text and your
            vessel profile, and cites the section so you can check it.
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
            {/* 2026-10-16 UI pass — matches the answer prompt since 2026-10-09
                (rag.prompts.PROVENANCE_RULES): no invented figures, and who to
                confirm with, rather than "we hedge". */}
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              Every citation is checked against the text
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              General AI will cite a CFR section that doesn&apos;t exist. RegKnot checks every
              citation against the regulation text before you see it and drops any that don&apos;t
              hold up. When an exact figure isn&apos;t in the text, it won&apos;t make one up: it tells
              you who publishes it and who to confirm with.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              02 — Real source texts
            </div>
            {/* 2026-10-16 UI pass — "licensed editions" and "9 flag-state
                regulators" came out: no claim about how texts were obtained, and
                the corpus is tagged for 14 flag states. */}
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              The full texts, not web summaries
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              SOLAS, MARPOL, the IMDG Code, STCW and the ISM Code; recent IMO resolutions with
              their adoption and entry-into-force dates; the CFR, NVICs and Coast Guard policy;
              rules from 14 flag states. Ask about UN 3480 stowage and the answer comes from the
              Dangerous Goods List entry.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              03 — Vessel-specific scoping
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              The answer changes with your ship
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              A Subchapter M towboat, a Subchapter K passenger vessel and a UK-flag bulker in
              U.S. waters get different answers. RegKnot reads your vessel profile (flag,
              tonnage, route, subchapter, cargo) and scopes the search and the answer to it.
            </p>
          </div>

          <div className="bg-[#111827] border border-white/8 rounded-2xl p-6 md:p-7">
            {/* 2026-10-16 UI pass — "audited daily" / "every few days" came out:
                no review schedule exists. The three examples are real fixes
                (MARPOL Annex V 2026-09-26, COSWP flag tag 2026-10-08, pilot-ladder
                manila 2026-10-08/09). */}
            <div className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-3">
              04 — Built by mariners
            </div>
            <h3 className="font-display text-xl font-bold text-[#f0ece4] mb-3 leading-snug">
              A Master Unlimited behind it
            </h3>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
              Karynn holds a USCG Master Unlimited license and sails as a containership captain.
              Misses that she or our users flag (an Annex V exemption, another flag&apos;s rule, a
              pilot-ladder material) get traced to the source and fixed. A mariner in the loop,
              not a wrapper around an API.
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
            Snap your MMC, TWIC or medical certificate. RegKnot reads it, tracks the
            expiry and tells you what the regulations ask of you next.
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
            {/* 2026-10-16 UI pass — was "…, free": Career Path is a Mate feature. */}
            <p className="font-mono text-[10px] text-[#2dd4bf]/70 uppercase tracking-wider">
              Your next license, mapped to the CFR
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
          <span className="text-[#f0ece4]/85">RegKnot stores it and explains the rule behind it.</span>
        </p>
      </div>
    </section>
  )
}
