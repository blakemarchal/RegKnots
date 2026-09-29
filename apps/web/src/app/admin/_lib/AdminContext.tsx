'use client'

// 2026-09-29 — state shared by every admin page: the viewer's role, the
// "hide internal data" switch, and the headline stats + Sentry issues that
// drive the sidebar's attention badges. Pages fetch their own data; this is
// only what the shell itself needs. Refreshes every 2 minutes while the tab
// is visible (the old single page re-polled nine endpoints every minute).

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '@/lib/api'
import type { AdminStats, SentryIssue } from './types'

interface AdminContextValue {
  excludeInternal: boolean
  setExcludeInternal: (v: boolean) => void
  /** exclude_internal query value */
  ei: 'true' | 'false'
  isOwner: boolean
  isReadOnly: boolean
  stats: AdminStats | null
  statsError: boolean
  sentry: SentryIssue[] | null
  refresh: () => void
  updatedAt: number | null
}

const AdminContext = createContext<AdminContextValue | null>(null)

const REFRESH_MS = 120_000

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [excludeInternal, setExcludeInternalState] = useState(true)
  const [isOwner, setIsOwner] = useState(false)
  const [isReadOnly, setIsReadOnly] = useState(false)
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [statsError, setStatsError] = useState(false)
  const [sentry, setSentry] = useState<SentryIssue[] | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)

  useEffect(() => {
    if (localStorage.getItem('admin_exclude_internal') === 'false') setExcludeInternalState(false)
    apiRequest<{ is_owner: boolean; is_readonly?: boolean }>('/admin/role')
      .then((r) => { setIsOwner(r.is_owner); setIsReadOnly(!!r.is_readonly) })
      .catch(() => setIsOwner(false))
  }, [])

  const setExcludeInternal = useCallback((v: boolean) => {
    setExcludeInternalState(v)
    setStats(null)
    localStorage.setItem('admin_exclude_internal', String(v))
  }, [])

  const ei = excludeInternal ? 'true' : 'false'

  const refresh = useCallback(() => {
    setStatsError(false)
    apiRequest<AdminStats>(`/admin/stats?exclude_internal=${ei}`)
      .then((s) => { setStats(s); setUpdatedAt(Date.now()) })
      .catch(() => setStatsError(true))
    apiRequest<SentryIssue[]>('/admin/sentry-issues')
      .then(setSentry)
      .catch(() => setSentry([]))
  }, [ei])

  useEffect(() => {
    refresh()
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  const value = useMemo<AdminContextValue>(() => ({
    excludeInternal, setExcludeInternal, ei, isOwner, isReadOnly,
    stats, statsError, sentry, refresh, updatedAt,
  }), [excludeInternal, setExcludeInternal, ei, isOwner, isReadOnly, stats, statsError, sentry, refresh, updatedAt])

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>
}

export function useAdmin(): AdminContextValue {
  const ctx = useContext(AdminContext)
  if (!ctx) throw new Error('useAdmin must be used inside <AdminProvider>')
  return ctx
}
