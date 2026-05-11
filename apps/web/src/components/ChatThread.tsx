'use client'

import { useEffect, useRef } from 'react'
import type { Message } from '@/types/chat'
import { ChatMessage } from './ChatMessage'
import { TypingIndicator } from './TypingIndicator'
import { EmptyState } from './EmptyState'
import type { VesselProfileForPrompts } from '@/lib/vesselPrompts'

interface Props {
  messages: Message[]
  loading: boolean
  progressMsg?: string | null
  onPrompt: (text: string) => void
  onCitationTap: (source: string, sectionNumber: string, sectionTitle: string) => void
  isNewConversation: boolean
  vessel?: VesselProfileForPrompts | null
  // Sprint D6.88 Phase 3 — render an inline indicator below the latest
  // message while the engine is dispatching a web fallback. Lets the
  // user know more content is coming after the streamed answer.
  webFallbackInFlight?: boolean
}

// Sprint D6.89 — within this many pixels of the bottom counts as
// "user is following the latest content." Outside this window we
// don't auto-scroll because the user has deliberately scrolled up
// to read prior content. Synchronously computed at scroll-decision
// time — no IntersectionObserver, no state, no event listeners.
const AT_BOTTOM_THRESHOLD_PX = 120

/** Walk up the DOM from a child element until we find the scrollable
 *  ancestor (the .chat-thread main element). Returns null if none
 *  found, in which case auto-scroll falls back to scrollIntoView
 *  defaults. */
function findScrollContainer(el: HTMLElement | null): HTMLElement | null {
  let cur: HTMLElement | null = el
  while (cur && !cur.classList.contains('chat-thread')) {
    cur = cur.parentElement
  }
  return cur
}

export function ChatThread({
  messages, loading, progressMsg = null, onPrompt, onCitationTap,
  isNewConversation, vessel = null, webFallbackInFlight = false,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Sprint D6.89 — auto-scroll logic, simplified.
  //
  // What got removed: the IntersectionObserver-based followLatest ref,
  // the user-scroll grace window, the wheel/touchmove event listeners,
  // the showJumpButton state, the "Jump to latest" pill.
  //
  // What we have instead: a single useEffect that computes scroll
  // position SYNCHRONOUSLY at the moment of the scroll decision. If
  // the user is within AT_BOTTOM_THRESHOLD_PX of the bottom of the
  // scrollable container, we scroll. Otherwise we don't. No state
  // toggling, no observer callbacks, no jitter, no fight with wheel
  // input — because the scroll decision reads the literal scroll
  // position rather than tracking it via a separate observer that
  // can race against the render.
  //
  // The 'instant' behavior is critical: smooth-scroll animation
  // during streaming was the original source of the jitter loop
  // (D6.87 history). Instant snap = no animation = no oscillation.
  useEffect(() => {
    if (messages.length === 0 && !loading) return
    const sentinel = bottomRef.current
    if (!sentinel) return
    const container = findScrollContainer(sentinel)
    if (!container) {
      // Defensive: if we can't find the scrollable parent, do nothing.
      // Better to leave the page where it is than to auto-scroll a
      // surface we can't reason about.
      return
    }
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
    if (distanceFromBottom > AT_BOTTOM_THRESHOLD_PX) {
      // User scrolled up to read earlier content. Don't yank them
      // back to the bottom.
      return
    }
    sentinel.scrollIntoView({ behavior: 'instant' as ScrollBehavior })
  }, [messages, loading, progressMsg])

  return (
    <div className="flex flex-col min-h-full">
      {messages.length === 0 && !loading ? (
        <EmptyState onPrompt={onPrompt} isNewConversation={isNewConversation} vessel={vessel} />
      ) : (
        <div className="flex flex-col py-3 gap-0.5">
          {messages.map(msg => (
            <ChatMessage key={msg.id} message={msg} onCitationTap={onCitationTap} />
          ))}
          {/* Sprint D6.88 Phase 3 — inline web-fallback indicator.
              Sits in the user's reading flow (just below the streamed
              answer, above the page-bottom typing indicator) so the
              "more content coming" signal is reachable without
              re-tracking the bottom of the page. */}
          {loading && webFallbackInFlight && (
            <div className="flex items-start gap-3 px-4 py-2 animate-[fadeSlideIn_0.2s_ease-out]">
              <div className="w-0.5 self-stretch bg-amber-400/40 rounded-full flex-shrink-0 mt-0.5" />
              <div className="flex-1 flex items-center gap-2 py-1">
                <svg
                  className="w-3.5 h-3.5 text-amber-400 animate-spin flex-shrink-0"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                  strokeLinecap="round" strokeLinejoin="round"
                >
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                <span className="font-mono text-xs text-amber-300/90 leading-snug">
                  Looking for additional authoritative sources on the web…
                </span>
              </div>
            </div>
          )}
          {loading && <TypingIndicator message={progressMsg} />}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
