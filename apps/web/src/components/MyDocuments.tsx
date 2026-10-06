'use client'

// 2026-10-05 — "My documents" on the account page: the PDF and Word files a
// user attached in chat (apps/api/app/user_docs.py). Maritime documents are
// kept so later answers can use them; anything else is deleted 7 days after
// upload. Kept documents are capped by plan (3 free / trial, 20 paid).

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

export interface UserDocumentDTO {
  id: string
  title: string
  filename: string
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
}

interface DocumentsList {
  documents: UserDocumentDTO[]
  kept_count: number
  keep_limit: number
}

const TYPE_LABELS: Record<string, string> = {
  sms_manual: 'SMS manual',
  procedure: 'Procedure',
  checklist: 'Checklist',
  certificate: 'Certificate',
  form: 'Form',
  correspondence: 'Letter or notice',
  regulation_copy: 'Regulation copy',
  plan_or_drawing: 'Plan or drawing',
  logbook_or_record: 'Log or record',
  other: 'Other',
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function statusLine(d: UserDocumentDTO): string {
  if (d.status === 'pending') return 'Reading…'
  if (d.status === 'failed') return d.error ?? "Couldn't read this file"
  if (d.kept) return 'Saved: answers can use it'
  return d.delete_after ? `Not maritime: deleted ${day(d.delete_after)}` : 'Not saved'
}

export function MyDocuments() {
  const [data, setData] = useState<DocumentsList | null>(null)
  const [failed, setFailed] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  const load = useCallback(() => {
    apiRequest<DocumentsList>('/me/documents')
      .then(d => { setData(d); setFailed(false) })
      .catch(() => setFailed(true))
  }, [])

  useEffect(() => { load() }, [load])

  async function remove(id: string) {
    setDeleting(id)
    try {
      await apiRequest(`/me/documents/${id}`, { method: 'DELETE' })
      setConfirming(null)
      load()
    } catch {
      setFailed(true)
    } finally {
      setDeleting(null)
    }
  }

  return (
    <section className="bg-[#111827] border border-white/8 rounded-xl p-5 flex flex-col gap-3">
      <p className="font-mono text-xs text-[#6b7594] uppercase tracking-wider">My Documents</p>
      <p className="font-mono text-xs text-[#f0ece4]/60 leading-relaxed">
        PDF and Word files you attach in chat. Maritime documents are saved so later answers can
        use them; anything else is deleted 7 days after upload. No other user can see them.
      </p>
      {failed && <p className="font-mono text-xs text-red-400">Couldn&apos;t load your documents. Try again later.</p>}
      {data && (
        <>
          <p className="font-mono text-xs text-[#f0ece4]/80">
            {data.kept_count} of {data.keep_limit} saved
            {data.keep_limit < 20 && <span className="text-[#6b7594]"> · paid plans keep 20</span>}
          </p>
          {data.documents.length === 0 ? (
            <p className="font-mono text-xs text-[#6b7594]">
              None yet. Use the paperclip in chat to attach a manual or procedure.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {data.documents.map(d => (
                <li key={d.id} className="rounded-lg border border-white/8 bg-[#0d1225] px-3 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-sm text-[#f0ece4] truncate">{d.title}</p>
                      <p className="font-mono text-[11px] text-[#6b7594]">
                        {d.mime_type.includes('pdf') ? 'PDF' : 'Word'}
                        {d.pages ? ` · ${d.pages} pages` : ''}
                        {d.doc_type ? ` · ${TYPE_LABELS[d.doc_type] ?? d.doc_type}` : ''}
                        {` · ${day(d.created_at)}`}
                      </p>
                      <p className={`font-mono text-[11px] mt-0.5 ${d.status === 'failed' ? 'text-red-400' : d.kept ? 'text-[#2dd4bf]' : 'text-[#6b7594]'}`}>
                        {statusLine(d)}
                      </p>
                    </div>
                    {confirming === d.id ? (
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => remove(d.id)}
                          disabled={deleting === d.id}
                          className="font-mono text-xs font-bold text-red-400 hover:underline disabled:opacity-50"
                        >
                          {deleting === d.id ? 'Deleting…' : 'Delete'}
                        </button>
                        <button onClick={() => setConfirming(null)} className="font-mono text-xs text-[#6b7594] hover:underline">
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirming(d.id)}
                        aria-label={`Delete ${d.title}`}
                        className="font-mono text-xs text-[#6b7594] hover:text-red-400 shrink-0"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
