'use client'

// 2026-10-02 — the /practice quiz: pick a topic (and an exam level), answer
// 10 questions one at a time with the answer shown after each pick, then a
// score with the missed questions. Public; talks to /practice/topics and
// /practice/quiz without credentials. A–F answer, Enter goes on.

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { signupHref } from './links'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const QUIZ_LENGTH = 10

interface ExamLevel { exam: string; count: number }
interface Topic { key: string; label: string; group: string; count: number; exams: ExamLevel[] }
interface TopicsResponse { topics: Topic[]; total: number; groups: string[] }
interface Related { source: string; section: string; title: string | null }
interface Question {
  id: number
  pool: string
  part: string
  exam: string
  stem: string
  choices: Record<string, string>
  answer: string
  related: Related | null
}

type Phase = 'pick' | 'setup' | 'quiz' | 'done'

function RelatedLine({ related }: { related: Related }) {
  // The NGA manuals (Bowditch, Pub 1310, Pub 102) explain; they are not rules.
  return (
    <p className="font-mono text-xs text-[#6b7594] leading-relaxed">
      {related.source === 'nga_pubs' ? 'Read more' : 'The rule behind it'}:{' '}
      <span className="text-[#2dd4bf]">{related.section}</span>
      {related.title ? <> &mdash; {related.title}</> : null}
    </p>
  )
}

export function PracticeQuiz() {
  const [topics, setTopics] = useState<TopicsResponse | null>(null)
  const [topicsError, setTopicsError] = useState(false)
  const [phase, setPhase] = useState<Phase>('pick')
  const [topic, setTopic] = useState<Topic | null>(null)
  const [exam, setExam] = useState('')
  const [questions, setQuestions] = useState<Question[]>([])
  const [index, setIndex] = useState(0)
  const [picks, setPicks] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const loadTopics = useCallback(() => {
    setTopicsError(false)
    fetch(`${API_URL}/practice/topics`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: TopicsResponse) => setTopics(data))
      .catch(() => setTopicsError(true))
  }, [])

  useEffect(() => { loadTopics() }, [loadTopics])

  // Keep the panel's top in view when the step changes (phones scroll far).
  const showPanel = useCallback(() => {
    requestAnimationFrame(() => {
      const el = panelRef.current
      if (el && el.getBoundingClientRect().top < 72) el.scrollIntoView({ block: 'start' })
    })
  }, [])

  const startQuiz = useCallback(async (t: Topic, level: string) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ topic: t.key, n: String(QUIZ_LENGTH) })
      if (level) params.set('exam', level)
      const r = await fetch(`${API_URL}/practice/quiz?${params}`)
      if (!r.ok) throw new Error(String(r.status))
      const data: { questions: Question[] } = await r.json()
      setQuestions(data.questions)
      setIndex(0)
      setPicks({})
      setPhase('quiz')
      showPanel()
    } catch {
      setError('Could not load questions. Try again in a moment.')
    } finally {
      setLoading(false)
    }
  }, [showPanel])

  const chooseTopic = (t: Topic) => {
    setTopic(t)
    setExam('')
    setError(null)
    if (t.exams.length > 1) {
      setPhase('setup')
      showPanel()
    } else {
      void startQuiz(t, '')
    }
  }

  const current = questions[index]
  const picked = current ? picks[current.id] : undefined

  const pick = useCallback((letter: string) => {
    if (!current || picks[current.id]) return
    setPicks((p) => ({ ...p, [current.id]: letter }))
  }, [current, picks])

  const next = useCallback(() => {
    if (!current || !picks[current.id]) return
    if (index + 1 < questions.length) setIndex(index + 1)
    else setPhase('done')
    showPanel()
  }, [current, picks, index, questions.length, showPanel])

  useEffect(() => {
    if (phase !== 'quiz') return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      const letter = e.key.toUpperCase()
      if (current && letter in current.choices && !picks[current.id]) {
        e.preventDefault()
        pick(letter)
      } else if (e.key === 'Enter' && current && picks[current.id]) {
        e.preventDefault()
        next()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, current, picks, pick, next])

  const score = questions.filter((q) => picks[q.id] === q.answer).length
  const missed = questions.filter((q) => picks[q.id] && picks[q.id] !== q.answer)

  return (
    <section className="px-5 md:px-10 pb-14">
      <div ref={panelRef} className="max-w-5xl mx-auto scroll-mt-24">
        {phase === 'pick' && (
          <TopicGrid topics={topics} failed={topicsError} onRetry={loadTopics} onPick={chooseTopic}
            loadingKey={loading ? topic?.key : undefined} error={error} />
        )}

        {phase === 'setup' && topic && (
          <div className="max-w-xl mx-auto rounded-xl border border-white/8 bg-[#111827] p-6">
            <button onClick={() => setPhase('pick')}
              className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4] mb-4">
              &larr; All topics
            </button>
            <h2 className="font-display text-2xl font-bold text-[#f0ece4] tracking-wide mb-1">{topic.label}</h2>
            <p className="font-mono text-sm text-[#6b7594] mb-5">{topic.count.toLocaleString()} questions</p>
            <label htmlFor="practice-exam" className="block font-mono text-xs uppercase tracking-wider text-[#6b7594] mb-2">
              Exam
            </label>
            <select id="practice-exam" value={exam} onChange={(e) => setExam(e.target.value)}
              className="w-full mb-5 rounded-lg bg-[#0a0e1a] border border-white/10 text-[#f0ece4]
                font-mono text-base px-3 py-2.5 focus:outline-none focus:border-[#2dd4bf]/60">
              <option value="">All exams</option>
              {topic.exams.map((e) => (
                <option key={e.exam} value={e.exam}>{e.exam} ({e.count})</option>
              ))}
            </select>
            <button onClick={() => void startQuiz(topic, exam)} disabled={loading}
              className="w-full font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110 rounded-lg py-3 px-6
                transition-[filter] duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
              {loading ? 'Loading…' : `Start ${QUIZ_LENGTH} questions`}
            </button>
            {error && <p role="alert" className="font-mono text-sm text-red-400 mt-3">{error}</p>}
          </div>
        )}

        {phase === 'quiz' && current && topic && (
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center justify-between gap-3 mb-3">
              <button onClick={() => setPhase('pick')}
                className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]">
                &larr; {topic.label}
              </button>
              <span className="font-mono text-xs text-[#6b7594] whitespace-nowrap">
                {index + 1} / {questions.length}
              </span>
            </div>
            <div className="h-1 rounded-full bg-white/5 mb-5 overflow-hidden" aria-hidden="true">
              <div className="h-full bg-[#2dd4bf] transition-[width] duration-300"
                style={{ width: `${((index + (picked ? 1 : 0)) / questions.length) * 100}%` }} />
            </div>

            <div className="rounded-xl border border-white/8 bg-[#111827] p-5 md:p-6">
              <p className="font-mono text-[11px] uppercase tracking-wider text-[#6b7594] mb-3">
                {current.exam || current.pool}
              </p>
              <h2 className="font-mono text-base md:text-lg text-[#f0ece4] leading-relaxed mb-5">
                {current.stem}
              </h2>
              <div className="space-y-2.5" role="group" aria-label="Answer choices">
                {Object.entries(current.choices).map(([letter, text]) => {
                  const isAnswer = letter === current.answer
                  const isPicked = letter === picked
                  let tone = 'border-white/10 hover:border-[#2dd4bf]/50 text-[#f0ece4]/90'
                  if (picked) {
                    if (isAnswer) tone = 'border-[#2dd4bf] bg-[#2dd4bf]/10 text-[#f0ece4]'
                    else if (isPicked) tone = 'border-red-400/70 bg-red-500/10 text-[#f0ece4]'
                    else tone = 'border-white/5 text-[#f0ece4]/45'
                  }
                  return (
                    <button key={letter} onClick={() => pick(letter)} disabled={!!picked}
                      aria-pressed={isPicked}
                      className={`w-full flex items-start gap-3 text-left rounded-lg border px-4 py-3
                        font-mono text-sm md:text-base leading-relaxed transition-colors duration-150
                        disabled:cursor-default ${tone}`}>
                      <span className={`shrink-0 w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold
                        ${picked && isAnswer ? 'bg-[#2dd4bf] text-[#0a0e1a]' : picked && isPicked ? 'bg-red-400 text-[#0a0e1a]' : 'bg-white/5 text-[#6b7594]'}`}>
                        {letter}
                      </span>
                      <span>{text}</span>
                    </button>
                  )
                })}
              </div>

              <div aria-live="polite">
                {picked && (
                  <div className="mt-5 pt-5 border-t border-white/5 space-y-3">
                    <p className={`font-mono text-sm font-bold ${picked === current.answer ? 'text-[#2dd4bf]' : 'text-red-400'}`}>
                      {picked === current.answer ? 'Correct.' : `Not quite. The answer is ${current.answer}.`}
                    </p>
                    {current.related && <RelatedLine related={current.related} />}
                    <button onClick={next}
                      className="w-full sm:w-auto font-mono font-bold text-sm uppercase tracking-wider
                        bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110 rounded-lg py-3 px-6
                        transition-[filter] duration-150">
                      {index + 1 < questions.length ? 'Next question →' : 'See your score →'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {phase === 'done' && topic && (
          <div className="max-w-2xl mx-auto">
            <div className="rounded-xl border border-white/8 bg-[#111827] p-6 text-center mb-5">
              <p className="font-mono text-xs uppercase tracking-wider text-[#6b7594] mb-2">{topic.label}</p>
              <p className="font-display text-5xl font-black text-[#f0ece4] mb-1">
                {score} <span className="text-[#6b7594] text-3xl">/ {questions.length}</span>
              </p>
              <p className="font-mono text-sm text-[#6b7594] mb-5">
                {missed.length === 0 ? 'All correct.' : `${missed.length} to review below.`}
              </p>
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <button onClick={() => void startQuiz(topic, exam)} disabled={loading}
                  className="font-mono font-bold text-sm uppercase tracking-wider
                    bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110 rounded-lg py-3 px-6
                    transition-[filter] duration-150 disabled:opacity-50">
                  {loading ? 'Loading…' : `Another ${QUIZ_LENGTH}`}
                </button>
                <button onClick={() => setPhase('pick')}
                  className="font-mono font-bold text-sm uppercase tracking-wider
                    border border-[#2dd4bf]/40 text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                    rounded-lg py-3 px-6 transition-colors duration-150">
                  Change topic
                </button>
              </div>
              {error && <p role="alert" className="font-mono text-sm text-red-400 mt-3">{error}</p>}
            </div>

            <SignupCard />

            {missed.length > 0 && (
              <div className="space-y-3 mt-5">
                <h3 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">Review</h3>
                {missed.map((q) => (
                  <div key={q.id} className="rounded-xl border border-white/8 bg-[#111827] p-5 space-y-2">
                    <p className="font-mono text-sm text-[#f0ece4] leading-relaxed">{q.stem}</p>
                    <p className="font-mono text-sm text-red-400/90">
                      Your answer: {picks[q.id]}. {q.choices[picks[q.id]]}
                    </p>
                    <p className="font-mono text-sm text-[#2dd4bf]">
                      Answer: {q.answer}. {q.choices[q.answer]}
                    </p>
                    {q.related && <RelatedLine related={q.related} />}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function TopicGrid({ topics, failed, onRetry, onPick, loadingKey, error }: {
  topics: TopicsResponse | null
  failed: boolean
  onRetry: () => void
  onPick: (t: Topic) => void
  loadingKey?: string
  error: string | null
}) {
  if (failed) {
    return (
      <div className="text-center py-10">
        <p className="font-mono text-sm text-[#6b7594] mb-3">Practice questions are unavailable right now.</p>
        <button onClick={onRetry} className="font-mono text-sm text-[#2dd4bf] hover:underline">Try again</button>
      </div>
    )
  }
  if (!topics) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="h-[72px] rounded-xl border border-white/5 bg-[#111827] animate-pulse" />
        ))}
      </div>
    )
  }
  return (
    <div>
      <p className="font-mono text-xs text-[#6b7594] text-center mb-6">
        {topics.total.toLocaleString()} questions across {topics.topics.length} topics
      </p>
      {error && <p role="alert" className="font-mono text-sm text-red-400 text-center mb-4">{error}</p>}
      {topics.groups.map((group) => {
        const list = topics.topics.filter((t) => t.group === group)
        if (!list.length) return null
        return (
          <div key={group} className="mb-8">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">{group}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((t) => (
                <button key={t.key} onClick={() => onPick(t)} disabled={!!loadingKey}
                  className="text-left rounded-xl border border-white/8 bg-[#111827] px-4 py-3.5
                    hover:border-[#2dd4bf]/40 transition-colors duration-150 disabled:opacity-60">
                  <span className="block font-mono text-sm font-bold text-[#f0ece4]">{t.label}</span>
                  <span className="block font-mono text-xs text-[#6b7594] mt-1">
                    {loadingKey === t.key ? 'Loading…' : `${t.count.toLocaleString()} questions`}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SignupCard() {
  return (
    <div className="rounded-xl border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 p-6">
      <h3 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide mb-2">
        Have a question the sample exams don&apos;t answer?
      </h3>
      <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed mb-4">
        Ask RegKnot. It answers maritime regulation questions with citations to 46 CFR, 33 CFR, the
        COLREGs, STCW, NVICs and more. Free 7-day trial, then 10 free questions every 30 days. No card.
      </p>
      <Link href={signupHref('score')}
        className="inline-block font-mono font-bold text-sm uppercase tracking-wider
          bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110 rounded-lg py-3 px-6
          transition-[filter] duration-150">
        Try RegKnot free &rarr;
      </Link>
    </div>
  )
}
