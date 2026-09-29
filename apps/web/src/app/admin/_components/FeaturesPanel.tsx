'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { fmtRelative } from '../_lib/format'

// ── Features tab (Sprint D6.25) ───────────────────────────────────────────
//
// Shows adoption signal for the four under-discovered features (Credentials,
// Compliance Log, PSC Checklist, Vessel Dossier) plus Vessels overall.
// Sourced from /admin/feature-usage — no new instrumentation required, just
// counts off the existing tables.

interface FeatureTotal {
  feature: string
  total_records: number
  distinct_users: number
  last_created_at: string | null
}

interface FeatureUserRow {
  user_id: string
  email: string
  full_name: string | null
  credentials: number
  compliance_logs: number
  psc_checklists: number
  vessels: number
  vessel_documents: number
  // Sprint D6.92 — new feature columns + tier inline
  conversations?: number
  studies?: number
  subscription_tier?: string
  last_activity_at: string | null
}

// Sprint D6.92 — sortable column keys for the Top Users table.
type FeatureUserSortKey =
  | 'email' | 'tier' | 'conversations' | 'studies'
  | 'credentials' | 'compliance_logs' | 'psc_checklists'
  | 'vessels' | 'vessel_documents' | 'last_activity_at'

type SortDir = 'asc' | 'desc'

export function FeaturesTab() {
  const [totals, setTotals] = useState<FeatureTotal[]>([])
  const [users, setUsers] = useState<FeatureUserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [excludeInternal, setExcludeInternal] = useState(true)

  // Sprint D6.92 — sortable Top Users table.
  // Default: server-side ORDER BY (total feature touches DESC). Once
  // the admin clicks a header, switch to client-side sort by that
  // column. Toggling the same header flips direction.
  const [sortKey, setSortKey] = useState<FeatureUserSortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        exclude_internal: String(excludeInternal),
        limit: '50',
      })
      const r = await apiRequest<{ totals: FeatureTotal[]; top_users: FeatureUserRow[] }>(
        `/admin/feature-usage?${params.toString()}`,
      )
      setTotals(r.totals)
      setUsers(r.top_users)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load feature usage')
    } finally {
      setLoading(false)
    }
  }, [excludeInternal])

  useEffect(() => { load() }, [load])

  /** Click handler: same key flips direction, new key resets to desc. */
  function onSort(key: FeatureUserSortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  /** Apply client-side sort when a column has been clicked; otherwise
   *  preserve the server's default ordering. */
  const sortedUsers = useMemo(() => {
    if (!sortKey) return users
    const dir = sortDir === 'asc' ? 1 : -1
    const out = [...users]
    out.sort((a, b) => {
      let av: string | number
      let bv: string | number
      switch (sortKey) {
        case 'email':           av = a.email.toLowerCase(); bv = b.email.toLowerCase(); break
        case 'tier':            av = a.subscription_tier ?? ''; bv = b.subscription_tier ?? ''; break
        case 'conversations':   av = a.conversations ?? 0; bv = b.conversations ?? 0; break
        case 'studies':         av = a.studies ?? 0; bv = b.studies ?? 0; break
        case 'credentials':     av = a.credentials; bv = b.credentials; break
        case 'compliance_logs': av = a.compliance_logs; bv = b.compliance_logs; break
        case 'psc_checklists':  av = a.psc_checklists; bv = b.psc_checklists; break
        case 'vessels':         av = a.vessels; bv = b.vessels; break
        case 'vessel_documents': av = a.vessel_documents; bv = b.vessel_documents; break
        case 'last_activity_at':
          av = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0
          bv = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0
          break
      }
      if (av < bv) return -1 * dir
      if (av > bv) return  1 * dir
      return 0
    })
    return out
  }, [users, sortKey, sortDir])

  /** Sort-header indicator arrow. */
  function SortHeader({ label, k, right }: { label: string; k: FeatureUserSortKey; right?: boolean }) {
    const active = sortKey === k
    const arrow = active ? (sortDir === 'asc' ? '▲' : '▼') : ''
    return (
      <th
        className={`${right ? 'text-right' : 'text-left'} px-3 py-2 cursor-pointer hover:text-[#f0ece4] transition-colors select-none`}
        onClick={() => onSort(k)}
        title={`Sort by ${label.toLowerCase()}`}
      >
        {label} {arrow && <span className="text-[#2dd4bf]">{arrow}</span>}
      </th>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="font-mono text-xs text-[#6b7594]">
          Counts straight off each feature's table. Use this to gauge whether the
          feature highlight cards on /welcome are nudging adoption over time.
        </p>
        <label className="flex items-center gap-1 text-xs font-mono whitespace-nowrap">
          <input
            type="checkbox"
            checked={excludeInternal}
            onChange={(e) => setExcludeInternal(e.target.checked)}
          />
          Exclude internal
        </label>
      </div>

      {error && (
        <div className="bg-[#111827] rounded-xl border border-red-500/30 px-4 py-3 mb-4">
          <p className="font-mono text-xs text-red-400">{error}</p>
        </div>
      )}

      {/* Per-feature totals */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
        {loading && totals.length === 0
          ? Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3 h-[88px] animate-pulse" />
            ))
          : totals.map((t) => (
              <div key={t.feature} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594] truncate">
                  {t.feature}
                </p>
                <p className="font-display text-2xl font-bold text-[#f0ece4] mt-1">
                  {t.total_records}
                </p>
                <p className="font-mono text-[10px] text-[#6b7594] mt-1">
                  {t.distinct_users} {t.distinct_users === 1 ? 'user' : 'users'}
                  {t.last_created_at && (
                    <> · last {fmtRelative(t.last_created_at)}</>
                  )}
                </p>
              </div>
            ))}
      </div>

      {/* Per-user breakdown — Sprint D6.92 sortable columns + new
          feature columns (Conversations, Studies, Tier). Click any
          header to sort by it; click again to flip direction. */}
      <h3 className="font-mono text-xs uppercase tracking-wider text-[#6b7594] mb-2">
        Top users (any feature)
      </h3>
      <div className="bg-[#111827] rounded-xl border border-white/8 overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="bg-[#0d1224] text-[#6b7594]">
              <SortHeader label="User"     k="email" />
              <SortHeader label="Tier"     k="tier" />
              <SortHeader label="Convos"   k="conversations" right />
              <SortHeader label="Studies"  k="studies" right />
              <SortHeader label="Creds"    k="credentials" right />
              <SortHeader label="Logs"     k="compliance_logs" right />
              <SortHeader label="PSC"      k="psc_checklists" right />
              <SortHeader label="Vessels"  k="vessels" right />
              <SortHeader label="Docs"     k="vessel_documents" right />
              <SortHeader label="Last activity" k="last_activity_at" />
            </tr>
          </thead>
          <tbody>
            {loading && users.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-6 text-center text-[#6b7594]">Loading…</td></tr>
            )}
            {!loading && users.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-6 text-center text-[#6b7594]">No users have engaged any feature yet.</td></tr>
            )}
            {sortedUsers.map((u) => (
              <tr key={u.user_id} className="border-t border-white/5 hover:bg-white/[0.02]">
                <td className="px-3 py-2">
                  <div className="text-[#f0ece4] truncate max-w-[240px]">{u.email}</div>
                  {u.full_name && <div className="text-[#6b7594] truncate max-w-[240px]">{u.full_name}</div>}
                </td>
                <td className="px-3 py-2">
                  {u.subscription_tier && u.subscription_tier !== 'free' ? (
                    <span className="inline-block text-[9px] font-bold uppercase tracking-wider
                      px-1.5 py-0.5 rounded border border-[#2dd4bf]/30 text-[#2dd4bf] bg-[#2dd4bf]/5">
                      {u.subscription_tier}
                    </span>
                  ) : (
                    <span className="text-[#6b7594]">—</span>
                  )}
                </td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.conversations || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.studies || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.credentials || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.compliance_logs || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.psc_checklists || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.vessels || '—'}</td>
                <td className="text-right px-3 py-2 text-[#f0ece4]">{u.vessel_documents || '—'}</td>
                <td className="px-3 py-2 text-[#6b7594]">{fmtRelative(u.last_activity_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
