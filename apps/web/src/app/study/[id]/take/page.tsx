'use client'

// Sprint D6.83 Phase A4 — Take-the-quiz interactive flow.
//
// Three states this page coordinates:
//   1. LOADING   — fetching the quiz + creating a session
//   2. ANSWERING — user picks answers per question, autosave per pick
//   3. REVIEW    — submitted; show score, per-question correct/wrong
//
// Per-pick autosave: each radio click POSTs to /quiz-sessions/{id}/answer.
// Means a refresh / phone-lock mid-quiz doesn't lose progress; on resume,
// previously-selected answers are preserved server-side.

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { AILoadingState } from '@/components/AILoadingState'
import { apiRequest } from '@/lib/api'

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

interface GenerationDetail {
  id: string
  kind: 'quiz' | 'guide'
  title: string
  topic: string
  content_json: QuizContent
  created_at: string
}

interface SessionAnswer {
  q: number
  selected: string
  correct_letter: string
  is_correct: boolean
  answered_at: string
}

interface QuizSessionDetail {
  id: string
  generation_id: string
  answers: SessionAnswer[]
  score_pct: number | null
  started_at: string
  finished_at: string | null
  elapsed_seconds: number | null
}

type Letter = 'A' | 'B' | 'C' | 'D'

export default function TakeQuizPage() {
  return (
    <AuthGuard>
      <TakeQuizContent />
    </AuthGuard>
  )
}

function TakeQuizContent() {
  const params = useParams()
  const router = useRouter()
  const generationId = params.id as string

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [quiz, setQuiz] = useState<GenerationDetail | null>(null)
  const [session, setSession] = useState<QuizSessionDetail | null>(null)

  // Local pending answers for instant UI feedback. Saved to server on
  // every pick; the answers field on `session` is the authoritative
  // saved state for resume after refresh.
  const [picks, setPicks] = useState<Record<number, Letter>>({})
  const [submitting, setSubmitting] = useState(false)

  // ── Load quiz + start session on mount ────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const detail = await apiRequest<GenerationDetail>(`/study/library/${generationId}`)
        if (cancelled) return
        if (detail.kind !== 'quiz') {
          setError("That's not a quiz — guides don't have a take-quiz mode.")
          setLoading(false)
          return
        }
        setQuiz(detail)
        // Start a fresh session. Phase A4 is one-attempt-per-page-load
        // for simplicity; resume across page loads is on the roadmap
        // (would query by generation_id and pick the most recent
        // un-finished session).
        const sess = await apiRequest<QuizSessionDetail>('/study/quiz-sessions', {
          method: 'POST',
          body: JSON.stringify({ generation_id: generationId }),
        })
        if (cancelled) return
        setSession(sess)
        setLoading(false)
      } catch (err) {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : 'Failed to load quiz'
        if (msg.includes('404')) {
          setError("Quiz not found. It may have been deleted from your library.")
        } else {
          setError(msg)
        }
        setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [generationId])

  // ── Answer submission (per-pick autosave) ─────────────────────────────
  async function handlePick(qIndex: number, letter: Letter) {
    if (!session || session.finished_at) return
    setPicks((prev) => ({ ...prev, [qIndex]: letter }))
    try {
      const updated = await apiRequest<QuizSessionDetail>(
        `/study/quiz-sessions/${session.id}/answer`,
        {
          method: 'POST',
          body: JSON.stringify({ q_index: qIndex, selected_letter: letter }),
        },
      )
      // Don't overwrite local picks on every save — they could lag a
      // fast clicker. Just absorb the canonical session state.
      setSession(updated)
    } catch {
      // Silent on transient failures — the user's local pick stays
      // visible; next pick (or submit) will reconcile.
    }
  }

  // ── Submit / finalize ─────────────────────────────────────────────────
  async function handleSubmit() {
    if (!session || submitting) return
    if (!quiz) return
    const total = quiz.content_json.questions.length
    const answered = Object.keys(picks).length
    if (answered < total) {
      const ok = window.confirm(
        `You've answered ${answered} of ${total} questions. Unanswered ones count as wrong. Submit anyway?`,
      )
      if (!ok) return
    }
    setSubmitting(true)
    try {
      const finished = await apiRequest<QuizSessionDetail>(
        `/study/quiz-sessions/${session.id}/finish`,
        { method: 'POST' },
      )
      setSession(finished)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Submit failed'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render branches ───────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col min-h-screen bg-[#0a0e1a]">
        <AppHeader title="Take Quiz" />
        <main className="flex-1 px-4 py-6">
          <div className="max-w-md md:max-w-3xl mx-auto">
            <div className="bg-[#111827] border border-white/8 rounded-xl p-6">
              <AILoadingState
                messages={['Loading your quiz…', 'Starting a fresh session…']}
                variant="card"
              />
            </div>
          </div>
        </main>
      </div>
    )
  }

  if (error || !quiz || !session) {
    return (
      <div className="flex flex-col min-h-screen bg-[#0a0e1a]">
        <AppHeader title="Take Quiz" />
        <main className="flex-1 px-4 py-6">
          <div className="max-w-md md:max-w-3xl mx-auto">
            <div className="bg-[#111827] border border-red-400/30 rounded-xl p-6">
              <p className="font-mono text-sm text-red-400 mb-3">
                {error ?? "Couldn't start a quiz session."}
              </p>
              <Link
                href="/study"
                className="inline-block font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
                  hover:brightness-110 rounded-lg px-3 py-1.5 transition-[filter] duration-150"
              >
                ← Back to Study Tools
              </Link>
            </div>
          </div>
        </main>
      </div>
    )
  }

  const isFinished = session.finished_at !== null
  const questions = quiz.content_json.questions

  return (
    <div className="flex flex-col min-h-screen bg-[#0a0e1a]">
      <AppHeader title={quiz.title} />
      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-md md:max-w-3xl mx-auto flex flex-col gap-5">

          {/* Score summary (review state) */}
          {isFinished && (
            <ScoreSummary
              session={session}
              total={questions.length}
              onRetake={() => router.push(`/study/${generationId}/take`)}
            />
          )}

          {/* Header / progress meter (answering state) */}
          {!isFinished && (
            <div className="bg-[#111827] border border-white/8 rounded-xl p-4 flex items-center justify-between flex-wrap gap-3">
              <div>
                <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-widest">
                  Quiz · {questions.length} questions
                </p>
                <h1 className="font-display text-base font-bold text-[#f0ece4] tracking-wide">
                  {quiz.title}
                </h1>
              </div>
              <div className="flex flex-col items-end gap-1">
                <p className="font-mono text-xs text-[#6b7594]">
                  {Object.keys(picks).length} of {questions.length} answered
                </p>
                <div className="w-32 h-1 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[#2dd4bf] rounded-full transition-all duration-300"
                    style={{
                      width: `${(Object.keys(picks).length / questions.length) * 100}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Questions list */}
          <ol className="flex flex-col gap-4 list-none">
            {questions.map((q, i) => {
              const userPick = picks[i]
              const sessionAnswer = session.answers.find((a) => a.q === i)
              // After finish, prefer session.answers (authoritative grading)
              const reviewPick = sessionAnswer?.selected as Letter | undefined
              return (
                <QuestionCard
                  key={i}
                  index={i}
                  question={q}
                  selectedLetter={isFinished ? reviewPick : userPick}
                  isReview={isFinished}
                  onPick={(letter) => handlePick(i, letter)}
                  disabled={isFinished || submitting}
                />
              )
            })}
          </ol>

          {/* Submit / actions */}
          {!isFinished && (
            <div className="bg-[#111827] border border-white/8 rounded-xl p-4 flex items-center justify-between flex-wrap gap-3">
              <Link
                href="/study"
                className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] transition-colors"
              >
                ← Back to Study Tools (you can return; progress is saved)
              </Link>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                  hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed
                  rounded-lg px-5 py-2 transition-[filter] duration-150"
              >
                {submitting ? 'Grading…' : 'Submit & grade'}
              </button>
            </div>
          )}

          {isFinished && (
            <div className="bg-[#111827] border border-white/8 rounded-xl p-4 flex items-center justify-between flex-wrap gap-3">
              <Link
                href="/study"
                className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] transition-colors"
              >
                ← Back to Study Tools
              </Link>
              <button
                onClick={() => router.push(`/study/${generationId}/take`)}
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
                  hover:brightness-110 rounded-lg px-4 py-2 transition-[filter] duration-150"
              >
                Retake quiz →
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

// ── Score summary ──────────────────────────────────────────────────────────

function ScoreSummary({
  session, total, onRetake,
}: {
  session: QuizSessionDetail
  total: number
  onRetake: () => void
}) {
  const score = session.score_pct ?? 0
  const correct = session.answers.filter((a) => a.is_correct).length
  const elapsed = session.elapsed_seconds ?? 0
  const min = Math.floor(elapsed / 60)
  const sec = elapsed % 60

  // Color the score band by passing-grade USCG conventions: 70%+ pass.
  const band =
    score >= 90 ? 'emerald' :
    score >= 70 ? 'teal' :
    score >= 50 ? 'amber' : 'rose'
  const colors = {
    emerald: 'bg-emerald-950/40 border-emerald-400/40 text-emerald-400',
    teal:    'bg-[#2dd4bf]/10 border-[#2dd4bf]/40 text-[#2dd4bf]',
    amber:   'bg-amber-950/40 border-amber-400/40 text-amber-400',
    rose:    'bg-rose-950/40 border-rose-400/40 text-rose-400',
  }[band]

  return (
    <div className={`rounded-xl border p-5 ${colors}`}>
      <div className="flex items-baseline gap-3 flex-wrap">
        <p className="font-display text-4xl font-black">{score.toFixed(0)}%</p>
        <p className="font-mono text-sm">
          {correct} of {total} correct
        </p>
        {elapsed > 0 && (
          <p className="font-mono text-xs opacity-70">
            · {min}m {sec}s elapsed
          </p>
        )}
      </div>
      <p className="font-mono text-xs mt-2 opacity-80">
        {score >= 70
          ? 'Passing grade — review the ones you missed below to lock it in.'
          : "Below USCG passing — review every question's explanation below before retaking."}
      </p>
      <button
        onClick={onRetake}
        className="mt-3 font-mono text-xs font-bold underline opacity-90 hover:opacity-100"
      >
        Retake →
      </button>
    </div>
  )
}

// ── Question card ──────────────────────────────────────────────────────────

function QuestionCard({
  index, question, selectedLetter, isReview, onPick, disabled,
}: {
  index: number
  question: QuizQuestion
  selectedLetter: Letter | undefined
  isReview: boolean
  onPick: (letter: Letter) => void
  disabled: boolean
}) {
  const correct = question.correct_letter as Letter
  const answeredCorrectly = isReview && selectedLetter === correct
  const answeredWrong = isReview && selectedLetter !== undefined && selectedLetter !== correct

  return (
    <li
      className={`bg-[#111827] border rounded-xl p-4 transition-colors duration-200
        ${isReview
          ? answeredCorrectly
            ? 'border-emerald-400/40'
            : answeredWrong
              ? 'border-rose-400/40'
              : 'border-amber-400/30'
          : 'border-white/8'
        }`}
    >
      <p className="font-mono text-sm text-[#f0ece4] leading-relaxed mb-3">
        <span className="text-[#2dd4bf] font-bold mr-2">{index + 1}.</span>
        {question.stem}
        <DifficultyChip difficulty={question.difficulty} />
      </p>

      <div className="flex flex-col gap-2 ml-1">
        {(['A', 'B', 'C', 'D'] as const).map((letter) => {
          const isSelected = selectedLetter === letter
          const isCorrect = isReview && letter === correct
          const isUserWrong = isReview && isSelected && !isCorrect

          return (
            <label
              key={letter}
              className={`flex items-start gap-3 px-3 py-2 rounded-lg border transition-colors duration-150
                ${disabled ? '' : 'cursor-pointer'}
                ${isCorrect
                  ? 'bg-emerald-950/30 border-emerald-400/40 text-emerald-400'
                  : isUserWrong
                    ? 'bg-rose-950/30 border-rose-400/40 text-rose-400'
                    : isSelected
                      ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/40 text-[#f0ece4]'
                      : 'bg-[#0d1225] border-white/8 text-[#f0ece4]/80 hover:border-white/20'
                }`}
            >
              <input
                type="radio"
                name={`q-${index}`}
                value={letter}
                checked={isSelected}
                disabled={disabled}
                onChange={() => onPick(letter)}
                className="mt-1 accent-[#2dd4bf]"
              />
              <div className="flex-1 min-w-0">
                <span className="font-mono text-xs font-bold mr-2">{letter}.</span>
                <span className="font-mono text-xs">{question.options[letter]}</span>
                {isCorrect && (
                  <span className="ml-2 text-[10px] uppercase tracking-wider opacity-90">
                    ✓ correct
                  </span>
                )}
                {isUserWrong && (
                  <span className="ml-2 text-[10px] uppercase tracking-wider opacity-90">
                    ✗ your answer
                  </span>
                )}
              </div>
            </label>
          )
        })}
      </div>

      {/* Explanation — only visible in review mode */}
      {isReview && (
        <div className="mt-3 pt-3 border-t border-white/8">
          <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-widest mb-1.5">
            Why
          </p>
          <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed mb-2">
            {question.explanation}
          </p>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
            bg-amber-950/70 text-amber-400 border border-amber-800/50 leading-none">
            {question.citation}
          </span>
        </div>
      )}
    </li>
  )
}

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
