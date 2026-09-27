'use client'

// 2026-09-27 — company documents in fleet chat. The fleet's own SMS / TSMS
// manual and procedures: workspace chats answer from them alongside the
// regulations and cite them as [Company: <title> §<section>]. Backed by
// /workspaces/{id}/documents (app/routers/company_documents.py).

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest, apiUpload, ApiError } from '@/lib/api'

interface CompanyDocument {
  id: string
  title: string
  filename: string
  mime_type: string
  size_bytes: number
  pages: number | null
  chunk_count: number
  status: 'pending' | 'ready' | 'failed'
  error: string | null
  created_at: string
}

interface Props {
  workspaceId: string
  /** Owners and admins upload and delete. */
  canManage: boolean
  /** Uploads need a trialing or active workspace. */
  writable: boolean
}

function size(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export function CompanyDocuments({ workspaceId, canManage, writable }: Props) {
  const [docs, setDocs] = useState<CompanyDocument[] | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    apiRequest<CompanyDocument[]>(`/workspaces/${workspaceId}/documents`)
      .then(setDocs)
      .catch(() => setDocs([]))
  }, [workspaceId])

  useEffect(() => { load() }, [load])

  // Poll while anything is still processing.
  useEffect(() => {
    if (!docs?.some((d) => d.status === 'pending')) return
    const t = setTimeout(load, 5000)
    return () => clearTimeout(t)
  }, [docs, load])

  async function upload(file: File) {
    setError(null)
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      await apiUpload(`/workspaces/${workspaceId}/documents`, form)
      load()
    } catch (e) {
      const detail = e instanceof ApiError && typeof e.body === 'object' && e.body && 'detail' in e.body
        ? String((e.body as { detail: unknown }).detail)
        : 'Upload failed. Try again.'
      setError(detail)
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function remove(doc: CompanyDocument) {
    if (!window.confirm(`Delete "${doc.title}"? Chats will stop citing it.`)) return
    try {
      await apiRequest(`/workspaces/${workspaceId}/documents/${doc.id}`, { method: 'DELETE' })
      load()
    } catch {
      setError('Could not delete the document. Try again.')
    }
  }

  return (
    <section className="mb-8 rounded-lg border border-white/8 p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h2 className="text-sm font-mono uppercase tracking-wider text-[#6b7594]">Company documents</h2>
          <p className="text-xs text-[#f0ece4]/60 mt-1 leading-relaxed max-w-prose">
            Your SMS or TSMS manual and procedures. Chats in this workspace answer from them alongside the
            regulations, cite them as <span className="font-mono text-[#c4b5fd]">[Company: …]</span>, and say
            where a procedure is stricter than or differs from the regulation.
          </p>
        </div>
        {canManage && writable && (
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="flex-shrink-0 px-3 py-1.5 rounded-md text-xs font-mono font-bold border border-[#2dd4bf]/40
              text-[#2dd4bf] bg-[#2dd4bf]/10 hover:bg-[#2dd4bf]/20 disabled:opacity-50 transition-colors"
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }}
        />
      </div>

      {error && <p className="text-xs text-amber-300 mb-2">{error}</p>}

      {docs === null ? (
        <p className="text-xs text-[#6b7594] font-mono">Loading…</p>
      ) : docs.length === 0 ? (
        <p className="text-xs text-[#6b7594] font-mono">
          {canManage
            ? 'No documents yet. PDF with text, Word (.docx), .txt or .md, up to 25 MB each.'
            : 'No documents yet. An owner or admin can upload them.'}
        </p>
      ) : (
        <ul className="divide-y divide-white/5">
          {docs.map((d) => (
            <li key={d.id} className="py-2.5 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-[#f0ece4] truncate">{d.title}</p>
                <p className="text-[11px] font-mono text-[#6b7594] truncate">
                  {d.filename} · {size(d.size_bytes)}
                  {d.status === 'ready' && ` · ready, ${d.chunk_count} passages${d.pages ? `, ${d.pages} pages` : ''}`}
                  {d.status === 'pending' && ' · processing…'}
                </p>
                {d.status === 'failed' && d.error && (
                  <p className="text-[11px] text-amber-300 mt-0.5">{d.error}</p>
                )}
              </div>
              {canManage && (
                <button
                  onClick={() => remove(d)}
                  className="flex-shrink-0 text-[11px] font-mono text-[#6b7594] hover:text-red-300 transition-colors"
                  aria-label={`Delete ${d.title}`}
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
