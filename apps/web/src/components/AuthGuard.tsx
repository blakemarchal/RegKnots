'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isAuthenticated, hydrated } = useAuthStore()

  useEffect(() => {
    // HydrationGate already ran hydrateAuth — if we're hydrated but not
    // authenticated, redirect to login
    if (hydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [hydrated, isAuthenticated, router])

  // HydrationGate shows spinner until hydrated, so if we get here we're hydrated.
  // If not authenticated, show nothing while redirect fires.
  if (!isAuthenticated) {
    return null
  }

  return <>{children}</>
}
