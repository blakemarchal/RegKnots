'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
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
import type { VesselProfileForPrompts } from '@/lib/vesselPrompts'

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

  // ── Sprint D6.23d — connection-lost recovery ──────────────────────────────
  // When the SSE stream drops mid-generation (phone-locked, network blip,
  // tab-backgrounded on iOS), the answer is still being generated and
  // persisted server-side. The recovery logic polls /conversations/:id/messages
  // for up to 90s looking for the assistant message that lands when generation
  // completes. The pending-question state is mirrored to localStorage so the
  // recovery survives a full page reload (user kills app → reopens later).
  const [recovering, setRecovering] = useState(false)
  const [recoveryFailed, setRecoveryFailed] = useState(false)
  const recoveryAbortRef = useRef<AbortController | null>(null)

  // Sprint D6.34 / D6.52 — verbosity chip state.
  //
  // savedVerbosity = user's account-settings preference (the "default
  // I want to live in"). Fetched on mount from /onboarding/persona;
  // falls back to 'standard' if the user never set a preference.
  //
  // verbosity = the currently-highlighted chip. Init = savedVerbosity
  // so the chip ALWAYS has one selected (UX bug fix — previously no
  // chip was highlighted on a fresh load, which looked broken).
  //
  // Per-message override: click a different chip → that chip is
  // highlighted for the next turn. After successful send, snap back
  // to savedVerbosity so the next blank turn doesn't accidentally
  // inherit the override. Tightly coupled to account settings: the
  // chip never silently mutates the saved preference.
  const [savedVerbosity, setSavedVerbosity] = useState<'brief' | 'standard' | 'detailed'>('standard')
  const [verbosity, setVerbosity] = useState<'brief' | 'standard' | 'detailed'>('standard')

  useEffect(() => {
    let cancelled = false
    apiRequest<{ verbosity_preference: string | null }>('/onboarding/persona')
      .then((r) => {
        if (cancelled) return
        const pref = r.verbosity_preference
        if (pref === 'brief' || pref === 'standard' || pref === 'detailed') {
          setSavedVerbosity(pref)
          setVerbosity(pref)
        }
      })
      .catch(() => { /* keep 'standard' fallback */ })
    return () => { cancelled = true }
  }, [])

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

  // Fetch the active vessel's full profile for tailored empty-chat prompts.
  // Re-runs when the user switches vessels. Only fetches when there's an id to match.
  const [activeVesselProfile, setActiveVesselProfile] = useState<VesselProfileForPrompts | null>(null)
  useEffect(() => {
    if (!activeVesselId) { setActiveVesselProfile(null); return }
    let cancelled = false
    apiRequest<VesselProfileForPrompts[]>('/vessels')
      .then((list) => {
        if (cancelled) return
        const v = list.find((x) => x.id === activeVesselId)
        setActiveVesselProfile(v ?? null)
      })
      .catch(() => { if (!cancelled) setActiveVesselProfile(null) })
    return () => { cancelled = true }
  }, [activeVesselId])

  const [vesselSheetOpen, setVesselSheetOpen] = useState(false)
  const searchParams = useSearchParams()

  // Sprint D6.49 — workspace context. URL-based opt-in: when the page
  // is loaded with ?workspace=<uuid>, all chats in this session bind to
  // that workspace. Without the param, behavior is bit-identical to
  // pre-D6.49 personal-tier chat. We capture the value once on mount;
  // the workspace detail page passes the URL via Link / router.push.
  const workspaceIdParam = searchParams.get('workspace')
  const [activeWorkspaceId] = useState<string | null>(workspaceIdParam || null)
  const [workspaceName, setWorkspaceName] = useState<string | null>(null)

  // Resolve workspace name once for header display. Fire-and-forget;
  // failure leaves workspaceName=null and shows just the UUID.
  useEffect(() => {
    if (!activeWorkspaceId) return
    let cancelled = false
    apiRequest<{ name: string }>(`/workspaces/${activeWorkspaceId}`)
      .then((ws) => { if (!cancelled) setWorkspaceName(ws.name) })
      .catch(() => { if (!cancelled) setWorkspaceName(null) })
    return () => { cancelled = true }
  }, [activeWorkspaceId])

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

  // ── Recovery helpers ──────────────────────────────────────────────────────
  //
  // localStorage shape: regknots:pending_chat:<conversation_id> →
  //   { query: string, sentAt: number(ms epoch) }
  // Cleared on success (done event) or when the recovery loop succeeds.

  const pendingKey = useCallback(
    (convId: string) => `regknots:pending_chat:${convId}`,
    [],
  )

  const writePending = useCallback(
    (convId: string, query: string) => {
      try {
        localStorage.setItem(
          pendingKey(convId),
          JSON.stringify({ query, sentAt: Date.now() }),
        )
      } catch {
        // localStorage may be unavailable in private mode — recovery still
        // works for the in-memory case (visibility-change handler).
      }
    },
    [pendingKey],
  )

  const clearPending = useCallback(
    (convId: string) => {
      try {
        localStorage.removeItem(pendingKey(convId))
      } catch {
        // ignore
      }
    },
    [pendingKey],
  )

  /**
   * Poll the server for an assistant message that arrived after `sentAt`.
   * Returns true on success (state has been updated), false on timeout.
   */
  const recoveryLoop = useCallback(
    async (convId: string, sentAt: number): Promise<boolean> => {
      setRecovering(true)
      setRecoveryFailed(false)
      const abort = new AbortController()
      recoveryAbortRef.current = abort
      const startedAt = Date.now()
      const deadline = 90_000  // 90s window

      try {
        while (Date.now() - startedAt < deadline) {
          if (abort.signal.aborted) return false
          try {
            const rows = await apiRequest<ConversationMessage[]>(
              `/conversations/${convId}/messages`,
            )
            const last = rows[rows.length - 1]
            if (
              last
              && last.role === 'assistant'
              && new Date(last.created_at).getTime() >= sentAt
            ) {
              // Hydrate the full conversation from the server (preserves
              // exact message ordering, citations, and content the server
              // saved — supersedes whatever optimistic state we had).
              const restored: Message[] = rows.map((r) => ({
                id: crypto.randomUUID(),
                role: r.role as 'user' | 'assistant',
                content: r.content,
                citations: r.cited_regulations,
              }))
              setMessages(restored)
              setConversationId(convId)
              clearPending(convId)
              setRecovering(false)
              setRecoveryFailed(false)
              return true
            }
          } catch {
            // Network blip during a poll; keep trying until the deadline.
          }
          // 5-second poll interval, abortable
          await new Promise<void>((resolve) => {
            const t = setTimeout(resolve, 5_000)
            abort.signal.addEventListener('abort', () => {
              clearTimeout(t)
              resolve()
            })
          })
        }
      } finally {
        recoveryAbortRef.current = null
      }

      // Timed out
      setRecovering(false)
      setRecoveryFailed(true)
      return false
    },
    [clearPending],
  )

  // On mount: if there's a pending question for this conversation in
  // localStorage, immediately enter recovery mode.
  useEffect(() => {
    if (!initialConversationId) return
    let raw: string | null = null
    try {
      raw = localStorage.getItem(pendingKey(initialConversationId))
    } catch {
      return
    }
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as { query: string; sentAt: number }
      // Only attempt recovery if it was sent in the last ~5 minutes; older
      // entries are stale and we just clear them.
      if (Date.now() - parsed.sentAt > 5 * 60 * 1000) {
        clearPending(initialConversationId)
        return
      }
      void recoveryLoop(initialConversationId, parsed.sentAt)
    } catch {
      try { localStorage.removeItem(pendingKey(initialConversationId)) } catch { /* ignore */ }
    }
  }, [initialConversationId, pendingKey, recoveryLoop, clearPending])

  // When the page is foregrounded after being hidden, kick the recovery
  // poll if we have a pending question. This catches the iOS Safari case
  // where the JS engine was throttled while the phone was locked.
  useEffect(() => {
    function onVisibility() {
      if (document.hidden) return
      if (!conversationId) return
      let raw: string | null = null
      try { raw = localStorage.getItem(pendingKey(conversationId)) } catch { return }
      if (!raw) return
      if (recovering) return  // already polling
      try {
        const parsed = JSON.parse(raw) as { sentAt: number }
        if (Date.now() - parsed.sentAt > 5 * 60 * 1000) {
          clearPending(conversationId)
          return
        }
        void recoveryLoop(conversationId, parsed.sentAt)
      } catch {
        // ignore
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [conversationId, recovering, pendingKey, recoveryLoop, clearPending])

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

    // Sprint D6.23d — capture sentAt up front so the recovery loop can
    // identify whether a server-side assistant message arrived after this
    // exact send (vs. a leftover from a prior turn).
    const sentAt = Date.now()
    let resolvedConvId: string | null = conversationId

    try {
      const currentVesselId = useAuthStore.getState().activeVesselId
      const turnVerbosity = verbosity  // capture before reset
      // D6.52 — snap back to the user's saved account preference so
      // the next blank turn picks up their default. Override is only
      // ever per-turn; tightly coupled to account settings.
      setVerbosity(savedVerbosity)
      await sendMessageStream(
        query,
        conversationId,
        currentVesselId,
        (status) => setProgressMsg(status),
        (data) => {
          resolvedConvId = data.conversation_id
          setConversationId(data.conversation_id)
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: data.answer,
            citations: data.cited_regulations,
            web_fallback: data.web_fallback ?? null,
          }
          setMessages(prev => [...prev, assistantMsg])
          // Generation succeeded — drop the pending marker.
          clearPending(data.conversation_id)
          // Refresh billing status in background after each message
          apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
        },
        (startedConvId) => {
          // First server event: persist pending marker keyed by conv id so
          // a later phone-lock / network blip can recover the answer.
          resolvedConvId = startedConvId
          setConversationId(startedConvId)
          writePending(startedConvId, query)
        },
        turnVerbosity,
        activeWorkspaceId,
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
      // Sprint D6.23d — instead of "Connection lost", enter recovery mode
      // if we know the conversation_id and the server is likely still
      // generating. The pending-question marker survives a page reload.
      if (resolvedConvId) {
        // Don't add a placeholder bubble — the recovery banner above the
        // input bar surfaces the in-flight state instead.
        setProgressMsg(null)
        setLoading(false)
        void recoveryLoop(resolvedConvId, sentAt)
        return
      }
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'Connection lost before your question reached the server. Please try again.',
          citations: [],
        },
      ])
    } finally {
      setProgressMsg(null)
      setLoading(false)
    }
  }, [input, loading, conversationId, router, setBilling, writePending, clearPending, recoveryLoop, verbosity, savedVerbosity])

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
      const sentAt = Date.now()
      let resolvedConvId: string | null = null
      sendMessageStream(
        text,
        null,
        useAuthStore.getState().activeVesselId,
        (status) => setProgressMsg(status),
        (data) => {
          resolvedConvId = data.conversation_id
          setConversationId(data.conversation_id)
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: data.answer,
            citations: data.cited_regulations,
            web_fallback: data.web_fallback ?? null,
          }
          setMessages(prev => [...prev, assistantMsg])
          clearPending(data.conversation_id)
          // Refresh billing status in background
          apiRequest<BillingStatus>('/billing/status').then(setBilling).catch(() => {})
        },
        (startedConvId) => {
          // Server confirmed receipt — persist the pending marker so a
          // phone-lock or network blip can recover the answer.
          resolvedConvId = startedConvId
          setConversationId(startedConvId)
          writePending(startedConvId, text)
        },
        undefined,
        activeWorkspaceId,
      )
        .catch(() => {
          if (resolvedConvId) {
            setProgressMsg(null)
            setLoading(false)
            void recoveryLoop(resolvedConvId, sentAt)
            return
          }
          setMessages(prev => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: 'Connection lost before your question reached the server. Please try again.',
              citations: [],
            },
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

      {/* ── Mate tier monthly-cap banner (Sprint D6.2) ─────────────── */}
      {billing && billing.tier === 'mate' && !billing.unlimited &&
        billing.monthly_message_cap !== null && (() => {
          const used = billing.monthly_messages_used
          const cap = billing.monthly_message_cap
          const remaining = billing.monthly_messages_remaining ?? 0
          // At cap: full-width red banner + upgrade CTA. At 90: red banner.
          // At 75: soft amber. Below 75: quiet single-line counter.
          const atCap = remaining === 0
          const nearCap = used >= 90 && !atCap
          const approachingCap = used >= 75 && used < 90
          const bgClass = atCap
            ? 'bg-rose-950/60 border-rose-800/50'
            : nearCap
            ? 'bg-rose-950/40 border-rose-800/30'
            : approachingCap
            ? 'bg-amber-950/40 border-amber-800/30'
            : 'bg-slate-900/60 border-slate-800/40'
          const textClass = atCap || nearCap
            ? 'text-rose-400'
            : approachingCap
            ? 'text-amber-400'
            : 'text-slate-400'
          const label = atCap
            ? `You've used all ${cap} messages on the Mate plan this month.`
            : `Mate plan: ${used}/${cap} messages used this month`
          return (
            <div className={`flex-shrink-0 flex items-center justify-between gap-3 px-4 py-2 border-b ${bgClass}`}>
              <p className={`font-mono text-xs ${textClass}`}>
                {label}
                {!atCap && approachingCap && ' — upgrade to Captain for unlimited.'}
              </p>
              {(atCap || nearCap || approachingCap) && (
                <button
                  onClick={() => router.push('/pricing')}
                  className="font-mono text-xs font-bold text-[#2dd4bf] hover:underline whitespace-nowrap"
                >
                  {atCap ? 'Upgrade to Captain' : 'Upgrade'}
                </button>
              )}
            </div>
          )
        })()}

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
            {/* Sprint D6.49 — workspace context banner. Renders ONLY when
                ?workspace=<id> URL param activated this session.
                Personal-tier users (no URL param) never see this. */}
            {activeWorkspaceId && (
              <div className="flex-shrink-0 bg-[#2dd4bf]/8 border-b border-[#2dd4bf]/25 px-4 py-2 flex items-center justify-between gap-3">
                <div className="text-xs font-mono text-[#2dd4bf]/80 truncate">
                  <span className="uppercase tracking-wider mr-1.5">Workspace:</span>
                  <span className="text-[#f0ece4]">
                    {workspaceName ?? 'Loading…'}
                  </span>
                  <span className="ml-2 text-[#6b7594]">
                    Chats are shared with all workspace members.
                  </span>
                </div>
                <a
                  href="/"
                  className="text-xs font-mono text-[#2dd4bf]/80 hover:text-[#2dd4bf]
                             underline whitespace-nowrap"
                >
                  Switch to personal →
                </a>
              </div>
            )}

            {/* Coming Up widget — full version on fresh chat, compact pill
                on active chats (so power users with one mega-thread still
                see DAU signals). Dismissible per session in either mode. */}
            <ComingUpWidget visible={true} compact={messages.length > 0} />
            <ChatThread
              messages={messages}
              loading={loading}
              progressMsg={progressMsg}
              onPrompt={handlePrompt}
              onCitationTap={handleCitationTap}
              isNewConversation={initialConversationId === null}
              vessel={activeVesselProfile}
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
          verbosity={verbosity}
          onVerbosityChange={setVerbosity}
        />
        {rateLimitMsg && (
          <p className="px-4 py-2 font-mono text-xs text-amber-400 bg-amber-950/30 border-t border-amber-800/20">
            {rateLimitMsg}
          </p>
        )}
        {/* Sprint D6.23d — Recovery banner shown when the SSE connection
            dropped mid-generation. The server is still working; we poll
            until the answer lands or we hit the 90s timeout. */}
        {recovering && (
          <p className="px-4 py-2 font-mono text-xs text-[#2dd4bf] bg-[#2dd4bf]/8 border-t border-[#2dd4bf]/20 flex items-center gap-2">
            <svg className="w-3 h-3 animate-spin flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
            </svg>
            Hang tight — your answer will appear when you&apos;re back online.
          </p>
        )}
        {recoveryFailed && (
          <p className="px-4 py-2 font-mono text-xs text-amber-400 bg-amber-950/30 border-t border-amber-800/20 flex items-center justify-between gap-2">
            <span>Couldn&apos;t recover the answer automatically. Pull-to-refresh to check, or send again.</span>
            <button
              onClick={() => setRecoveryFailed(false)}
              aria-label="Dismiss"
              className="flex-shrink-0 text-[#6b7594] hover:text-[#f0ece4]"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
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
