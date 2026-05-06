'use client'

// Sprint D6.62 — sea-time logger.
//
// Each entry is a BLOCK of consecutive sea time (a trip / voyage /
// contract). Mobile-first card layout: tap "Add" → modal opens with
// vessel + dates + capacity → save. List shows totals at top.
//
// The data feeds the existing /credentials/sea-service-letter
// generator (Sprint D6.62 Phase C wires that), and powers chat
// reasoning like "you've logged 720 near-coastal days in 3 years —
// that qualifies you for Mate Near-Coastal under 46 CFR 11.464."

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'

const ROUTE_TYPES = ['Inland', 'Near-Coastal', 'Coastal', 'Oceans'] as const
const CAPACITIES = [
  'Master', 'Mate', 'Chief Mate', '2nd Mate', '3rd Mate',
  'Chief Engineer', '1st A/E', '2nd A/E', '3rd A/E',
  'Pilot', 'AB', 'OS', 'QMED', 'Wiper', 'Other',
] as const

interface SeaTimeEntry {
  id: string
  vessel_id: string | null
  vessel_name: string
  official_number: string | null
  vessel_type: string | null
  gross_tonnage: number | null
  horsepower: string | null
  propulsion: string | null
  route_type: string | null
  capacity_served: string
  from_date: string
  to_date: string
  days_on_board: number
  employer_name: string | null
  employer_signed: boolean
  notes: string | null
}

interface SeaTimeTotals {
  total_days: number
  days_last_3_years: number
  days_last_5_years: number
  by_route_type: Record<string, number>
  by_capacity: Record<string, number>
  entry_count: number
  earliest_date: string | null
  latest_date: string | null
}

interface VesselOption {
  id: string
  name: string
  vessel_type: string | null
  flag_state: string | null
  gross_tonnage: number | null
}

function fmtDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00Z')
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
  })
}

function dayDiff(from: string, to: string): number {
  const f = new Date(from + 'T00:00:00Z').getTime()
  const t = new Date(to + 'T00:00:00Z').getTime()
  if (isNaN(f) || isNaN(t)) return 0
  return Math.max(0, Math.round((t - f) / (1000 * 60 * 60 * 24)) + 1)
}

function emptyEntry(): Partial<SeaTimeEntry> {
  return {
    vessel_id: null,
    vessel_name: '',
    official_number: null,
    vessel_type: null,
    gross_tonnage: null,
    horsepower: null,
    propulsion: null,
    route_type: null,
    capacity_served: '',
    from_date: '',
    to_date: '',
    days_on_board: 0,
    employer_name: null,
    employer_signed: false,
    notes: null,
  }
}


function Content() {
  const [entries, setEntries] = useState<SeaTimeEntry[]>([])
  const [totals, setTotals] = useState<SeaTimeTotals | null>(null)
  const [vessels, setVessels] = useState<VesselOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [editing, setEditing] = useState<Partial<SeaTimeEntry> | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, agg, vlist] = await Promise.all([
        apiRequest<SeaTimeEntry[]>('/sea-time/entries'),
        apiRequest<SeaTimeTotals>('/sea-time/totals'),
        apiRequest<{ items: VesselOption[] }>('/vessels').catch(
          () => ({ items: [] as VesselOption[] }),
        ),
      ])
      setEntries(list)
      setTotals(agg)
      // /vessels returns either {items: []} or [], depending on call —
      // tolerate both shapes.
      const vesselArr = Array.isArray(vlist) ? vlist : (vlist?.items || [])
      setVessels(vesselArr as VesselOption[])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  function startNew() { setEditing(emptyEntry()) }

  function startEdit(e: SeaTimeEntry) { setEditing({ ...e }) }

  function vesselPicked(vid: string) {
    if (!editing) return
    if (!vid) {
      setEditing({ ...editing, vessel_id: null })
      return
    }
    const v = vessels.find((x) => x.id === vid)
    if (!v) return
    setEditing({
      ...editing,
      vessel_id: v.id,
      vessel_name: v.name || editing.vessel_name || '',
      vessel_type: v.vessel_type ?? editing.vessel_type ?? null,
      gross_tonnage: v.gross_tonnage ?? editing.gross_tonnage ?? null,
    })
  }

  // Auto-recompute days when dates change unless user has manually
  // overridden (we treat any non-zero days_on_board different from the
  // computed value as a manual override and stop touching it).
  function patchDates(field: 'from_date' | 'to_date', value: string) {
    if (!editing) return
    const next = { ...editing, [field]: value }
    const auto = (next.from_date && next.to_date) ? dayDiff(next.from_date as string, next.to_date as string) : 0
    const wasAuto = editing.from_date && editing.to_date
      ? dayDiff(editing.from_date, editing.to_date) === editing.days_on_board
      : true
    if (wasAuto || !editing.days_on_board) {
      next.days_on_board = auto
    }
    setEditing(next)
  }

  async function save() {
    if (!editing) return
    if (!editing.vessel_name || !editing.capacity_served || !editing.from_date || !editing.to_date) {
      setError('Vessel name, capacity, and both dates are required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      // Normalize numeric + nullable string fields the API expects.
      const body: Record<string, unknown> = {
        vessel_id: editing.vessel_id || null,
        vessel_name: editing.vessel_name,
        official_number: editing.official_number || null,
        vessel_type: editing.vessel_type || null,
        gross_tonnage: editing.gross_tonnage ?? null,
        horsepower: editing.horsepower || null,
        propulsion: editing.propulsion || null,
        route_type: editing.route_type || null,
        capacity_served: editing.capacity_served,
        from_date: editing.from_date,
        to_date: editing.to_date,
        days_on_board: editing.days_on_board ?? 0,
        employer_name: editing.employer_name || null,
        employer_signed: !!editing.employer_signed,
        notes: editing.notes || null,
      }
      if (editing.id) {
        await apiRequest(`/sea-time/entries/${editing.id}`, {
          method: 'PUT', body: JSON.stringify(body),
        })
      } else {
        await apiRequest('/sea-time/entries', {
          method: 'POST', body: JSON.stringify(body),
        })
      }
      setEditing(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    if (!confirm('Delete this sea-time entry? This cannot be undone.')) return
    try {
      await apiRequest(`/sea-time/entries/${id}`, { method: 'DELETE' })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-[#f0ece4]">
      <AppHeader title="Sea-Time Log" />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8 pb-32">
        {/* ── Totals card ───────────────────────────────────────── */}
        {totals && (
          <div className="bg-[#111827] rounded-2xl border border-[#2dd4bf]/20 p-5 md:p-6 mb-6">
            <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-3">
              Sea-time totals
            </p>
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div>
                <p className="font-display font-black text-[#f0ece4] text-2xl md:text-3xl">
                  {totals.total_days}
                </p>
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  total days
                </p>
              </div>
              <div>
                <p className="font-display font-black text-[#f0ece4] text-2xl md:text-3xl">
                  {totals.days_last_3_years}
                </p>
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  last 3 years
                </p>
              </div>
              <div>
                <p className="font-display font-black text-[#f0ece4] text-2xl md:text-3xl">
                  {totals.days_last_5_years}
                </p>
                <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">
                  last 5 years
                </p>
              </div>
            </div>
            {Object.keys(totals.by_route_type).length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {Object.entries(totals.by_route_type).map(([route, days]) => (
                  <span key={route} className="font-mono text-[11px] px-2 py-1 rounded
                    bg-white/5 border border-white/8 text-[#f0ece4]/85">
                    {route}: <span className="text-[#2dd4bf]">{days}d</span>
                  </span>
                ))}
              </div>
            )}
            <p className="font-mono text-[10px] text-[#6b7594] mt-3">
              {totals.entry_count} entr{totals.entry_count === 1 ? 'y' : 'ies'}
              {totals.earliest_date && totals.latest_date && (
                <> · {fmtDate(totals.earliest_date)} → {fmtDate(totals.latest_date)}</>
              )}
            </p>
          </div>
        )}

        {/* ── Add button ────────────────────────────────────────── */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display font-bold text-[#f0ece4] text-lg">
            Entries
          </h2>
          <div className="flex items-center gap-2">
            <Link
              href="/sea-service-letter"
              className="font-mono text-xs text-[#2dd4bf] hover:underline"
            >
              Generate USCG letter →
            </Link>
            <button
              onClick={startNew}
              className="font-mono text-xs font-bold uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-3.5 py-2
                hover:brightness-110 transition-[filter] duration-150"
            >
              + Add Entry
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4
            font-mono text-xs text-red-400">{error}</div>
        )}

        {/* ── Entry list ────────────────────────────────────────── */}
        {loading && (
          <div className="font-mono text-xs text-[#6b7594] p-6 text-center">
            Loading…
          </div>
        )}

        {!loading && entries.length === 0 && (
          <div className="bg-[#111827] rounded-2xl border border-white/8 p-8 text-center">
            <p className="font-mono text-sm text-[#f0ece4]/85 mb-2">
              No sea-time entries yet.
            </p>
            <p className="font-mono text-xs text-[#6b7594] mb-5 max-w-sm mx-auto">
              Log a trip / voyage / contract block. We&apos;ll calculate your
              totals across the windows the USCG cares about and feed
              your sea-service letter generator.
            </p>
            <button
              onClick={startNew}
              className="font-mono text-xs font-bold uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-4 py-2"
            >
              + Add your first entry
            </button>
          </div>
        )}

        <div className="space-y-3">
          {entries.map((e) => (
            <div key={e.id} className="bg-[#111827] rounded-xl border border-white/8 p-4 md:p-5">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex-1 min-w-0">
                  <p className="font-display font-bold text-[#f0ece4] text-base">
                    {e.vessel_name}
                    {e.official_number && (
                      <span className="font-mono text-xs text-[#6b7594] ml-2">
                        ON {e.official_number}
                      </span>
                    )}
                  </p>
                  <p className="font-mono text-xs text-[#f0ece4]/85 mt-1">
                    <span className="text-[#2dd4bf]">{e.capacity_served}</span>
                    {e.route_type && <> · {e.route_type}</>}
                    {e.vessel_type && <> · {e.vessel_type}</>}
                    {e.gross_tonnage && <> · {e.gross_tonnage} GT</>}
                    {e.horsepower && <> · {e.horsepower} HP</>}
                  </p>
                  <p className="font-mono text-[11px] text-[#6b7594] mt-1">
                    {fmtDate(e.from_date)} → {fmtDate(e.to_date)}{' '}
                    · <span className="text-[#f0ece4]/85">{e.days_on_board} days</span>
                    {e.employer_name && <> · {e.employer_name}</>}
                    {e.employer_signed && (
                      <span className="ml-1.5 text-emerald-400">✓ signed</span>
                    )}
                  </p>
                  {e.notes && (
                    <p className="font-mono text-[11px] text-[#6b7594] mt-1 italic">
                      {e.notes}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1">
                  <button
                    onClick={() => startEdit(e)}
                    className="font-mono text-[11px] text-[#2dd4bf] hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => remove(e.id)}
                    className="font-mono text-[11px] text-red-400/70 hover:text-red-400"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* ── Edit modal ──────────────────────────────────────────── */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-end md:items-center justify-center
          bg-[#0a0e1a]/80 backdrop-blur-sm p-0 md:p-4">
          <div className="w-full max-w-lg bg-[#111827] border border-white/10
            rounded-t-2xl md:rounded-2xl p-5 md:p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display font-bold text-[#f0ece4] text-lg">
                {editing.id ? 'Edit Entry' : 'New Entry'}
              </h3>
              <button
                onClick={() => setEditing(null)}
                className="text-[#6b7594] hover:text-[#f0ece4] text-xl leading-none"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Existing vessel quick-pick */}
            {vessels.length > 0 && !editing.id && (
              <div className="mb-3">
                <label className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
                  Pick from your vessels (optional)
                </label>
                <select
                  value={editing.vessel_id || ''}
                  onChange={(e) => vesselPicked(e.target.value)}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded
                    px-2 py-2 font-mono text-sm text-[#f0ece4]"
                >
                  <option value="">— Manual entry —</option>
                  {vessels.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                      {v.vessel_type ? ` (${v.vessel_type})` : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <Field label="Vessel name *">
              <input
                value={editing.vessel_name || ''}
                onChange={(e) => setEditing({ ...editing, vessel_name: e.target.value })}
                className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                placeholder="M/V Jane Doe"
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Official number">
                <input
                  value={editing.official_number || ''}
                  onChange={(e) => setEditing({ ...editing, official_number: e.target.value || null })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                  placeholder="123456"
                />
              </Field>
              <Field label="Vessel type">
                <input
                  value={editing.vessel_type || ''}
                  onChange={(e) => setEditing({ ...editing, vessel_type: e.target.value || null })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                  placeholder="Tugboat"
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Gross tonnage">
                <input
                  type="number"
                  inputMode="decimal"
                  value={editing.gross_tonnage ?? ''}
                  onChange={(e) => setEditing({
                    ...editing,
                    gross_tonnage: e.target.value === '' ? null : Number(e.target.value),
                  })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                />
              </Field>
              <Field label="Horsepower">
                <input
                  value={editing.horsepower || ''}
                  onChange={(e) => setEditing({ ...editing, horsepower: e.target.value || null })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                  placeholder="3000"
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Propulsion">
                <input
                  value={editing.propulsion || ''}
                  onChange={(e) => setEditing({ ...editing, propulsion: e.target.value || null })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                  placeholder="Diesel"
                />
              </Field>
              <Field label="Route">
                <select
                  value={editing.route_type || ''}
                  onChange={(e) => setEditing({ ...editing, route_type: e.target.value || null })}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm text-[#f0ece4]"
                >
                  <option value="">—</option>
                  {ROUTE_TYPES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </Field>
            </div>

            <Field label="Capacity served *">
              <select
                value={editing.capacity_served || ''}
                onChange={(e) => setEditing({ ...editing, capacity_served: e.target.value })}
                className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm text-[#f0ece4]"
              >
                <option value="">— Select —</option>
                {CAPACITIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="From date *">
                <input
                  type="date"
                  value={editing.from_date || ''}
                  onChange={(e) => patchDates('from_date', e.target.value)}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                />
              </Field>
              <Field label="To date *">
                <input
                  type="date"
                  value={editing.to_date || ''}
                  onChange={(e) => patchDates('to_date', e.target.value)}
                  className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                />
              </Field>
            </div>

            <Field label="Days on board (override if needed)">
              <input
                type="number"
                inputMode="numeric"
                value={editing.days_on_board ?? 0}
                onChange={(e) => setEditing({
                  ...editing, days_on_board: Math.max(0, Number(e.target.value)),
                })}
                className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
              />
            </Field>

            <Field label="Employer / company">
              <input
                value={editing.employer_name || ''}
                onChange={(e) => setEditing({ ...editing, employer_name: e.target.value || null })}
                className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm"
                placeholder="Acme Marine LLC"
              />
            </Field>

            <label className="flex items-center gap-2 mb-3 font-mono text-xs text-[#f0ece4]/85">
              <input
                type="checkbox"
                checked={!!editing.employer_signed}
                onChange={(e) => setEditing({ ...editing, employer_signed: e.target.checked })}
              />
              Signed sea-service letter on file for this entry
            </label>

            <Field label="Notes">
              <textarea
                value={editing.notes || ''}
                onChange={(e) => setEditing({ ...editing, notes: e.target.value || null })}
                className="w-full bg-[#0a0e1a] border border-white/10 rounded px-2 py-2 font-mono text-sm h-20 resize-none"
              />
            </Field>

            <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-white/8">
              <button
                onClick={() => setEditing(null)}
                disabled={saving}
                className="font-mono text-xs uppercase tracking-wider px-3 py-2 text-[#6b7594] hover:text-[#f0ece4]"
              >
                Cancel
              </button>
              <button
                onClick={() => void save()}
                disabled={saving}
                className="font-mono text-xs font-bold uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-4 py-2
                  hover:brightness-110 disabled:opacity-50 transition-[filter]"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <label className="block font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-1">
        {label}
      </label>
      {children}
    </div>
  )
}


export default function SeaTimePage() {
  return (
    <AuthGuard>
      <Content />
    </AuthGuard>
  )
}
