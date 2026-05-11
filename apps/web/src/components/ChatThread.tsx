'use client'

import { useEffect, useRef, useState } from 'react'
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
}

// Sprint D6.87 — how close to the bottom of the scrollable container
// counts as "the user is reading the latest content." Below this
// threshold, auto-scroll engages; above it, we leave them where they
// are and surface a "Jump to latest" button instead.
const AT_BOTTOM_THRESHOLD_PX = 100

export function ChatThread({ messages, loading, progressMsg = null, onPrompt, onCitationTap, isNewConversation, vessel = null }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  // Sprint D6.88 Phase 1.5 — `followLatest` lives in a ref, not state,
  // so the intersection observer can update it without re-running the
  // auto-scroll useEffect. Previously this was state, and the previous
  // smooth-scroll behavior produced a jitter loop:
  //   observer fires "in view" → state changes → useEffect re-runs →
  //   scrollIntoView({behavior:'smooth'}) → animation moves bottomRef
  //   through viewport → observer fires "out of view" → state changes
  //   → re-runs again → restart smooth scroll → repeat.
  // Storing as a ref breaks the feedback path. The button visibility
  // is a separate piece of state that the observer can flip freely
  // without affecting the scroll logic.
  const followLatestRef = useRef(true)
  const [showJumpButton, setShowJumpButton] = useState(false)
  // Sprint D6.88 Phase 2 follow-up — timestamp of the last user-
  // initiated scroll input (wheel, touch, keyboard). The auto-scroll
  // effect skips when this is recent so the user's wheel doesn't
  // fight the auto-scroll during streaming. Was: jitter while
  // streaming, even after the ref refactor + 'auto' behavior. Root
  // cause: every delta (~50ms) fired scrollIntoView, which on some
  // browsers/contexts still produced a subtle animation that
  // conflicted with concurrent wheel input. Suppress for 800ms
  // post user-input gives wheels and touches breathing room.
  const lastUserScrollAtRef = useRef(0)
  const USER_SCROLL_GRACE_MS = 800

  useEffect(() => {
    const el = bottomRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        followLatestRef.current = entry.isIntersecting
        setShowJumpButton(!entry.isIntersecting)
      },
      // rootMargin lets the sentinel "see" itself slightly above the
      // viewport bottom, so small content additions during streaming
      // (typing indicator height shifts) don't toggle the state.
      { rootMargin: `0px 0px ${AT_BOTTOM_THRESHOLD_PX}px 0px`, threshold: 0 },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Sprint D6.88 Phase 2 follow-up — track user-initiated scroll
  // input so the auto-scroll effect can defer when the user is
  // actively wheeling or touching. Attach listeners to the nearest
  // scrollable parent (the chat-thread main element) so the events
  // fire during real scroll interaction.
  useEffect(() => {
    const sentinel = bottomRef.current
    if (!sentinel) return
    // Walk up to find the scrollable ancestor — Tailwind class
    // 'chat-thread' marks it in ChatInterface.
    let container: HTMLElement | null = sentinel.parentElement
    while (container && !container.classList.contains('chat-thread')) {
      container = container.parentElement
    }
    if (!container) return

    function markUserScroll() {
      lastUserScrollAtRef.current = Date.now()
    }
    container.addEventListener('wheel', markUserScroll, { passive: true })
    container.addEventListener('touchmove', markUserScroll, { passive: true })
    container.addEventListener('touchstart', markUserScroll, { passive: true })
    return () => {
      container?.removeEventListener('wheel', markUserScroll)
      container?.removeEventListener('touchmove', markUserScroll)
      container?.removeEventListener('touchstart', markUserScroll)
    }
  }, [])

  // Auto-scroll only when (a) the user is following the latest AND
  // (b) they haven't actively scrolled in the last 800ms. The grace
  // window prevents the wheel-vs-auto-scroll fight Blake reported
  // mid-stream. Uses 'instant' explicitly (not 'auto') so no browser
  // interprets the call as a smooth animation.
  useEffect(() => {
    if (messages.length === 0 && !loading) return
    if (!followLatestRef.current) return
    if (Date.now() - lastUserScrollAtRef.current < USER_SCROLL_GRACE_MS) return
    bottomRef.current?.scrollIntoView({ behavior: 'instant' as ScrollBehavior })
  }, [messages, loading, progressMsg])

  // Manual jump-to-bottom — the explicit user-initiated path. Keep
  // 'smooth' here because (a) it's a single one-shot action, not a
  // streaming barrage, and (b) the user pressed a button so they
  // expect a deliberate animation. Re-arm follow-latest manually
  // because the smooth-scroll animation may take a moment to land,
  // and we want the NEXT incoming token to follow immediately rather
  // than waiting for the observer to catch up.
  function jumpToLatest() {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    followLatestRef.current = true
    setShowJumpButton(false)
  }

  // The jump-to-latest button appears when the user is scrolled up.
  // Only render it when there's something worth jumping to (either
  // a stream is in flight, or there's at least one message). On an
  // empty chat with no in-flight generation, the button is noise.
  const showJumpPill = showJumpButton && (loading || messages.length > 0)

  return (
    <div className="flex flex-col min-h-full">
      {messages.length === 0 && !loading ? (
        <EmptyState onPrompt={onPrompt} isNewConversation={isNewConversation} vessel={vessel} />
      ) : (
        <div className="flex flex-col py-3 gap-0.5">
          {messages.map(msg => (
            <ChatMessage key={msg.id} message={msg} onCitationTap={onCitationTap} />
          ))}
          {loading && <TypingIndicator message={progressMsg} />}
        </div>
      )}
      <div ref={bottomRef} />

      {/* Sprint D6.87 — Jump-to-latest pill. Anchored to the bottom of
          the scrollable container but sticky to the viewport, so it
          rides above the input bar and is reachable mid-stream.
          Position uses `sticky` rather than `fixed` so it scrolls
          out of the way naturally if the user reaches the bottom on
          their own. */}
      {showJumpPill && (
        <button
          type="button"
          onClick={jumpToLatest}
          aria-label="Jump to latest message"
          className="sticky bottom-3 self-center z-30 mb-2
            inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
            bg-[#0d1225]/95 backdrop-blur-sm
            border border-[#2dd4bf]/40 text-[#2dd4bf]
            text-xs font-mono font-medium
            shadow-[0_4px_12px_rgba(0,0,0,0.4)]
            hover:bg-[#111a30] hover:border-[#2dd4bf]/70
            active:scale-95
            transition-all duration-150"
        >
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
          Jump to latest
        </button>
      )}
    </div>
  )
}
