'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { fmtDate, fmtRelative } from '../_lib/format'

// ── Chats tab (Sprint D6.21) ────────────────────────────────────────────────

interface ChatListItem {
  conversation_id: string
  user_id: string
  user_email: string
  user_name: string | null
  is_internal: boolean
  vessel_id: string | null
  vessel_name: string | null
  vessel_type: string | null
  flag_state: string | null
  title: string | null
  message_count: number
  has_unverified: boolean
  has_hedge: boolean
  last_model: string | null
  created_at: string
  last_message_at: string | null
}

interface ChatListResponse {
  items: ChatListItem[]
  total: number
  limit: number
  offset: number
}

interface ChatMessageDetail {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_used: string | null
  tokens_used: number | null
  cited_regulations: { source: string; section_number: string; section_title: string | null }[]
  unverified_citations: string[]
  hedge_phrase: string | null
  created_at: string
  // D6.59 — populated for assistant turns that fired the web fallback
  // so admin chat preview can render the same yellow card the user saw.
  web_fallback?: {
    fallback_id: string
    source_url: string
    source_domain: string
    quote: string
    summary: string
    confidence: number
    surface_tier?: 'verified' | 'consensus' | 'reference' | null
  } | null
}

interface VesselSnapshot {
  id: string | null
  name: string | null
  vessel_type: string | null
  flag_state: string | null
  route_types: string[]
  cargo_types: string[]
  gross_tonnage: number | null
  subchapter: string | null
  route_limitations: string | null
}

interface ChatDetail {
  conversation_id: string
  user_id: string
  user_email: string
  user_name: string | null
  is_internal: boolean
  title: string | null
  created_at: string
  vessel: VesselSnapshot | null
  messages: ChatMessageDetail[]
}

interface ChatsTabProps {
  /** Conversation id to auto-open on mount (deep-link from hedge-audit
   *  / web-fallback admin pages via ?conversation_id=...). */
  initialChatId?: string | null
  /** Starting value of the page's own "Exclude internal" switch (the sidebar's setting). */
  defaultExcludeInternal?: boolean
}

export function ChatsTab({ initialChatId, defaultExcludeInternal = true }: ChatsTabProps = {}) {
  const [items, setItems] = useState<ChatListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [excludeInternal, setExcludeInternal] = useState(defaultExcludeInternal)
  const [filterFlag, setFilterFlag] = useState('')
  const [filterUnverified, setFilterUnverified] = useState<'all' | 'with' | 'without'>('all')
  const [filterHedged, setFilterHedged] = useState<'all' | 'with' | 'without'>('all')
  const [filterEmail, setFilterEmail] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ChatDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const PAGE_SIZE = 25

  const fetchList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
        exclude_internal: String(excludeInternal),
      })
      if (filterFlag) params.set('flag_state', filterFlag)
      if (filterEmail) params.set('user_email', filterEmail)
      if (filterUnverified !== 'all') params.set('has_unverified', String(filterUnverified === 'with'))
      if (filterHedged !== 'all') params.set('has_hedge', String(filterHedged === 'with'))
      const r = await apiRequest<ChatListResponse>(`/admin/chats?${params.toString()}`)
      setItems(r.items)
      setTotal(r.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chats')
    } finally {
      setLoading(false)
    }
  }, [offset, excludeInternal, filterFlag, filterEmail, filterUnverified, filterHedged])

  useEffect(() => { fetchList() }, [fetchList])

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id)
    setDetail(null)
    setDetailLoading(true)
    try {
      const r = await apiRequest<ChatDetail>(`/admin/chats/${id}`)
      setDetail(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chat detail')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  // Deep-link: when navigated to with ?conversation_id=<id>, auto-open
  // that chat in the detail panel. The chat detail comes from
  // /admin/chats/<id> directly; it does not need to be in the filtered
  // list. Runs once per distinct id.
  useEffect(() => {
    if (initialChatId && initialChatId !== selectedId) {
      void openDetail(initialChatId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialChatId])

  return (
    <div>
      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 mb-4 items-center text-xs font-mono">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={excludeInternal} onChange={(e) => { setExcludeInternal(e.target.checked); setOffset(0) }} />
          Exclude internal
        </label>
        <input
          placeholder="email contains"
          value={filterEmail}
          onChange={(e) => { setFilterEmail(e.target.value); setOffset(0) }}
          className="bg-[#0d1224] border border-white/10 rounded px-2 py-1 text-[#f0ece4] w-48"
        />
        <input
          placeholder="flag (e.g. United States)"
          value={filterFlag}
          onChange={(e) => { setFilterFlag(e.target.value); setOffset(0) }}
          className="bg-[#0d1224] border border-white/10 rounded px-2 py-1 text-[#f0ece4] w-56"
        />
        <select
          value={filterUnverified}
          onChange={(e) => { setFilterUnverified(e.target.value as 'all' | 'with' | 'without'); setOffset(0) }}
          className="bg-[#0d1224] border border-white/10 rounded px-2 py-1 text-[#f0ece4]"
        >
          <option value="all">unverified: any</option>
          <option value="with">unverified: yes</option>
          <option value="without">unverified: no</option>
        </select>
        <select
          value={filterHedged}
          onChange={(e) => { setFilterHedged(e.target.value as 'all' | 'with' | 'without'); setOffset(0) }}
          className="bg-[#0d1224] border border-white/10 rounded px-2 py-1 text-[#f0ece4]"
        >
          <option value="all">hedged: any</option>
          <option value="with">hedged: yes</option>
          <option value="without">hedged: no</option>
        </select>
        <span className="text-[#6b7594] ml-auto">
          {total} total · showing {items.length} from offset {offset}
        </span>
      </div>

      {error && <div className="text-red-400 text-sm font-mono mb-2">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.5fr] gap-4">
        {/* List */}
        <div className="overflow-y-auto max-h-[80vh] border border-white/8 rounded-md">
          {loading && <div className="p-4 text-[#6b7594] text-xs">Loading…</div>}
          {!loading && items.length === 0 && (
            <div className="p-4 text-[#6b7594] text-xs">No chats match these filters.</div>
          )}
          {items.map((it) => (
            <button
              key={it.conversation_id}
              onClick={() => openDetail(it.conversation_id)}
              className={`w-full text-left px-3 py-2 border-b border-white/5 hover:bg-white/5 ${
                selectedId === it.conversation_id ? 'bg-[#2dd4bf]/10' : ''
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-mono text-[#f0ece4] truncate">
                    {it.title || '(untitled)'}
                  </div>
                  <div className="text-[10px] font-mono text-[#6b7594] mt-0.5 truncate">
                    {it.user_email}
                    {it.is_internal && <span className="ml-1 text-[#fbbf24]">[internal]</span>}
                    {it.vessel_name && <span className="ml-1">· {it.vessel_name}</span>}
                    {it.flag_state && <span className="ml-1">· {it.flag_state}</span>}
                  </div>
                </div>
                <div className="flex flex-col items-end text-[10px] font-mono text-[#6b7594] gap-0.5">
                  <span>{fmtRelative(it.last_message_at || it.created_at)}</span>
                  <div className="flex gap-1">
                    {it.has_unverified && <span className="text-red-400">unv</span>}
                    {it.has_hedge && <span className="text-amber-400">hdg</span>}
                    <span>{it.message_count}m</span>
                  </div>
                </div>
              </div>
            </button>
          ))}
          {/* Pagination */}
          <div className="flex justify-between p-2 text-xs font-mono border-t border-white/8">
            <button
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="text-[#2dd4bf] disabled:text-[#6b7594]"
            >
              ← prev
            </button>
            <button
              disabled={offset + items.length >= total || loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="text-[#2dd4bf] disabled:text-[#6b7594]"
            >
              next →
            </button>
          </div>
        </div>

        {/* Detail */}
        <div className="border border-white/8 rounded-md p-4 max-h-[80vh] overflow-y-auto">
          {!selectedId && <div className="text-[#6b7594] text-xs font-mono">Select a chat from the list to inspect.</div>}
          {selectedId && detailLoading && <div className="text-[#6b7594] text-xs font-mono">Loading…</div>}
          {detail && (
            <>
              {/* Header */}
              <div className="border-b border-white/10 pb-2 mb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-mono text-[#f0ece4]">{detail.title || '(untitled)'}</div>
                    <div className="text-[10px] font-mono text-[#6b7594] mt-1">
                      {detail.user_email} · {fmtDate(detail.created_at)}
                    </div>
                  </div>
                  <a
                    href={`/admin/chat-preview/${detail.conversation_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-shrink-0 px-2.5 py-1 rounded border border-[#2dd4bf]/30 bg-[#2dd4bf]/5
                               text-[10px] font-mono text-[#2dd4bf] hover:bg-[#2dd4bf]/10
                               transition-colors"
                    title="Render this chat in the production UI to verify what the user actually saw"
                  >
                    View as user ↗
                  </a>
                </div>
              </div>

              {/* Vessel snapshot */}
              {detail.vessel && (
                <div className="bg-[#0d1224] rounded p-2 mb-3 text-[11px] font-mono">
                  <div className="text-[#2dd4bf] text-[10px] uppercase tracking-wide mb-1">Vessel context</div>
                  <div className="grid grid-cols-2 gap-1 text-[#f0ece4]">
                    <div>Name: {detail.vessel.name || '—'}</div>
                    <div>Type: {detail.vessel.vessel_type || '—'}</div>
                    <div>Flag: {detail.vessel.flag_state || '—'}</div>
                    <div>Tonnage: {detail.vessel.gross_tonnage ?? '—'}</div>
                    <div className="col-span-2">Routes: {detail.vessel.route_types.join(', ') || '—'}</div>
                    <div className="col-span-2">Cargo: {detail.vessel.cargo_types.join(', ') || '—'}</div>
                    {detail.vessel.route_limitations && (
                      <div className="col-span-2">Route note: {detail.vessel.route_limitations}</div>
                    )}
                  </div>
                </div>
              )}

              {/* Messages */}
              {detail.messages.map((m) => (
                <div key={m.id} className="mb-4">
                  <div className="flex items-center justify-between text-[10px] font-mono text-[#6b7594] mb-1">
                    <span className={m.role === 'user' ? 'text-[#fbbf24]' : 'text-[#2dd4bf]'}>
                      {m.role.toUpperCase()}
                    </span>
                    <span>
                      {m.model_used && <span className="mr-2">{m.model_used}</span>}
                      {m.tokens_used !== null && <span className="mr-2">{m.tokens_used}t</span>}
                      <span>{fmtRelative(m.created_at)}</span>
                    </span>
                  </div>
                  <div className="text-xs text-[#f0ece4] whitespace-pre-wrap break-words bg-[#0a0e1c] rounded p-2 border border-white/5">
                    {m.content}
                  </div>
                  {m.role === 'assistant' && (m.cited_regulations.length > 0 || m.unverified_citations.length > 0 || m.hedge_phrase) && (
                    <div className="mt-1 text-[10px] font-mono space-y-0.5">
                      {m.cited_regulations.length > 0 && (
                        <div className="text-[#6b7594]">
                          Cited:{' '}
                          {m.cited_regulations.map((c, i) => (
                            <span key={i} className="text-[#2dd4bf] mr-2">
                              {c.section_number}
                            </span>
                          ))}
                        </div>
                      )}
                      {m.unverified_citations.length > 0 && (
                        <div className="text-red-400">
                          Unverified: {m.unverified_citations.join(' · ')}
                        </div>
                      )}
                      {m.hedge_phrase && (
                        <div className="text-amber-400">Hedged: &quot;{m.hedge_phrase}&quot;</div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
