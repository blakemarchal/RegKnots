'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

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
 * Renders children immediately while the status check is in flight to avoid
 * a blank screen — if a redirect happens, it overrides whatever rendered.
 */
export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const checkedRef = useRef(false)
  const [redirecting, setRedirecting] = useState(false)

  useEffect(() => {
    if (!isAuthenticated || checkedRef.current) return
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
  }, [isAuthenticated, router])

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
