'use client'

import { create } from 'zustand'

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
  unlimited?: boolean  // True for admin/internal — bypass all limits/banners
  // Sprint D6.2 — Mate tier monthly message cap visibility.
  // Only meaningful when tier === 'mate'. Captain and legacy pro return
  // monthly_message_cap=null; free users return whatever their state is
  // but the UI should rely on trial_active + messages_remaining instead.
  monthly_message_cap: number | null
  monthly_messages_used: number
  monthly_messages_remaining: number | null
  cycle_resets_at: string | null
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
  },

  setActiveVessel: (id: string | null) =>
    set({ activeVesselId: id }),

  setBilling: (billing: BillingStatus) =>
    set({ billing }),

  setToken: (token: string, user: AuthUser) => {
    set({ accessToken: token, user, isAuthenticated: true })
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
    set({ accessToken: null, user: null, isAuthenticated: false, vessels: [], activeVesselId: null, billing: null })
  },

  hydrateAuth: async () => {
    if (get().hydrated) return // Already hydrated, never re-run
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
        return true
      } catch {
        set({ accessToken: null, user: null, isAuthenticated: false })
        return false
      } finally {
        refreshPromise = null
      }
    })()

    return refreshPromise
  },
}))
