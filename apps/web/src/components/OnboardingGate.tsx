'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useViewMode } from '@/lib/useViewMode'

interface OnboardingStatus {
  onboarding_completed_at: string | null
  vessel_count: number
  credential_count: number
  needs_onboarding: boolean
}

/**
 * Wrap the chat home page. On mount, checks /onboarding/status — if the user
 * is brand new (no flag, no vessels, no credentials), redirects to /welcome.
 *
 * Existing users with any data are implicitly onboarded; the gate is a no-op
 * for them. Also a no-op for unauthenticated users (AuthGuard handles those).
 *
 * D6.53 — additional skip conditions:
 *   - URL has ?workspace=<id>: user is in workspace chat context, the
 *     workspace owns vessel data; personal onboarding doesn't apply.
 *   - view mode is wheelhouse_only: user has no personal-tier surface
 *     and shouldn't be asked about personal vessels at all. (Belt and
 *     suspenders — WheelhouseRedirect already kicks them to the
 *     workspace dashboard, but defense in depth in case a wheelhouse-
 *     only user navigates here directly via a deep link.)
 *
 * Renders children immediately while the status check is in flight to avoid
 * a blank screen — if a redirect happens, it overrides whatever rendered.
 */
export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const { viewMode } = useViewMode()
  const checkedRef = useRef(false)
  const [redirecting, setRedirecting] = useState(false)

  const inWorkspaceContext = searchParams.get('workspace') !== null
  const isWheelhouseOnly = viewMode?.mode === 'wheelhouse_only'

  useEffect(() => {
    if (!isAuthenticated || checkedRef.current) return
    if (inWorkspaceContext || isWheelhouseOnly) {
      // No personal onboarding for workspace surfaces or invite-only
      // accounts. Mark as checked so we don't re-evaluate on re-render.
      checkedRef.current = true
      return
    }
    checkedRef.current = true

    apiRequest<OnboardingStatus>('/onboarding/status')
      .then((status) => {
        if (status.needs_onboarding) {
          setRedirecting(true)
          router.replace('/welcome')
        }
      })
      .catch(() => {
        // Silent: a status check failure shouldn't block chat access
      })
  }, [isAuthenticated, router, inWorkspaceContext, isWheelhouseOnly])

  if (redirecting) {
    // Brief loading state during redirect to avoid flash of chat
    return (
      <div className="flex flex-col h-dvh bg-[#0a0e1a] items-center justify-center">
        <div className="w-8 h-8 border-2 border-[#2dd4bf] border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return <>{children}</>
}
