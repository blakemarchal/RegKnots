'use client'

// 2026-09-29 — citations the verifier couldn't match to the corpus, moved from
// the old "Content" tab. "Purge all" now says what it does: the endpoint
// empties the whole table, not only the rows loaded here.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { apiRequest } from '@/lib/api'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate } from '../_lib/format'
import type { CitationError } from '../_lib/types'
import { Empty, Page, Skeleton, TEXT_MUTED, btn } from '../_components/ui'

export default function AdminCitationsPage() {
  const { ei, isOwner, refresh } = useAdmin()
  const [rows, setRows] = useState<CitationError[] | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    setRows(null)
    apiRequest<CitationError[]>(`/admin/citation-errors?limit=50&exclude_internal=${ei}`).then(setRows).catch(() => setRows([]))
  }, [ei])

  async function purge() {
    if (!confirm('Delete EVERY citation error in the database, not only the ones listed here?\n\nThis cannot be undone.')) return
    try {
      await apiRequest('/admin/citation-errors/purge', { method: 'DELETE' })
      setRows([])
      refresh()
    } catch {
      alert('Failed to purge citation errors')
    }
  }

  return (
    <Page
      title="Citation errors"
      description="Answers that cited something the verifier couldn't find in the corpus. Newest 50; click a row for the full answer."
      actions={isOwner && rows && rows.length > 0 && <button onClick={purge} className={btn.danger}>Purge all</button>}
    >
      {!rows ? <Skeleton className="h-[160px]" /> : rows.length === 0 ? (
        <Empty tone="good">No citation errors.</Empty>
      ) : (
        <div className="rounded-xl border border-white/8 overflow-auto">
          <table className="w-full text-left font-mono text-xs" style={{ minWidth: 640 }}>
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#1a1d24] text-amber-400">
                {['Citation', 'Model', 'Answer', 'Date', ''].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((ce, i) => {
                const open = expanded === ce.id
                return (
                  <tr key={ce.id} onClick={() => setExpanded(open ? null : ce.id)}
                    className={`border-t border-white/5 cursor-pointer hover:bg-white/[0.03] align-top ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                    <td className="px-3 py-2 text-[#f0ece4]/90 whitespace-nowrap font-bold">{ce.unverified_citation}</td>
                    <td className="px-3 py-2 text-[#8b93ad] whitespace-nowrap">{ce.model_used ?? 'unknown'}</td>
                    <td className="px-3 py-2 text-[#f0ece4]/65">
                      {open ? (
                        <div className="whitespace-pre-wrap break-words text-[#f0ece4]/85 leading-relaxed">{ce.message_preview}</div>
                      ) : (
                        <div className="truncate max-w-[420px]">{ce.message_preview.slice(0, 140)}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[#8b93ad] whitespace-nowrap">{fmtDate(ce.created_at)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <Link href={`/admin/chats?conversation_id=${ce.conversation_id}`} onClick={(e) => e.stopPropagation()}
                        className="text-[#2dd4bf] hover:underline">Conversation →</Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className={`font-mono text-[11px] ${TEXT_MUTED} mt-3`}>
        Hedges (answers that said the corpus didn&apos;t cover something) are tracked separately in <Link href="/admin/hedge-audit" className="text-[#2dd4bf] hover:underline">Hedge audit</Link>.
      </p>
    </Page>
  )
}
