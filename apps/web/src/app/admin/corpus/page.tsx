'use client'

// 2026-09-29 — the knowledge base by source (was the last card on the old
// Overview, collapsed to the top 12).

import { useMemo, useState } from 'react'
import { useAdmin } from '../_lib/AdminContext'
import { Card, MeterBar, Page, Skeleton, TEXT_MUTED } from '../_components/ui'

export default function AdminCorpusPage() {
  const { stats } = useAdmin()
  const [q, setQ] = useState('')
  const sorted = useMemo(
    () => Object.entries(stats?.chunks_by_source ?? {}).sort((a, b) => b[1] - a[1]),
    [stats],
  )
  const shown = sorted.filter(([s]) => s.toLowerCase().includes(q.trim().toLowerCase()))
  const max = sorted[0]?.[1] ?? 1

  return (
    <Page
      title="Corpus"
      description={stats ? `${stats.total_chunks.toLocaleString()} passages from ${sorted.length} sources. docs/corpus-status.md has what each source covers.` : 'Loading…'}
    >
      {!stats ? <Skeleton className="h-[400px]" /> : (
        <Card
          title="Passages by source"
          action={
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter sources…"
              aria-label="Filter sources"
              className="bg-[#0a0e1a] border border-white/10 rounded-lg px-3 py-1.5 font-mono text-xs text-[#f0ece4] placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40 w-44"
            />
          }
        >
          <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5">
            {shown.map(([source, n]) => (
              <li key={source} className="min-w-0">
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="font-mono text-xs text-[#2dd4bf]/90 truncate" title={source}>{source}</span>
                  <span className="font-mono text-xs text-[#f0ece4]/75 tabular-nums">{n.toLocaleString()}</span>
                </div>
                <MeterBar value={n} max={max} />
              </li>
            ))}
          </ul>
          {shown.length === 0 && <p className={`font-mono text-xs ${TEXT_MUTED} py-6 text-center`}>No source matches “{q}”.</p>}
        </Card>
      )}
    </Page>
  )
}
