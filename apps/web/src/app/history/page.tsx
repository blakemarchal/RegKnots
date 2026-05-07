'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { CompassRose } from '@/components/CompassRose'
import { signalNavigation } from '@/components/NavigationProgress'
import { useAuthStore } from '@/lib/auth'
import {
  formatSingleConversationAsText,
  triggerDownload,
  type ExportConversation,
} from '@/lib/export'

interface ConversationSummary {
  id: string
  title: string
  updated_at: string
  vessel_name: string | null
  // Sprint D6.79 — surfaced so openConversation can sync the auth-store
  // active vessel before navigating, eliminating the context-drift where
  // a user clicks a chat tied to vessel A but the selector still shows
  // whatever was active before.
  vessel_id: string | null
  // Sprint D6.80 — soft archive timestamp. Null = active. Default list
  // filters archived rows out; "Show archived" toggle reveals them.
  archived_at: string | null
}

// Sprint D6.3c — discreet history search. Returned by /conversations/search
// when the user has typed ≥2 chars in the search input.
interface ConversationSearchResult {
  id: string
  title: string
  updated_at: string
  vessel_name: string | null
  vessel_id: string | null
  matched_role: 'user' | 'assistant'
  matched_preview: string
  matched_at: string
}

// ── Date formatting ────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  const now = new Date()
  const then = new Date(iso)

  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const weekStart = new Date(todayStart)
  weekStart.setDate(todayStart.getDate() - 6)

  if (then >= todayStart) {
    return then.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }
  if (then >= weekStart) {
    return then.toLocaleDateString('en-US', { weekday: 'long' })
  }
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
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

// ── Icons ──────────────────────────────────────────────────────────────────────

function DownloadIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M10 3v10" />
      <path d="m6 9 4 4 4-4" />
      <path d="M4 16h12" />
    </svg>
  )
}

// Sprint D6.80 — archive icon (filing-cabinet box). Used to soft-archive
// a conversation (hide from default /history) without losing the data.
function ArchiveIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="3" y="4" width="14" height="3" rx="0.5" />
      <path d="M4 7v8a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7" />
      <path d="M8 11h4" />
    </svg>
  )
}

// Restore icon — counterpart to archive. Used in the archived list to
// move a conversation back to active.
function RestoreIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M3 10a7 7 0 1 1 2 4.95" />
      <path d="M3 16v-4h4" />
    </svg>
  )
}

// ── Vessel group ───────────────────────────────────────────────────────────────

interface VesselGroup {
  name: string
  conversations: ConversationSummary[]
}

function VesselGroupSection({
  group,
  expanded,
  onToggle,
  onOpen,
  onExport,
  exportingId,
  onArchive,
  onUnarchive,
  archivingId,
}: {
  group: VesselGroup
  expanded: boolean
  onToggle: () => void
  onOpen: (id: string) => void
  onExport: (id: string, title: string) => void
  exportingId: string | null
  // Sprint D6.80 — archive/restore action handlers + in-flight tracker
  // so we can dim the row and prevent double-clicks.
  onArchive: (id: string) => void
  onUnarchive: (id: string) => void
  archivingId: string | null
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-2 px-1 py-2"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-[#6b7594] text-xs transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}>
            ▸
          </span>
          <span className="font-display text-sm font-bold text-[#2dd4bf] tracking-wide truncate">
            {group.name}
          </span>
        </div>
        <span className="font-mono text-[10px] text-[#6b7594] flex-shrink-0">
          {group.conversations.length} {group.conversations.length === 1 ? 'chat' : 'chats'}
        </span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-1.5 ml-1 mb-3">
          {group.conversations.map(c => {
            const isArchived = c.archived_at !== null
            const isPending = archivingId === c.id
            return (
            <div
              key={c.id}
              className={`relative bg-[#111827] border-l-2
                hover:bg-[#111827]/80 rounded-r-xl transition-all duration-150
                ${isArchived
                  ? 'border-white/10 opacity-70 hover:opacity-100'
                  : 'border-[#2dd4bf]/30 hover:border-[#2dd4bf]'}
                ${isPending ? 'pointer-events-none opacity-50' : ''}`}
            >
              <button
                onClick={() => onOpen(c.id)}
                className="w-full text-left px-4 py-3 pr-20"
              >
                <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                  {c.title}
                </p>
                <p className="font-mono text-xs text-[#6b7594] mt-1">
                  {formatDate(c.updated_at)}
                  {isArchived && <span className="ml-2 text-[10px] text-amber-400/70 uppercase tracking-wider">Archived</span>}
                </p>
              </button>
              <div className="absolute top-2 right-2 flex items-center gap-0.5">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onExport(c.id, c.title)
                  }}
                  disabled={exportingId === c.id}
                  aria-label="Export conversation"
                  title="Export conversation"
                  className="p-1.5 rounded-md
                    text-[#6b7594] hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                    disabled:opacity-40 transition-colors duration-150"
                >
                  <DownloadIcon className="w-4 h-4" />
                </button>
                {isArchived ? (
                  <button
                    onClick={(e) => { e.stopPropagation(); onUnarchive(c.id) }}
                    disabled={isPending}
                    aria-label="Restore conversation"
                    title="Restore conversation"
                    className="p-1.5 rounded-md
                      text-[#6b7594] hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                      disabled:opacity-40 transition-colors duration-150"
                  >
                    <RestoreIcon className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); onArchive(c.id) }}
                    disabled={isPending}
                    aria-label="Archive conversation"
                    title="Archive conversation"
                    className="p-1.5 rounded-md
                      text-[#6b7594] hover:text-amber-400 hover:bg-amber-400/10
                      disabled:opacity-40 transition-colors duration-150"
                  >
                    <ArchiveIcon className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── History content ────────────────────────────────────────────────────────────

function HistoryContent() {
  const router = useRouter()
  const vessels = useAuthStore((s) => s.vessels)
  // Sprint D6.79 — sync active vessel when opening a chat from history
  // so the vessel selector reflects the conversation's context instead
  // of whatever was previously active.
  const setActiveVessel = useAuthStore((s) => s.setActiveVessel)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [filter, setFilter] = useState<string>('all')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [exportingId, setExportingId] = useState<string | null>(null)
  // Sprint D6.3c — chat history search state
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<ConversationSearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  // Sprint D6.80 — soft archive UX state. Default hide; toggle reveals
  // archived rows. archivingId tracks an in-flight archive/restore so
  // we can dim the row while the API call is pending and keep the
  // user from double-clicking.
  const [showArchived, setShowArchived] = useState(false)
  const [archivingId, setArchivingId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    // Sprint D6.49 — workspace context. URL-based opt-in: when the
    // history page is opened with ?workspace=<uuid>, list workspace
    // conversations. Without the param, list personal conversations
    // (legacy behavior, identical for non-workspace users).
    // Sprint D6.80 — also pass include_archived flag from the toggle.
    const params = new URLSearchParams(window.location.search)
    const wsId = params.get('workspace')
    const qs = new URLSearchParams()
    if (wsId) qs.set('workspace_id', wsId)
    if (showArchived) qs.set('include_archived', 'true')
    const url = qs.toString() ? `/conversations?${qs.toString()}` : '/conversations'

    apiRequest<ConversationSummary[]>(url)
      .then(data => {
        if (cancelled) return
        setConversations(data)
        const names = new Set<string>()
        data.forEach(c => names.add(c.vessel_name ?? '__general__'))
        setExpandedGroups(names)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError(true)
        setLoading(false)
      })

    return () => { cancelled = true }
  }, [showArchived])

  // Debounced search effect — fires 300ms after the user stops typing.
  // Trims and requires ≥2 chars to avoid pinging the API on every keystroke.
  useEffect(() => {
    const trimmed = searchQuery.trim()
    if (trimmed.length < 2) {
      setSearchResults(null)
      setSearching(false)
      return
    }
    let cancelled = false
    setSearching(true)
    const handle = setTimeout(() => {
      apiRequest<ConversationSearchResult[]>(
        `/conversations/search?q=${encodeURIComponent(trimmed)}&limit=25`,
      )
        .then(data => {
          if (cancelled) return
          setSearchResults(data)
          setSearching(false)
        })
        .catch(() => {
          if (cancelled) return
          setSearchResults([])
          setSearching(false)
        })
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [searchQuery])

  function openConversation(id: string) {
    signalNavigation()
    // Sprint D6.79 — sync the active vessel to whatever this conversation
    // is bound to BEFORE navigating, so the vessel selector reflects the
    // chat's context the moment ChatInterface mounts. Look up vessel_id
    // from either the main list OR the search results (both carry it).
    const conv =
      conversations.find(c => c.id === id) ??
      searchResults?.find(c => c.id === id)
    if (conv) {
      // null vessel_id (general chats) is a valid value to pass through —
      // it explicitly clears the active vessel, matching the conversation's
      // "no vessel" state. The auth store accepts string|null.
      setActiveVessel(conv.vessel_id ?? null)
    }
    // Preserve workspace context if currently viewing workspace history,
    // so the chat opens in the right context (Sprint D6.49).
    const params = new URLSearchParams(window.location.search)
    const wsId = params.get('workspace')
    const target = wsId
      ? `/?conversation_id=${id}&workspace=${wsId}`
      : `/?conversation_id=${id}`
    router.push(target)
  }

  // Sprint D6.80 — soft archive a conversation. Optimistic-local update
  // so the row disappears immediately when not in show-archived mode;
  // fallback re-fetch if the server call fails.
  async function archiveConversation(id: string) {
    if (archivingId) return
    setArchivingId(id)
    try {
      await apiRequest(`/conversations/${id}/archive`, { method: 'POST' })
      // Optimistic update — flip the row's archived_at locally.
      setConversations(prev =>
        prev.map(c =>
          c.id === id ? { ...c, archived_at: new Date().toISOString() } : c,
        ).filter(c => showArchived || c.archived_at === null),
      )
    } catch {
      // Silent on failure — the next nav refetch will reconcile.
    } finally {
      setArchivingId(null)
    }
  }

  async function unarchiveConversation(id: string) {
    if (archivingId) return
    setArchivingId(id)
    try {
      await apiRequest(`/conversations/${id}/unarchive`, { method: 'POST' })
      setConversations(prev =>
        prev.map(c => (c.id === id ? { ...c, archived_at: null } : c)),
      )
    } catch {
      // Silent on failure — see archiveConversation.
    } finally {
      setArchivingId(null)
    }
  }

  async function exportConversation(id: string, title: string) {
    if (exportingId) return
    setExportingId(id)
    try {
      const data = await apiRequest<ExportConversation>(`/conversations/${id}/export`)
      const safeTitle = (title || 'conversation')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 40) || 'conversation'
      const stamp = new Date().toISOString().slice(0, 10)
      const blob = new Blob([formatSingleConversationAsText(data)], {
        type: 'text/plain;charset=utf-8',
      })
      triggerDownload(blob, `regknot_${safeTitle}_${stamp}.txt`)
    } catch {
      // Silent failure — secondary action, no prominent error UI here.
    } finally {
      setExportingId(null)
    }
  }

  function toggleGroup(name: string) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // Build grouped data
  const filtered = filter === 'all'
    ? conversations
    : filter === '__general__'
      ? conversations.filter(c => !c.vessel_name)
      : conversations.filter(c => c.vessel_name === filter)

  const vesselGroups: VesselGroup[] = []
  const groupMap = new Map<string, ConversationSummary[]>()

  for (const c of filtered) {
    const key = c.vessel_name ?? '__general__'
    if (!groupMap.has(key)) groupMap.set(key, [])
    groupMap.get(key)!.push(c)
  }

  // Vessel groups first (sorted by most recent), general last
  const vesselKeys = [...groupMap.keys()].filter(k => k !== '__general__')
  vesselKeys.sort((a, b) => {
    const aTime = groupMap.get(a)![0]?.updated_at ?? ''
    const bTime = groupMap.get(b)![0]?.updated_at ?? ''
    return bTime.localeCompare(aTime)
  })

  for (const key of vesselKeys) {
    vesselGroups.push({ name: key, conversations: groupMap.get(key)! })
  }
  if (groupMap.has('__general__')) {
    vesselGroups.push({ name: 'General', conversations: groupMap.get('__general__')! })
  }

  // Unique vessel names from conversations (not just user's vessels)
  const allVesselNames = [...new Set(conversations.filter(c => c.vessel_name).map(c => c.vessel_name!))]

  // Sprint D6.49 — workspace context banner. Renders ONLY when the
  // history page was opened with ?workspace=<id>; personal-tier users
  // (no URL param) never see this.
  const wsParam = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('workspace')
    : null

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Chat History" />

      {/* Workspace context banner — workspace mode only */}
      {wsParam && (
        <div className="flex-shrink-0 bg-[#2dd4bf]/8 border-b border-[#2dd4bf]/25 px-4 py-2 flex items-center justify-between gap-3">
          <div className="text-xs font-mono text-[#2dd4bf]/80 truncate">
            <span className="uppercase tracking-wider mr-1.5">Workspace history</span>
            <span className="text-[#6b7594]">
              · Showing chats shared with all workspace members
            </span>
          </div>
          <a
            href="/history"
            className="text-xs font-mono text-[#2dd4bf]/80 hover:text-[#2dd4bf] underline whitespace-nowrap"
          >
            Personal history →
          </a>
        </div>
      )}

      {/* Content */}
      <main className="chat-thread flex-1 overflow-y-auto">
        <div className="px-4 py-4 flex flex-col gap-2">

          {/* ── Search input (Sprint D6.3c — discreet) ─────────────────── */}
          {!loading && !error && conversations.length > 0 && (
            <div className="relative mb-1">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#6b7594]"
                viewBox="0 0 16 16" fill="none" stroke="currentColor"
                strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="7" cy="7" r="5" />
                <path d="m11 11 3 3" />
              </svg>
              <input
                type="search"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search your chat history…"
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-[#0d1225] border border-white/8
                  font-mono text-sm text-[#f0ece4] placeholder:text-[#6b7594]
                  focus:outline-none focus:border-[#2dd4bf]/40 transition-colors"
              />
              {searchQuery.trim().length >= 2 && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 rounded
                    font-mono text-[10px] uppercase tracking-wider text-[#6b7594]
                    hover:text-[#f0ece4] transition-colors"
                  aria-label="Clear search"
                >
                  Clear
                </button>
              )}
            </div>
          )}

          {/* Filter bar — hidden when actively searching to keep focus on results */}
          {!loading && !error && conversations.length > 0 && searchResults === null && (
            <div className="flex items-center gap-1.5 overflow-x-auto pb-2 -mx-1 px-1 no-scrollbar">
              <button
                onClick={() => setFilter('all')}
                className={`flex-shrink-0 font-mono text-xs px-3 py-1.5 rounded-lg border transition-colors
                  ${filter === 'all'
                    ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                    : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                  }`}
              >
                All
              </button>
              {allVesselNames.map(name => (
                <button
                  key={name}
                  onClick={() => setFilter(name)}
                  className={`flex-shrink-0 font-mono text-xs px-3 py-1.5 rounded-lg border transition-colors truncate max-w-[160px]
                    ${filter === name
                      ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                      : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                    }`}
                >
                  {name}
                </button>
              ))}
              {conversations.some(c => !c.vessel_name) && (
                <button
                  onClick={() => setFilter('__general__')}
                  className={`flex-shrink-0 font-mono text-xs px-3 py-1.5 rounded-lg border transition-colors
                    ${filter === '__general__'
                      ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                      : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                    }`}
                >
                  General
                </button>
              )}
              {/* Sprint D6.80 — show-archived toggle. Lives at the
                  rightmost end of the filter bar so the default filter
                  affordances stay where users expect them. Visually
                  distinct (amber) from the vessel filter chips so it
                  reads as a different axis of filtering, not another
                  vessel. */}
              <button
                onClick={() => setShowArchived(s => !s)}
                aria-pressed={showArchived}
                className={`ml-auto flex-shrink-0 flex items-center gap-1.5 font-mono text-xs px-3 py-1.5 rounded-lg border transition-colors
                  ${showArchived
                    ? 'bg-amber-400/10 border-amber-400/40 text-amber-400'
                    : 'border-white/10 text-[#6b7594] hover:text-[#f0ece4] hover:border-white/20'
                  }`}
              >
                <ArchiveIcon className="w-3.5 h-3.5" />
                {showArchived ? 'Hide archived' : 'Show archived'}
              </button>
            </div>
          )}

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
                onClick={() => router.push('/')}
                className="font-mono text-xs text-[#2dd4bf] hover:underline"
              >
                Ask your first question
              </button>
            </div>
          )}

          {/* Search results — shown only when actively searching */}
          {searchResults !== null && (
            <>
              {searching && (
                <p className="font-mono text-xs text-[#6b7594] text-center py-4">
                  Searching…
                </p>
              )}
              {!searching && searchResults.length === 0 && (
                <p className="font-mono text-sm text-[#6b7594] text-center py-8">
                  No matches for &ldquo;{searchQuery.trim()}&rdquo;
                </p>
              )}
              {!searching && searchResults.length > 0 && (
                <div className="flex flex-col gap-2">
                  <p className="font-mono text-[10px] uppercase tracking-widest text-[#6b7594] mt-1 mb-1">
                    {searchResults.length} match{searchResults.length === 1 ? '' : 'es'}
                  </p>
                  {searchResults.map(r => (
                    <button
                      key={`${r.id}-${r.matched_at}`}
                      onClick={() => openConversation(r.id)}
                      className="text-left bg-[#111827] border-l-2 border-[#2dd4bf]/30
                        hover:border-[#2dd4bf] hover:bg-[#111827]/80
                        rounded-r-xl transition-all duration-150 px-4 py-3"
                    >
                      <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                        {r.title}
                      </p>
                      <p className="font-mono text-xs text-[#6b7594] mt-1">
                        {r.vessel_name
                          ? <><span className="text-[#2dd4bf]">{r.vessel_name}</span> · {formatDate(r.matched_at)}</>
                          : formatDate(r.matched_at)}
                        {' · '}
                        <span className="text-[#f0ece4]/50">{r.matched_role === 'user' ? 'you' : 'RegKnot'}</span>
                      </p>
                      <p className="font-mono text-xs text-[#f0ece4]/60 mt-1.5 line-clamp-2 leading-snug">
                        {r.matched_preview}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {/* Grouped conversation cards — hidden during search */}
          {!loading && searchResults === null && filter === 'all' && vesselGroups.length > 0 && (
            <div className="flex flex-col gap-1">
              {vesselGroups.map(group => (
                <VesselGroupSection
                  key={group.name}
                  group={group}
                  expanded={expandedGroups.has(group.name === 'General' ? '__general__' : group.name)}
                  onToggle={() => toggleGroup(group.name === 'General' ? '__general__' : group.name)}
                  onOpen={openConversation}
                  onExport={exportConversation}
                  exportingId={exportingId}
                  onArchive={archiveConversation}
                  onUnarchive={unarchiveConversation}
                  archivingId={archivingId}
                />
              ))}
            </div>
          )}

          {/* Flat list when filtering by vessel — hidden during search */}
          {!loading && searchResults === null && filter !== 'all' && filtered.map(c => {
            const isArchived = c.archived_at !== null
            const isPending = archivingId === c.id
            return (
            <div
              key={c.id}
              className={`relative bg-[#111827] border-l-2
                hover:bg-[#111827]/80 rounded-r-xl transition-all duration-150
                animate-[fadeSlideIn_0.2s_ease-out]
                ${isArchived
                  ? 'border-white/10 opacity-70 hover:opacity-100'
                  : 'border-[#2dd4bf]/30 hover:border-[#2dd4bf]'}
                ${isPending ? 'pointer-events-none opacity-50' : ''}`}
            >
              <button
                onClick={() => openConversation(c.id)}
                className="w-full text-left px-4 py-3.5 pr-20"
              >
                <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                  {c.title}
                </p>
                <p className="font-mono text-xs text-[#6b7594] mt-1">
                  {c.vessel_name
                    ? <><span className="text-[#2dd4bf]">{c.vessel_name}</span> · {formatDate(c.updated_at)}</>
                    : formatDate(c.updated_at)
                  }
                  {isArchived && <span className="ml-2 text-[10px] text-amber-400/70 uppercase tracking-wider">Archived</span>}
                </p>
              </button>
              <div className="absolute top-2 right-2 flex items-center gap-0.5">
                <button
                  onClick={(e) => { e.stopPropagation(); exportConversation(c.id, c.title) }}
                  disabled={exportingId === c.id}
                  aria-label="Export conversation"
                  title="Export conversation"
                  className="p-1.5 rounded-md
                    text-[#6b7594] hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                    disabled:opacity-40 transition-colors duration-150"
                >
                  <DownloadIcon className="w-4 h-4" />
                </button>
                {isArchived ? (
                  <button
                    onClick={(e) => { e.stopPropagation(); unarchiveConversation(c.id) }}
                    disabled={isPending}
                    aria-label="Restore conversation"
                    title="Restore conversation"
                    className="p-1.5 rounded-md
                      text-[#6b7594] hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                      disabled:opacity-40 transition-colors duration-150"
                  >
                    <RestoreIcon className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); archiveConversation(c.id) }}
                    disabled={isPending}
                    aria-label="Archive conversation"
                    title="Archive conversation"
                    className="p-1.5 rounded-md
                      text-[#6b7594] hover:text-amber-400 hover:bg-amber-400/10
                      disabled:opacity-40 transition-colors duration-150"
                  >
                    <ArchiveIcon className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            )
          })}

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
