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
  // 2026-10-14 — public search pages: their content must be in the server
  // HTML, not behind the spinner.
  '/practice',
  '/coverage',
  '/regs',
]

// 2026-10-14 — public pages that render for everyone at once but also read the
// session when there is one (a signed-in CTA, the menu): rendered immediately,
// with the auth refresh in the background.
const PUBLIC_AUTH_AWARE_ROUTES = ['/education', '/whale-zones']

function matches(routes: string[], pathname: string): boolean {
  return routes.some(p => pathname === p || pathname.startsWith(p + '/'))
}

function isPublicRoute(pathname: string): boolean {
  return matches(PUBLIC_ROUTES, pathname)
}

export function HydrationGate({ children }: { children: React.ReactNode }) {
  const { hydrated, hydrateAuth } = useAuthStore()
  const pathname = usePathname()

  const isPublic = isPublicRoute(pathname)
  const authAware = matches(PUBLIC_AUTH_AWARE_ROUTES, pathname)

  useEffect(() => {
    if (hydrated) return
    if (isPublic) return
    hydrateAuth()
  }, [hydrated, isPublic, hydrateAuth])

  if (isPublic || authAware) {
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
