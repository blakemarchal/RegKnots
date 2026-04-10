'use client'

import { useEffect } from 'react'
import { HydrationGate } from './HydrationGate'
import { NavigationProgress } from './NavigationProgress'

export function Providers({ children }: { children: React.ReactNode }) {
  // Register SW after hydration to avoid MessagePort interference
  // during React hydration (React error #418). next-pwa generates
  // the SW file; we just defer the registration to post-mount.
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js')
    }
  }, [])

  return (
    <HydrationGate>
      <NavigationProgress />
      {children}
    </HydrationGate>
  )
}
