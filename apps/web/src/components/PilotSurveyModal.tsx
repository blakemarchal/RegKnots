'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { CompassRose } from './CompassRose'
import { apiRequest } from '@/lib/api'
import type { BillingStatus } from '@/lib/auth'

const SESSION_KEY = 'pilot_survey_shown'

// ── Shared radio helper ────────────────────────────────────────────────────────

function RadioGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-sm text-[#f0ece4] font-medium">{label}</p>
      <div className="flex flex-col gap-1.5">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`w-full text-left font-mono text-xs px-3 py-2.5 rounded-lg border transition-colors
              ${value === opt.value
                ? 'border-[#2dd4bf] bg-[#2dd4bf]/10 text-[#2dd4bf]'
                : 'border-white/10 bg-[#0d1225] text-[#f0ece4]/70 hover:border-white/20'
              }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Star rating ────────────────────────────────────────────────────────────────

function StarRating({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-sm text-[#f0ece4] font-medium">How was your overall experience?</p>
      <div className="flex gap-2">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => onChange(star)}
            className="transition-transform hover:scale-110 active:scale-95"
            aria-label={`${star} star${star > 1 ? 's' : ''}`}
          >
            <svg
              className={`w-9 h-9 ${star <= value ? 'text-[#2dd4bf]' : 'text-[#6b7594]/40'}`}
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface Props {
  billing?: BillingStatus | null
  /** When true the modal opens immediately (admin preview / menu trigger) */
  forceOpen?: boolean
  /** Called when the modal closes itself */
  onClose?: () => void
  /** When true, don't POST to the backend (admin preview mode) */
  preview?: boolean
}

// ── Modal ──────────────────────────────────────────────────────────────────────

export function PilotSurveyModal({ billing, forceOpen, onClose, preview }: Props) {
  const [visible, setVisible] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()

  // Form state
  const [rating, setRating] = useState(0)
  const [usefulness, setUsefulness] = useState('')
  const [favorite, setFavorite] = useState('')
  const [missing, setMissing] = useState('')
  const [missingOther, setMissingOther] = useState('')
  const [wouldSubscribe, setWouldSubscribe] = useState('')
  const [priceFeedback, setPriceFeedback] = useState('')
  const [vesselType, setVesselType] = useState('')
  const [comments, setComments] = useState('')

  // Auto-show from billing status (trial ending)
  useEffect(() => {
    if (forceOpen) { setVisible(true); return }
    if (!billing) return
    if (billing.tier !== 'free') return
    if (sessionStorage.getItem(SESSION_KEY)) return
    if (!billing.trial_ends_at) return

    const trialEnd = new Date(billing.trial_ends_at)
    const now = new Date()
    const hoursLeft = (trialEnd.getTime() - now.getTime()) / (1000 * 60 * 60)

    if (hoursLeft <= 48) {
      setVisible(true)
    }
  }, [billing, forceOpen])

  if (!visible) return null

  function dismiss() {
    sessionStorage.setItem(SESSION_KEY, '1')
    setVisible(false)
    onClose?.()
  }

  async function handleSubmit() {
    if (rating === 0) { setError('Please select a star rating.'); return }
    setError(null)

    if (preview) {
      setSubmitted(true)
      return
    }

    setSubmitting(true)
    try {
      await apiRequest('/survey/pilot', {
        method: 'POST',
        body: JSON.stringify({
          overall_rating: rating,
          usefulness: usefulness || null,
          favorite_feature: favorite || null,
          missing_feature: missing === 'Other' ? (missingOther || 'Other') : (missing || null),
          would_subscribe: wouldSubscribe === 'Yes' ? true : wouldSubscribe === 'No — too expensive' || wouldSubscribe === 'No — doesn\'t meet my needs' ? false : null,
          price_feedback: priceFeedback || null,
          vessel_type_used: vesselType || null,
          additional_comments: comments || null,
        }),
      })
      setSubmitted(true)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to submit'
      if (msg.includes('409') || msg.includes('already')) {
        setSubmitted(true) // Already submitted — just show thanks
      } else {
        setError(msg)
      }
    } finally {
      setSubmitting(false)
    }
  }

  // ── Thank you state ────────────────────────────────────────────────────────
  if (submitted) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-5">
        <div className="w-full max-w-sm rounded-2xl bg-[#111827] border border-white/10 p-6 shadow-xl">
          <div className="flex flex-col items-center text-center gap-4 py-4">
            <CompassRose className="w-16 h-16 text-[#2dd4bf]" />
            <h2 className="font-display text-xl font-bold text-[#f0ece4]">
              Thanks for your feedback!
            </h2>
            <p className="font-mono text-sm text-[#6b7594] leading-relaxed max-w-[260px]">
              Your input shapes what we build next.
            </p>
            <div className="flex flex-col gap-2 w-full mt-2">
              <button
                onClick={() => { dismiss(); router.push('/pricing') }}
                className="w-full font-mono font-bold text-sm uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-2.5
                  hover:brightness-110 transition-[filter] duration-150"
              >
                View Plans
              </button>
              <button
                onClick={dismiss}
                className="w-full font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
                  transition-colors duration-150 py-2"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Questionnaire ──────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md max-h-[90dvh] rounded-2xl bg-[#111827] border border-white/10 shadow-xl
        flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 pt-5 pb-3 border-b border-white/8">
          <div className="flex items-center gap-3">
            <CompassRose className="w-7 h-7 text-[#2dd4bf]" />
            <h2 className="font-display text-lg font-bold text-[#f0ece4]">Pilot Feedback</h2>
          </div>
          <button
            onClick={dismiss}
            className="w-7 h-7 flex items-center justify-center rounded-lg
              text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/8 transition-colors"
            aria-label="Close"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-5">

          {/* 1. Star rating */}
          <StarRating value={rating} onChange={setRating} />

          {/* 2. Usefulness */}
          <RadioGroup
            label="How useful was RegKnot for your work?"
            options={[
              { value: 'Very useful', label: 'Very useful' },
              { value: 'Somewhat useful', label: 'Somewhat useful' },
              { value: 'Not very useful', label: 'Not very useful' },
              { value: 'Too early to tell', label: 'Too early to tell' },
            ]}
            value={usefulness}
            onChange={setUsefulness}
          />

          {/* 3. Favorite feature */}
          <RadioGroup
            label="What was your favorite feature?"
            options={[
              { value: 'Cited regulation answers', label: 'Cited regulation answers' },
              { value: 'Vessel-specific responses', label: 'Vessel-specific responses' },
              { value: 'Citation chips / source links', label: 'Citation chips / source links' },
              { value: 'Certificates tab', label: 'Certificates tab' },
              { value: 'Other', label: 'Other' },
            ]}
            value={favorite}
            onChange={setFavorite}
          />

          {/* 4. Missing feature */}
          <RadioGroup
            label="What feature would you most want added?"
            options={[
              { value: 'More regulation sources (MARPOL, STCW)', label: 'More regulation sources (MARPOL, STCW)' },
              { value: 'Offline access', label: 'Offline access' },
              { value: 'COI/document scanning', label: 'COI/document scanning' },
              { value: 'Fleet/team features', label: 'Fleet/team features' },
              { value: 'Other', label: 'Other' },
            ]}
            value={missing}
            onChange={setMissing}
          />
          {missing === 'Other' && (
            <input
              type="text"
              value={missingOther}
              onChange={(e) => setMissingOther(e.target.value)}
              placeholder="What feature would you add?"
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors -mt-3
                placeholder:text-[#6b7594]/50"
            />
          )}

          {/* 5. Would subscribe */}
          <RadioGroup
            label="Would you subscribe at $39/month?"
            options={[
              { value: 'Yes', label: 'Yes' },
              { value: 'Maybe', label: 'Maybe' },
              { value: 'No — too expensive', label: 'No — too expensive' },
              { value: "No — doesn't meet my needs", label: "No — doesn't meet my needs" },
            ]}
            value={wouldSubscribe}
            onChange={setWouldSubscribe}
          />

          {/* 6. Price feedback */}
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-sm text-[#f0ece4] font-medium">Any thoughts on pricing?</p>
            <textarea
              value={priceFeedback}
              onChange={(e) => setPriceFeedback(e.target.value)}
              placeholder="Optional"
              rows={2}
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors resize-none
                placeholder:text-[#6b7594]/50"
            />
          </div>

          {/* 7. Vessel type */}
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-sm text-[#f0ece4] font-medium">What vessel type(s) did you use RegKnot with?</p>
            <input
              type="text"
              value={vesselType}
              onChange={(e) => setVesselType(e.target.value)}
              placeholder="Optional — e.g., tanker, tug, container"
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors
                placeholder:text-[#6b7594]/50"
            />
          </div>

          {/* 8. Additional comments */}
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-sm text-[#f0ece4] font-medium">Anything else you&apos;d like to tell us?</p>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Optional"
              rows={3}
              className="font-mono w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2 text-sm
                text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors resize-none
                placeholder:text-[#6b7594]/50"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-6 py-4 border-t border-white/8 flex flex-col gap-2">
          {error && (
            <p className="font-mono text-xs text-red-400 text-center">{error}</p>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-2.5
              hover:brightness-110 disabled:opacity-50
              transition-[filter] duration-150"
          >
            {submitting ? 'Submitting...' : 'Submit Feedback'}
          </button>
          <button
            onClick={dismiss}
            className="w-full font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
              transition-colors duration-150 py-1"
          >
            {forceOpen ? 'Close' : 'Remind me later'}
          </button>
        </div>
      </div>
    </div>
  )
}
