'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
import { CompassRose } from './CompassRose'

// Pages that don't require auth — never block them with a loading screen
const GUEST_PAGES = ['/landing', '/login', '/register', '/forgot-password', '/reset-password']

export function HydrationGate({ children }: { children: React.ReactNode }) {
  const { hydrated, hydrateAuth } = useAuthStore()
  const pathname = usePathname()

  const isGuestPage = GUEST_PAGES.some(p => pathname.startsWith(p))

  useEffect(() => {
    if (!hydrated) {
      hydrateAuth()
    }
  }, [hydrated, hydrateAuth])

  // Guest pages render immediately — no auth gate
  if (isGuestPage) {
    return <>{children}</>
  }

  if (!hydrated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#0a0e1a]">
        <CompassRose className="w-12 h-12 text-[#2dd4bf] animate-[compassSpin_3s_linear_infinite]" />
      </div>
    )
  }

  return <>{children}</>
}
