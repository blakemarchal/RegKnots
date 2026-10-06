'use client'

// 2026-10-05 — documents users attached in chat (apps/api/app/user_docs.py):
// what the internal check made of each, and its text. Opening a document's
// text is recorded in the audit log. This is where we learn which documents
// mariners bring and which public sources the corpus is missing; nothing here
// copies a user's document anywhere.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useEscapeKey } from '@/lib/useEscapeKey'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate, fmtRelative } from '../_lib/format'
import { Empty, Page, Pill, Skeleton, TEXT_MUTED } from '../_components/ui'

interface AdminUserDocument {
  id: string
  user_email: string
  filename: string
  title: string
  mime_type: string
  size_bytes: number
  pages: number | null
  chunk_count: number
  status: 'pending' | 'ready' | 'failed'
  error: string | null
  doc_type: string | null
  maritime: boolean | null
  summary: string | null
  kept: boolean
  delete_after: string | null
  created_at: string
  last_used_at: string | null
  questions: number
}

interface AdminDocumentText {
  id: string
  user_email: string
  title: string
  filename: string
  doc_type: string | null
  summary: string | null
  sections: { section: string; text: string }[]
}

function kb(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

export default function AdminDocumentsPage() {
  const { ei } = useAdmin()
  const [rows, setRows] = useState<AdminUserDocument[] | null>(null)
  const [open, setOpen] = useState<AdminDocumentText | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  useEscapeKey(open !== null, () => setOpen(null))

  useEffect(() => {
    setRows(null)
    apiRequest<AdminUserDocument[]>(`/admin/user-documents?exclude_internal=${ei}`).then(setRows).catch(() => setRows([]))
  }, [ei])

  async function openText(id: string) {
    setOpening(id)
    try {
      setOpen(await apiRequest<AdminDocumentText>(`/admin/user-documents/${id}/text`))
    } catch {
      alert('Could not open this document.')
    } finally {
      setOpening(null)
    }
  }

  return (
    <Page
      title="Documents"
      description="PDF and Word files users attached in chat, with the internal check's verdict. Maritime documents stay in the user's account; the rest are deleted 7 days after upload. Opening a document's text is recorded in the audit log."
    >
      {!rows ? <Skeleton className="h-[160px]" /> : rows.length === 0 ? (
        <Empty>No documents yet.</Empty>
      ) : (
        <div className="rounded-xl border border-white/8 overflow-auto">
          <table className="w-full text-left font-mono text-xs" style={{ minWidth: 820 }}>
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#1a1d24] text-amber-400">
                {['Uploaded', 'User', 'Document', 'Check', 'Kept', 'Used', ''].map((h) => (
                  <th key={h} className="px-3 py-2.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => (
                <tr key={d.id} className={`border-t border-white/5 align-top ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                  <td className="px-3 py-2 text-[#8b93ad] whitespace-nowrap">{fmtDate(d.created_at)}</td>
                  <td className="px-3 py-2 text-[#f0ece4]/85 whitespace-nowrap">{d.user_email}</td>
                  <td className="px-3 py-2">
                    <div className="text-[#f0ece4]/90 font-bold truncate max-w-[260px]" title={d.filename}>{d.title}</div>
                    <div className={TEXT_MUTED}>
                      {d.mime_type.includes('pdf') ? 'PDF' : 'Word'} · {kb(d.size_bytes)}
                      {d.pages ? ` · ${d.pages} pp` : ''}{d.chunk_count ? ` · ${d.chunk_count} chunks` : ''}
                    </div>
                    {d.status === 'failed' && <div className="text-red-400 mt-0.5">{d.error}</div>}
                    {d.status === 'pending' && <div className="text-amber-400 mt-0.5">Reading…</div>}
                  </td>
                  <td className="px-3 py-2">
                    {d.doc_type ? (
                      <div className="flex flex-col gap-1">
                        <span className="flex gap-1">
                          <Pill tone={d.maritime ? 'teal' : 'gray'}>{d.doc_type.replace(/_/g, ' ')}</Pill>
                          {d.maritime === false && <Pill tone="gray">not maritime</Pill>}
                        </span>
                        {d.summary && <span className="text-[#f0ece4]/65 max-w-[280px]">{d.summary}</span>}
                      </div>
                    ) : d.status === 'ready' ? <Pill tone="amber">unlabelled</Pill> : null}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {d.kept ? <Pill tone="teal">kept</Pill> : d.delete_after ? (
                      <span className={TEXT_MUTED}>deletes {fmtDate(d.delete_after)}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-[#8b93ad]">
                    {d.questions} q{d.last_used_at ? ` · ${fmtRelative(d.last_used_at)}` : ''}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {d.status === 'ready' && (
                      <button onClick={() => openText(d.id)} disabled={opening === d.id}
                        className="text-[#2dd4bf] hover:underline disabled:opacity-50">
                        {opening === d.id ? 'Opening…' : 'Open text'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setOpen(null)}>
          <div className="w-full max-w-3xl max-h-[85vh] overflow-auto rounded-xl border border-white/10 bg-[#0d1225] p-5"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <p className="font-display text-lg font-bold text-[#f0ece4]">{open.title}</p>
                <p className={`font-mono text-[11px] ${TEXT_MUTED}`}>
                  {open.user_email} · {open.filename}{open.doc_type ? ` · ${open.doc_type.replace(/_/g, ' ')}` : ''}
                </p>
                {open.summary && <p className="font-mono text-xs text-[#f0ece4]/70 mt-1">{open.summary}</p>}
              </div>
              <button onClick={() => setOpen(null)} aria-label="Close" className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4]">×</button>
            </div>
            <p className="font-mono text-[11px] text-amber-400/80 mb-3">This viewing is recorded in the audit log.</p>
            {open.sections.map((s, i) => (
              <div key={i} className="mb-4">
                <p className="font-mono text-xs font-bold text-[#2dd4bf] mb-1">{s.section}</p>
                <p className="font-mono text-xs text-[#f0ece4]/85 whitespace-pre-wrap leading-relaxed">{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </Page>
  )
}
