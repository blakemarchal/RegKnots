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

  // Authenticated users hitting guest-only pages → send to app
  if (GUEST_ONLY.includes(pathname) && hasSession) {
    return NextResponse.redirect(new URL('/', request.url))
  }

  // Unauthenticated users hitting the app root → send to landing
  if (pathname === '/' && !hasSession) {
    return NextResponse.redirect(new URL('/landing', request.url))
  }

  return NextResponse.next()
}

export const config = {
  // Only run on these routes — never on /_next/*, /api/*, or static assets
  matcher: ['/', '/landing', '/login', '/register', '/pricing', '/subscribe/success'],
}
