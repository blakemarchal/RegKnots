'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import type { Message } from '@/types/chat'
import { sendMessageStream } from '@/lib/mockApi'
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
import { NotificationBanner } from './NotificationBanner'
import { VerificationBanner } from './VerificationBanner'
import { ComingUpWidget } from './ComingUpWidget'

interface ConversationMessage {
  role: string
  content: string
  cited_regulations: { source: string; section_number: string; section_title: string }[]
  created_at: string
}

interface Props {
  initialConversationId: string | null
  initialQuery?: string | null
}

export function ChatInterface({ initialConversationId, initialQuery }: Props) {
  return (
    <PwaProvider>
      <ChatInterfaceInner initialConversationId={initialConversationId} initialQuery={initialQuery} />
    </PwaProvider>
  )
}

function ChatInterfaceInner({ initialConversationId, initialQuery }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [progressMsg, setProgressMsg] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId)
  const [menuOpen, setMenuOpen] = useState(false)
  const [surveyOpen, setSurveyOpen] = useState(false)
  const [restoring, setRestoring] = useState(!!initialConversationId)
  const [rateLimitMsg, setRateLimitMsg] = useState<string | null>(null)
  const [pilotEndedMsg, setPilotEndedMsg] = useState<string | null>(null)
  const [verifyRequiredMsg, setVerifyRequiredMsg] = useState<string | null>(null)
  const [resendStatus, setResendStatus] = useState<string | null>(null)
  const [vesselNudgeDismissed, setVesselNudgeDismissed] = useState(false)

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

    let cancelled = false
    apiRequest<ConversationMessage[]>(`/conversations/${initialConversationId}/messages`)
      .then(rows => {
        if (cancelled) return
        const restored: Message[] = rows.map(r => ({
          id: crypto.randomUUID(),
          role: r.role as 'user' | 'assistant',
          content: r.content,
          citations: r.cited_regulations,
        }))
        setMessages(restored)
      })
      .catch(() => {
        // Network failure — start fresh
      })
      .finally(() => {
        if (!cancelled) setRestoring(false)
      })

    return () => { cancelled = true }
  }, [initialConversationId])

  // Auto-send a pre-filled query from URL (e.g., ?q=... from PSC checklist "Ask" button)
  useEffect(() => {
    if (!initialQuery || initialConversationId) return
    // Clean the URL param so it doesn't re-fire on navigation
    window.history.replaceState({}, '', '/')
    // Use handlePrompt which creates a fresh conversation with the query
    handlePrompt(initialQuery)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
    setProgressMsg(null)

    try {
      const currentVesselId = useAuthStore.getState().activeVesselId
      await sendMessageStream(
        query,
        conversationId,
        currentVesselId,
        (status) => setProgressMsg(status),
        (data) => {
          setConversationId(data.conversation_id)
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: data.answer,
            citations: data.cited_regulations,
          }
          setMessages(prev => [...prev, assistantMsg])
          // Refresh billing status in background after each message
          apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
        },
      )
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
      if (err instanceof Error && err.message.includes('403') && err.message.toLowerCase().includes('trial has ended')) {
        setPilotEndedMsg(
          'Your RegKnot free trial has ended. Subscribe to keep access to cited regulation answers.'
        )
        setMessages(prev => prev.slice(0, -1))
        return
      }
      if (err instanceof Error && err.message.includes('403') && err.message.toLowerCase().includes('verify')) {
        setVerifyRequiredMsg(
          'Please verify your email to continue using RegKnot. Check your inbox for a verification link.'
        )
        setMessages(prev => prev.slice(0, -1))
        return
      }
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'Connection lost. Please try again.',
          citations: [],
        },
      ])
    } finally {
      setProgressMsg(null)
      setLoading(false)
    }
  }, [input, loading, conversationId, router, setBilling])

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
      setProgressMsg(null)
      sendMessageStream(
        text,
        null,
        useAuthStore.getState().activeVesselId,
        (status) => setProgressMsg(status),
        (data) => {
          setConversationId(data.conversation_id)
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: data.answer,
            citations: data.cited_regulations,
          }
          setMessages(prev => [...prev, assistantMsg])
          // Refresh billing status in background
          apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
        },
      )
        .catch(() => {
          setMessages(prev => [
            ...prev,
            { id: crypto.randomUUID(), role: 'assistant', content: 'Connection lost. Please try again.', citations: [] },
          ])
        })
        .finally(() => {
          setProgressMsg(null)
          setLoading(false)
        })
    }, 50)
  }

  async function handleResendVerification() {
    setResendStatus(null)
    try {
      await apiRequest('/auth/resend-verification', { method: 'POST' })
      setResendStatus('Verification email sent — check your inbox.')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to send'
      if (msg.includes('429')) {
        setResendStatus('Please wait a moment before requesting another email.')
      } else {
        setResendStatus('Failed to send verification email. Try again shortly.')
      }
    }
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
              RegKnot
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

      {/* ── Email verification banner ─────────────────────────────── */}
      <VerificationBanner />

      {/* ── Regulation-update / system notification banners ────────── */}
      <NotificationBanner />

      {/* ── Trial banner ─────────────────────────────────────────── */}
      {billing && billing.tier === 'free' && billing.trial_active && !billing.unlimited && (
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
          <>
            {/* Coming Up widget: fresh chat only, dismissible per session */}
            <ComingUpWidget visible={messages.length === 0 && !loading} />
            <ChatThread
              messages={messages}
              loading={loading}
              progressMsg={progressMsg}
              onPrompt={handlePrompt}
              onCitationTap={handleCitationTap}
              isNewConversation={initialConversationId === null}
            />
          </>
        )}
      </main>

      {/* ── Bottom bar ───────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-[#111827] border-t border-white/8">
        <InstallPrompt />

        {/* Vessel-less onboarding nudge — shown only when the user has no
            vessels and hasn't sent a message in this conversation yet. */}
        {vessels.length === 0 && messages.length === 0 && !vesselNudgeDismissed && (
          <div className="flex items-start justify-between gap-3 px-4 py-2
            bg-[#2dd4bf]/6 border-t border-[#2dd4bf]/15">
            <p className="font-mono text-[11px] text-[#6b7594] leading-snug">
              Tip: Add a vessel profile for answers tailored to your specific ship.{' '}
              <button
                onClick={() => router.push('/onboarding')}
                className="text-[#2dd4bf] hover:underline font-bold"
              >
                Add vessel →
              </button>
            </p>
            <button
              onClick={() => setVesselNudgeDismissed(true)}
              aria-label="Dismiss tip"
              className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded
                text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        )}

        <div className="flex items-center justify-between">
        <VesselPill
          vesselName={activeVessel?.name ?? null}
          hasVessels={vessels.length > 0}
          onClick={openVesselSheet}
        />

          {/* Quick Log — compact, right-aligned next to vessel pill */}
          <button
            onClick={() => router.push('/log?quick=true')}
            className="flex items-center gap-1 px-2.5 py-1 mr-3 rounded-full text-xs
              border border-white/10 bg-white/5 hover:bg-[#2dd4bf]/10 hover:border-[#2dd4bf]/30
              transition-colors duration-150"
            aria-label="Quick Log"
          >
            <svg className="w-3 h-3 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="1" width="6" height="14" rx="3" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            </svg>
            <span className="font-mono text-[10px] font-bold text-[#2dd4bf]">Log</span>
          </button>
        </div>
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
        {verifyRequiredMsg && (
          <div className="px-4 py-3 bg-teal-950/30 border-t border-[#2dd4bf]/20 flex items-start justify-between gap-3">
            <div className="flex flex-col min-w-0">
              <p className="font-mono text-xs text-[#2dd4bf] leading-snug">
                {verifyRequiredMsg}
              </p>
              {resendStatus && (
                <p className="font-mono text-[10px] text-[#f0ece4]/80 mt-1">
                  {resendStatus}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={handleResendVerification}
                className="font-mono text-xs font-bold text-[#2dd4bf] hover:underline whitespace-nowrap"
              >
                Resend email
              </button>
              <button
                onClick={() => { setVerifyRequiredMsg(null); setResendStatus(null) }}
                className="w-6 h-6 flex items-center justify-center rounded
                  text-[#6b7594] hover:text-[#f0ece4] hover:bg-white/5 transition-colors"
                aria-label="Dismiss"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>
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
