'use client'

import { useEffect, useState, useRef } from 'react'

const DISMISSED_KEY = 'pwa-install-dismissed'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallPrompt() {
  const [visible, setVisible] = useState(false)
  const deferredPrompt = useRef<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    // Don't show if already running as installed PWA
    if (window.matchMedia('(display-mode: standalone)').matches) return
    // Don't show if previously dismissed
    if (localStorage.getItem(DISMISSED_KEY)) return

    function handler(e: Event) {
      e.preventDefault()
      deferredPrompt.current = e as BeforeInstallPromptEvent
      setVisible(true)
    }

    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  if (!visible) return null

  async function handleInstall() {
    if (!deferredPrompt.current) return
    await deferredPrompt.current.prompt()
    const { outcome } = await deferredPrompt.current.userChoice
    if (outcome === 'accepted') {
      deferredPrompt.current = null
    }
    setVisible(false)
  }

  function handleDismiss() {
    localStorage.setItem(DISMISSED_KEY, '1')
    setVisible(false)
  }

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5
      bg-[#0d1225] border-b border-[#2dd4bf]/15 text-[#f0ece4]">
      <p className="font-mono text-xs text-[#6b7594] leading-snug">
        Add <span className="text-[#f0ece4]/80">RegKnots</span> to your home screen for the best experience
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleInstall}
          className="font-mono text-xs font-bold text-[#0a0e1a] bg-[#2dd4bf]
            hover:brightness-110 rounded-md px-3 py-1 transition-[filter] duration-150"
        >
          Install
        </button>
        <button
          onClick={handleDismiss}
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
