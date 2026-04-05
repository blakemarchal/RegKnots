'use client'

import { useState } from 'react'
import { HamburgerMenu } from './HamburgerMenu'
import { PilotSurveyModal } from './PilotSurveyModal'

interface Props {
  title?: string
  /** Extra elements rendered between title and hamburger (e.g. badges, buttons) */
  trailing?: React.ReactNode
}

/**
 * Shared header for standalone pages.
 * Shows RegKnots logo, optional page title, and hamburger menu.
 */
export function AppHeader({ title, trailing }: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [surveyOpen, setSurveyOpen] = useState(false)

  return (
    <>
      <header className="flex-shrink-0 flex items-center justify-between
        px-4 py-3 bg-[#111827]/95 backdrop-blur-md
        border-b border-white/8 z-10">
        <div className="flex items-center gap-2.5">
          <svg className="w-6 h-6 text-teal flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
            <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
          </svg>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
              {title ?? 'RegKnots'}
            </h1>
            {trailing}
          </div>
        </div>

        <button
          onClick={() => setMenuOpen(true)}
          className="w-9 h-9 flex flex-col items-center justify-center gap-1
            rounded-lg hover:bg-white/8 transition-colors duration-150"
          aria-label="Open menu"
          aria-expanded={menuOpen}
        >
          <span className="w-5 h-0.5 bg-[#f0ece4]/70 rounded-full" />
          <span className="w-5 h-0.5 bg-[#f0ece4]/70 rounded-full" />
          <span className="w-3.5 h-0.5 bg-[#f0ece4]/70 rounded-full self-start ml-[5px]" />
        </button>
      </header>

      <HamburgerMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onNewChat={() => { setMenuOpen(false); window.location.href = '/' }}
        onOpenVessels={() => { setMenuOpen(false); window.location.href = '/?vessels=open' }}
        onOpenSurvey={() => setSurveyOpen(true)}
      />

      {surveyOpen && (
        <PilotSurveyModal forceOpen onClose={() => setSurveyOpen(false)} />
      )}
    </>
  )
}
