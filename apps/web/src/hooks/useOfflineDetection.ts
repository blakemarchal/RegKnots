'use client'

import { useEffect, useState } from 'react'

/**
 * Tracks browser online/offline status.
 *
 * SSR-safe: defaults to `false` on the server (no direct `window`/`navigator`
 * access at module level). Initializes from `navigator.onLine` on mount and
 * subscribes to the window `online`/`offline` events.
 */
export function useOfflineDetection(): { isOffline: boolean } {
  const [isOffline, setIsOffline] = useState(() =>
    typeof navigator !== 'undefined' ? !navigator.onLine : false
  )

  useEffect(() => {
    if (typeof window === 'undefined') return

    // Initialize from navigator.onLine on mount
    setIsOffline(!navigator.onLine)

    const handleOnline = () => setIsOffline(false)
    const handleOffline = () => setIsOffline(true)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return { isOffline }
}
