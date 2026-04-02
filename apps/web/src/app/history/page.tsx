'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { apiRequest } from '@/lib/api'
import { CompassRose } from '@/components/CompassRose'

interface ConversationSummary {
  id: string
  title: string
  updated_at: string
  vessel_name: string | null
}

// ── Relative time ──────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  const diff = Math.floor((now - then) / 1000)

  if (diff < 60) return 'Just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 172800) return 'Yesterday'

  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Skeleton card ──────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-[#111827] border-l-2 border-[#2dd4bf]/20 rounded-r-xl px-4 py-3.5 flex flex-col gap-2">
      <div className="h-3.5 bg-white/8 rounded animate-pulse w-3/4" />
      <div className="h-2.5 bg-white/5 rounded animate-pulse w-1/3" />
    </div>
  )
}

// ── History content ────────────────────────────────────────────────────────────

function HistoryContent() {
  const router = useRouter()
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    apiRequest<ConversationSummary[]>('/conversations')
      .then(data => { setConversations(data); setLoading(false) })
      .catch(() => { setError(true); setLoading(false) })
  }, [])

  function openConversation(id: string) {
    router.push(`/?conversation_id=${id}`)
  }

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      {/* Header */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
        bg-[#111827]/95 backdrop-blur-md border-b border-white/8">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 flex items-center justify-center rounded-lg
            text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150"
          aria-label="Back to chat"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
          Chat History
        </h1>
      </header>

      {/* Content */}
      <main className="chat-thread flex-1 overflow-y-auto">
        <div className="px-4 py-4 flex flex-col gap-2">

          {/* Loading */}
          {loading && (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          )}

          {/* Error */}
          {error && !loading && (
            <p className="font-mono text-sm text-[#6b7594] text-center mt-12">
              Failed to load conversations.
            </p>
          )}

          {/* Empty state */}
          {!loading && !error && conversations.length === 0 && (
            <div className="flex flex-col items-center gap-4 mt-16">
              <CompassRose className="w-16 h-16 text-[#f0ece4]/20" />
              <p className="font-mono text-sm text-[#6b7594]">No conversations yet</p>
              <button
                onClick={() => router.back()}
                className="font-mono text-xs text-[#2dd4bf] hover:underline"
              >
                Ask your first question
              </button>
            </div>
          )}

          {/* Conversation cards */}
          {!loading && conversations.map(c => (
            <button
              key={c.id}
              onClick={() => openConversation(c.id)}
              className="w-full text-left bg-[#111827] border-l-2 border-[#2dd4bf]/30
                hover:border-[#2dd4bf]/70 hover:bg-[#111827]/80
                rounded-r-xl px-4 py-3.5 transition-colors duration-150
                animate-[fadeSlideIn_0.2s_ease-out]"
            >
              <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                {c.title}
              </p>
              <p className="font-mono text-xs text-[#6b7594] mt-1">
                {c.vessel_name
                  ? <span><span className="text-[#2dd4bf]/70">{c.vessel_name}</span> · {formatRelative(c.updated_at)}</span>
                  : <span>No vessel · {formatRelative(c.updated_at)}</span>
                }
              </p>
            </button>
          ))}

        </div>
      </main>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  return (
    <AuthGuard>
      <HistoryContent />
    </AuthGuard>
  )
}
