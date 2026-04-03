'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { CompassRose } from './CompassRose'
import type { BillingStatus } from '@/lib/auth'

const SESSION_KEY = 'pilot_survey_shown'

interface Props {
  billing: BillingStatus | null
}

export function PilotSurveyModal({ billing }: Props) {
  const [visible, setVisible] = useState(false)
  const router = useRouter()

  useEffect(() => {
    if (!billing) return
    // Don't show for Pro users
    if (billing.tier !== 'free') return
    // Don't show if already shown this session
    if (sessionStorage.getItem(SESSION_KEY)) return

    if (!billing.trial_ends_at) return
    const trialEnd = new Date(billing.trial_ends_at)
    const now = new Date()
    const hoursLeft = (trialEnd.getTime() - now.getTime()) / (1000 * 60 * 60)

    // Show if within 48 hours of trial end or already past
    if (hoursLeft <= 48) {
      setVisible(true)
    }
  }, [billing])

  if (!visible) return null

  function dismiss() {
    sessionStorage.setItem(SESSION_KEY, '1')
    setVisible(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-5">
      <div className="w-full max-w-sm rounded-2xl bg-[#111827] border border-white/10 p-6 shadow-xl">
        <div className="flex flex-col items-center text-center mb-6">
          <CompassRose className="w-10 h-10 text-[#2dd4bf] mb-4" />
          <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-3">
            Your pilot access is ending soon
          </h2>
          <p className="font-mono text-sm text-[#6b7594] leading-relaxed">
            You&apos;ve been part of the RegKnots founding pilot. We&apos;d love your feedback before you go.
          </p>
        </div>

        <div className="flex flex-col gap-2.5 mb-4">
          <a
            href="https://forms.gle/placeholder"
            target="_blank"
            rel="noopener noreferrer"
            onClick={dismiss}
            className="w-full text-center font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-lg py-2.5
              hover:brightness-110 transition-[filter] duration-150"
          >
            Give Feedback
          </a>
          <button
            onClick={() => { dismiss(); router.push('/pricing') }}
            className="w-full font-mono font-bold text-sm uppercase tracking-wider
              border border-[#2dd4bf]/40 text-[#2dd4bf] rounded-lg py-2.5
              hover:bg-[#2dd4bf]/10 transition-colors duration-150"
          >
            Upgrade Now
          </button>
        </div>

        <button
          onClick={dismiss}
          className="w-full font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
            transition-colors duration-150 py-2"
        >
          Remind me later
        </button>
      </div>
    </div>
  )
}
