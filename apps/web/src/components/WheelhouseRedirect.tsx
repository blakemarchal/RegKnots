'use client'

// Sprint D6.53 — Wheelhouse-only landing redirect.
//
// Wraps the root chat surface (`/`). If the signed-in user has no
// personal access (no paid sub, no active trial, not admin/internal)
// but DOES have a workspace seat, they're "Wheelhouse-only" — we
// redirect them straight into their primary workspace dashboard
// instead of rendering the personal chat surface.
//
// CRITICAL: We must allow `/?workspace=<id>` (and other context
// params) through unconditionally, even for wheelhouse_only users.
// That URL IS the workspace chat surface — the workspace detail
// page's "Open chat →" button links there. If we redirect those
// requests, the user can never enter chat (they bounce between
// /workspaces/<id> and /?workspace=<id> forever).
//
// The redirect only fires when the user lands at `/` WITHOUT any
// signal that they're trying to reach a specific surface.

import { useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useViewMode } from '@/lib/useViewMode'

export function WheelhouseRedirect({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { viewMode } = useViewMode()

  // If the URL is carrying any context that means "I want to be on
  // the personal chat surface right now", let it through. Workspace
  // chat is `/?workspace=<id>`; conversation deep-links are
  // `?conversation_id=<id>`; landing-from-search has `?q=`.
  const hasContextParam =
    searchParams.get('workspace') !== null
    || searchParams.get('conversation_id') !== null
    || searchParams.get('q') !== null

  useEffect(() => {
    if (!viewMode) return
    if (hasContextParam) return
    if (viewMode.mode === 'wheelhouse_only' && viewMode.primary_workspace_id) {
      router.replace(`/workspaces/${viewMode.primary_workspace_id}`)
    }
  }, [viewMode, router, hasContextParam])

  // Blocking render: while we're still loading view-mode AND the user
  // could plausibly be wheelhouse_only AND has no context param,
  // render nothing to avoid a flash of personal chat. Otherwise let
  // the children render — they handle their own auth/workspace logic.
  if (hasContextParam) return <>{children}</>
  if (!viewMode) return null
  if (viewMode.mode === 'wheelhouse_only') return null
  return <>{children}</>
}
