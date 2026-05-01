'use client'

import { useEffect } from 'react'
import { HydrationGate } from './HydrationGate'
import { NavigationProgress } from './NavigationProgress'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

// Sprint D6.37 — light/dark theme application.
// Storage strategy: localStorage cache for synchronous apply (avoid flash
// of wrong theme on page load), API source of truth refreshed on auth.
const THEME_STORAGE_KEY = 'regknot_theme'
type ThemePref = 'dark' | 'light' | 'auto'

/** Apply the theme attribute to <html>. "auto" resolves via prefers-color-scheme. */
function applyTheme(pref: ThemePref) {
  if (typeof document === 'undefined') return
  const resolved =
    pref === 'auto'
      ? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
      : pref
  document.documentElement.setAttribute('data-theme', resolved)
}

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

  // Sprint D6.37 — apply theme on mount. Read localStorage first
  // (synchronous, no flash), then fetch the user's saved preference
  // from the API once authenticated and reconcile.
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  useEffect(() => {
    // Pass 1: localStorage (instant)
    if (typeof window !== 'undefined') {
      const cached = (localStorage.getItem(THEME_STORAGE_KEY) ?? 'dark') as ThemePref
      applyTheme(cached)
    }
  }, [])

  useEffect(() => {
    // Pass 2: source-of-truth fetch when authenticated. Updates
    // localStorage so subsequent loads are instant. Logged-out users
    // retain their last cached choice (logout doesn't clear theme).
    if (!isAuthenticated) return
    apiRequest<{ theme_preference: string | null }>('/onboarding/persona')
      .then((r) => {
        const pref = (r.theme_preference ?? 'dark') as ThemePref
        if (pref === 'dark' || pref === 'light' || pref === 'auto') {
          localStorage.setItem(THEME_STORAGE_KEY, pref)
          applyTheme(pref)
        }
      })
      .catch(() => { /* keep cached theme on fetch failure */ })
  }, [isAuthenticated])

  return (
    <HydrationGate>
      <NavigationProgress />
      {children}
    </HydrationGate>
  )
}
