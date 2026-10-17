'use client'

// 2026-10-16 — the salesperson's lead tracker: the imported towing-company list
// plus anything they add, with a status, a next step and notes. Lookup searches
// what we already hold on a company (vessel counts from the Coast Guard records).

import { useCallback, useEffect, useState } from 'react'
import { apiDownload, apiRequest } from '@/lib/api'
import { useEscapeKey } from '@/lib/useEscapeKey'
import { useSales } from '../_lib/context'

interface Lead {
  id: string; lead_ref: string | null; company: string; dba: string | null; city: string | null; state: string | null
  phone: string | null; website: string | null; contact_name: string | null; contact_role: string | null; contact_email: string | null
  towboats: number | null; tugs: number | null; passenger: number | null; osv: number | null; service: string | null
  commodities: string | null; area: string | null; source: string | null; status: string; next_step: string | null
  next_step_at: string | null; notes: string | null; created_at: string; updated_at: string
}
type Status = 'new' | 'contacted' | 'demo' | 'trial' | 'paying' | 'lost'
const STATUSES: { value: Status | 'all'; label: string }[] = [
  { value: 'all', label: 'All' }, { value: 'new', label: 'New' }, { value: 'contacted', label: 'Contacted' },
  { value: 'demo', label: 'Demo' }, { value: 'trial', label: 'Trial' }, { value: 'paying', label: 'Paying' }, { value: 'lost', label: 'Lost' },
]
const TONE: Record<string, string> = {
  new: 'bg-white/10 text-[#f0ece4]/80', contacted: 'bg-sky-950/60 text-sky-300', demo: 'bg-violet-950/60 text-violet-300',
  trial: 'bg-amber-950/60 text-amber-300', paying: 'bg-emerald-950/60 text-emerald-300', lost: 'bg-white/5 text-[#6b7594]',
}
const EMPTY: Partial<Lead> = { company: '', city: '', state: '', phone: '', contact_name: '', contact_role: '', contact_email: '', status: 'new', next_step: '', next_step_at: null, notes: '' }

function boats(l: Lead): string {
  const parts = [l.towboats ? `${l.towboats} towboat${l.towboats === 1 ? '' : 's'}` : '', l.tugs ? `${l.tugs} tug${l.tugs === 1 ? '' : 's'}` : '',
    l.osv ? `${l.osv} OSV` : '', l.passenger ? `${l.passenger} passenger` : ''].filter(Boolean)
  return parts.join(', ')
}
function due(l: Lead): string {
  if (!l.next_step_at) return ''
  const d = new Date(l.next_step_at + 'T00:00:00')
  const days = Math.round((d.getTime() - Date.now()) / 86400000)
  return days < 0 ? `${-days}d overdue` : days === 0 ? 'today' : `in ${days}d`
}

export default function SalesLeads() {
  const { me, codeQuery } = useSales()
  const [rows, setRows] = useState<Lead[] | null>(null)
  const [status, setStatus] = useState<Status | 'all'>('all')
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<Partial<Lead> | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEscapeKey(editing !== null, () => setEditing(null))

  const sep = codeQuery ? '&' : '?'
  const load = useCallback(() => {
    if (!me) return
    const qs = `${codeQuery}${sep}${status === 'all' ? '' : `status=${status}&`}${q ? `q=${encodeURIComponent(q)}` : ''}`
    apiRequest<Lead[]>(`/sales/leads${qs}`).then(setRows).catch(() => setRows([]))
  }, [me, codeQuery, sep, status, q])
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t) }, [load])

  async function save() {
    if (!editing?.company?.trim()) { setError('Company is required.'); return }
    setSaving(true)
    setError(null)
    const body: Record<string, unknown> = {}
    for (const k of ['company', 'dba', 'city', 'state', 'phone', 'website', 'contact_name', 'contact_role', 'contact_email', 'service', 'area', 'status', 'next_step', 'next_step_at', 'notes'] as const) {
      const v = editing[k]
      body[k] = typeof v === 'string' ? (v.trim() || null) : (v ?? null)
    }
    for (const k of ['towboats', 'tugs', 'passenger', 'osv'] as const) body[k] = editing[k] ?? null
    if (body.status === null) body.status = 'new'
    try {
      if (editing.id) {
        await apiRequest(`/sales/leads/${editing.id}${codeQuery}`, { method: 'PATCH', body: JSON.stringify(body) })
      } else {
        await apiRequest(`/sales/leads${codeQuery}`, { method: 'POST', body: JSON.stringify(body) })
      }
      setEditing(null)
      load()
    } catch {
      setError('Could not save.')
    } finally {
      setSaving(false)
    }
  }

  async function quickStatus(l: Lead, s: Status) {
    setRows((prev) => prev?.map((x) => x.id === l.id ? { ...x, status: s } : x) ?? null)
    try { await apiRequest(`/sales/leads/${l.id}${codeQuery}`, { method: 'PATCH', body: JSON.stringify({ status: s }) }) } catch { load() }
  }

  const counts: Record<string, number> = {}
  for (const r of rows ?? []) counts[r.status] = (counts[r.status] ?? 0) + 1

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <button key={s.value} onClick={() => setStatus(s.value)}
            className={`font-mono text-xs rounded-full px-3 py-1 border ${status === s.value ? 'border-[#2dd4bf] text-[#2dd4bf]' : 'border-white/10 text-[#8a94ad] hover:text-[#f0ece4]'}`}>
            {s.label}{s.value !== 'all' && status === 'all' && counts[s.value] ? ` ${counts[s.value]}` : ''}
          </button>
        ))}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search company, city, contact…"
          className="ml-auto bg-[#0d1225] border border-white/10 rounded-lg px-3 py-1.5 font-mono text-sm text-[#f0ece4] placeholder:text-[#6b7594] focus:outline-none focus:border-[#2dd4bf]/40 w-full sm:w-72" />
        <button onClick={() => setEditing({ ...EMPTY })} className="font-mono text-xs font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-3 py-1.5 hover:brightness-110">+ Lead</button>
        <button onClick={() => apiDownload(`/sales/leads/export${codeQuery}`, `leads-${me?.code ?? 'sales'}.csv`)} className="font-mono text-xs text-[#8a94ad] hover:text-[#f0ece4] underline">Export CSV</button>
      </div>

      {!rows ? <p className="font-mono text-sm text-[#8a94ad]">Loading…</p> : rows.length === 0 ? (
        <p className="font-mono text-sm text-[#8a94ad]">No leads here yet. Add one, or ask Blake to import the towing list.</p>
      ) : (
        <div className="rounded-xl border border-white/8 overflow-auto">
          <table className="w-full text-left font-mono text-xs" style={{ minWidth: 860 }}>
            <thead><tr className="bg-[#1a1d24] text-[#2dd4bf]">
              {['Company', 'Boats', 'Contact', 'Status', 'Next step', ''].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((l, i) => (
                <tr key={l.id} className={`border-t border-white/5 align-top ${i % 2 ? 'bg-[#0f1629]' : 'bg-[#111827]'}`}>
                  <td className="px-3 py-2">
                    <div className="text-[#f0ece4]/90 font-bold">{l.company}{l.dba ? <span className="font-normal text-[#8b93ad]"> (dba {l.dba})</span> : null}</div>
                    <div className="text-[#8b93ad]">{[l.city, l.state].filter(Boolean).join(', ')}{l.service ? ` · ${l.service}` : ''}</div>
                    {l.website && <a href={l.website.startsWith('http') ? l.website : `https://${l.website}`} target="_blank" rel="noopener noreferrer" className="text-[#2dd4bf] hover:underline">{l.website.replace(/^https?:\/\//, '')}</a>}
                  </td>
                  <td className="px-3 py-2 text-[#f0ece4]/85 whitespace-nowrap">{boats(l) || <span className="text-[#6b7594]">—</span>}</td>
                  <td className="px-3 py-2">
                    <div className="text-[#f0ece4]/90">{l.contact_name ?? ''}{l.contact_role ? <span className="text-[#8b93ad]"> · {l.contact_role}</span> : null}</div>
                    <div className="text-[#8b93ad]">{l.contact_email ?? ''}{l.phone ? `${l.contact_email ? ' · ' : ''}${l.phone}` : ''}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <select value={l.status} onChange={(e) => quickStatus(l, e.target.value as Status)}
                      className={`rounded px-2 py-0.5 border-0 ${TONE[l.status]} bg-transparent`}>
                      {STATUSES.filter((s) => s.value !== 'all').map((s) => <option key={s.value} value={s.value} className="bg-[#0d1225] text-[#f0ece4]">{s.label}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <div className="text-[#f0ece4]/85">{l.next_step ?? ''}</div>
                    {l.next_step_at && <div className={`${due(l).includes('overdue') ? 'text-amber-300' : 'text-[#8b93ad]'}`}>{l.next_step_at} · {due(l)}</div>}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap"><button onClick={() => setEditing({ ...l })} className="text-[#2dd4bf] hover:underline">Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="w-full max-w-2xl max-h-[88vh] overflow-auto rounded-xl border border-white/10 bg-[#0d1225] p-5" onClick={(e) => e.stopPropagation()}>
            <p className="font-display text-lg font-bold text-[#f0ece4] mb-3">{editing.id ? editing.company : 'New lead'}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 font-mono text-sm">
              {([['company', 'Company'], ['dba', 'DBA'], ['city', 'City'], ['state', 'State'], ['phone', 'Phone'], ['website', 'Website'],
                ['contact_name', 'Contact'], ['contact_role', 'Role'], ['contact_email', 'Email'], ['service', 'Service'], ['area', 'Area']] as const).map(([k, label]) => (
                <label key={k} className="block">
                  <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">{label}</span>
                  <input value={(editing[k] as string | null) ?? ''} onChange={(e) => setEditing({ ...editing, [k]: e.target.value })}
                    className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/40" />
                </label>
              ))}
              {([['towboats', 'Towboats'], ['tugs', 'Tugs'], ['osv', 'OSVs'], ['passenger', 'Passenger']] as const).map(([k, label]) => (
                <label key={k} className="block">
                  <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">{label}</span>
                  <input type="number" min={0} value={editing[k] ?? ''} onChange={(e) => setEditing({ ...editing, [k]: e.target.value === '' ? null : Number(e.target.value) })}
                    className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/40" />
                </label>
              ))}
              <label className="block">
                <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Status</span>
                <select value={editing.status ?? 'new'} onChange={(e) => setEditing({ ...editing, status: e.target.value })}
                  className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4]">
                  {STATUSES.filter((s) => s.value !== 'all').map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </label>
              <label className="block">
                <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Next step date</span>
                <input type="date" value={editing.next_step_at ?? ''} onChange={(e) => setEditing({ ...editing, next_step_at: e.target.value || null })}
                  className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4]" />
              </label>
              <label className="block sm:col-span-2">
                <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Next step</span>
                <input value={editing.next_step ?? ''} onChange={(e) => setEditing({ ...editing, next_step: e.target.value })}
                  className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/40" />
              </label>
              <label className="block sm:col-span-2">
                <span className="block text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">Notes</span>
                <textarea rows={4} value={editing.notes ?? ''} onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
                  className="w-full bg-[#111827] border border-white/10 rounded-lg px-3 py-1.5 text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/40 resize-y" />
              </label>
            </div>
            {error && <p className="font-mono text-xs text-amber-300 mt-2">{error}</p>}
            <div className="flex items-center gap-3 mt-4">
              <button onClick={save} disabled={saving} className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-5 py-2 disabled:opacity-50 hover:brightness-110">{saving ? 'Saving…' : 'Save'}</button>
              <button onClick={() => setEditing(null)} className="font-mono text-sm text-[#8a94ad] hover:text-[#f0ece4]">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
