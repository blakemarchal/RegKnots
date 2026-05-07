'use client'

// Sprint D6.83 Phase A3 — Study Tools landing page.
//
// Single-page surface for the quiz + study guide generators with a
// "library" section showing the user's recent generations. Tier-gated:
// free tier sees an upsell, Mate sees a usage counter (200/mo cap),
// Captain is unlimited.
//
// Phase A4 layers the take-the-quiz interactive flow on top of this
// page (a dedicated /study/[id]/take route that consumes the quiz
// JSON shape produced by /api/study/quiz).

import { useEffect, useState } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { AILoadingState } from '@/components/AILoadingState'
import { apiRequest } from '@/lib/api'

// ── Types matching the API response shapes ─────────────────────────────────

interface QuizQuestion {
  stem: string
  options: { A: string; B: string; C: string; D: string }
  correct_letter: 'A' | 'B' | 'C' | 'D'
  explanation: string
  citation: string
  difficulty: 'easy' | 'medium' | 'hard'
}

interface QuizContent {
  title: string
  topic: string
  questions: QuizQuestion[]
}

interface GuideSection {
  heading: string
  content_md: string
  citations: string[]
}

interface GuideContent {
  title: string
  topic: string
  sections: GuideSection[]
  key_citations: string[]
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

interface GenerationSummary {
  id: string
  kind: 'quiz' | 'guide'
  title: string
  topic: string
  topic_key: string | null
  model_used: string
  created_at: string
  archived_at: string | null
}

interface UsageDTO {
  tier: string
  used_this_month: number
  cap: number | null
  can_generate: boolean
}

// ── Suggested-topic chips ──────────────────────────────────────────────────
//
// Hand-curated covering the highest-traffic USCG exam categories.
// Free-text input remains primary — these are starters, not a fixed
// taxonomy. Each chip is the literal topic string sent to the API.

const SUGGESTED_QUIZ_TOPICS = [
  'Lifeboat inspection requirements',
  'COLREGs Rule 13 overtaking',
  'Fire pump capacity small passenger vessel',
  'MARPOL Annex VI sulfur ECA',
  'Subchapter M TSMS',
  'Tankerman-PIC endorsement',
  'Engine room watch standing',
  'STCW basic safety training',
] as const

const SUGGESTED_GUIDE_TOPICS = [
  'MMC renewal — what to gather and when',
  'Medical certificate (CG-719K) — what examiners look for',
  'Stability principles for small passenger vessels',
  'Ballast water management compliance',
  'Hazmat segregation tables (IMDG)',
  'Polar Code crew qualifications',
  'Engineer license endorsement ladder',
  'Sea-service letter — what counts and how to log it',
] as const

// ── Page component ─────────────────────────────────────────────────────────

export default function StudyToolsPage() {
  return (
    <AuthGuard>
      <StudyToolsContent />
    </AuthGuard>
  )
}

function StudyToolsContent() {
  // Generator form state
  const [mode, setMode] = useState<'quiz' | 'guide'>('quiz')
  const [topic, setTopic] = useState('')
  const [deepDive, setDeepDive] = useState(false)        // guide-only
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState<GenerationDetail | null>(null)

  // Library + usage state (lazy fetched on mount and after successful generation)
  const [library, setLibrary] = useState<GenerationSummary[]>([])
  const [usage, setUsage] = useState<UsageDTO | null>(null)
  const [showArchived, setShowArchived] = useState(false)

  // Initial load — usage + library in parallel.
  useEffect(() => {
    void refreshUsage()
    void refreshLibrary(false)
  }, [])

  async function refreshUsage() {
    try {
      const u = await apiRequest<UsageDTO>('/study/usage')
      setUsage(u)
    } catch {
      // 401/403 handled by AuthGuard; silent on transient errors
    }
  }

  async function refreshLibrary(includeArchived: boolean) {
    try {
      const qs = includeArchived ? '?include_archived=true' : ''
      const items = await apiRequest<GenerationSummary[]>(`/study/library${qs}`)
      setLibrary(items)
    } catch {
      setLibrary([])
    }
  }

  async function handleGenerate() {
    if (!topic.trim()) {
      setError('Enter a topic first.')
      return
    }
    if (usage && !usage.can_generate) {
      // Defensive — usually we surface the upsell instead of letting the
      // user click. But just in case, fall back here.
      setError('You are out of generations for this month. Upgrade or wait until next month.')
      return
    }
    setGenerating(true)
    setError(null)
    setCurrent(null)
    try {
      const path = mode === 'quiz' ? '/study/quiz' : '/study/guide'
      const body: Record<string, unknown> = { topic: topic.trim() }
      if (mode === 'guide') body.deep_dive = deepDive
      const result = await apiRequest<GenerationDetail>(path, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setCurrent(result)
      // Refresh usage + library so the new gen shows in the count and list.
      void refreshUsage()
      void refreshLibrary(showArchived)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Generation failed'
      // Friendly error text — the API returns 402 for cap-hit, 400 for
      // topic-too-broad, 502 for parse failure, 503 for upstream issues.
      if (msg.includes('402')) {
        setError(
          "You've hit your monthly Study Tools limit. Upgrade to Captain for unlimited, or wait until next month.",
        )
        void refreshUsage()
      } else if (msg.includes('400')) {
        setError("That topic was too broad to find good source material. Try something more specific.")
      } else if (msg.includes('502')) {
        setError("The generator returned an unparseable response. Please try again.")
      } else if (msg.includes('503')) {
        setError("The generator is temporarily unavailable. Try again in a moment.")
      } else {
        setError(msg)
      }
    } finally {
      setGenerating(false)
    }
  }

  function pickChip(t: string) {
    setTopic(t)
    setError(null)
  }

  async function openGeneration(id: string) {
    try {
      const detail = await apiRequest<GenerationDetail>(`/study/library/${id}`)
      setCurrent(detail)
      // Scroll to top so the user sees the loaded result.
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch {
      setError('Could not load that generation.')
    }
  }

  async function archiveGeneration(id: string) {
    try {
      await apiRequest(`/study/library/${id}/archive`, { method: 'POST' })
      void refreshLibrary(showArchived)
    } catch { /* silent */ }
  }

  async function unarchiveGeneration(id: string) {
    try {
      await apiRequest(`/study/library/${id}/unarchive`, { method: 'POST' })
      void refreshLibrary(showArchived)
    } catch { /* silent */ }
  }

  function toggleArchived() {
    const next = !showArchived
    setShowArchived(next)
    void refreshLibrary(next)
  }

  const suggestions = mode === 'quiz' ? SUGGESTED_QUIZ_TOPICS : SUGGESTED_GUIDE_TOPICS
  const tierBlocked = usage && !usage.can_generate && usage.cap === 0

  return (
    <div className="flex flex-col min-h-screen bg-[#0a0e1a]">
      <AppHeader title="Study Tools" />

      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-md md:max-w-3xl mx-auto flex flex-col gap-5">

          {/* ── Tier-blocked upsell ─────────────────────────────────────── */}
          {tierBlocked && (
            <section className="bg-[#111827] border border-amber-400/30 rounded-xl p-5">
              <p className="font-display text-lg font-bold text-[#f0ece4] mb-2">
                Study Tools require Mate or Captain
              </p>
              <p className="font-mono text-sm text-[#6b7594] leading-relaxed mb-4">
                The quiz and study-guide generators are part of the paid tiers.
                Both pull from the same USCG exam pool and cite real regulations
                — your study time stays grounded.
              </p>
              <Link
                href="/pricing"
                className="inline-block font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                  hover:brightness-110 rounded-lg px-4 py-2 transition-[filter] duration-150"
              >
                See plans →
              </Link>
            </section>
          )}

          {/* ── Generator form ──────────────────────────────────────────── */}
          {!tierBlocked && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
              {/* Mode toggle */}
              <div className="flex items-center gap-1 bg-[#0d1225] rounded-full p-1 border border-white/8 self-start">
                <ModeButton active={mode === 'quiz'} onClick={() => setMode('quiz')}>
                  Quiz
                </ModeButton>
                <ModeButton active={mode === 'guide'} onClick={() => setMode('guide')}>
                  Study guide
                </ModeButton>
              </div>

              {/* Topic input */}
              <div className="flex flex-col gap-1">
                <label className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">
                  Topic
                </label>
                <input
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder={
                    mode === 'quiz'
                      ? 'e.g. lifeboat inspection requirements'
                      : 'e.g. MMC renewal — what to gather'
                  }
                  className="font-mono text-sm bg-[#0d1225] border border-white/10 rounded-lg
                    px-3 py-2 text-[#f0ece4] outline-none focus:border-[#2dd4bf]
                    transition-colors"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !generating) handleGenerate()
                  }}
                />
              </div>

              {/* Suggested-topic chips */}
              <div className="flex flex-col gap-2">
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-widest">
                  Try one of these
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      onClick={() => pickChip(s)}
                      className="font-mono text-[11px] text-[#6b7594] border border-white/10
                        rounded-full px-2.5 py-1
                        hover:text-[#2dd4bf] hover:border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/5
                        transition-colors duration-150"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>

              {/* Deep-dive toggle (guide mode only) */}
              {mode === 'guide' && (
                <div className="flex items-center gap-2">
                  <input
                    id="deep-dive"
                    type="checkbox"
                    checked={deepDive}
                    onChange={(e) => setDeepDive(e.target.checked)}
                    className="accent-[#2dd4bf]"
                  />
                  <label htmlFor="deep-dive" className="font-mono text-xs text-[#f0ece4]/80 cursor-pointer">
                    Deep dive (longer, deeper analysis — uses more of your monthly quota)
                  </label>
                </div>
              )}

              {/* Submit */}
              <div className="flex items-center gap-3 flex-wrap">
                <button
                  onClick={handleGenerate}
                  disabled={generating || !topic.trim()}
                  className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                    hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed
                    rounded-lg px-4 py-2 transition-[filter] duration-150"
                >
                  {generating
                    ? mode === 'quiz' ? 'Generating quiz…' : 'Writing guide…'
                    : mode === 'quiz' ? 'Generate quiz' : 'Generate guide'}
                </button>
                {usage && (
                  <span className="font-mono text-xs text-[#6b7594]">
                    {usage.cap === null
                      ? `Unlimited · ${usage.used_this_month} this month`
                      : `${usage.used_this_month} of ${usage.cap} used this month`}
                  </span>
                )}
              </div>

              {error && (
                <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                  {error}
                </p>
              )}
            </section>
          )}

          {/* ── Generation result ───────────────────────────────────────── */}
          {generating && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-6">
              <AILoadingState
                messages={
                  mode === 'quiz'
                    ? [
                        'Pulling exam-pool questions on this topic…',
                        'Cross-referencing with the regulation corpus…',
                        'Drafting questions and grading distractors…',
                      ]
                    : [
                        'Pulling regulation passages on this topic…',
                        'Identifying what exam writers commonly test…',
                        'Drafting your guide…',
                      ]
                }
                variant="card"
              />
            </section>
          )}

          {!generating && current && current.kind === 'quiz' && (
            <QuizResult
              detail={current}
              onRetake={() => {
                setTopic(current.topic)
                setMode('quiz')
                window.scrollTo({ top: 0, behavior: 'smooth' })
              }}
            />
          )}

          {!generating && current && current.kind === 'guide' && (
            <GuideResult detail={current} />
          )}

          {/* ── Library ──────────────────────────────────────────────────── */}
          {!tierBlocked && (
            <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="font-display text-base font-bold text-[#f0ece4] tracking-wide">
                  Your library
                </h2>
                <button
                  onClick={toggleArchived}
                  className={`font-mono text-[11px] px-2.5 py-1 rounded-full border transition-colors duration-150
                    ${showArchived
                      ? 'border-amber-400/40 bg-amber-400/10 text-amber-400'
                      : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                    }`}
                >
                  {showArchived ? 'Hide archived' : 'Show archived'}
                </button>
              </div>

              {library.length === 0 ? (
                <p className="font-mono text-xs text-[#6b7594]">
                  Nothing yet. Generate a quiz or guide above and it&apos;ll show here.
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {library.map((item) => (
                    <LibraryRow
                      key={item.id}
                      item={item}
                      onOpen={() => openGeneration(item.id)}
                      onArchive={() => archiveGeneration(item.id)}
                      onUnarchive={() => unarchiveGeneration(item.id)}
                    />
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

// ── Mode toggle button ─────────────────────────────────────────────────────

function ModeButton({
  children, active, onClick,
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`font-mono text-xs font-bold px-4 py-1.5 rounded-full transition-colors duration-150
        ${active
          ? 'bg-[#2dd4bf] text-[#0a0e1a]'
          : 'text-[#6b7594] hover:text-[#f0ece4]'
        }`}
    >
      {children}
    </button>
  )
}

// ── Quiz result rendering ──────────────────────────────────────────────────

function QuizResult({
  detail, onRetake,
}: { detail: GenerationDetail; onRetake: () => void }) {
  const quiz = detail.content_json as QuizContent
  const [showAnswers, setShowAnswers] = useState(false)

  // Phase A4 will add a take-the-quiz route. For now, we can show
  // questions inline with a toggle to reveal answers + explanations.
  return (
    <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-1">
            Quiz · {quiz.questions.length} questions
          </p>
          <h2 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">
            {quiz.title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/study/${detail.id}/take`}
            className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 rounded-lg px-3 py-1.5 transition-[filter] duration-150"
          >
            Take quiz →
          </Link>
          <button
            onClick={() => setShowAnswers((v) => !v)}
            className="font-mono text-xs text-[#6b7594] border border-white/10 rounded-lg
              px-3 py-1.5 hover:text-[#f0ece4] hover:border-white/20 transition-colors"
          >
            {showAnswers ? 'Hide answers' : 'Show answers'}
          </button>
        </div>
      </header>

      <ol className="flex flex-col gap-3 list-none">
        {quiz.questions.map((q, i) => (
          <li
            key={i}
            className="border-l-2 border-[#2dd4bf]/30 pl-4 py-1"
          >
            <p className="font-mono text-sm text-[#f0ece4] leading-relaxed mb-2">
              <span className="text-[#2dd4bf] font-bold mr-2">{i + 1}.</span>
              {q.stem}
              <DifficultyChip difficulty={q.difficulty} />
            </p>
            <ul className="flex flex-col gap-1 ml-6">
              {(['A', 'B', 'C', 'D'] as const).map((letter) => {
                const isCorrect = showAnswers && letter === q.correct_letter
                return (
                  <li
                    key={letter}
                    className={`font-mono text-xs leading-relaxed
                      ${isCorrect
                        ? 'text-[#2dd4bf] font-bold'
                        : 'text-[#f0ece4]/70'
                      }`}
                  >
                    <span className="font-bold mr-2">{letter}.</span>
                    {q.options[letter]}
                    {isCorrect && <span className="ml-2 text-[10px] uppercase tracking-wider">✓ correct</span>}
                  </li>
                )
              })}
            </ul>
            {showAnswers && (
              <div className="mt-2 ml-6 border-l border-amber-400/30 pl-3">
                <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed mb-1">
                  {q.explanation}
                </p>
                <StaticChip label={q.citation} />
              </div>
            )}
          </li>
        ))}
      </ol>

      <footer className="flex items-center justify-between flex-wrap gap-2 pt-2 border-t border-white/8">
        <p className="font-mono text-[10px] text-[#6b7594]">
          Generated {new Date(detail.created_at).toLocaleString()} · {detail.model_used.replace(/^claude-/, '')}
        </p>
        <button
          onClick={onRetake}
          className="font-mono text-[11px] text-[#2dd4bf] hover:underline"
        >
          Generate another on this topic
        </button>
      </footer>
    </section>
  )
}

// ── Guide result rendering ─────────────────────────────────────────────────

function GuideResult({ detail }: { detail: GenerationDetail }) {
  const guide = detail.content_json as GuideContent

  return (
    <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-4">
      <header>
        <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest mb-1">
          Study guide · {guide.sections?.length ?? 0} sections
        </p>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">
          {guide.title}
        </h2>
      </header>

      <div className="flex flex-col gap-5">
        {(guide.sections || []).map((s, i) => (
          <article key={i} className="border-l-2 border-[#2dd4bf]/30 pl-4">
            <h3 className="font-display text-base font-bold text-[#2dd4bf] tracking-wide mb-2">
              {s.heading}
            </h3>
            <div className="font-mono text-sm text-[#f0ece4]/85 leading-relaxed whitespace-pre-wrap">
              {s.content_md}
            </div>
            {s.citations && s.citations.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {s.citations.map((c) => (
                  <StaticChip key={c} label={c} />
                ))}
              </div>
            )}
          </article>
        ))}
      </div>

      {guide.key_citations && guide.key_citations.length > 0 && (
        <div className="border-t border-white/8 pt-3">
          <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-widest mb-2">
            Key citations
          </p>
          <div className="flex flex-wrap gap-1.5">
            {guide.key_citations.map((c) => (
              <StaticChip key={c} label={c} />
            ))}
          </div>
        </div>
      )}

      <footer className="flex items-center justify-between flex-wrap gap-2 pt-2 border-t border-white/8">
        <p className="font-mono text-[10px] text-[#6b7594]">
          Generated {new Date(detail.created_at).toLocaleString()} · {detail.model_used.replace(/^claude-/, '')}
        </p>
      </footer>
    </section>
  )
}

// ── Library row ────────────────────────────────────────────────────────────

function LibraryRow({
  item, onOpen, onArchive, onUnarchive,
}: {
  item: GenerationSummary
  onOpen: () => void
  onArchive: () => void
  onUnarchive: () => void
}) {
  const isArchived = item.archived_at !== null
  return (
    <li
      className={`relative bg-[#0d1225] border-l-2 rounded-r-xl transition-all duration-150
        ${isArchived
          ? 'border-white/10 opacity-70 hover:opacity-100'
          : 'border-[#2dd4bf]/30 hover:border-[#2dd4bf]'}`}
    >
      <button
        onClick={onOpen}
        className="w-full text-left px-3 py-2.5 pr-12"
      >
        <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
          {item.title}
        </p>
        <p className="font-mono text-xs text-[#6b7594] mt-0.5">
          <span className={`text-[10px] uppercase tracking-wider mr-2
            ${item.kind === 'quiz' ? 'text-[#2dd4bf]' : 'text-[#9b87f5]'}`}>
            {item.kind}
          </span>
          {new Date(item.created_at).toLocaleDateString()}
          {isArchived && <span className="ml-2 text-amber-400/70">· archived</span>}
        </p>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          isArchived ? onUnarchive() : onArchive()
        }}
        aria-label={isArchived ? 'Unarchive' : 'Archive'}
        title={isArchived ? 'Restore' : 'Archive'}
        className="absolute top-2 right-2 p-1.5 rounded-md
          text-[#6b7594] hover:text-amber-400 hover:bg-amber-400/10
          transition-colors duration-150"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor"
             strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {isArchived ? (
            <>
              <path d="M3 10a7 7 0 1 1 2 4.95" />
              <path d="M3 16v-4h4" />
            </>
          ) : (
            <>
              <rect x="3" y="4" width="14" height="3" rx="0.5" />
              <path d="M4 7v8a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7" />
              <path d="M8 11h4" />
            </>
          )}
        </svg>
      </button>
    </li>
  )
}

// ── Difficulty chip + static citation chip ─────────────────────────────────

function DifficultyChip({ difficulty }: { difficulty: 'easy' | 'medium' | 'hard' }) {
  const colors = {
    easy: 'bg-emerald-950/70 text-emerald-400 border-emerald-800/50',
    medium: 'bg-blue-950/70 text-blue-400 border-blue-800/50',
    hard: 'bg-rose-950/70 text-rose-400 border-rose-800/50',
  }[difficulty]
  return (
    <span className={`ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px]
      font-medium border ${colors} leading-none align-baseline`}>
      {difficulty}
    </span>
  )
}

function StaticChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
      bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none align-baseline mr-1">
      {label}
    </span>
  )
}
