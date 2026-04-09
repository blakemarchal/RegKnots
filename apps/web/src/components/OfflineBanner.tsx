'use client'

import { useOfflineDetection } from '@/hooks/useOfflineDetection'

/**
 * Fixed top banner shown whenever the browser reports offline.
 *
 * Lives above all page content so cached-data fallbacks and disabled inputs
 * in child pages stay discoverable. Animates in with a short translate-y
 * transition; hidden entirely while online so it doesn't shift layout.
 */
export function OfflineBanner() {
  const { isOffline } = useOfflineDetection()

  if (!isOffline) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-0 left-0 right-0 z-50 bg-amber-500/90 py-2 px-4
        font-mono text-xs text-[#0a0e1a] text-center
        transform transition-transform duration-200 ease-out translate-y-0
        motion-safe:animate-[slideDown_0.25s_ease-out]"
    >
      You&apos;re offline &mdash; showing cached data. New queries unavailable.
    </div>
  )
}
