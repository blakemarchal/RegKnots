'use client'

import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { CorpusBadges } from '@/components/CorpusBadges'

// Sprint D6.23 — public Coverage page. Honest framing of what's IN
// the corpus, what's PARTIAL, and what's NOT yet — counter to the
// marketing instinct, specifics about scope build trust faster than
// sweeping claims.
//
// The CorpusBadges component is the canonical chip render; this page
// adds the "what's curated vs what's full" honesty layer around it.

export default function CoveragePage() {
  return (
    <main className="min-h-screen bg-[#0a0e1a] text-[#f0ece4]">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="border-b border-white/8 px-5 md:px-10 py-4">
        <Link href="/" className="inline-flex items-center gap-2 text-[#f0ece4] hover:text-[#2dd4bf] transition-colors">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-lg font-bold tracking-wide">RegKnot</span>
        </Link>
      </header>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 py-16 md:py-20 max-w-4xl mx-auto">
        <p className="font-mono text-xs text-[#2dd4bf] uppercase tracking-[0.25em] mb-4">
          Coverage
        </p>
        <h1 className="font-display font-black text-[#f0ece4] leading-tight tracking-tight
          text-[clamp(32px,6vw,52px)] mb-6">
          What&apos;s in the knowledge base.
        </h1>
        <p className="font-mono text-[#6b7594] leading-relaxed max-w-2xl">
          We&apos;d rather be specific than impressive. Here&apos;s every regulation source
          RegKnot indexes, organized by where it sits in the chain of authority. Every
          answer cites one of these directly — if a topic isn&apos;t covered, we&apos;ll
          tell you instead of making something up.
        </p>
      </section>

      {/* ── Corpus chips (canonical render) ────────────────────────────── */}
      <section className="px-5 md:px-10 pb-16">
        <CorpusBadges
          mode="categorized"
          className="max-w-4xl mx-auto"
        />
      </section>

      {/* ── Coverage detail ────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 py-16 bg-[#111827]">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] mb-8 tracking-wide">
            How deep does coverage go?
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* International */}
            <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-5">
              <p className="font-mono text-[10px] uppercase tracking-widest text-[#2dd4bf] mb-2">
                International conventions
              </p>
              <h3 className="font-display text-lg font-bold mb-3">Full text</h3>
              <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
                SOLAS, MARPOL, COLREGs, STCW, ISM Code, IMDG Code in full. Plus the
                supplementary IMO instruments — HSC Code (high-speed craft), IGC Code
                (gas carriers), IBC Code (chemical tankers), CSS Code, and the Load Lines
                Convention. IACS Unified Requirements for class-society technical standards.
                These bind every vessel on international voyages regardless of flag.
              </p>
            </div>

            {/* US Federal */}
            <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-5">
              <p className="font-mono text-[10px] uppercase tracking-widest text-[#2dd4bf] mb-2">
                U.S. Federal
              </p>
              <h3 className="font-display text-lg font-bold mb-3">Full text</h3>
              <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
                CFR Titles 33, 46, and 49 in full (the regulations that bind U.S.-flag vessels
                and any vessel calling at a U.S. port). 46 USC Subtitle II for the underlying
                statute. NVIC, NMC policy letters, USCG Marine Safety Manual, and active
                MSIB / ALCOAST bulletins for guidance and operational notices.
              </p>
            </div>

            {/* Flag State */}
            <div className="bg-[#0a0e1a] rounded-lg border border-white/8 p-5 md:col-span-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-[#2dd4bf] mb-2">
                Non-U.S. flag-state regulators
              </p>
              <h3 className="font-display text-lg font-bold mb-3">Curated to the operational essentials</h3>
              <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
                For each non-U.S. flag, we&apos;ve indexed the specific notices a working
                mariner is most likely to need — drills, manning, lifesaving, fire safety,
                MARPOL implementation, dangerous goods, port-state interactions, certification.
                Not every flag-state notice ever published, but the ones with operational weight.
              </p>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 font-mono text-xs text-[#6b7594]">
                <li>• <span className="text-[#f0ece4]">UK (MCA)</span> — MGNs and MSNs covering passenger ferry operations, ro-ro stability, manning, drills, dangerous goods</li>
                <li>• <span className="text-[#f0ece4]">Australia (AMSA)</span> — Marine Orders 1, 11, 12, 15, 21, 25, 28, 30, 31, 32, 41, 42, 43, 47, 50, 51, 54, 70-74, 91, 95</li>
                <li>• <span className="text-[#f0ece4]">Singapore (MPA)</span> — Shipping Circulars + Port Marine Circulars on flag-state guidance and port operations</li>
                <li>• <span className="text-[#f0ece4]">Hong Kong (Marine Department)</span> — current Merchant Shipping Information Notes (MSINs)</li>
                <li>• <span className="text-[#f0ece4]">Norway (NMA / Sjøfartsdirektoratet)</span> — RSR / RSV / SM circulars on cyber, LSA, fire, manning, MLC, Polar Code</li>
                <li>• <span className="text-[#f0ece4]">Liberia (LISCR)</span> — Marine Notices on drills, manning, ISM, ISPS, fire, MARPOL, MLC, STCW, PSC</li>
                <li>• <span className="text-[#f0ece4]">Marshall Islands (RMI / IRI)</span> — Marine Notices on ISM, ISPS, LSA, BWM, MARPOL, manning, watchkeeping, enclosed spaces</li>
                <li>• <span className="text-[#f0ece4]">Bahamas (BMA)</span> — Marine Notices on lifesaving, fire, MARPOL implementation</li>
              </ul>
            </div>
          </div>

          {/* What's missing */}
          <div className="mt-10 bg-[#0a0e1a] rounded-lg border border-amber-900/40 p-5">
            <p className="font-mono text-[10px] uppercase tracking-widest text-amber-500 mb-2">
              Honest scope notes
            </p>
            <ul className="font-mono text-sm text-[#6b7594] leading-relaxed space-y-2">
              <li>
                <span className="text-[#f0ece4]">Translation pipeline coming.</span> Non-English
                regulators (France, Germany, Greece, Japan, China, Korea) are on the roadmap but
                require careful translation work — coming after we validate quality with the
                first non-English flag.
              </li>
              <li>
                <span className="text-[#f0ece4]">Class society rules.</span> We index IACS
                Unified Requirements (technical standards adopted by all major class societies)
                but not the proprietary class rules of ABS / DNV / Lloyd&apos;s Register / Bureau
                Veritas / ClassNK individually — those are paid publications.
              </li>
              <li>
                <span className="text-[#f0ece4]">Currency.</span> Sources are refreshed manually
                as amendments publish. We&apos;ll automate this for high-cadence sources
                (USCG bulletins, MOU campaigns) when traffic warrants.
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* ── Footer CTA ─────────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 py-16 max-w-4xl mx-auto text-center">
        <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] mb-4">
          Ask a regulation question.
        </h2>
        <p className="font-mono text-sm text-[#6b7594] mb-8 max-w-xl mx-auto">
          Try it on your real compliance question. Citations land on whichever source above
          actually answers — no guessing, no hallucination.
        </p>
        <Link
          href="/register"
          className="inline-flex font-mono font-bold text-sm uppercase tracking-wider
            bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
            hover:brightness-110 transition-[filter] duration-150"
        >
          Start Free Trial
        </Link>
      </section>
    </main>
  )
}
