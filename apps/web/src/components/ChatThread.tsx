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
  // Tracks the user's intent: are they following the latest content
  // (true) or have they scrolled up to read something earlier (false)?
  // Defaults to true so a fresh chat or first message scrolls naturally.
  const [followLatest, setFollowLatest] = useState(true)

  // Sprint D6.87 — Detect at-bottom state via IntersectionObserver on
  // the bottomRef sentinel. When the sentinel is in viewport, the user
  // is reading the latest content; when it leaves viewport (because
  // they scrolled up), we stop pinning. This is more reliable than
  // scroll-event math against an unknown scrollable parent.
  useEffect(() => {
    const el = bottomRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => setFollowLatest(entry.isIntersecting),
      // rootMargin lets the sentinel "see" itself slightly above the
      // viewport bottom, so small content additions during streaming
      // (typing indicator height shifts) don't toggle the state.
      { rootMargin: `0px 0px ${AT_BOTTOM_THRESHOLD_PX}px 0px`, threshold: 0 },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Auto-scroll only when the user is following the latest. If they've
  // scrolled up to read mid-stream (Blake's pain point — first-paragraph
  // skim during a long response), we leave the viewport alone.
  useEffect(() => {
    if (messages.length === 0 && !loading) return
    if (!followLatest) return  // user scrolled up; don't yank the page
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, progressMsg, followLatest])

  // Manual jump-to-bottom — when the user clicks the "Jump to latest"
  // button, scroll AND re-engage follow-latest mode.
  function jumpToLatest() {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    setFollowLatest(true)
  }

  // The jump-to-latest button appears when the user is scrolled up.
  // Only render it when there's something worth jumping to (either
  // a stream is in flight, or there's at least one message). On an
  // empty chat with no in-flight generation, the button is noise.
  const showJumpButton = !followLatest && (loading || messages.length > 0)

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
      {showJumpButton && (
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
