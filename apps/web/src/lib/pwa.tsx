'use client'

import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import type { ReactNode } from 'react'

const DISMISSED_KEY = 'pwa-install-dismissed'

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
    if (window.matchMedia('(display-mode: standalone)').matches) return

    function handler(e: Event) {
      e.preventDefault()
      deferredPrompt.current = e as BeforeInstallPromptEvent
      setCanInstall(true)
      if (!localStorage.getItem(DISMISSED_KEY)) {
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
    localStorage.setItem(DISMISSED_KEY, '1')
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
