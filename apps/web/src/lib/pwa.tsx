'use client'

import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import type { ReactNode } from 'react'

// Persistent dismiss key — store the UNIX timestamp (ms) at which the
// dismissal expires. We re-show the banner after 7 days so users who
// weren't ready on first prompt can install later without having to
// clear site data.
const DISMISSED_KEY = 'pwa_dismissed'
const DISMISS_DURATION_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function isCurrentlyDismissed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const raw = localStorage.getItem(DISMISSED_KEY)
    if (!raw) return false
    const expiresAt = parseInt(raw, 10)
    if (!Number.isFinite(expiresAt)) {
      // Legacy value (e.g. the old "1" sentinel) — treat as expired and clear.
      localStorage.removeItem(DISMISSED_KEY)
      return false
    }
    if (Date.now() >= expiresAt) {
      localStorage.removeItem(DISMISSED_KEY)
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

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

interface PwaContextValue {
  canInstall: boolean
  bannerVisible: boolean
  install: () => Promise<void>
  dismissBanner: () => void
}

const PwaContext = createContext<PwaContextValue>({
  canInstall: false,
  bannerVisible: false,
  install: async () => {},
  dismissBanner: () => {},
})

export function PwaProvider({ children }: { children: ReactNode }) {
  const [canInstall, setCanInstall] = useState(false)
  const [bannerVisible, setBannerVisible] = useState(false)
  const deferredPrompt = useRef<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    // If already running as an installed PWA, never prompt — nothing to install.
    if (isStandalone()) return

    function handler(e: Event) {
      e.preventDefault()
      deferredPrompt.current = e as BeforeInstallPromptEvent
      setCanInstall(true)
      if (!isCurrentlyDismissed()) {
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

  return (
    <PwaContext.Provider value={{ canInstall, bannerVisible, install, dismissBanner }}>
      {children}
    </PwaContext.Provider>
  )
}

export function usePwa() {
  return useContext(PwaContext)
}
