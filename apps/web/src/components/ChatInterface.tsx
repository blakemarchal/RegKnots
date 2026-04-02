'use client'

import { useState, useCallback, useEffect } from 'react'
import type { Message } from '@/types/chat'
import { sendMessage } from '@/lib/mockApi'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { ChatThread } from './ChatThread'
import { InputBar } from './InputBar'
import { VesselPill } from './VesselPill'
import { HamburgerMenu } from './HamburgerMenu'
import { CitationSheet } from './CitationSheet'
import { VesselSheet } from './VesselSheet'

interface ConversationMessage {
  role: string
  content: string
  cited_regulations: { source: string; section_number: string; section_title: string }[]
  created_at: string
}

interface Props {
  initialConversationId: string | null
}

export function ChatInterface({ initialConversationId }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId)
  const [menuOpen, setMenuOpen] = useState(false)
  const [restoring, setRestoring] = useState(!!initialConversationId)

  const { vessels, activeVesselId } = useAuthStore()
  const activeVessel = vessels.find(v => v.id === activeVesselId) ?? null

  const [vesselSheetOpen, setVesselSheetOpen] = useState(false)

  function openVesselSheet() {
    setMenuOpen(false)
    // Brief delay so hamburger closes before sheet opens — avoids z-index conflict
    setTimeout(() => setVesselSheetOpen(true), 50)
  }

  const [citation, setCitation] = useState<{
    source: string
    sectionNumber: string
    sectionTitle: string
  } | null>(null)

  const handleCitationTap = useCallback(
    (source: string, sectionNumber: string, sectionTitle: string) => {
      setCitation({ source, sectionNumber, sectionTitle })
    },
    []
  )

  // Restore existing conversation on mount
  useEffect(() => {
    if (!initialConversationId) return

    apiRequest<ConversationMessage[]>(`/conversations/${initialConversationId}/messages`)
      .then(rows => {
        const restored: Message[] = rows.map(r => ({
          id: crypto.randomUUID(),
          role: r.role as 'user' | 'assistant',
          content: r.content,
          citations: r.cited_regulations,
        }))
        setMessages(restored)
      })
      .catch(() => {
        // If load fails, start fresh — don't block the UI
      })
      .finally(() => {
        setRestoring(false)
      })
  }, [initialConversationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = useCallback(async () => {
    const query = input.trim()
    if (!query || loading) return

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: query,
      citations: [],
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const response = await sendMessage(query, conversationId, activeVesselId)
      setConversationId(response.conversation_id)
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        citations: response.cited_regulations,
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'Something went wrong. Please try again.',
          citations: [],
        },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, conversationId, activeVesselId])

  function handlePrompt(text: string) {
    setInput(text)
    setTimeout(() => {
      setInput('')
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        citations: [],
      }
      setMessages([userMsg])
      setLoading(true)
      sendMessage(text, null, activeVesselId).then(response => {
        setConversationId(response.conversation_id)
        setMessages(prev => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: response.answer,
            citations: response.cited_regulations,
          },
        ])
      }).catch(() => {
        setMessages(prev => [
          ...prev,
          { id: crypto.randomUUID(), role: 'assistant', content: 'Something went wrong.', citations: [] },
        ])
      }).finally(() => setLoading(false))
    }, 50)
  }

  function handleNewChat() {
    setMessages([])
    setConversationId(null)
    setInput('')
    // Clear conversation_id from URL without re-render
    window.history.replaceState({}, '', '/')
  }

  return (
    <div className="flex flex-col h-dvh overflow-hidden bg-[#0a0e1a]">

      {/* ── Header ───────────────────────────────────────────────── */}
      <header className="flex-shrink-0 flex items-center justify-between
        px-4 py-3 bg-[#111827]/95 backdrop-blur-md
        border-b border-white/8 z-10">
        <div className="flex items-center gap-2.5">
          {/* Teal compass mark */}
          <svg className="w-6 h-6 text-teal flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
            <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
          </svg>
          <div>
            <h1 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide leading-none">
              RegKnots
            </h1>
            <p className="text-[9px] text-[#6b7594] tracking-[0.2em] uppercase leading-tight mt-0.5">
              CFR Co-Pilot
            </p>
          </div>
        </div>

        <button
          onClick={() => setMenuOpen(true)}
          className="w-9 h-9 flex flex-col items-center justify-center gap-1
            rounded-lg hover:bg-white/8 transition-colors duration-150"
          aria-label="Open menu"
          aria-expanded={menuOpen}
        >
          <span className="w-5 h-0.5 bg-[#f0ece4]/70 rounded-full" />
          <span className="w-5 h-0.5 bg-[#f0ece4]/70 rounded-full" />
          <span className="w-3.5 h-0.5 bg-[#f0ece4]/70 rounded-full self-start ml-[5px]" />
        </button>
      </header>

      {/* ── Chat thread ──────────────────────────────────────────── */}
      <main className="chat-thread flex-1 overflow-y-auto overscroll-contain
        bg-[image:repeating-linear-gradient(0deg,transparent,transparent_47px,rgba(45,212,191,0.018)_47px,rgba(45,212,191,0.018)_48px),repeating-linear-gradient(90deg,transparent,transparent_47px,rgba(45,212,191,0.018)_47px,rgba(45,212,191,0.018)_48px)]">
        {restoring ? (
          <div className="flex flex-col gap-3 px-4 py-6">
            {[1, 2, 3].map(i => (
              <div key={i} className="flex flex-col gap-2">
                <div className={`h-3 bg-white/8 rounded animate-pulse ${i % 2 === 0 ? 'w-1/2 ml-auto' : 'w-3/4'}`} />
                <div className={`h-3 bg-white/5 rounded animate-pulse ${i % 2 === 0 ? 'w-1/3 ml-auto' : 'w-full'}`} />
              </div>
            ))}
          </div>
        ) : (
          <ChatThread
            messages={messages}
            loading={loading}
            onPrompt={handlePrompt}
            onCitationTap={handleCitationTap}
          />
        )}
      </main>

      {/* ── Bottom bar ───────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-[#111827] border-t border-white/8">
        <VesselPill vesselName={activeVessel?.name ?? null} onClick={openVesselSheet} />
        <InputBar
          value={input}
          onChange={setInput}
          onSend={handleSend}
          loading={loading || restoring}
        />
      </div>

      {/* ── Hamburger drawer ─────────────────────────────────────── */}
      <HamburgerMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onNewChat={handleNewChat}
        onOpenVessels={openVesselSheet}
      />

      {/* ── Vessel selector sheet ────────────────────────────────── */}
      {vesselSheetOpen && (
        <VesselSheet onClose={() => setVesselSheetOpen(false)} />
      )}

      {/* ── Citation bottom sheet ─────────────────────────────────── */}
      {citation && (
        <CitationSheet
          source={citation.source}
          sectionNumber={citation.sectionNumber}
          sectionTitle={citation.sectionTitle}
          onClose={() => setCitation(null)}
        />
      )}
    </div>
  )
}
