'use client'

// 2026-09-29 — one gate and one shell for every /admin route. Before this,
// /admin/hedge-audit, /admin/web-fallback and /admin/chat-preview each
// carried their own header and relied on the API's 403 alone.

import { Suspense, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { MilestoneCelebration } from '@/components/MilestoneCelebration'
import { useAuthStore } from '@/lib/auth'
import { AdminProvider, useAdmin } from './_lib/AdminContext'
import { AdminShell } from './_components/AdminShell'

function AdminGate({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const hydrated = useAuthStore((s) => s.hydrated)
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false)
  useEffect(() => {
    if (hydrated && !isAdmin) router.replace('/')
  }, [hydrated, isAdmin, router])
  if (!hydrated || !isAdmin) return null
  return <>{children}</>
}

function Celebration() {
  const { stats } = useAdmin()
  return <MilestoneCelebration paidUsersAlltime={stats?.paid_users_alltime ?? null} />
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <AdminGate>
        <AdminProvider>
          <Celebration />
          {/* Suspense: pages read useSearchParams() (deep links, filters). */}
          <AdminShell><Suspense fallback={null}>{children}</Suspense></AdminShell>
        </AdminProvider>
      </AdminGate>
    </AuthGuard>
  )
}
