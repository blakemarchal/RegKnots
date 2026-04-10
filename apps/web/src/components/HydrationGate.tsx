'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
import { CompassRose } from './CompassRose'

// Fully public routes that never need an auth refresh. `/` is intentionally
// NOT included — it renders the authenticated chat via AuthGuard and must
// still hydrate. When adding a new public marketing/legal page, add it here
// so anonymous visitors don't trigger a spurious POST /auth/refresh 401.
const PUBLIC_ROUTES = [
  '/landing',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/terms',
  '/privacy',
  '/giving',
  '/pricing',
  '/support',
  '/whitelisting',
  '/brand',
  '/reference',
]

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some(p => pathname === p || pathname.startsWith(p + '/'))
}

export function HydrationGate({ children }: { children: React.ReactNode }) {
  const { hydrated, hydrateAuth } = useAuthStore()
  const pathname = usePathname()

  const isPublic = isPublicRoute(pathname)

  useEffect(() => {
    if (hydrated) return
    if (isPublic) return
    hydrateAuth()
  }, [hydrated, isPublic, hydrateAuth])

  if (isPublic) {
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
