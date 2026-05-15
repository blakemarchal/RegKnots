'use client'

import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import type { ReactNode } from 'react'

// Persistent dismiss keys — store the UNIX timestamp (ms) at which the
// dismissal expires. We re-show the banner after 7 days so users who
// weren't ready on first prompt can install later without having to
// clear site data.
//
// Sprint D6.92 — iOS gets its own dismiss key. Reason: a user on
// Android Chrome dismissing the install banner has different context
// than the same user on Safari iPad later — they may want to install
// on iPad even after dismissing on phone, and vice versa. Separate
// keys keep the two flows independent.
const DISMISSED_KEY = 'pwa_dismissed'
const IOS_DISMISSED_KEY = 'pwa_ios_dismissed'
const DISMISS_DURATION_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function isCurrentlyDismissed(key: string): boolean {
  if (typeof window === 'undefined') return false
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return false
    const expiresAt = parseInt(raw, 10)
    if (!Number.isFinite(expiresAt)) {
      // Legacy value (e.g. the old "1" sentinel) — treat as expired and clear.
      localStorage.removeItem(key)
      return false
    }
    if (Date.now() >= expiresAt) {
      localStorage.removeItem(key)
      return false
    }
    return true
  } catch {
    return false
  }
}

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    // iOS Safari exposes this non-standard flag when launched from home screen
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  )
}

/** Sprint D6.92 — detect iOS Safari specifically (NOT Chrome/Firefox/Edge
 *  on iOS, which use WebKit underneath but route the "Add to Home Screen"
 *  action through their own browser-chrome menu rather than Safari's
 *  Share sheet, so the tutorial we show would be wrong for those).
 *
 *  iPadOS 13+ reports as `MacIntel` in navigator.platform — we detect
 *  that via `maxTouchPoints > 1` (real Macs don't have a touchscreen).
 *  Non-Safari iOS browsers add their own marker (`CriOS`, `FxiOS`,
 *  `EdgiOS`, `OPiOS`, `Mercury`) which we filter out. */
function isIosSafari(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  const isIosDevice =
    /iPad|iPhone|iPod/.test(ua) ||
    // iPadOS 13+ masquerades as desktop Mac in UA; detect via touch.
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  if (!isIosDevice) return false
  // Filter out non-Safari iOS browsers.
  if (/CriOS|FxiOS|EdgiOS|OPiOS|mercury/i.test(ua)) return false
  // Final check: Safari proper. The UA always contains "Safari" on iOS
  // Safari (Chromium-on-iOS also includes "Safari" but we've already
  // filtered those above).
  return /Safari/.test(ua)
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

interface PwaContextValue {
  canInstall: boolean
  bannerVisible: boolean
  // Sprint D6.92 — iOS Safari doesn't support `beforeinstallprompt`,
  // so we surface a separate iOS-flavored banner with a Share-icon
  // tutorial. iosBannerVisible is true when we're on iOS Safari, not
  // already installed (standalone), and not within the 7-day dismiss
  // window.
  iosBannerVisible: boolean
  install: () => Promise<void>
  dismissBanner: () => void
  dismissIosBanner: () => void
}

const PwaContext = createContext<PwaContextValue>({
  canInstall: false,
  bannerVisible: false,
  iosBannerVisible: false,
  install: async () => {},
  dismissBanner: () => {},
  dismissIosBanner: () => {},
})

export function PwaProvider({ children }: { children: ReactNode }) {
  const [canInstall, setCanInstall] = useState(false)
  const [bannerVisible, setBannerVisible] = useState(false)
  const [iosBannerVisible, setIosBannerVisible] = useState(false)
  const deferredPrompt = useRef<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    // If already running as an installed PWA, never prompt — nothing to install.
    if (isStandalone()) return

    // Sprint D6.92 — iOS Safari path. No browser event fires, so we
    // surface the banner directly on mount when conditions match.
    // Runs once per session; the 7-day dismiss key prevents nagging.
    if (isIosSafari() && !isCurrentlyDismissed(IOS_DISMISSED_KEY)) {
      setIosBannerVisible(true)
    }

    function handler(e: Event) {
      e.preventDefault()
      deferredPrompt.current = e as BeforeInstallPromptEvent
      setCanInstall(true)
      if (!isCurrentlyDismissed(DISMISSED_KEY)) {
        setBannerVisible(true)
      }
    }

    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const install = useCallback(async () => {
    if (!deferredPrompt.current) return
    await deferredPrompt.current.prompt()
    const { outcome } = await deferredPrompt.current.userChoice
    if (outcome === 'accepted') {
      deferredPrompt.current = null
      setCanInstall(false)
    }
    setBannerVisible(false)
  }, [])

  const dismissBanner = useCallback(() => {
    try {
      localStorage.setItem(DISMISSED_KEY, String(Date.now() + DISMISS_DURATION_MS))
    } catch {
      // localStorage can throw in private mode — proceed anyway so the banner hides.
    }
    setBannerVisible(false)
  }, [])

  const dismissIosBanner = useCallback(() => {
    try {
      localStorage.setItem(IOS_DISMISSED_KEY, String(Date.now() + DISMISS_DURATION_MS))
    } catch {
      // see above
    }
    setIosBannerVisible(false)
  }, [])

  return (
    <PwaContext.Provider value={{
      canInstall, bannerVisible, iosBannerVisible,
      install, dismissBanner, dismissIosBanner,
    }}>
      {children}
    </PwaContext.Provider>
  )
}

export function usePwa() {
  return useContext(PwaContext)
}
