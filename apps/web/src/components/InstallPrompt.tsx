'use client'

import { usePwa } from '@/lib/pwa'

export function InstallPrompt() {
  const { bannerVisible, install, dismissBanner } = usePwa()

  if (!bannerVisible) return null

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5
      bg-[#0d1225] border-b border-[#2dd4bf]/15 text-[#f0ece4]">
      <p className="font-mono text-xs text-[#6b7594] leading-snug">
        Add <span className="text-[#f0ece4]/80">RegKnot</span> to your home screen for the best experience
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={install}
          className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
            hover:brightness-110 rounded-md px-3 py-1 transition-[filter] duration-150"
        >
          Install
        </button>
        <button
          onClick={dismissBanner}
          className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
            transition-colors duration-150"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
