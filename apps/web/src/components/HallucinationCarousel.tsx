'use client'

// Sprint D6.57 — landing-page proof of the hallucination claim.
//
// Rotating side-by-side examples: real ChatGPT answer (with the
// hallucinated bit highlighted) vs RegKnot's verified answer. Three
// cases sourced from a 2026-05-04 grading session against ChatGPT
// with web browsing enabled — these aren't cherry-picked weak-model
// examples; they're current-state failures of the strongest mass-
// market AI.
//
// Each case verifies in <60 seconds against eCFR / IMDG / NMC. The
// point isn't "ChatGPT is always wrong" — it's "ChatGPT confidently
// gives wrong answers at a non-zero rate, and you can't tell which
// is which without checking yourself."

import { useEffect, useState } from 'react'

interface Example {
  id: string
  question: string
  // ChatGPT's actual response, abridged. The `hallucinated` field
  // identifies the portion of the response that is factually wrong
  // and gets highlighted inline in the UI.
  chatgpt: {
    summary: string
    detail: string
    hallucinated: string  // exact substring of detail to highlight
  }
  // RegKnot's verified response — what we actually cite from corpus.
  regknot: {
    summary: string
    citation: string
    quote: string
    source: string
  }
  // Why this matters in plain English (one sentence).
  whyMatters: string
}


const EXAMPLES: Example[] = [
  {
    id: 'un3480',
    question: 'What’s the stowage category for UN 3480 (lithium-ion batteries packed without equipment) on a passenger vessel?',
    chatgpt: {
      summary: 'Bottom line: Category C — on deck only on passenger vessels.',
      detail:
        'Under the IMDG Code, UN 3480 (fully regulated lithium-ion batteries) is assigned Stowage Category C, which means “on deck only” on passenger vessels. If this is for a Coast Guard exam or company policy question, the expected answer is almost always Category C.',
      hallucinated: 'Stowage Category C, which means “on deck only” on passenger vessels',
    },
    regknot: {
      summary: 'Stowage Category: A — on or under deck on cargo and passenger ships.',
      citation: 'IMDG 3.2 — UN 3480',
      quote:
        'Stowage Category A means the substance may be stowed on or under deck on cargo ships and on or under deck on passenger ships. Stowage codes: SW19. Segregation codes: SG7.',
      source: 'IMDG Code, Volume 2, Dangerous Goods List entry for UN 3480',
    },
    whyMatters:
      'Over-restricting stowage based on a hallucinated category fails a tabletop audit and creates avoidable operational cost.',
  },
  {
    id: 'nvic0408',
    question: 'What’s NVIC 04-08 Change 2 specifically allow for STCW endorsements?',
    chatgpt: {
      summary:
        '“Grandfathering” of prior STCW training and assessments — transitional relief for the 2010 Manila Amendments.',
      detail:
        'NVIC 04-08, Change 2 is the Coast Guard policy that allows certain equivalencies and transitional provisions for STCW endorsements based on older service and credentialing paths—especially for mariners upgrading from domestic licenses or older STCW structures. It permits crediting of previously completed STCW courses that met earlier standards (pre-2010 Manila Amendments implementation) and assessments signed off under older guidance.',
      hallucinated: 'NVIC 04-08, Change 2 is the Coast Guard policy that allows certain equivalencies and transitional provisions for STCW endorsements',
    },
    regknot: {
      summary:
        'NVIC 04-08 is the Medical and Physical Evaluation Guidelines for Merchant Mariner Credentials. Change 2 updates medical evaluation criteria — not STCW endorsements.',
      citation: 'NVIC 04-08 Change 2',
      quote:
        'Hearing standards, environmental factors, stimulant medication evaluation — the actual Change 2 covers medical and physical evaluation guidelines used by NMC evaluators when reviewing MMC applications.',
      source: 'USCG NVIC 04-08 Change 2 (Medical and Physical Evaluation Guidelines)',
    },
    whyMatters:
      'Citing the wrong NVIC at an NMC office gets your application returned. ChatGPT’s confident answer here is about a completely different document.',
  },
  {
    id: 'solas2024',
    question: 'What MSC resolution updated SOLAS Chapter II-1 with new damage stability requirements in 2024?',
    chatgpt: {
      summary: 'MSC.549(108) — adopted at MSC 108 (2024), enters into force 1 January 2026.',
      detail:
        'The 2024 update to SOLAS Chapter II-1 damage stability requirements was adopted by the IMO Maritime Safety Committee as MSC.549(108). MSC 108 produced a package of SOLAS amendments, with MSC.549(108) for Chapter II-1 (structure, subdivision, stability) and MSC.550(108) for Chapter II-2 (fire safety).',
      hallucinated: 'MSC.549(108) for Chapter II-1 (structure, subdivision, stability) and MSC.550(108) for Chapter II-2 (fire safety)',
    },
    regknot: {
      summary:
        'The operational SOLAS Chapter II-1 amendments entering force 1 January 2026 are MSC.522(106) and MSC.534(107) — ingested with their entry-into-force timing so we can scope the answer to your vessel’s applicability date.',
      citation: 'SOLAS Supplement Jan 2026 — MSC.522(106), MSC.534(107)',
      quote:
        'January 2026 Amendment: Chapter II-1 Construction. Amendments adopted at MSC 106 and MSC 107 affecting subdivision, watertight integrity, and damage stability provisions for new ships.',
      source: 'IMO MSC adopted resolutions — SOLAS supplement, ingested verbatim',
    },
    whyMatters:
      'The number you cite to your DOC auditor matters. Citing a resolution number you can’t verify is a quick path to a Section 12 finding.',
  },
]


export function HallucinationCarousel() {
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)

  // Auto-advance every 12s, paused on hover/focus.
  useEffect(() => {
    if (paused) return
    const id = setInterval(() => {
      setActive((i) => (i + 1) % EXAMPLES.length)
    }, 12000)
    return () => clearInterval(id)
  }, [paused])

  const example = EXAMPLES[active]

  return (
    <div
      className="max-w-5xl mx-auto"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {/* Question header */}
      <div className="text-center mb-8">
        <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-3">
          Real question, real answers
        </p>
        <h3 className="font-display text-[#f0ece4] font-bold leading-tight tracking-tight
                       text-[clamp(20px,3vw,28px)] max-w-3xl mx-auto px-2">
          &ldquo;{example.question}&rdquo;
        </h3>
      </div>

      {/* Side-by-side panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5">
        {/* ── ChatGPT panel — light styling that evokes the chatbot UI ── */}
        <div className="rounded-2xl bg-[#f7f7f8] text-[#1f1f1f] p-5 md:p-6
                        border border-[#d9d9e3] flex flex-col gap-3 min-h-[280px]">
          <div className="flex items-center gap-2 pb-3 border-b border-[#e5e5e5]">
            <div className="w-6 h-6 rounded-full bg-[#10a37f] flex items-center justify-center
                            text-white text-[11px] font-bold flex-shrink-0">
              AI
            </div>
            <span className="text-[12px] font-medium text-[#1f1f1f]">ChatGPT</span>
            <span className="ml-auto text-[10px] font-medium text-[#dc2626] bg-[#fee2e2]
                             border border-[#fecaca] rounded px-1.5 py-0.5 uppercase tracking-wider">
              ! Hallucination
            </span>
          </div>
          <p className="text-[14px] font-semibold leading-snug text-[#1f1f1f]">
            {example.chatgpt.summary}
          </p>
          <p className="text-[13px] leading-relaxed text-[#374151]">
            {renderHighlighted(example.chatgpt.detail, example.chatgpt.hallucinated)}
          </p>
        </div>

        {/* ── RegKnot panel — dark, brand styling, verified citation ── */}
        <div className="rounded-2xl bg-[#0a0e1a] text-[#f0ece4] p-5 md:p-6
                        border border-[#2dd4bf]/40 shadow-[0_0_30px_rgba(45,212,191,0.08)]
                        flex flex-col gap-3 min-h-[280px]">
          <div className="flex items-center gap-2 pb-3 border-b border-white/10">
            <svg viewBox="0 0 24 24" className="w-6 h-6 text-[#2dd4bf] flex-shrink-0"
                 fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
              <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
            </svg>
            <span className="text-[12px] font-medium text-[#f0ece4]">RegKnot</span>
            <span className="ml-auto text-[10px] font-bold text-[#2dd4bf] bg-[#2dd4bf]/15
                             border border-[#2dd4bf]/40 rounded px-1.5 py-0.5
                             uppercase tracking-wider flex items-center gap-1">
              <svg className="w-2.5 h-2.5" viewBox="0 0 16 16" fill="currentColor">
                <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
              </svg>
              Verified
            </span>
          </div>
          <p className="text-[14px] font-semibold leading-snug text-[#f0ece4]">
            {example.regknot.summary}
          </p>
          <div className="bg-[#0d1225] border border-[#2dd4bf]/20 rounded-lg p-3">
            <p className="font-mono text-[10px] text-[#2dd4bf] mb-1.5 uppercase tracking-wider">
              Cited — {example.regknot.citation}
            </p>
            <p className="font-mono text-[12px] leading-relaxed text-[#f0ece4]/85">
              &ldquo;{example.regknot.quote}&rdquo;
            </p>
          </div>
          <p className="font-mono text-[10px] text-[#6b7594] leading-relaxed mt-auto">
            Source: {example.regknot.source}
          </p>
        </div>
      </div>

      {/* Why this matters */}
      <div className="text-center mt-6">
        <p className="font-mono text-[12px] text-[#6b7594] leading-relaxed max-w-2xl mx-auto px-2">
          <span className="text-[#f0ece4]/80">Why this matters:</span> {example.whyMatters}
        </p>
      </div>

      {/* Pagination dots */}
      <div className="flex justify-center gap-2 mt-7">
        {EXAMPLES.map((ex, i) => (
          <button
            key={ex.id}
            onClick={() => setActive(i)}
            aria-label={`Show example ${i + 1}`}
            className={`h-2 rounded-full transition-all duration-200 ${
              i === active
                ? 'w-8 bg-[#2dd4bf]'
                : 'w-2 bg-white/15 hover:bg-white/30'
            }`}
          />
        ))}
      </div>
    </div>
  )
}


/**
 * Render `text` with the substring `mark` wrapped in a red-underline
 * span. Falls back to plain text if `mark` is empty or not found.
 * Designed for use inside ChatGPT-styled paragraphs to draw the eye
 * to the specific hallucinated phrase without overformatting the
 * whole answer.
 */
function renderHighlighted(text: string, mark: string) {
  if (!mark) return text
  const idx = text.indexOf(mark)
  if (idx < 0) return text
  return (
    <>
      {text.slice(0, idx)}
      <span className="bg-[#fee2e2] text-[#991b1b] underline decoration-[#dc2626]
                       decoration-wavy decoration-[1.5px] underline-offset-[3px]
                       rounded px-0.5">
        {text.slice(idx, idx + mark.length)}
      </span>
      {text.slice(idx + mark.length)}
    </>
  )
}
