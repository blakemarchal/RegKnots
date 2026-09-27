import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Routes that authenticated users should never see — send them to the app
const GUEST_ONLY = ['/landing', '/login', '/register']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // The refresh_token cookie (httpOnly, path="/", SameSite=Lax) is set by the
  // FastAPI auth router on login/register/refresh. Its presence means the
  // browser has an active session.
  const hasSession = request.cookies.has('refresh_token')

  // 2026-09-26 — redirects keep the query string. `new URL('/landing', url)`
  // dropped it, so a link to regknots.com/?utm_source=... lost its
  // attribution before the page loaded.
  const redirectTo = (path: string) => {
    const url = request.nextUrl.clone()
    url.pathname = path
    return NextResponse.redirect(url)
  }

  // Authenticated users hitting guest-only pages → send to app
  if (GUEST_ONLY.includes(pathname) && hasSession) {
    return redirectTo('/')
  }

  // Unauthenticated users hitting the app root → send to landing
  if (pathname === '/' && !hasSession) {
    return redirectTo('/landing')
  }

  return NextResponse.next()
}

export const config = {
  // Only run on these routes — never on /_next/*, /api/*, or static assets
  matcher: ['/', '/landing', '/login', '/register', '/pricing', '/subscribe/success'],
}
