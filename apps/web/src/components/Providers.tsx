'use client'

import { useEffect } from 'react'
import { HydrationGate } from './HydrationGate'
import { NavigationProgress } from './NavigationProgress'

export function Providers({ children }: { children: React.ReactNode }) {
  // Sprint D6.23e — HOTFIX: PWA service worker was caching stale page
  // content under the start-url cache, sending some users to /womenoffshore
  // when they visited / after login. The next-pwa config was already a
  // no-op (cacheStartUrl: false, runtimeCaching: [], exclude: [/./]) but
  // the deployed SW still had routing rules from an older build, and
  // existing PWA users kept getting that stale SW.
  //
  // Resolution: stop registering any SW. Manifest.json still drives
  // "Add to Home Screen" / PWA install — we just lose offline caching,
  // which we weren't using anyway. Any existing SW gets unregistered on
  // next mount, and all caches are wiped, so PWA users self-heal on
  // their next app open without needing to reinstall.
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
      return
    }
    // Unregister any service workers currently running for this origin.
    navigator.serviceWorker.getRegistrations()
      .then((regs) => Promise.all(regs.map((r) => r.unregister())))
      .catch(() => { /* nothing to clean up */ })
    // Wipe all caches — the stale `/womenoffshore` content was living in
    // a NetworkFirst start-url cache; clearing all named caches removes
    // any other lingering state too.
    if (typeof window !== 'undefined' && 'caches' in window) {
      caches.keys()
        .then((names) => Promise.all(names.map((n) => caches.delete(n))))
        .catch(() => { /* not fatal */ })
    }
  }, [])

  return (
    <HydrationGate>
      <NavigationProgress />
      {children}
    </HydrationGate>
  )
}
