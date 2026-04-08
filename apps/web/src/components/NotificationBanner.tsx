'use client'

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

interface Notification {
  id: string
  title: string
  body: string
  notification_type: string
  source: string | null
  link_url: string | null
  created_at: string
}

const MAX_VISIBLE = 2

/**
 * In-app banner stack shown above the chat thread.
 * Displays up to 2 active notifications at once; any excess collapses
 * to a "N more updates" pill. Dismissals persist server-side.
 */
export function NotificationBanner() {
  const user = useAuthStore((s) => s.user)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    if (!user) return
    let cancelled = false
    apiRequest<Notification[]>('/notifications/active')
      .then((data) => {
        if (!cancelled) {
          setNotifications(data)
          // Allow one tick so the slide-down transition plays.
          requestAnimationFrame(() => setMounted(true))
        }
      })
      .catch(() => {
        // Silently ignore — banner is a nice-to-have, never a blocker.
      })
    return () => {
      cancelled = true
    }
  }, [user])

  async function dismiss(id: string) {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
    try {
      await apiRequest(`/notifications/${id}/dismiss`, { method: 'POST' })
    } catch {
      // If the dismiss call fails, the banner will come back on next page load.
    }
  }

  if (!user || notifications.length === 0) return null

  const visible = notifications.slice(0, MAX_VISIBLE)
  const overflow = notifications.length - visible.length

  return (
    <div
      className={`flex-shrink-0 flex flex-col gap-2 px-4 pt-3 pb-1
        transition-all duration-300 ease-out
        ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-2'}`}
    >
      {visible.map((n) => (
        <NotificationCard key={n.id} notification={n} onDismiss={() => dismiss(n.id)} />
      ))}
      {overflow > 0 && (
        <p className="font-mono text-[10px] text-[#6b7594] pl-3">
          + {overflow} more update{overflow === 1 ? '' : 's'}
        </p>
      )}
    </div>
  )
}

function NotificationCard({
  notification,
  onDismiss,
}: {
  notification: Notification
  onDismiss: () => void
}) {
  return (
    <div
      className="relative flex items-start gap-3 p-3
        bg-[#111827] rounded-lg border-l-4 border-[#2dd4bf]"
    >
      <div className="flex-shrink-0 mt-0.5 text-[#2dd4bf]">
        <TypeIcon type={notification.notification_type} />
      </div>
      <div className="flex-1 min-w-0 pr-6">
        <p className="font-display font-bold text-sm text-[#f0ece4] leading-tight uppercase tracking-wide">
          {notification.title}
        </p>
        <p className="font-mono text-xs text-[#6b7594] mt-1 leading-snug">
          {notification.body}
        </p>
        {notification.link_url && (
          <a
            href={notification.link_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block mt-1 font-mono text-[11px] text-[#2dd4bf] hover:underline"
          >
            Learn more →
          </a>
        )}
      </div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="absolute top-2 right-2 w-6 h-6 flex items-center justify-center
          rounded text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  )
}

function TypeIcon({ type }: { type: string }) {
  if (type === 'regulation_update') {
    // Scroll / document icon for regulation updates
    return (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" />
        <line x1="8" y1="17" x2="14" y2="17" />
      </svg>
    )
  }
  // Default: bell icon
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  )
}
