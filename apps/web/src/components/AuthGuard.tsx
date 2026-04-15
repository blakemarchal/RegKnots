'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/auth'
import { apiRequest } from '@/lib/api'

interface VesselRow {
  id: string
  name: string
}

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isAuthenticated, hydrated, vessels, setVessels } = useAuthStore()
  const hydrationStartedRef = useRef(false)

  useEffect(() => {
    if (hydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [hydrated, isAuthenticated, router])

  // Hydrate vessel list into the store on first mount for authenticated users.
  // Ensures pages like /psc-checklist and /log have vessels available even
  // when the user navigates there directly without touching the home screen.
  useEffect(() => {
    if (!isAuthenticated || hydrationStartedRef.current) return
    if (vessels.length > 0) {
      hydrationStartedRef.current = true
      return
    }
    hydrationStartedRef.current = true
    apiRequest<VesselRow[]>('/vessels')
      .then((rows) => {
        setVessels(rows.map((v) => ({ id: v.id, name: v.name })))
      })
      .catch(() => {
        // Silent — pages will show their own empty-state UX
      })
  }, [isAuthenticated, vessels.length, setVessels])

  if (!isAuthenticated) {
    return null
  }

  return <>{children}</>
}
