'use client'

// Sprint D6.53 — Wheelhouse-only view mode.
//
// Three views, derived server-side from "what does this user have?":
//
//   individual                  free or paid, no workspaces. Default RegKnot view.
//   individual_with_workspaces  paid sub AND workspace seat(s). Shows the
//                               personal view with a Wheelhouse switcher
//                               in the nav.
//   wheelhouse_only             ONLY a workspace seat (no personal sub).
//                               They land directly in the workspace
//                               portal — no personal chat surface, no
//                               upgrade nag.
//
// We compute this on the server (/me/view-mode) rather than in the
// JWT so it stays fresh without a token refresh when a workspace is
// added or a subscription changes.
//
// Caching strategy: the result is cached in module-scope state with a
// 60s TTL keyed by the JWT subject. This avoids fanning out one
// /me/view-mode call per render across the app while still picking up
// changes within a minute. Components that mutate workspace
// membership (accept invite, join workspace) call refresh() to bust
// the cache immediately.

import { useEffect, useState } from 'react'
import { useAuthStore } from './auth'
import { apiRequest, ApiError } from './api'

export type ViewMode =
  | 'individual'
  | 'individual_with_workspaces'
  | 'wheelhouse_only'

export interface ViewModeData {
  mode: ViewMode
  workspace_count: number
  has_personal_access: boolean
  primary_workspace_id: string | null
  pending_invite_count: number
}

interface CacheEntry {
  data: ViewModeData
  fetchedAt: number
}

const TTL_MS = 60_000
const cache = new Map<string, CacheEntry>()
let inFlight: Map<string, Promise<ViewModeData | null>> = new Map()

async function fetchViewMode(userId: string): Promise<ViewModeData | null> {
  // De-dupe concurrent calls so a fresh page load with five components
  // mounting in parallel still only sends one request.
  const existing = inFlight.get(userId)
  if (existing) return existing
  const p = (async () => {
    try {
      const data = await apiRequest<ViewModeData>('/me/view-mode')
      cache.set(userId, { data, fetchedAt: Date.now() })
      return data
    } catch (e) {
      // 404 = crew tier disabled (CREW_TIER_ENABLED=false). Treat as
      // a stable "individual" mode so the rest of the UI works for
      // users who don't see the Wheelhouse feature at all.
      if (e instanceof ApiError && e.status === 404) {
        const fallback: ViewModeData = {
          mode: 'individual',
          workspace_count: 0,
          has_personal_access: true,
          primary_workspace_id: null,
          pending_invite_count: 0,
        }
        cache.set(userId, { data: fallback, fetchedAt: Date.now() })
        return fallback
      }
      return null
    } finally {
      inFlight.delete(userId)
    }
  })()
  inFlight.set(userId, p)
  return p
}

/**
 * Hook returning the caller's view mode. Returns `null` while loading
 * or if the user is not authenticated. Components should typically
 * render a neutral loading state until this resolves.
 *
 * Call `refresh()` after mutations that change workspace membership
 * (accepting/declining an invite, leaving a workspace, etc.) so the
 * UI doesn't lag behind the new mode.
 */
export function useViewMode(): {
  viewMode: ViewModeData | null
  loading: boolean
  refresh: () => Promise<void>
} {
  const user = useAuthStore((s) => s.user)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const userId = user?.id ?? null

  const [viewMode, setViewMode] = useState<ViewModeData | null>(() => {
    if (!userId) return null
    const cached = cache.get(userId)
    return cached ? cached.data : null
  })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!isAuthenticated || !userId) {
      setViewMode(null)
      return
    }
    const cached = cache.get(userId)
    if (cached && Date.now() - cached.fetchedAt < TTL_MS) {
      setViewMode(cached.data)
      return
    }
    setLoading(true)
    void (async () => {
      const data = await fetchViewMode(userId)
      setViewMode(data)
      setLoading(false)
    })()
  }, [isAuthenticated, userId])

  async function refresh() {
    if (!userId) return
    cache.delete(userId)
    inFlight.delete(userId)
    setLoading(true)
    const data = await fetchViewMode(userId)
    setViewMode(data)
    setLoading(false)
  }

  return { viewMode, loading, refresh }
}
