'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
import { useOfflineDetection } from '@/hooks/useOfflineDetection'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isAuthenticated, hydrated } = useAuthStore()
  const { isOffline } = useOfflineDetection()

  useEffect(() => {
    // HydrationGate already ran hydrateAuth — if we're hydrated but not
    // authenticated, redirect to login. Suppress the redirect when offline:
    // the user may still have a valid session we can't verify right now,
    // and bouncing them to /login (which they also can't use offline) just
    // strands them. The persisted auth hint in hydrateAuth will already
    // have populated isAuthenticated=true for returning users with cached
    // credentials.
    if (hydrated && !isAuthenticated && !isOffline) {
      router.replace('/login')
    }
  }, [hydrated, isAuthenticated, isOffline, router])

  // When offline with no auth hint, render children anyway — the cached
  // data paths (IndexedDB conversations, vessel cache) will still work,
  // and the OfflineBanner makes the state visible to the user.
  if (!isAuthenticated && !isOffline) {
    return null
  }

  return <>{children}</>
}
