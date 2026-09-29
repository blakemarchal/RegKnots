'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

// ── Data tab: universal table browser ────────────────────────────────────────

interface TableInfo { name: string; columns: string[] }
interface TableRowsResponse {
  name: string
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  limit: number
  offset: number
}

export function DataTab() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('users')
  const [data, setData] = useState<TableRowsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [userIdFilter, setUserIdFilter] = useState('')
  const [vesselIdFilter, setVesselIdFilter] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [expandedRow, setExpandedRow] = useState<number | null>(null)
  // Sprint D6.92 — toggle to hide ID columns. UUID columns eat ~36
  // chars of width each and rarely carry signal in a quick scan;
  // hide-by-default-but-toggleable lets the admin see content
  // without scrolling sideways.
  const [hideIds, setHideIds] = useState(true)
  const limit = 50

  useEffect(() => {
    apiRequest<TableInfo[]>('/admin/data/tables')
      .then(setTables)
      .catch(() => setError('Failed to load tables'))
  }, [])

  const fetchData = useCallback(async () => {
    if (!selectedTable) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      })
      if (userIdFilter.trim()) params.set('user_id', userIdFilter.trim())
      if (vesselIdFilter.trim()) params.set('vessel_id', vesselIdFilter.trim())
      if (search.trim()) params.set('search', search.trim())
      const result = await apiRequest<TableRowsResponse>(
        `/admin/data/table/${selectedTable}?${params}`,
      )
      setData(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load data')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [selectedTable, offset, userIdFilter, vesselIdFilter, search])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  function handleTableChange(name: string) {
    setSelectedTable(name)
    setOffset(0)
    setExpandedRow(null)
  }

  function downloadJson() {
    if (!data) return
    const blob = new Blob([JSON.stringify(data.rows, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${data.name}_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mb-8 flex flex-col gap-4">
      {/* Controls */}
      <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <label className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">Table</label>
          <select
            value={selectedTable}
            onChange={(e) => handleTableChange(e.target.value)}
            className="font-mono text-xs border border-white/10 rounded-lg px-3 py-1.5
              outline-none focus:border-[#2dd4bf] transition-colors"
            style={{ backgroundColor: '#0d1225', color: '#f0ece4' }}
          >
            {tables.map((t) => (
              <option key={t.name} value={t.name} style={{ backgroundColor: '#111827' }}>
                {t.name}
              </option>
            ))}
          </select>
          {data && (
            <span className="font-mono text-[10px] text-[#6b7594] ml-2">
              {data.total} total
            </span>
          )}
          <button
            onClick={fetchData}
            className="font-mono text-[10px] text-[#2dd4bf] hover:underline ml-auto"
          >
            Refresh
          </button>
          <button
            onClick={downloadJson}
            disabled={!data}
            className="font-mono text-[10px] text-[#2dd4bf] hover:underline disabled:opacity-40"
          >
            Export JSON
          </button>
          {/* Sprint D6.92 — Hide IDs toggle. Filters columns named
              `id` or ending in `_id` from the rendered table. The
              expanded-row JSON view always shows everything. */}
          <label className="flex items-center gap-1.5 font-mono text-[10px] text-[#6b7594] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={hideIds}
              onChange={(e) => setHideIds(e.target.checked)}
              className="accent-[#2dd4bf]"
            />
            Hide IDs
          </label>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <input
            value={userIdFilter}
            onChange={(e) => { setUserIdFilter(e.target.value); setOffset(0) }}
            placeholder="Filter: user_id (UUID)"
            className="font-mono text-xs bg-[#0d1225] border border-white/10 rounded-lg px-3 py-1.5
              text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors flex-1 min-w-[200px]"
          />
          <input
            value={vesselIdFilter}
            onChange={(e) => { setVesselIdFilter(e.target.value); setOffset(0) }}
            placeholder="Filter: vessel_id (UUID)"
            className="font-mono text-xs bg-[#0d1225] border border-white/10 rounded-lg px-3 py-1.5
              text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors flex-1 min-w-[200px]"
          />
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setOffset(0) }}
            placeholder="Search text columns"
            className="font-mono text-xs bg-[#0d1225] border border-white/10 rounded-lg px-3 py-1.5
              text-[#f0ece4] outline-none focus:border-[#2dd4bf] transition-colors flex-1 min-w-[200px]"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3">
          <p className="font-mono text-xs text-red-400">{error}</p>
        </div>
      )}

      {loading && !data && (
        <div className="bg-[#111827] rounded-xl border border-white/8 h-32 animate-pulse" />
      )}

      {/* Rows — Sprint D6.92: columns filtered when Hide IDs is on.
          The expanded-row JSON view always shows ALL columns regardless
          of the toggle, so no data is hidden — just collapsed from the
          condensed scan view. */}
      {data && (() => {
        const visibleColumns = hideIds
          ? data.columns.filter(c => c !== 'id' && !c.endsWith('_id'))
          : data.columns
        return (
        <div className="bg-[#111827] rounded-xl border border-white/8 overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="border-b border-white/8">
                {visibleColumns.map((c) => (
                  <th key={c} className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-[#6b7594] whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={visibleColumns.length} className="px-3 py-6 text-center text-[#6b7594]">
                    No rows
                  </td>
                </tr>
              )}
              {data.rows.map((row, idx) => {
                const isExpanded = expandedRow === idx
                return (
                  <>
                    <tr
                      key={idx}
                      onClick={() => setExpandedRow(isExpanded ? null : idx)}
                      className="border-b border-white/5 hover:bg-white/2 cursor-pointer transition-colors"
                    >
                      {visibleColumns.map((c) => {
                        const v = row[c]
                        const display =
                          v === null || v === undefined
                            ? <span className="text-[#6b7594]/50">—</span>
                            : typeof v === 'object'
                              ? <span className="text-[#2dd4bf]/70">{'{…}'}</span>
                              : String(v).length > 40
                                ? String(v).slice(0, 38) + '…'
                                : String(v)
                        return (
                          <td key={c} className="px-3 py-2 text-[#f0ece4]/80 whitespace-nowrap">
                            {display}
                          </td>
                        )
                      })}
                    </tr>
                    {isExpanded && (
                      <tr key={`${idx}-detail`} className="bg-[#0d1225]">
                        <td colSpan={visibleColumns.length} className="px-3 py-3">
                          <pre className="font-mono text-[10px] text-[#f0ece4]/80 whitespace-pre-wrap break-all">
                            {JSON.stringify(row, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )})()}

      {/* Pagination */}
      {data && data.total > limit && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="font-mono text-xs text-[#2dd4bf] hover:underline disabled:opacity-40"
          >
            ← Previous
          </button>
          <p className="font-mono text-[10px] text-[#6b7594]">
            Rows {offset + 1}–{Math.min(offset + limit, data.total)} of {data.total}
          </p>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= data.total}
            className="font-mono text-xs text-[#2dd4bf] hover:underline disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}
