'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { fmtRelative } from '../_lib/format'

// ── Audit log section ────────────────────────────────────────────────────────

interface AuditEntry {
  id: string
  admin_email: string
  action: string
  target_id: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export function AuditLogSection() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiRequest<AuditEntry[]>('/admin/audit-log?limit=100')
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="mb-8">
      {loading ? (
        <div className="bg-[#111827] rounded-xl border border-white/8 h-[72px] animate-pulse" />
      ) : entries.length === 0 ? (
        <div className="bg-[#111827] rounded-xl border border-white/8 px-4 py-4 text-center">
          <p className="font-mono text-sm text-[#6b7594]">No admin actions recorded yet</p>
        </div>
      ) : (
        <div className="rounded-xl border border-white/8 overflow-auto max-h-[320px]">
          <table className="w-full text-left font-mono text-xs" style={{ minWidth: '600px' }}>
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#111827] text-[#6b7594]">
                <th className="px-3 py-2.5 font-medium bg-[#111827]">Time</th>
                <th className="px-3 py-2.5 font-medium bg-[#111827]">Admin</th>
                <th className="px-3 py-2.5 font-medium bg-[#111827]">Action</th>
                <th className="px-3 py-2.5 font-medium bg-[#111827]">Target</th>
                <th className="px-3 py-2.5 font-medium bg-[#111827]">Details</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={e.id} className={`border-t border-white/5 ${i % 2 === 0 ? 'bg-[#111827]' : 'bg-[#0f1629]'}`}>
                  <td className="px-3 py-2 text-[#6b7594] whitespace-nowrap">{fmtRelative(e.created_at)}</td>
                  <td className="px-3 py-2 text-[#f0ece4]/80">{e.admin_email.split('@')[0]}</td>
                  <td className="px-3 py-2">
                    <span className="text-[#2dd4bf] font-bold">{e.action}</span>
                  </td>
                  <td className="px-3 py-2 text-[#f0ece4]/60 truncate max-w-[120px]">{e.target_id ?? '—'}</td>
                  <td className="px-3 py-2 text-[#6b7594] truncate max-w-[200px]">
                    {e.details ? JSON.stringify(e.details) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
