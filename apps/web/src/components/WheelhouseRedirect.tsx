'use client'

// Sprint D6.53 — Wheelhouse-only landing redirect.
//
// Wraps a page (typically `/`). If the signed-in user has NO personal
// access (no paid sub, no active trial, not admin/internal) but DOES
// have a workspace seat, they're "Wheelhouse-only" — we redirect them
// straight into their primary workspace instead of showing the
// personal chat surface. Other modes pass through unchanged.
//
// The redirect runs once per page load. We deliberately don't loop
// the workspace page back to `/` for individual users — they're
// allowed to navigate there manually, the redirect just changes the
// default landing.

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useViewMode } from '@/lib/useViewMode'

export function WheelhouseRedirect({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { viewMode } = useViewMode()

  useEffect(() => {
    if (!viewMode) return
    if (viewMode.mode === 'wheelhouse_only' && viewMode.primary_workspace_id) {
      router.replace(`/workspaces/${viewMode.primary_workspace_id}`)
    }
  }, [viewMode, router])

  // While we're fetching view-mode AND the user might be Wheelhouse-only,
  // render nothing to avoid a flash of the personal chat surface for a
  // user who's about to be redirected away from it. Once we know the
  // mode (or after the timeout below), let the children render.
  if (!viewMode) return null
  if (viewMode.mode === 'wheelhouse_only') return null
  return <>{children}</>
}
