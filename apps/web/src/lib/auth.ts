'use client'

import { create } from 'zustand'
import { cacheVessels } from './offlineCache'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface AuthUser {
  id: string
  email: string
  full_name: string | null
  role: string
  is_admin: boolean
  email_verified: boolean
}

function decodeJwtUser(token: string): AuthUser | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return {
      id: payload.sub as string,
      email: payload.email as string,
      full_name: (payload.full_name as string) ?? null,
      role: payload.role as string,
      is_admin: (payload.is_admin as boolean) ?? false,
      email_verified: (payload.email_verified as boolean) ?? false,
    }
  } catch {
    return null
  }
}

export interface BillingStatus {
  tier: string
  subscription_status: string
  trial_ends_at: string | null
  trial_active: boolean
  message_count: number
  messages_remaining: number | null
  needs_subscription: boolean
  cancel_at_period_end: boolean
  current_period_end: string | null
  billing_interval: string | null
  price_amount: number | null
}

export interface VesselSummary {
  id: string
  name: string
}

interface AuthState {
  user: AuthUser | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  hydrated: boolean
  vessels: VesselSummary[]
  activeVesselId: string | null
  billing: BillingStatus | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName: string, role: string) => Promise<void>
  logout: () => Promise<void>
  refreshAuth: () => Promise<boolean>
  hydrateAuth: () => Promise<void>
  setToken: (token: string, user: AuthUser) => void
  updateUserFromToken: (token: string) => void
  addVessel: (vessel: VesselSummary) => void
  removeVessel: (id: string) => void
  setVessels: (vessels: VesselSummary[]) => void
  setActiveVessel: (id: string | null) => void
  setBilling: (billing: BillingStatus) => void
}

// Mutex: only one refresh call in flight at a time
let refreshPromise: Promise<boolean> | null = null

// Persisted auth hint — lets offline users hydrate the UI with their last
// known user info without hitting /auth/refresh. NOT a secret: just the
// decoded JWT payload (id/email/role), which is already sent to the client
// on every login. The actual refresh token stays in an HttpOnly cookie.
const AUTH_HINT_KEY = 'regknots_auth_hint'

function persistAuthHint(user: AuthUser): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(AUTH_HINT_KEY, JSON.stringify(user))
  } catch {
    // ignore private-mode / quota errors
  }
}

function clearAuthHint(): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(AUTH_HINT_KEY)
  } catch {
    // ignore
  }
}

function readAuthHint(): AuthUser | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem(AUTH_HINT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthUser
    if (!parsed || typeof parsed.id !== 'string') return null
    return parsed
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: false,
  hydrated: false,
  vessels: [],
  activeVesselId: null,
  billing: null,

  addVessel: (vessel: VesselSummary) =>
    set((s) => ({ vessels: [...s.vessels, vessel] })),

  removeVessel: (id: string) =>
    set((s) => ({
      vessels: s.vessels.filter((v) => v.id !== id),
      activeVesselId: s.activeVesselId === id ? null : s.activeVesselId,
    })),

  setVessels: (vessels: VesselSummary[]) => {
    set({ vessels })
    // Best-effort offline cache — never block or fail the main flow.
    cacheVessels(vessels).catch(() => {})
  },

  setActiveVessel: (id: string | null) =>
    set({ activeVesselId: id }),

  setBilling: (billing: BillingStatus) =>
    set({ billing }),

  setToken: (token: string, user: AuthUser) => {
    set({ accessToken: token, user, isAuthenticated: true })
    persistAuthHint(user)
  },

  updateUserFromToken: (token: string) => {
    const user = decodeJwtUser(token)
    if (user) set({ accessToken: token, user })
  },

  login: async (email: string, password: string) => {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(err.detail ?? 'Login failed')
    }

    const data = await res.json()
    const user = decodeJwtUser(data.access_token)
    set({
      accessToken: data.access_token,
      user,
      isAuthenticated: true,
    })
    if (user) persistAuthHint(user)
  },

  register: async (email: string, password: string, fullName: string, role: string) => {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password, full_name: fullName, role }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Registration failed' }))
      throw new Error(err.detail ?? 'Registration failed')
    }

    const data = await res.json()
    const user = decodeJwtUser(data.access_token)
    set({
      accessToken: data.access_token,
      user,
      isAuthenticated: true,
    })
    if (user) persistAuthHint(user)
  },

  logout: async () => {
    const { accessToken } = get()
    try {
      await fetch(`${API_URL}/auth/logout`, {
        method: 'POST',
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
        credentials: 'include',
      })
    } catch {
      // Ignore network errors on logout
    }
    clearAuthHint()
    set({ accessToken: null, user: null, isAuthenticated: false, vessels: [], activeVesselId: null, billing: null })
  },

  hydrateAuth: async () => {
    if (get().hydrated) return // Already hydrated, never re-run

    // Offline shortcut: don't even attempt /auth/refresh — it's guaranteed
    // to fail and would leave us with no auth state. Instead, restore the
    // last known user from the persisted auth hint so the cached UI can
    // render (API calls will fail gracefully, cached data fills the gap).
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      const hint = readAuthHint()
      if (hint) {
        set({ user: hint, isAuthenticated: true })
      }
      set({ hydrated: true })
      return
    }

    await get().refreshAuth()
    set({ hydrated: true })
  },

  refreshAuth: async () => {
    // If a refresh is already in flight, wait for it instead of firing another
    if (refreshPromise) {
      return refreshPromise
    }

    refreshPromise = (async () => {
      try {
        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        })

        if (!res.ok) {
          // Clear the revoked cookie so we don't loop on next page load
          try {
            await fetch(`${API_URL}/auth/logout`, {
              method: 'POST',
              credentials: 'include',
            })
          } catch {}
          clearAuthHint()
          set({ accessToken: null, user: null, isAuthenticated: false })
          return false
        }

        const data = await res.json()
        const user = decodeJwtUser(data.access_token)
        set({
          accessToken: data.access_token,
          user,
          isAuthenticated: true,
        })
        if (user) persistAuthHint(user)
        return true
      } catch {
        // Network error (offline, DNS fail, CORS, etc.) — distinguish from a
        // real auth failure. If the user is offline, DO NOT clear auth state
        // or log them out; they may still have a valid session we just can't
        // verify right now. Restore the persisted hint so the UI renders
        // with the last-known user, and let the offline-cache fallbacks
        // supply the data.
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
          const hint = readAuthHint()
          if (hint) {
            set({ user: hint, isAuthenticated: true })
          }
          return false
        }
        set({ accessToken: null, user: null, isAuthenticated: false })
        return false
      } finally {
        refreshPromise = null
      }
    })()

    return refreshPromise
  },
}))
