'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { CompassRose } from '@/components/CompassRose'
import { signalNavigation } from '@/components/NavigationProgress'
import { useAuthStore } from '@/lib/auth'

interface ConversationSummary {
  id: string
  title: string
  updated_at: string
  vessel_name: string | null
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
}: {
  group: VesselGroup
  expanded: boolean
  onToggle: () => void
  onOpen: (id: string) => void
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
          {group.conversations.map(c => (
            <button
              key={c.id}
              onClick={() => onOpen(c.id)}
              className="w-full text-left bg-[#111827] border-l-2 border-[#2dd4bf]/30
                hover:border-[#2dd4bf] hover:bg-[#111827]/80
                rounded-r-xl px-4 py-3 transition-all duration-150"
            >
              <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                {c.title}
              </p>
              <p className="font-mono text-xs text-[#6b7594] mt-1">
                {formatDate(c.updated_at)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── History content ────────────────────────────────────────────────────────────

function HistoryContent() {
  const router = useRouter()
  const vessels = useAuthStore((s) => s.vessels)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [filter, setFilter] = useState<string>('all')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

  useEffect(() => {
    apiRequest<ConversationSummary[]>('/conversations')
      .then(data => {
        setConversations(data)
        // Auto-expand all groups on first load
        const names = new Set<string>()
        data.forEach(c => names.add(c.vessel_name ?? '__general__'))
        setExpandedGroups(names)
        setLoading(false)
      })
      .catch(() => { setError(true); setLoading(false) })
  }, [])

  function openConversation(id: string) {
    signalNavigation()
    router.push(`/?conversation_id=${id}`)
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

  return (
    <div className="flex flex-col h-dvh bg-[#0a0e1a]">
      <AppHeader title="Chat History" />

      {/* Content */}
      <main className="chat-thread flex-1 overflow-y-auto">
        <div className="px-4 py-4 flex flex-col gap-2">

          {/* Filter bar */}
          {!loading && !error && conversations.length > 0 && (
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

          {/* Grouped conversation cards */}
          {!loading && filter === 'all' && vesselGroups.length > 0 && (
            <div className="flex flex-col gap-1">
              {vesselGroups.map(group => (
                <VesselGroupSection
                  key={group.name}
                  group={group}
                  expanded={expandedGroups.has(group.name === 'General' ? '__general__' : group.name)}
                  onToggle={() => toggleGroup(group.name === 'General' ? '__general__' : group.name)}
                  onOpen={openConversation}
                />
              ))}
            </div>
          )}

          {/* Flat list when filtering by vessel */}
          {!loading && filter !== 'all' && filtered.map(c => (
            <button
              key={c.id}
              onClick={() => openConversation(c.id)}
              className="w-full text-left bg-[#111827] border-l-2 border-[#2dd4bf]/30
                hover:border-[#2dd4bf] hover:bg-[#111827]/80
                rounded-r-xl px-4 py-3.5 transition-all duration-150
                animate-[fadeSlideIn_0.2s_ease-out]"
            >
              <p className="font-mono text-sm text-[#f0ece4] truncate leading-snug">
                {c.title}
              </p>
              <p className="font-mono text-xs text-[#6b7594] mt-1">
                {c.vessel_name
                  ? <><span className="text-[#2dd4bf]">{c.vessel_name}</span> · {formatDate(c.updated_at)}</>
                  : formatDate(c.updated_at)
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
