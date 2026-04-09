'use client'

import { usePathname } from 'next/navigation'
import { usePwa } from '@/lib/pwa'

// Only show the install prompt inside the authenticated app shell. Marketing
// and auth-flow routes (/landing, /login, /register, etc.) never see it.
const IN_APP_ROUTES = ['/', '/history', '/account', '/reference', '/certificates', '/admin']

function isInAppRoute(pathname: string): boolean {
  return IN_APP_ROUTES.some(p => pathname === p || pathname.startsWith(p + '/'))
}

export function InstallPrompt() {
  const { bannerVisible, install, dismissBanner } = usePwa()
  const pathname = usePathname()

  if (!bannerVisible) return null
  if (!isInAppRoute(pathname)) return null

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
            transition-colors duration-150 px-1"
          aria-label="Dismiss for 7 days"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
