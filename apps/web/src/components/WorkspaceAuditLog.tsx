'use client'

// 2026-07-19 Wk4 — team audit log. "Who asked what, when, and what did
// the system answer" for a workspace: the internal-QA + show-the-auditor
// record an enterprise compliance department expects. Backed by
// GET /workspaces/{id}/audit-log (JSON here; CSV via the export button).

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { apiDownload, apiRequest } from '@/lib/api'

interface AuditEntry {
  conversation_id: string
  conversation_title: string | null
  asked_by: string
  asked_at: string
  question: string
  answer_preview: string | null
  citations: string[]
}

interface AuditLogResponse {
  workspace_id: string
  total: number
  limit: number
  offset: number
  entries: AuditEntry[]
}

interface Props {
  workspaceId: string
}

export function WorkspaceAuditLog({ workspaceId }: Props) {
  const [data, setData] = useState<AuditLogResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiRequest<AuditLogResponse>(`/workspaces/${workspaceId}/audit-log?limit=50`)
      .then((r) => { if (!cancelled) setData(r) })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load audit log')
      })
    return () => { cancelled = true }
  }, [workspaceId])

  async function exportCsv() {
    if (exporting) return
    setExporting(true)
    try {
      await apiDownload(
        `/workspaces/${workspaceId}/audit-log?limit=500&format=csv`,
        `regknots-audit-log-${new Date().toISOString().slice(0, 10)}.csv`,
      )
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Export failed.')
    } finally {
      setExporting(false)
    }
  }

  if (error) return null // non-essential surface — fail silent on the page
  if (!data) return null
  if (data.total === 0) return null // nothing to show until the team chats

  const shown = expanded ? data.entries : data.entries.slice(0, 5)

  return (
    <section className="mb-6 rounded-md border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div>
          <h2 className="text-sm font-semibold text-[#f0ece4]">Team activity log</h2>
          <p className="text-xs text-[#8a94ad]">
            {data.total} question{data.total === 1 ? '' : 's'} asked in this workspace.
            Every entry records who asked, when, and the citations behind the answer.
          </p>
        </div>
        <button
          onClick={() => void exportCsv()}
          disabled={exporting}
          className="px-2.5 py-1 rounded-md border border-white/10 text-xs font-medium
                     text-[#f0ece4]/80 hover:bg-white/5 transition-colors
                     disabled:opacity-50 whitespace-nowrap"
        >
          {exporting ? 'Exporting…' : '⤓ Export CSV'}
        </button>
      </div>

      <div className="space-y-2">
        {shown.map((e, i) => (
          <div key={`${e.conversation_id}-${i}`} className="rounded border border-white/8 bg-[#0a0e1a]/40 px-3 py-2">
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <span className="text-xs font-medium text-[#f0ece4]/90 break-words">
                {e.question.length > 140 ? `${e.question.slice(0, 140)}…` : e.question}
              </span>
              <span className="text-[10px] text-[#8a94ad] font-mono whitespace-nowrap">
                {e.asked_by} · {new Date(e.asked_at).toLocaleString([], {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                })}
              </span>
            </div>
            {e.citations.length > 0 && (
              <div className="mt-1 text-[10px] font-mono text-[#2dd4bf]/80 break-words">
                {e.citations.slice(0, 4).join(' · ')}
                {e.citations.length > 4 ? ` · +${e.citations.length - 4} more` : ''}
              </div>
            )}
            <Link
              href={`/history?workspace=${workspaceId}`}
              className="text-[10px] text-[#8a94ad] hover:text-[#2dd4bf] transition-colors"
            >
              View conversation →
            </Link>
          </div>
        ))}
      </div>

      {data.entries.length > 5 && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-xs text-[#2dd4bf] hover:underline"
        >
          {expanded ? 'Show fewer' : `Show all ${data.entries.length} loaded`}
        </button>
      )}
    </section>
  )
}
