'use client'

import { usePathname } from 'next/navigation'
import { usePwa } from '@/lib/pwa'

// Only show the install prompt inside the authenticated app shell. Marketing
// and auth-flow routes (/landing, /login, /register, etc.) never see it.
const IN_APP_ROUTES = ['/', '/history', '/account', '/reference', '/certificates', '/admin']

function isInAppRoute(pathname: string): boolean {
  return IN_APP_ROUTES.some(p => pathname === p || pathname.startsWith(p + '/'))
}

/** Sprint D6.92 — iOS Safari share-icon SVG. Matches Apple's iOS share
 *  glyph (rectangle with up-arrow) so users see the same icon they'd
 *  tap on their device's toolbar. Inline so we don't need an asset. */
function ShareIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {/* upload-out arrow */}
      <path d="M12 3v12" />
      <path d="M7 8l5-5 5 5" />
      {/* enclosing box */}
      <path d="M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" />
    </svg>
  )
}

/** Sprint D6.92 — "Add to Home Screen" plus icon, mirrors how the
 *  action appears in iOS Safari's Share sheet. */
function AddToHomeIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M12 8v8" />
      <path d="M8 12h8" />
    </svg>
  )
}

export function InstallPrompt() {
  const {
    bannerVisible, iosBannerVisible,
    install, dismissBanner, dismissIosBanner,
  } = usePwa()
  const pathname = usePathname()

  if (!isInAppRoute(pathname)) return null

  // Sprint D6.92 — iOS Safari banner takes precedence when both somehow
  // flag (shouldn't normally — iOS doesn't fire beforeinstallprompt —
  // but defensive). iOS users get a 3-step tutorial since there's no
  // programmatic install path on iOS Safari.
  if (iosBannerVisible) {
    return (
      <div className="flex items-start gap-3 px-4 py-2.5
        bg-[#0d1225] border-b border-[#2dd4bf]/15 text-[#f0ece4]">
        <div className="flex-1 min-w-0">
          <p className="font-mono text-xs text-[#f0ece4]/85 leading-snug mb-1.5">
            Install <span className="text-[#f0ece4]">RegKnot</span> on your iPhone / iPad
          </p>
          <ol className="flex flex-col gap-1 font-mono text-[11px] text-[#6b7594] leading-snug">
            <li className="flex items-center gap-1.5">
              <span className="text-[#2dd4bf]/80 font-bold w-3 inline-block">1.</span>
              Tap the
              <ShareIcon className="w-3.5 h-3.5 text-[#2dd4bf]/90 inline-block flex-shrink-0" />
              <span className="text-[#f0ece4]/75">Share</span>
              icon in Safari
            </li>
            <li className="flex items-center gap-1.5">
              <span className="text-[#2dd4bf]/80 font-bold w-3 inline-block">2.</span>
              Scroll down and tap
              <AddToHomeIcon className="w-3.5 h-3.5 text-[#2dd4bf]/90 inline-block flex-shrink-0" />
              <span className="text-[#f0ece4]/75">Add to Home Screen</span>
            </li>
            <li className="flex items-center gap-1.5">
              <span className="text-[#2dd4bf]/80 font-bold w-3 inline-block">3.</span>
              Tap <span className="text-[#f0ece4]/75">Add</span> in the top-right corner
            </li>
          </ol>
        </div>
        <button
          onClick={dismissIosBanner}
          className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]
            transition-colors duration-150 px-1 pt-0.5 flex-shrink-0"
          aria-label="Dismiss for 7 days"
        >
          ×
        </button>
      </div>
    )
  }

  // Chromium / Android / desktop browsers that support beforeinstallprompt.
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
            transition-colors duration-150 px-1"
          aria-label="Dismiss for 7 days"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
