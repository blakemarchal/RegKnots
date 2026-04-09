'use client'

import { useOfflineDetection } from '@/hooks/useOfflineDetection'

/**
 * Small amber pill rendered inline next to the RegKnot logo in each header
 * when the browser reports offline. Replaces the previous fixed top banner
 * which overlapped the header action buttons. Returns null while online so
 * it takes up zero layout space on the happy path.
 */
export function OfflineIndicator() {
  const { isOffline } = useOfflineDetection()

  if (!isOffline) return null

  return (
    <span
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
        border border-amber-500/40 bg-amber-500/15
        font-mono text-[9px] font-bold uppercase tracking-wider text-amber-400
        flex-shrink-0"
      title="You're offline — showing cached data. New queries unavailable."
    >
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" aria-hidden="true" />
      Offline
    </span>
  )
}
