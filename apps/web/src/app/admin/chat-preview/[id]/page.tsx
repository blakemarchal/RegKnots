'use client'

// Sprint D6.59 — admin "view as user" chat preview.
//
// The /admin Chats-tab detail panel shows the raw text + per-message
// forensic metadata (model, tokens, hedge phrase, etc.). This page
// renders the SAME conversation through the production ChatMessage
// component so admin can verify exactly what the user saw — wrapping,
// citations, web-fallback yellow card, copy button, all of it.
//
// Read-only: citation taps open the source URL in a new tab instead of
// navigating into the in-app regulation viewer (which assumes a user
// context this page doesn't have).

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { ChatThread } from '@/components/ChatThread'
import { apiRequest } from '@/lib/api'
import type { Message, CitedRegulation, WebFallbackCard } from '@/types/chat'

// Same shape as in /admin/page.tsx — duplicated here to keep this page
// self-contained; if it drifts we'll consolidate into a shared types
// module.
interface AdminChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_used: string | null
  tokens_used: number | null
  cited_regulations: { source: string; section_number: string; section_title: string | null }[]
  unverified_citations: string[]
  hedge_phrase: string | null
  created_at: string
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

interface AdminChatDetail {
  conversation_id: string
  user_id: string
  user_email: string
  user_name: string | null
  is_internal: boolean
  title: string | null
  created_at: string
  vessel: VesselSnapshot | null
  messages: AdminChatMessage[]
}

function fmtDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// Map admin payload → production Message shape so we can reuse
// ChatThread/ChatMessage rendering verbatim.
function toUiMessages(detail: AdminChatDetail): Message[] {
  return detail.messages.map((m): Message => {
    const citations: CitedRegulation[] = m.cited_regulations.map(c => ({
      source: c.source,
      section_number: c.section_number,
      // ChatMessage's CitationChip handles empty title gracefully —
      // null becomes ''.
      section_title: c.section_title ?? '',
    }))
    let web_fallback: WebFallbackCard | undefined
    if (m.web_fallback) {
      web_fallback = {
        fallback_id: m.web_fallback.fallback_id,
        source_url: m.web_fallback.source_url,
        source_domain: m.web_fallback.source_domain,
        quote: m.web_fallback.quote,
        summary: m.web_fallback.summary,
        confidence: m.web_fallback.confidence,
        surface_tier: (m.web_fallback.surface_tier ?? undefined) as
          | 'verified' | 'consensus' | 'reference' | undefined,
      }
    }
    return {
      id: m.id,
      role: m.role,
      content: m.content,
      citations,
      web_fallback: web_fallback ?? null,
    }
  })
}

function Content() {
  const params = useParams<{ id: string }>()
  const id = params?.id
  const [detail, setDetail] = useState<AdminChatDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const r = await apiRequest<AdminChatDetail>(`/admin/chats/${id}`)
      setDetail(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chat')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load])

  // Citation tap handler — read-only mode opens the regulator source URL
  // in a new tab. The production handler navigates to /reference?...,
  // which assumes the user is mid-conversation; in admin preview that
  // would be a confusing context switch.
  const handleCitationTap = useCallback((source: string, sectionNumber: string) => {
    // Best-effort: build a sensible eCFR URL for CFR sections, else
    // do nothing. Most cited reg URLs in the corpus aren't directly
    // reconstructable from (source, section_number); leave as no-op
    // for non-CFR.
    const cfrMatch = sectionNumber.match(/^(\d+)\s+CFR\s+(\d+)\.(.+)$/)
    if (cfrMatch) {
      const [, title, part, sect] = cfrMatch
      const url = `https://www.ecfr.gov/current/title-${title}/part-${part}/section-${part}.${sect}`
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }, [])

  if (!id) return null

  return (
    <div className="flex flex-col h-dvh overflow-hidden bg-[#0a0e1a]">
      {/* ── Admin metadata strip — distinguishes preview from real chat ── */}
      <div className="flex-shrink-0 bg-[#0a1628] border-b border-[#2dd4bf]/30 px-4 py-2">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-[#2dd4bf] uppercase tracking-wider">Admin preview</span>
            {detail && (
              <>
                <span className="text-[#6b7594]">·</span>
                <span className="text-[#f0ece4]">{detail.user_email}</span>
                {detail.is_internal && (
                  <span className="text-[#fbbf24]">[internal]</span>
                )}
                <span className="text-[#6b7594]">·</span>
                <span className="text-[#6b7594]">{fmtDate(detail.created_at)}</span>
                {detail.vessel?.name && (
                  <>
                    <span className="text-[#6b7594]">·</span>
                    <span className="text-[#f0ece4]/80">{detail.vessel.name}</span>
                    {detail.vessel.flag_state && (
                      <span className="text-[#6b7594]">({detail.vessel.flag_state})</span>
                    )}
                  </>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Link
              href={`/admin?tab=chats&conversation_id=${id}`}
              className="text-xs font-mono text-[#2dd4bf] hover:underline"
            >
              Forensic view →
            </Link>
            <Link
              href="/admin"
              className="text-xs font-mono text-[#6b7594] hover:text-[#f0ece4]"
            >
              ← Admin
            </Link>
          </div>
        </div>
      </div>

      {/* ── Vessel context (collapsible-ish detail card) ── */}
      {detail?.vessel && (detail.vessel.vessel_type || detail.vessel.gross_tonnage || detail.vessel.route_types.length > 0) && (
        <div className="flex-shrink-0 bg-[#0d1224] border-b border-white/5 px-4 py-1.5">
          <div className="max-w-3xl mx-auto text-[10px] font-mono text-[#6b7594] flex items-center gap-3 flex-wrap">
            {detail.vessel.vessel_type && <span>type: <span className="text-[#f0ece4]/80">{detail.vessel.vessel_type}</span></span>}
            {detail.vessel.gross_tonnage !== null && <span>tonnage: <span className="text-[#f0ece4]/80">{detail.vessel.gross_tonnage}</span></span>}
            {detail.vessel.subchapter && <span>subchapter: <span className="text-[#f0ece4]/80">{detail.vessel.subchapter}</span></span>}
            {detail.vessel.route_types.length > 0 && <span>routes: <span className="text-[#f0ece4]/80">{detail.vessel.route_types.join(', ')}</span></span>}
            {detail.vessel.cargo_types.length > 0 && <span>cargo: <span className="text-[#f0ece4]/80">{detail.vessel.cargo_types.join(', ')}</span></span>}
          </div>
        </div>
      )}

      {/* ── Chat thread (production rendering, read-only) ── */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto">
          {loading && (
            <div className="px-4 py-12 text-center text-sm font-mono text-[#6b7594]">
              Loading…
            </div>
          )}
          {error && (
            <div className="px-4 py-12 text-center text-sm font-mono text-red-400">
              {error}
            </div>
          )}
          {detail && !loading && (
            <ChatThread
              messages={toUiMessages(detail)}
              loading={false}
              onPrompt={() => { /* no-op in preview */ }}
              onCitationTap={handleCitationTap}
              isNewConversation={false}
              vessel={null}
            />
          )}
        </div>
      </main>
    </div>
  )
}

export default function AdminChatPreviewPage() {
  return (
    <AuthGuard>
      <Content />
    </AuthGuard>
  )
}
