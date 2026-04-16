'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'

type ItemType = 'credential_expiry' | 'coi_expiry' | 'regulation_update' | 'psc_checklist_progress' | 'log_gap'
type Urgency = 'high' | 'medium' | 'low'

interface ComingUpItem {
  type: ItemType
  urgency: Urgency
  title: string
  description: string
  target_url: string
  vessel_id: string | null
  vessel_name: string | null
  days_until: number | null
}

interface ComingUpResponse {
  items: ComingUpItem[]
  generated_at: string
}

const SESSION_KEY = 'regknot:coming_up:dismissed'

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.sessionStorage.getItem(SESSION_KEY) === '1'
  } catch {
    return false
  }
}

function writeDismissed(): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(SESSION_KEY, '1')
  } catch {
    /* noop */
  }
}

const URGENCY_STYLES: Record<Urgency, string> = {
  high: 'border-red-400/40 bg-red-500/5',
  medium: 'border-amber-400/40 bg-amber-500/5',
  low: 'border-white/10 bg-white/2',
}

const URGENCY_DOT: Record<Urgency, string> = {
  high: 'bg-red-400',
  medium: 'bg-amber-400',
  low: 'bg-[#6b7594]',
}

const TYPE_ICON: Record<ItemType, string> = {
  credential_expiry: '\u2299',     // ⊙
  coi_expiry: '\u25A1',             // □
  regulation_update: '\u2750',      // ❐
  psc_checklist_progress: '\u2611', // ☑
  log_gap: '\u270E',                // ✎
}

interface Props {
  /** When true, render the widget. Caller controls visibility. */
  visible: boolean
  /**
   * When true, render as a single-line pill that expands on tap.
   * When false (default), render the full widget. Used for active chats
   * where vertical space is precious.
   */
  compact?: boolean
}

export function ComingUpWidget({ visible, compact = false }: Props) {
  const router = useRouter()
  const [items, setItems] = useState<ComingUpItem[]>([])
  const [loading, setLoading] = useState(true)
  const [dismissed, setDismissed] = useState(readDismissed())
  const [expanded, setExpanded] = useState(false)
  // Compact-mode tap-to-expand. Independent of the "show more" expansion below.
  const [pillExpanded, setPillExpanded] = useState(false)

  useEffect(() => {
    if (!visible || dismissed) return
    let cancelled = false
    apiRequest<ComingUpResponse>('/coming-up')
      .then((r) => { if (!cancelled) setItems(r.items) })
      .catch(() => { if (!cancelled) setItems([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [visible, dismissed])

  function handleDismiss() {
    writeDismissed()
    setDismissed(true)
  }

  function handleItemClick(item: ComingUpItem) {
    router.push(item.target_url)
  }

  if (!visible || dismissed) return null
  if (loading) {
    // Skip the loading skeleton in compact mode — too noisy for active chats
    if (compact) return null
    return (
      <div className="mx-4 mt-4 mb-2 bg-[#111827] border border-white/8 rounded-xl px-4 py-3 animate-pulse h-16" />
    )
  }
  if (items.length === 0) {
    // Quiet success state — don't shout when nothing is up
    return null
  }

  const visibleItems = expanded ? items : items.slice(0, 3)
  const hiddenCount = items.length - visibleItems.length
  const highCount = items.filter((i) => i.urgency === 'high').length

  // ── Compact pill mode (active chats) ───────────────────────────────────
  // Single-line summary that expands inline on tap.
  if (compact && !pillExpanded) {
    return (
      <div className="mx-4 mt-3 mb-1 flex items-center gap-2">
        <button
          onClick={() => setPillExpanded(true)}
          className={`flex-1 flex items-center gap-2 px-3 py-1.5 rounded-full
            border text-left transition-colors duration-150
            ${highCount > 0
              ? 'border-red-400/40 bg-red-500/5 hover:bg-red-500/10'
              : 'border-[#2dd4bf]/30 bg-[#2dd4bf]/5 hover:bg-[#2dd4bf]/10'
            }`}
          aria-label="Show Coming Up items"
        >
          {highCount > 0 ? (
            <span className="font-mono text-[10px] text-red-400 font-bold">⚠</span>
          ) : (
            <span className="font-mono text-[10px] text-[#2dd4bf] font-bold">●</span>
          )}
          <span className="font-mono text-[10px] uppercase tracking-wider text-[#2dd4bf]">
            Coming Up
          </span>
          <span className="font-mono text-[10px] text-[#f0ece4]/80 truncate flex-1">
            {highCount > 0 ? (
              <>
                <span className="text-red-400 font-bold">{highCount} urgent</span>
                <span className="text-[#6b7594]"> · {items.length} total</span>
              </>
            ) : (
              <span className="text-[#6b7594]">{items.length} item{items.length !== 1 ? 's' : ''}</span>
            )}
          </span>
          <span className="font-mono text-[10px] text-[#6b7594]">tap</span>
        </button>
        <button
          onClick={handleDismiss}
          aria-label="Dismiss until next session"
          className="w-6 h-6 flex items-center justify-center rounded-full
            text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors shrink-0"
        >
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    )
  }

  // ── Full widget (fresh chat OR expanded compact) ──────────────────────
  return (
    <div className="mx-4 mt-4 mb-2 bg-[#111827] border border-[#2dd4bf]/20 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-[#2dd4bf] uppercase tracking-wider font-bold">
            Coming Up
          </span>
          <span className="font-mono text-[10px] text-[#6b7594]">
            {items.length} item{items.length !== 1 ? 's' : ''}
            {highCount > 0 && (
              <span className="text-red-400 ml-1.5">· {highCount} urgent</span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {compact && pillExpanded && (
            <button
              onClick={() => setPillExpanded(false)}
              aria-label="Collapse"
              className="w-6 h-6 flex items-center justify-center rounded
                text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
              title="Collapse to pill"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="18 15 12 9 6 15" />
              </svg>
            </button>
          )}
          <button
            onClick={handleDismiss}
            aria-label="Dismiss until next session"
            className="w-6 h-6 flex items-center justify-center rounded
              text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Items */}
      <div className="flex flex-col">
        {visibleItems.map((item, idx) => (
          <button
            key={`${item.type}-${idx}`}
            onClick={() => handleItemClick(item)}
            className={`flex items-start gap-3 px-4 py-2.5 text-left
              border-l-2 ${URGENCY_STYLES[item.urgency]}
              hover:bg-white/3 transition-colors duration-100
              ${idx > 0 ? 'border-t border-t-white/5' : ''}`}
          >
            <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${URGENCY_DOT[item.urgency]}`} aria-hidden="true" />
            <span className="font-mono text-xs text-[#2dd4bf]/70 shrink-0 w-4 leading-tight" aria-hidden="true">
              {TYPE_ICON[item.type]}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-mono text-sm text-[#f0ece4] leading-tight">{item.title}</p>
              {item.description && (
                <p className="font-mono text-[11px] text-[#6b7594] mt-0.5 leading-snug truncate">
                  {item.description}
                </p>
              )}
            </div>
            <svg className="w-3.5 h-3.5 text-[#6b7594]/50 mt-1 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        ))}
      </div>

      {/* Footer: show more / collapse */}
      {hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full font-mono text-[10px] text-[#2dd4bf] hover:text-[#2dd4bf]/80
            text-center py-2 border-t border-white/5 transition-colors"
        >
          Show {hiddenCount} more
        </button>
      )}
      {expanded && items.length > 3 && (
        <button
          onClick={() => setExpanded(false)}
          className="w-full font-mono text-[10px] text-[#6b7594] hover:text-[#f0ece4]
            text-center py-2 border-t border-white/5 transition-colors"
        >
          Collapse
        </button>
      )}
    </div>
  )
}
