'use client'

// Sprint D6.83 Phase A5 — Print / PDF export route.
//
// Loads a saved generation (quiz or guide) and renders a stripped-down,
// print-friendly view. No app chrome, light background, generous margins,
// black-on-white text. Auto-triggers `window.print()` on first load so
// the user lands directly in the browser's Save-as-PDF dialog.
//
// Quizzes print with the answer key + explanations + citations inline
// so the printout doubles as a study packet (USCG candidates often work
// from paper). Guides print sections + key citations.
//
// Citation chips render a "[verified]" / "[not verified]" suffix instead
// of the colored badges since print readability is more important than
// brand colors at this stage.

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest } from '@/lib/api'

interface QuizQuestion {
  stem: string
  options: { A: string; B: string; C: string; D: string }
  correct_letter: 'A' | 'B' | 'C' | 'D'
  explanation: string
  citation: string
  difficulty: 'easy' | 'medium' | 'hard'
  verified?: boolean
}

interface QuizContent {
  title: string
  topic: string
  questions: QuizQuestion[]
  citation_verification_rate?: number
  citations_verified?: number
  citations_total?: number
}

interface GuideSection {
  heading: string
  content_md: string
  citations: string[]
  verified_citations?: string[]
  unverified_citations?: string[]
}

interface GuideContent {
  title: string
  topic: string
  sections: GuideSection[]
  key_citations: string[]
  verified_key_citations?: string[]
  unverified_key_citations?: string[]
  citation_verification_rate?: number
  citations_verified?: number
  citations_total?: number
}

interface GenerationDetail {
  id: string
  kind: 'quiz' | 'guide'
  title: string
  topic: string
  topic_key: string | null
  content_json: QuizContent | GuideContent
  model_used: string
  created_at: string
  archived_at: string | null
}

export default function PrintPage() {
  return (
    <AuthGuard>
      <PrintContent />
    </AuthGuard>
  )
}

function PrintContent() {
  const params = useParams()
  const id = params.id as string

  const [detail, setDetail] = useState<GenerationDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const d = await apiRequest<GenerationDetail>(`/study/library/${id}`)
        if (cancelled) return
        setDetail(d)
        // Tiny delay so the layout paints before print dialog opens —
        // otherwise some browsers (Chrome) capture a half-rendered page.
        setTimeout(() => {
          if (!cancelled) window.print()
        }, 400)
      } catch (err) {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : 'Could not load generation'
        setError(msg)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [id])

  if (error) {
    return (
      <div className="min-h-screen bg-white text-black p-8 print:p-0">
        <p className="font-mono text-sm text-red-600">{error}</p>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="min-h-screen bg-white text-black p-8 print:p-0">
        <p className="font-mono text-sm text-gray-600">Loading…</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-white text-black">
      {/* Print-specific styling. We rely on Tailwind's `print:` variant
          for most of this, with a small inline `@media print` block for
          page margins / hiding the action bar. */}
      <style jsx global>{`
        @media print {
          @page { margin: 0.6in 0.55in 0.6in 0.55in; }
          .no-print { display: none !important; }
          body { background: white !important; }
          /* Avoid orphan question stems splitting from their options. */
          .quiz-question { break-inside: avoid; page-break-inside: avoid; }
          .guide-section { break-inside: avoid-page; page-break-inside: avoid; }
        }
        @media screen {
          body { background: #f3f4f6; }
        }
      `}</style>

      <div className="max-w-4xl mx-auto bg-white p-8 print:p-0 print:max-w-full print:mx-0">

        {/* Action bar — hidden on print */}
        <div className="no-print mb-6 flex items-center justify-between border-b border-gray-200 pb-3">
          <button
            onClick={() => window.print()}
            className="bg-black text-white px-4 py-1.5 text-sm font-bold rounded hover:bg-gray-800"
          >
            Print / Save as PDF
          </button>
          <a
            href={`/study/${id}`}
            className="text-sm text-gray-600 hover:text-black underline"
          >
            ← Back to Study Tools
          </a>
        </div>

        {/* Document header */}
        <header className="mb-6 pb-4 border-b-2 border-black">
          <p className="text-xs uppercase tracking-widest text-gray-500 mb-1">
            RegKnots · Study Tools · {detail.kind === 'quiz' ? 'Quiz' : 'Study guide'}
          </p>
          <h1 className="text-2xl font-bold mb-1">{detail.title}</h1>
          <p className="text-xs text-gray-600">
            Topic: {detail.topic} · Generated {new Date(detail.created_at).toLocaleDateString()}
            {' · '}
            <PrintVerificationLine
              verified={detail.content_json.citations_verified}
              total={detail.content_json.citations_total}
            />
          </p>
        </header>

        {detail.kind === 'quiz'
          ? <QuizPrint quiz={detail.content_json as QuizContent} />
          : <GuidePrint guide={detail.content_json as GuideContent} />}

        <footer className="mt-8 pt-3 border-t border-gray-300 text-xs text-gray-500">
          <p>
            Generated by RegKnots Study Tools using {detail.model_used.replace(/^claude-/, '')}.
            Citations verified against the RegKnots regulations corpus where possible.
            Always confirm against the official regulation before relying on for compliance decisions.
          </p>
        </footer>
      </div>
    </div>
  )
}

function PrintVerificationLine({
  verified, total,
}: {
  verified?: number
  total?: number
}) {
  if (verified === undefined || total === undefined || total === 0) return null
  return (
    <span className="text-gray-700">
      {verified} of {total} citations verified
    </span>
  )
}

// ── Quiz print rendering ───────────────────────────────────────────────────

function QuizPrint({ quiz }: { quiz: QuizContent }) {
  return (
    <>
      <p className="text-sm mb-5 text-gray-700">
        Answer key, explanations, and citations follow each question.
        For a clean test-yourself printout, use the browser's "Print
        selection" feature to print just the question stems and options.
      </p>

      <ol className="space-y-5 list-none">
        {(quiz.questions || []).map((q, i) => (
          <li key={i} className="quiz-question">
            <p className="font-semibold mb-2">
              <span className="mr-2">{i + 1}.</span>
              {q.stem}
              <span className="ml-2 text-xs text-gray-500 uppercase">
                [{q.difficulty}]
              </span>
            </p>
            <ul className="ml-5 mb-2 space-y-0.5">
              {(['A', 'B', 'C', 'D'] as const).map((letter) => {
                const isCorrect = letter === q.correct_letter
                return (
                  <li
                    key={letter}
                    className={isCorrect ? 'font-semibold' : ''}
                  >
                    <span className="font-bold mr-2">{letter}.</span>
                    {q.options[letter]}
                    {isCorrect && <span className="ml-2 text-xs">✓ correct</span>}
                  </li>
                )
              })}
            </ul>
            <div className="ml-5 mt-1 pl-3 border-l-2 border-gray-300 text-sm">
              <p className="text-gray-800 mb-1">{q.explanation}</p>
              <p className="text-xs text-gray-600">
                Citation: <span className="font-mono">{q.citation}</span>
                {q.verified === true && <span className="ml-2 text-green-700">[verified]</span>}
                {q.verified === false && <span className="ml-2 text-orange-700">[not verified]</span>}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </>
  )
}

// ── Guide print rendering ──────────────────────────────────────────────────

function GuidePrint({ guide }: { guide: GuideContent }) {
  return (
    <>
      <div className="space-y-6">
        {(guide.sections || []).map((s, i) => {
          const verifiedSet = new Set(s.verified_citations || [])
          const unverifiedSet = new Set(s.unverified_citations || [])
          return (
            <article key={i} className="guide-section">
              <h2 className="text-lg font-bold mb-2 border-b border-gray-300 pb-1">
                {s.heading}
              </h2>
              {/* Plain whitespace-pre-wrap is fine for print — markdown
                  formatting is preserved as text and the user is going
                  to read this on paper, not navigate it. Bolds will look
                  like literal asterisks in print, but the alternative
                  (dragging react-markdown into a print route) trades
                  bundle size for cosmetic gain on a printout. Acceptable
                  for v1. */}
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {s.content_md}
              </p>
              {s.citations && s.citations.length > 0 && (
                <p className="mt-2 text-xs text-gray-600">
                  <span className="font-semibold">Citations: </span>
                  {s.citations.map((c, idx) => {
                    const v = verifiedSet.has(c)
                      ? 'verified'
                      : unverifiedSet.has(c) ? 'not verified' : null
                    return (
                      <span key={c}>
                        <span className="font-mono">{c}</span>
                        {v && (
                          <span className={
                            v === 'verified' ? 'ml-1 text-green-700' : 'ml-1 text-orange-700'
                          }>
                            [{v}]
                          </span>
                        )}
                        {idx < s.citations.length - 1 && '; '}
                      </span>
                    )
                  })}
                </p>
              )}
            </article>
          )
        })}
      </div>

      {guide.key_citations && guide.key_citations.length > 0 && (
        <section className="mt-8 pt-4 border-t-2 border-black">
          <h2 className="text-base font-bold mb-2 uppercase tracking-wider">
            Key citations
          </h2>
          <ul className="list-disc list-inside text-sm space-y-0.5">
            {guide.key_citations.map((c) => {
              const verifiedSet = new Set(guide.verified_key_citations || [])
              const unverifiedSet = new Set(guide.unverified_key_citations || [])
              const v = verifiedSet.has(c)
                ? 'verified'
                : unverifiedSet.has(c) ? 'not verified' : null
              return (
                <li key={c}>
                  <span className="font-mono">{c}</span>
                  {v && (
                    <span className={
                      v === 'verified' ? 'ml-2 text-green-700' : 'ml-2 text-orange-700'
                    }>
                      [{v}]
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </>
  )
}
