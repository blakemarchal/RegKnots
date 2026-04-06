'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import type { Message } from '@/types/chat'
import { sendMessage } from '@/lib/mockApi'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'
import { ChatThread } from './ChatThread'
import { InputBar } from './InputBar'
import { VesselPill } from './VesselPill'
import { HamburgerMenu } from './HamburgerMenu'
import { CitationSheet } from './CitationSheet'
import { VesselSheet } from './VesselSheet'
import { InstallPrompt } from './InstallPrompt'
import { PwaProvider, usePwa } from '@/lib/pwa'
import { PilotEndedModal } from './PilotEndedModal'
import { PilotSurveyModal } from './PilotSurveyModal'

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
  return (
    <PwaProvider>
      <ChatInterfaceInner initialConversationId={initialConversationId} />
    </PwaProvider>
  )
}

function ChatInterfaceInner({ initialConversationId }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId)
  const [menuOpen, setMenuOpen] = useState(false)
  const [surveyOpen, setSurveyOpen] = useState(false)
  const [restoring, setRestoring] = useState(!!initialConversationId)
  const [rateLimitMsg, setRateLimitMsg] = useState<string | null>(null)
  const [pilotEndedMsg, setPilotEndedMsg] = useState<string | null>(null)

  const router = useRouter()
  const { canInstall, install } = usePwa()
  const { vessels, activeVesselId, billing, setBilling } = useAuthStore()

  // Fetch billing status on mount
  useEffect(() => {
    apiRequest<BillingStatus>('/billing/status')
      .then(setBilling)
      .catch(() => {})
  }, [setBilling])
  const activeVessel = vessels.find(v => v.id === activeVesselId) ?? null

  const [vesselSheetOpen, setVesselSheetOpen] = useState(false)
  const searchParams = useSearchParams()

  function openVesselSheet() {
    setMenuOpen(false)
    // Brief delay so hamburger closes before sheet opens — avoids z-index conflict
    setTimeout(() => setVesselSheetOpen(true), 50)
  }

  // Auto-open vessel sheet when navigated with ?vessels=open (e.g. from hamburger menu)
  useEffect(() => {
    if (searchParams.get('vessels') === 'open') {
      setVesselSheetOpen(true)
      // Clean up the URL without triggering navigation
      window.history.replaceState({}, '', '/')
    }
  }, [searchParams])

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
      const currentVesselId = useAuthStore.getState().activeVesselId
      const response = await sendMessage(query, conversationId, currentVesselId)
      setConversationId(response.conversation_id)
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        citations: response.cited_regulations,
      }
      setMessages(prev => [...prev, assistantMsg])
      // Refresh billing status in background after each message
      apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
    } catch (err) {
      if (err instanceof Error && err.message.includes('402')) {
        router.push('/pricing')
        return
      }
      if (err instanceof Error && err.message.includes('429')) {
        setRateLimitMsg('Too many messages — please wait a moment before sending another.')
        setTimeout(() => setRateLimitMsg(null), 5000)
        // Remove the user message we optimistically added
        setMessages(prev => prev.slice(0, -1))
        return
      }
      if (err instanceof Error && err.message.includes('403') && err.message.includes('pilot')) {
        setPilotEndedMsg(
          'The RegKnots pilot program has ended. Thank you for your feedback! Stay tuned for our official launch at regknots.com.'
        )
        setMessages(prev => prev.slice(0, -1))
        return
      }
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
  }, [input, loading, conversationId])

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
      sendMessage(text, null, useAuthStore.getState().activeVesselId).then(response => {
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
        // Refresh billing status in background
        apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
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
              Maritime Compliance Co-Pilot
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {canInstall && (
            <button
              onClick={install}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg
                border border-[#2dd4bf]/40 text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                transition-colors duration-150"
              aria-label="Install app"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span className="hidden md:inline font-mono text-xs font-bold">Install</span>
            </button>
          )}
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
        </div>
      </header>

      {/* ── Trial banner ─────────────────────────────────────────── */}
      {billing && billing.tier === 'free' && billing.trial_active && (
        <div className="flex-shrink-0 flex items-center justify-between gap-3 px-4 py-2
          bg-amber-950/40 border-b border-amber-800/30">
          <p className="font-mono text-xs text-amber-400">
            Free trial: {billing.messages_remaining ?? 0} messages remaining
          </p>
          <button
            onClick={() => router.push('/pricing')}
            className="font-mono text-xs font-bold text-[#2dd4bf] hover:underline"
          >
            Upgrade
          </button>
        </div>
      )}

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
            isNewConversation={initialConversationId === null}
          />
        )}
      </main>

      {/* ── Bottom bar ───────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-[#111827] border-t border-white/8">
        <InstallPrompt />
        <VesselPill vesselName={activeVessel?.name ?? null} onClick={openVesselSheet} />
        <InputBar
          value={input}
          onChange={setInput}
          onSend={handleSend}
          loading={loading || restoring}
        />
        {rateLimitMsg && (
          <p className="px-4 py-2 font-mono text-xs text-amber-400 bg-amber-950/30 border-t border-amber-800/20">
            {rateLimitMsg}
          </p>
        )}
      </div>

      {/* ── Hamburger drawer ─────────────────────────────────────── */}
      <HamburgerMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onNewChat={handleNewChat}
        onOpenVessels={openVesselSheet}
        onOpenSurvey={() => setSurveyOpen(true)}
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

      {/* ── Pilot ended modal ────────────────────────────────────── */}
      {pilotEndedMsg && (
        <PilotEndedModal
          message={pilotEndedMsg}
          onClose={() => setPilotEndedMsg(null)}
        />
      )}

      {/* ── Pilot survey modal (auto-triggered by billing or menu) ── */}
      <PilotSurveyModal billing={billing} />
      {surveyOpen && (
        <PilotSurveyModal forceOpen onClose={() => setSurveyOpen(false)} />
      )}
    </div>
  )
}
