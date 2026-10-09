'use client'

// 2026-10-08 — answer pipeline phase 2 (apps/api/app/routers/admin_gaps.py):
// what the coverage check found missing from the library, whether the web
// research found it, and what the ingest task did. Replaces hedge audits as
// the working list: a found-but-skipped item is a source to add by hand; an
// ingested document can be removed here if it shouldn't be in the library.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useAdmin } from '../_lib/AdminContext'
import { fmtDate } from '../_lib/format'
import { Empty, Page, Pill, Skeleton, TEXT_MUTED } from '../_components/ui'

interface GapSource {
  label?: string
  url: string
  title: string
  publisher?: string
  domain: string
  quote?: string
  verified: boolean
}

interface CorpusGap {
  id: string
  created_at: string
  user_email: string | null
  question: string
  item: string
  search_query: string | null
  coverage: string | null
  web_searched: boolean
  found: boolean
  answer: string | null
  sources: GapSource[]
  status: string
  ingest_note: string | null
  ingested_section: string | null
  ingest_url: string | null
  latency_ms: number | null
}

interface GapSummary {
  gaps: CorpusGap[]
  counts: Record<string, number>
  web_ingest_documents: number
}

const STATUS_TONE: Record<string, 'teal' | 'amber' | 'gray' | 'red'> = {
  ingested: 'teal', found: 'amber', ingest_queued: 'amber', not_found: 'gray', open: 'gray',
  ingest_skipped: 'gray', ingest_failed: 'red', dismissed: 'gray',
}
const STATUSES = ['all', 'found', 'ingested', 'ingest_skipped', 'not_found', 'ingest_failed', 'dismissed']

export default function CorpusGapsPage() {
  const { ei } = useAdmin()
  const [data, setData] = useState<GapSummary | null>(null)
  const [filter, setFilter] = useState('all')
  const [busy, setBusy] = useState<string | null>(null)

  function load() {
    setData(null)
    const st = filter === 'all' ? '' : `&status=${filter}`
    apiRequest<GapSummary>(`/admin/corpus-gaps?exclude_internal=${ei}${st}`)
      .then(setData)
      .catch(() => setData({ gaps: [], counts: {}, web_ingest_documents: 0 }))
  }
  useEffect(load, [ei, filter]) // eslint-disable-line react-hooks/exhaustive-deps

  async function dismiss(id: string) {
    setBusy(id)
    try { await apiRequest(`/admin/corpus-gaps/${id}/dismiss`, { method: 'POST' }); load() }
    catch { alert('Could not dismiss this gap.') }
    finally { setBusy(null) }
  }

  async function removeDoc(section: string, id: string) {
    if (!confirm(`Remove "${section}" from the library? Answers stop citing it immediately.`)) return
    setBusy(id)
    try { await apiRequest(`/admin/web-ingest?section=${encodeURIComponent(section)}`, { method: 'DELETE' }); load() }
    catch { alert('Could not remove this document.') }
    finally { setBusy(null) }
  }

  const counts = data?.counts ?? {}
  return (
    <Page
      title="Corpus gaps"
      description="Facts the coverage check found missing from the library before an answer was written, what the web research found on official sites, and what the ingest task added. Found-but-skipped items are sources to add by hand."
    >
      <div className="flex flex-wrap items-center gap-2 mb-4 font-mono text-xs">
        {STATUSES.map(s => (
          <button key={s} onClick={() => setFilter(s)}
            className={`px-2.5 py-1 rounded-md border ${filter === s ? 'border-teal/60 text-[#2dd4bf]' : 'border-white/10 text-[#8b93ad] hover:text-[#f0ece4]'}`}>
            {s.replace(/_/g, ' ')}{s !== 'all' && counts[s] ? ` · ${counts[s]}` : ''}
          </button>
        ))}
        {data && <span className={`ml-auto ${TEXT_MUTED}`}>{data.web_ingest_documents} documents added from the web</span>}
      </div>

      {!data ? <Skeleton className="h-[160px]" /> : data.gaps.length === 0 ? (
        <Empty>No gaps yet.</Empty>
      ) : (
        <div className="space-y-2">
          {data.gaps.map(g => (
            <div key={g.id} className="rounded-xl border border-white/8 bg-[#111827] p-3 font-mono text-xs">
              <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <Pill tone={STATUS_TONE[g.status] ?? 'gray'}>{g.status.replace(/_/g, ' ')}</Pill>
                {g.coverage && <span className={TEXT_MUTED}>coverage {g.coverage}</span>}
                <span className={TEXT_MUTED}>{fmtDate(g.created_at)} · {g.user_email ?? 'deleted user'}</span>
                {g.latency_ms != null && <span className={TEXT_MUTED}>{(g.latency_ms / 1000).toFixed(1)} s</span>}
              </div>
              <p className="text-[#f0ece4]/90"><span className={TEXT_MUTED}>Missing:</span> {g.item}</p>
              <p className="text-[#f0ece4]/60 mt-0.5"><span className={TEXT_MUTED}>Question:</span> {g.question}</p>
              {g.answer && <p className="text-[#f0ece4]/75 mt-1.5">{g.answer}</p>}
              {g.sources.length > 0 && (
                <ul className="mt-1.5 space-y-0.5">
                  {g.sources.map((s, i) => (
                    <li key={i}>
                      <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">
                        {s.domain}: {s.title}
                      </a>
                      <span className={TEXT_MUTED}>{s.verified ? ' · quote verified' : ' · quote not matched'}</span>
                    </li>
                  ))}
                </ul>
              )}
              {(g.ingest_note || g.ingested_section) && (
                <p className="mt-1.5 text-[#f0ece4]/70">
                  {g.ingested_section && <span className="text-[#2dd4bf]">{g.ingested_section}</span>}
                  {g.ingested_section && g.ingest_note ? ' · ' : ''}{g.ingest_note}
                </p>
              )}
              <div className="flex gap-3 mt-2">
                {g.status !== 'dismissed' && g.status !== 'ingested' && (
                  <button onClick={() => dismiss(g.id)} disabled={busy === g.id}
                    className="text-[#8b93ad] hover:text-[#f0ece4] disabled:opacity-50">Dismiss</button>
                )}
                {g.status === 'ingested' && g.ingested_section && (
                  <button onClick={() => removeDoc(g.ingested_section as string, g.id)} disabled={busy === g.id}
                    className="text-red-400 hover:text-red-300 disabled:opacity-50">Remove from library</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Page>
  )
}
