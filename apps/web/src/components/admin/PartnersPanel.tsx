'use client'

// Sprint D6.14b — Partners admin tab.
//
// Renders /admin/partner-tithes against the new partner-first schema:
//   - Partners are the entities receiving money.
//   - Each partner can be fed by multiple referral_source rules
//     (direct routing for /womenoffshore + /ass; default-pool split
//     for everything else, including /captainkarynn and unattributed).
//   - "Mark paid" records a payout against a partner_id.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

// ── Types (mirror backend Pydantic) ──────────────────────────────────────────

interface PartnerRoute {
  referral_source: string | null  // null = default pool
  weight: number
  tithe_pct: number
  total_weight: number
}

interface TithePartnerSummary {
  id: number
  name: string
  active: boolean
  notes: string | null
  payout_method: string | null
  payout_contact: string | null
  routes: PartnerRoute[]
  accrued_alltime_cents: number
  paid_out_cents: number
  outstanding_cents: number
  payout_count: number
}

interface MonthlyPartnerAccrual {
  month: string  // 'YYYY-MM'
  partner_id: number
  partner_name: string
  accrued_cents: number
}

interface MonthlyChannelRevenue {
  month: string
  referral_source: string | null
  revenue_cents: number
  invoice_count: number
}

interface PartnerPayoutEntry {
  id: string
  partner_id: number
  partner_name_at_time: string
  amount_cents: number
  currency: string
  paid_at: string
  notes: string | null
  created_by_email: string | null
  created_at: string
}

interface PartnerTithesResponse {
  partners: TithePartnerSummary[]
  monthly_partner_accrual: MonthlyPartnerAccrual[]
  monthly_channel_revenue: MonthlyChannelRevenue[]
  recent_payouts: PartnerPayoutEntry[]
  total_revenue_alltime_cents: number
  total_tithe_alltime_cents: number
  total_paid_out_cents: number
  total_outstanding_cents: number
}

// ── Formatters ───────────────────────────────────────────────────────────────

function fmtUSD(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(cents / 100)
}

function fmtMonth(iso: string): string {
  const [y, m] = iso.split('-').map(Number)
  if (!y || !m) return iso
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('en-US', {
    month: 'short', year: 'numeric', timeZone: 'UTC',
  })
}

function fmtPaidAt(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

function describeRoute(route: PartnerRoute): string {
  const channel = route.referral_source ?? 'default pool'
  const share = route.total_weight > 0
    ? Math.round((route.weight / route.total_weight) * 100)
    : 0
  const pctOfTithe = (route.tithe_pct * route.weight / Math.max(1, route.total_weight)).toFixed(2)
  return `${channel} → ${share}% share (${pctOfTithe}% of revenue)`
}

// ── Top-level panel ──────────────────────────────────────────────────────────

export function PartnersPanel() {
  const [data, setData] = useState<PartnerTithesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [recordingFor, setRecordingFor] = useState<number | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiRequest<PartnerTithesResponse>('/admin/partner-tithes?months=12')
      setData(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  if (loading && !data) {
    return <div className="font-mono text-sm text-[#6b7594] py-8 text-center">Loading partner tithes…</div>
  }
  if (error) {
    return (
      <div className="font-mono text-sm text-red-400 px-4 py-4 bg-red-500/8 rounded border border-red-500/20">
        {error}
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="flex flex-col gap-6">
      {/* Cross-totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Revenue (all-time)"
          value={fmtUSD(data.total_revenue_alltime_cents)}
          hint="All paid invoices"
        />
        <StatCard
          label="Tithe accrued"
          value={fmtUSD(data.total_tithe_alltime_cents)}
          hint="Owed across all partners"
        />
        <StatCard
          label="Paid out"
          value={fmtUSD(data.total_paid_out_cents)}
          hint="Recorded payouts"
        />
        <StatCard
          label="Outstanding"
          value={fmtUSD(data.total_outstanding_cents)}
          hint="What we still owe"
          accent={data.total_outstanding_cents > 0}
        />
      </div>

      {/* Per-partner cards */}
      <section>
        <h2 className="font-display text-lg font-bold text-[#f0ece4] mb-3 tracking-wide">
          Partners
        </h2>
        <div className="grid gap-4">
          {data.partners.map((p) => (
            <PartnerCard
              key={p.id}
              partner={p}
              recording={recordingFor === p.id}
              onStartRecord={() => setRecordingFor(p.id)}
              onCancelRecord={() => setRecordingFor(null)}
              onRecorded={async () => { setRecordingFor(null); await refresh() }}
            />
          ))}
          {data.partners.length === 0 && (
            <div className="font-mono text-xs text-[#6b7594] px-4 py-4 bg-white/3 rounded border border-white/8 text-center">
              No partners configured.
            </div>
          )}
        </div>
      </section>

      {/* Monthly per-partner accrual */}
      <section>
        <h2 className="font-display text-lg font-bold text-[#f0ece4] mb-3 tracking-wide">
          Monthly per-partner accrual <span className="font-mono text-xs text-[#6b7594]">(last 12 months)</span>
        </h2>
        <MonthlyPartnerTable rows={data.monthly_partner_accrual} partners={data.partners} />
      </section>

      {/* Monthly channel revenue */}
      <section>
        <h2 className="font-display text-lg font-bold text-[#f0ece4] mb-3 tracking-wide">
          Revenue by channel <span className="font-mono text-xs text-[#6b7594]">(input side, last 12 months)</span>
        </h2>
        <MonthlyChannelTable rows={data.monthly_channel_revenue} />
      </section>

      {/* Recent payouts */}
      <section>
        <h2 className="font-display text-lg font-bold text-[#f0ece4] mb-3 tracking-wide">
          Recent payouts
        </h2>
        <PayoutsTable payouts={data.recent_payouts} onDeleted={refresh} />
      </section>
    </div>
  )
}

// ── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, hint, accent }: {
  label: string
  value: string
  hint?: string
  accent?: boolean
}) {
  return (
    <div className={`bg-white/3 rounded-lg border px-4 py-3 ${
      accent ? 'border-amber-500/40' : 'border-white/8'
    }`}>
      <p className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">{label}</p>
      <p className={`font-display text-2xl font-bold mt-1 ${
        accent ? 'text-amber-400' : 'text-[#f0ece4]'
      }`}>{value}</p>
      {hint && <p className="font-mono text-[10px] text-[#6b7594] mt-1">{hint}</p>}
    </div>
  )
}

// ── Per-partner card ─────────────────────────────────────────────────────────

function PartnerCard({
  partner,
  recording,
  onStartRecord,
  onCancelRecord,
  onRecorded,
}: {
  partner: TithePartnerSummary
  recording: boolean
  onStartRecord: () => void
  onCancelRecord: () => void
  onRecorded: () => Promise<void>
}) {
  const owed = partner.outstanding_cents
  return (
    <div className="rounded-lg border border-white/8 bg-white/3 overflow-hidden">
      <div className="px-4 py-3 flex items-start gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <p className="font-display text-base font-bold text-[#f0ece4] tracking-wide">
              {partner.name}
            </p>
            {!partner.active && (
              <span className="font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#6b7594]/15 text-[#6b7594]">
                inactive
              </span>
            )}
          </div>
          {partner.notes && (
            <p className="font-mono text-[11px] text-[#6b7594] mt-1 leading-relaxed">
              {partner.notes}
            </p>
          )}
          {partner.routes.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {partner.routes.map((r, i) => (
                <li key={i} className="font-mono text-[10px] text-[#2dd4bf]/80">
                  {describeRoute(r)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex flex-col items-end">
          <p className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">Outstanding</p>
          <p className={`font-display text-xl font-bold ${
            owed > 0 ? 'text-amber-400' : 'text-[#f0ece4]/60'
          }`}>{fmtUSD(owed)}</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-px bg-white/8">
        <MiniStat label="Accrued (all-time)" value={fmtUSD(partner.accrued_alltime_cents)} />
        <MiniStat label="Paid out" value={fmtUSD(partner.paid_out_cents)} sub={`${partner.payout_count} payout${partner.payout_count === 1 ? '' : 's'}`} />
        <MiniStat label="Outstanding" value={fmtUSD(owed)} accent={owed > 0} />
      </div>
      <div className="px-4 py-3 border-t border-white/8 bg-white/2">
        {!recording ? (
          <div className="flex items-center justify-between gap-3">
            <p className="font-mono text-[11px] text-[#6b7594]">
              Sent a payout? Mark it here to keep the ledger straight.
            </p>
            <button
              onClick={onStartRecord}
              disabled={owed <= 0}
              className="font-mono text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded
                bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110
                disabled:opacity-30 disabled:cursor-not-allowed
                transition-[filter] duration-150"
            >
              Mark paid
            </button>
          </div>
        ) : (
          <RecordPayoutForm
            partner_id={partner.id}
            suggestedAmountCents={owed}
            onCancel={onCancelRecord}
            onRecorded={onRecorded}
          />
        )}
      </div>
    </div>
  )
}

function MiniStat({ label, value, sub, accent }: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="bg-[#0a0e1a] px-3 py-2.5">
      <p className="font-mono text-[9px] uppercase tracking-wider text-[#6b7594]">{label}</p>
      <p className={`font-mono text-sm font-bold tabular-nums mt-0.5 ${
        accent ? 'text-amber-400' : 'text-[#f0ece4]'
      }`}>{value}</p>
      {sub && <p className="font-mono text-[9px] text-[#6b7594] mt-0.5">{sub}</p>}
    </div>
  )
}

// ── Inline "Mark paid" form ──────────────────────────────────────────────────

function RecordPayoutForm({
  partner_id,
  suggestedAmountCents,
  onCancel,
  onRecorded,
}: {
  partner_id: number
  suggestedAmountCents: number
  onCancel: () => void
  onRecorded: () => Promise<void>
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [amountStr, setAmountStr] = useState((suggestedAmountCents / 100).toFixed(2))
  const [paidAt, setPaidAt] = useState(today)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setErr(null)
    const cents = Math.round(parseFloat(amountStr) * 100)
    if (!Number.isFinite(cents) || cents <= 0) {
      setErr('Amount must be a positive dollar value.')
      return
    }
    setSubmitting(true)
    try {
      await apiRequest('/admin/partner-payouts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          partner_id,
          amount_cents: cents,
          currency: 'usd',
          paid_at: `${paidAt}T12:00:00Z`,
          notes: notes.trim() || null,
        }),
      })
      await onRecorded()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to record payout.')
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">Amount (USD)</span>
          <input
            type="number" step="0.01" min="0.01"
            value={amountStr}
            onChange={(e) => setAmountStr(e.target.value)}
            className="bg-[#0a0e1a] border border-white/10 rounded px-2 py-1.5
              font-mono text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">Paid date</span>
          <input
            type="date"
            value={paidAt}
            onChange={(e) => setPaidAt(e.target.value)}
            className="bg-[#0a0e1a] border border-white/10 rounded px-2 py-1.5
              font-mono text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">Notes (optional)</span>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Wire ref WO-2026-04"
            className="bg-[#0a0e1a] border border-white/10 rounded px-2 py-1.5
              font-mono text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]
              placeholder:text-[#6b7594]/50"
          />
        </label>
      </div>
      {err && <p className="font-mono text-xs text-red-400">{err}</p>}
      <div className="flex gap-2">
        <button
          onClick={submit}
          disabled={submitting}
          className="font-mono text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded
            bg-[#2dd4bf] text-[#0a0e1a] hover:brightness-110 disabled:opacity-50
            transition-[filter] duration-150"
        >
          {submitting ? 'Recording…' : 'Record payout'}
        </button>
        <button
          onClick={onCancel}
          disabled={submitting}
          className="font-mono text-xs uppercase tracking-wider px-3 py-1.5 rounded
            border border-white/10 text-[#9ca5be] hover:bg-white/5
            disabled:opacity-50 transition-colors duration-150"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Monthly per-partner accrual table ────────────────────────────────────────

function MonthlyPartnerTable({ rows, partners }: {
  rows: MonthlyPartnerAccrual[]
  partners: TithePartnerSummary[]
}) {
  if (rows.length === 0) {
    return (
      <div className="font-mono text-xs text-[#6b7594] px-4 py-4 bg-white/3 rounded border border-white/8 text-center">
        No accruals in the last 12 months yet.
      </div>
    )
  }
  // Pivot: months as rows, partners as columns.
  const months = Array.from(new Set(rows.map(r => r.month))).sort().reverse()
  const partnerCols = partners.slice().sort((a, b) => a.name.localeCompare(b.name))
  const cell = new Map<string, number>()
  for (const r of rows) cell.set(`${r.month}|${r.partner_id}`, r.accrued_cents)
  return (
    <div className="rounded-lg border border-white/8 bg-white/3 overflow-x-auto">
      <table className="w-full font-mono text-xs">
        <thead className="bg-white/5">
          <tr className="text-left">
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Month</th>
            {partnerCols.map(p => (
              <th key={p.id} className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px] text-right">
                {p.name}
              </th>
            ))}
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px] text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {months.map(m => {
            let monthTotal = 0
            return (
              <tr key={m} className="border-t border-white/8">
                <td className="px-3 py-2 text-[#f0ece4]">{fmtMonth(m)}</td>
                {partnerCols.map(p => {
                  const v = cell.get(`${m}|${p.id}`) ?? 0
                  monthTotal += v
                  return (
                    <td key={p.id} className="px-3 py-2 text-right tabular-nums text-[#2dd4bf]/90">
                      {v > 0 ? fmtUSD(v) : <span className="text-[#6b7594]/50">—</span>}
                    </td>
                  )
                })}
                <td className="px-3 py-2 text-right tabular-nums text-[#f0ece4]">{fmtUSD(monthTotal)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Monthly channel revenue table ────────────────────────────────────────────

function MonthlyChannelTable({ rows }: { rows: MonthlyChannelRevenue[] }) {
  if (rows.length === 0) {
    return (
      <div className="font-mono text-xs text-[#6b7594] px-4 py-4 bg-white/3 rounded border border-white/8 text-center">
        No invoices in the last 12 months yet.
      </div>
    )
  }
  // Group by month for visual grouping.
  const byMonth = new Map<string, MonthlyChannelRevenue[]>()
  for (const r of rows) {
    const list = byMonth.get(r.month) ?? []
    list.push(r)
    byMonth.set(r.month, list)
  }
  return (
    <div className="rounded-lg border border-white/8 bg-white/3 overflow-x-auto">
      <table className="w-full font-mono text-xs">
        <thead className="bg-white/5">
          <tr className="text-left">
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Month</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Channel</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px] text-right">Invoices</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px] text-right">Revenue</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(byMonth.entries()).map(([month, monthRows]) => (
            monthRows.map((r, j) => (
              <tr key={`${month}-${r.referral_source ?? 'none'}`}
                  className={j === 0 ? 'border-t border-white/8' : ''}>
                <td className="px-3 py-2 text-[#f0ece4]">{j === 0 ? fmtMonth(month) : ''}</td>
                <td className="px-3 py-2 text-[#f0ece4]/80">
                  {r.referral_source ?? <span className="text-[#6b7594]">unattributed (default pool)</span>}
                </td>
                <td className="px-3 py-2 text-right text-[#f0ece4]/80 tabular-nums">{r.invoice_count}</td>
                <td className="px-3 py-2 text-right text-[#f0ece4] tabular-nums">{fmtUSD(r.revenue_cents)}</td>
              </tr>
            ))
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Recent payouts ledger ────────────────────────────────────────────────────

function PayoutsTable({ payouts, onDeleted }: {
  payouts: PartnerPayoutEntry[]
  onDeleted: () => Promise<void>
}) {
  const [deletingId, setDeletingId] = useState<string | null>(null)

  if (payouts.length === 0) {
    return (
      <div className="font-mono text-xs text-[#6b7594] px-4 py-4 bg-white/3 rounded border border-white/8 text-center">
        No payouts recorded yet.
      </div>
    )
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this payout record? Use only for typo corrections — the audit log keeps a copy.')) return
    setDeletingId(id)
    try {
      await apiRequest(`/admin/partner-payouts/${id}`, { method: 'DELETE' })
      await onDeleted()
    } catch (e) {
      alert('Failed to delete: ' + (e instanceof Error ? e.message : 'unknown'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="rounded-lg border border-white/8 bg-white/3 overflow-x-auto">
      <table className="w-full font-mono text-xs">
        <thead className="bg-white/5">
          <tr className="text-left">
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Paid date</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Partner</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px] text-right">Amount</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Notes</th>
            <th className="px-3 py-2 text-[#6b7594] font-normal uppercase tracking-wider text-[10px]">Recorded by</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {payouts.map((p) => (
            <tr key={p.id} className="border-t border-white/8">
              <td className="px-3 py-2 text-[#f0ece4] tabular-nums">{fmtPaidAt(p.paid_at)}</td>
              <td className="px-3 py-2 text-[#f0ece4]/80">{p.partner_name_at_time}</td>
              <td className="px-3 py-2 text-right text-[#2dd4bf] tabular-nums">{fmtUSD(p.amount_cents)}</td>
              <td className="px-3 py-2 text-[#9ca5be] max-w-xs truncate" title={p.notes ?? ''}>
                {p.notes ?? <span className="text-[#6b7594]/50">—</span>}
              </td>
              <td className="px-3 py-2 text-[#6b7594] text-[10px]">
                {p.created_by_email ?? <span className="text-[#6b7594]/50">unknown</span>}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => handleDelete(p.id)}
                  disabled={deletingId === p.id}
                  className="font-mono text-[10px] uppercase tracking-wider text-red-400/60 hover:text-red-400
                    disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title="Delete this payout record"
                >
                  {deletingId === p.id ? '…' : 'Delete'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
