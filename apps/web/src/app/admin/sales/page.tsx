'use client'

// 2026-10-17 — Admin > Sales (apps/api/app/routers/admin_sales.py). Every
// salesperson, the accounts credited to each, what they paid, what we owe, the
// lead lists, and checks for anything that would make a salesperson's numbers
// wrong. Credit is the pilot code in the signup link unless an admin set it by
// hand (app/sales_credit.py); the salesperson's own /sales pages use the same rule.

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { apiDownload, apiRequest, apiUpload } from '@/lib/api'
import { fmtDate, fmtRelative } from '../_lib/format'
import { Card, Empty, Page, Pill, Section, Skeleton, TEXT_MUTED, btn } from '../_components/ui'

interface SalesFleet {
  id: string
  name: string
  status: string
  boats: number
  paying: boolean
  invoiced: boolean
  internal_only: boolean
  trial_ends_at: string | null
  trial_custom: boolean
}

interface SalesAccount {
  user_id: string
  name: string | null
  email: string
  created_at: string
  code: string
  credit: 'link' | 'admin'
  signup_src: string | null
  stage: 'signed_up' | 'asked' | 'trial' | 'paying'
  questions: number
  paying_plan: boolean
  internal: boolean
  fleets: SalesFleet[]
  paid_total: number
}

interface Salesperson {
  user_id: string
  name: string | null
  email: string
  code: string | null
  access: boolean
  pilot_label: string | null
  pilot_active: boolean | null
  trial_days: number | null
  short_link: string | null
  accounts: number
  stages: Record<string, number>
  boats_paying: number
  revenue_total: number
  commission_total: number
  commission_this_month: number
  commission_last_month: number
  leads_total: number
  leads_by_status: Record<string, number>
  leads_overdue: number
  last_lead_update: string | null
  last_seen: string | null
}

interface PayoutRow { month: string; code: string; revenue: number; commission: number }
interface Issue { level: 'error' | 'warn' | 'info'; code: string | null; text: string; user_id: string | null; fix: string | null }

interface Overview {
  rate: number
  this_month: string
  last_month: string
  people: Salesperson[]
  accounts: SalesAccount[]
  payouts: PayoutRow[]
  issues: Issue[]
}

const STAGE: Record<string, { label: string; tone: 'gray' | 'purple' | 'amber' | 'teal' }> = {
  signed_up: { label: 'Signed up', tone: 'gray' },
  asked: { label: 'Asked', tone: 'purple' },
  trial: { label: 'Fleet trial', tone: 'amber' },
  paying: { label: 'Paying', tone: 'teal' },
}
const LEAD_ORDER = ['new', 'contacted', 'demo', 'trial', 'paying', 'lost']

const INPUT = 'w-full rounded-lg bg-[#0a0e1a] border border-white/15 focus:border-[#2dd4bf]/60 outline-none ' +
  'px-3 py-2 font-mono text-base md:text-sm text-[#f0ece4] placeholder:text-[#6b7594]'
// Compact controls for table rows and the page header; 16px on phones so iOS doesn't zoom.
const SMALL = 'rounded-lg bg-[#0a0e1a] border border-white/15 focus:border-[#2dd4bf]/60 outline-none ' +
  'px-2 py-1 font-mono text-base md:text-xs text-[#f0ece4] placeholder:text-[#6b7594]'

function usd(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function monthLabel(m: string): string {
  return new Date(`${m}-01T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback
}

export default function SalesAdminPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [loadError, setLoadError] = useState('')
  const [toast, setToast] = useState<{ ok: boolean; msg: string } | null>(null)

  function load() {
    apiRequest<Overview>('/admin/sales')
      .then((d) => { setData(d); setLoadError('') })
      .catch((e) => setLoadError(errText(e, 'Could not load sales data.')))
  }
  useEffect(load, [])

  function say(ok: boolean, msg: string) {
    setToast({ ok, msg })
    setTimeout(() => setToast(null), 6000)
  }

  async function post(path: string, body: unknown, done?: string) {
    try {
      const res = await apiRequest<{ ok: boolean; message: string }>(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      say(true, res.message || done || 'Saved.')
      load()
      return true
    } catch (e) {
      say(false, errText(e, 'That did not save.'))
      return false
    }
  }

  const codes = useMemo(() => (data?.people ?? []).filter((p) => p.code).map((p) => p.code as string), [data])
  const totals = useMemo(() => {
    const t = { active: 0, accounts: 0, trial: 0, boats: 0, month: 0, all: 0 }
    for (const p of data?.people ?? []) {
      if (p.access) t.active++
      t.accounts += p.accounts
      t.trial += p.stages.trial ?? 0
      t.boats += p.boats_paying
      t.month += p.commission_this_month
      t.all += p.commission_total
    }
    return t
  }, [data])

  return (
    <Page
      title="Sales"
      description={<>Everyone selling RegKnot, the accounts credited to each, what they paid and what we owe. Commission is {data ? Math.round(data.rate * 100) : 25}% of what a credited account pays, for as long as it pays. An account is credited by the pilot code in its signup link unless you set it by hand below.</>}
      actions={data && <PayoutExport payouts={data.payouts} thisMonth={data.this_month} onError={(m) => say(false, m)} />}
    >
      {toast && (
        <div role="status" className={`mb-4 font-mono text-xs px-3 py-2 rounded-lg border ${toast.ok
          ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/30 text-[#2dd4bf]' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>
          {toast.msg}
        </div>
      )}
      {loadError && <Empty>{loadError}</Empty>}
      {!data && !loadError && <Skeleton className="h-[240px]" />}
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-8">
            {([
              ['Salespeople', String(totals.active)],
              ['Accounts credited', String(totals.accounts)],
              ['Fleets in trial', String(totals.trial)],
              ['Boats paying', String(totals.boats)],
              [`Commission, ${monthLabel(data.this_month)}`, usd(totals.month)],
              ['Commission to date', usd(totals.all)],
            ] as const).map(([label, value]) => (
              <div key={label} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3">
                <p className={`font-mono text-[10px] ${TEXT_MUTED} uppercase tracking-wider`}>{label}</p>
                <p className="font-mono text-2xl font-bold text-[#f0ece4] mt-1 tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          <Section title="Checks" description="Anything that would make a salesperson's link, credit or commission wrong.">
            {data.issues.length === 0 ? (
              <Empty tone="good">Everything lines up.</Empty>
            ) : (
              <ul className="flex flex-col gap-2">
                {data.issues.map((i, n) => (
                  <li key={n} className="bg-[#111827] rounded-xl border border-white/8 px-4 py-3 flex flex-wrap items-start gap-3">
                    <Pill tone={i.level === 'error' ? 'red' : i.level === 'warn' ? 'amber' : 'gray'}>{i.level}</Pill>
                    <p className="font-mono text-xs text-[#f0ece4]/85 flex-1 min-w-[240px] leading-relaxed">{i.text}</p>
                    {i.fix === 'credit_owner' && i.user_id && i.code && (
                      <button className={btn.secondary}
                        onClick={() => post('/admin/sales/credit', { user_id: i.user_id, credit: i.code })}>
                        Credit the owner to {i.code}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Salespeople">
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
              {data.people.map((p) => (
                <PersonCard key={p.user_id} p={p} thisMonth={data.this_month} lastMonth={data.last_month}
                  onAccess={(active) => post(`/admin/sales/people/${p.user_id}/access`, { active })}
                  onImported={(msg, ok) => { say(ok, msg); if (ok) load() }} />
              ))}
              <AddPerson onAdd={(body) => post('/admin/sales/people', body)} />
            </div>
          </Section>

          <Section title="Credited accounts"
            description="Every account that counts toward a salesperson, newest first. Change who it counts toward on the right."
            action={<CreditByEmail codes={codes} onCredit={(email, credit) => post('/admin/sales/credit', { email, credit })} />}>
            {data.accounts.length === 0 ? (
              <Empty>No credited accounts yet. A signup through a salesperson&apos;s link shows up here.</Empty>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-white/8">
                <table className="w-full font-mono text-xs" style={{ minWidth: 860 }}>
                  <thead className={`text-left ${TEXT_MUTED}`}>
                    <tr className="border-b border-white/8">
                      {['Signed up', 'Account', 'Credited to', 'Stage', 'Questions', 'Fleets', 'Paid us', 'Credit'].map((h) => (
                        <th key={h} className="px-3 py-2 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.accounts.map((a) => (
                      <tr key={a.user_id} className="border-b border-white/5 last:border-0 align-top">
                        <td className="px-3 py-2 whitespace-nowrap text-[#f0ece4]/70">{fmtDate(a.created_at)}</td>
                        <td className="px-3 py-2">
                          <div className="text-[#f0ece4]/90">{a.name ?? '—'}{a.internal && <span className={TEXT_MUTED}> · internal</span>}</div>
                          <div className={TEXT_MUTED}>{a.email}</div>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className="text-[#2dd4bf]">{a.code}</span>{' '}
                          <Pill tone={a.credit === 'admin' ? 'purple' : 'gray'} title={a.signup_src ? `signup link: ${a.signup_src}` : 'no signup link'}>
                            {a.credit === 'admin' ? 'set by hand' : 'link'}
                          </Pill>
                        </td>
                        <td className="px-3 py-2"><Pill tone={STAGE[a.stage]?.tone ?? 'gray'}>{STAGE[a.stage]?.label ?? a.stage}</Pill></td>
                        <td className="px-3 py-2 text-[#f0ece4]/70">{a.questions}</td>
                        <td className="px-3 py-2">
                          {a.fleets.length === 0 ? <span className={TEXT_MUTED}>none</span> : a.fleets.map((f) => (
                            <div key={f.id} className="mb-0.5">
                              <span className="text-[#f0ece4]/85">{f.name}</span>
                              <span className={TEXT_MUTED}> · {f.boats} boat{f.boats === 1 ? '' : 's'} · {f.paying ? 'paying' : f.status === 'trialing' || f.status === 'card_pending' ? `trial to ${fmtDate(f.trial_ends_at)}${f.trial_custom ? '' : ' (standard)'}` : f.status}</span>
                            </div>
                          ))}
                        </td>
                        <td className="px-3 py-2 text-[#f0ece4]/80 tabular-nums">{a.paid_total ? usd(a.paid_total) : '—'}</td>
                        <td className="px-3 py-2">
                          <select aria-label={`Credit for ${a.email}`} className={SMALL}
                            value={a.credit === 'admin' ? a.code : '__link'}
                            onChange={(e) => {
                              const v = e.target.value
                              post('/admin/sales/credit', { user_id: a.user_id, credit: v === '__link' ? null : v === '__none' ? '' : v })
                            }}>
                            <option value="__link">From the link</option>
                            {codes.map((c) => <option key={c} value={c}>{c}</option>)}
                            <option value="__none">No one</option>
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section title="Payouts by month"
            description="What credited accounts paid us each month, from our billing records, and the commission on it. Refunds come off in the monthly statement (scripts/sales/commission_report.py, from Stripe).">
            {data.payouts.length === 0 ? (
              <Empty>Nothing paid yet.</Empty>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-white/8 max-w-2xl">
                <table className="w-full font-mono text-xs">
                  <thead className={`text-left ${TEXT_MUTED}`}>
                    <tr className="border-b border-white/8">
                      <th className="px-3 py-2 font-normal">Month</th>
                      <th className="px-3 py-2 font-normal">Salesperson</th>
                      <th className="px-3 py-2 font-normal text-right">Paid us</th>
                      <th className="px-3 py-2 font-normal text-right">Commission</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.payouts.map((r) => (
                      <tr key={`${r.month}-${r.code}`} className="border-b border-white/5 last:border-0">
                        <td className="px-3 py-2 text-[#f0ece4]/80">{monthLabel(r.month)}</td>
                        <td className="px-3 py-2 text-[#2dd4bf]">{r.code}</td>
                        <td className="px-3 py-2 text-right text-[#f0ece4]/70 tabular-nums">{usd(r.revenue)}</td>
                        <td className="px-3 py-2 text-right text-[#f0ece4] tabular-nums">{usd(r.commission)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </Page>
  )
}

function PersonCard({ p, thisMonth, lastMonth, onAccess, onImported }: {
  p: Salesperson
  thisMonth: string
  lastMonth: string
  onAccess: (active: boolean) => void
  onImported: (msg: string, ok: boolean) => void
}) {
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)

  async function copy() {
    if (!p.short_link) return
    try {
      await navigator.clipboard.writeText(`https://${p.short_link}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      prompt('Copy the link:', `https://${p.short_link}`)
    }
  }

  async function importLeads(file: File) {
    setBusy(true)
    const form = new FormData()
    form.append('file', file)
    form.append('niche', 'towing')
    try {
      const r = await apiUpload<{ inserted: number; updated: number; skipped: number; rows: number }>(
        `/admin/sales/people/${p.user_id}/leads/import`, form)
      onImported(`${p.name ?? p.email}: ${r.inserted} leads added, ${r.updated} updated, ${r.skipped} skipped of ${r.rows} rows (towing only).`, true)
    } catch (e) {
      onImported(errText(e, 'The import failed.'), false)
    } finally {
      setBusy(false)
    }
  }

  const pilot = p.pilot_active === null ? <Pill tone="red">no pilot code</Pill>
    : p.pilot_active ? <Pill tone="teal">{p.trial_days} days</Pill> : <Pill tone="amber">paused</Pill>

  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p className="font-display text-lg font-bold text-[#f0ece4] truncate">{p.name ?? p.email}</p>
          <p className={`font-mono text-[11px] ${TEXT_MUTED} truncate`}>{p.email}</p>
        </div>
        <Pill tone={p.access ? 'teal' : 'gray'}>{p.access ? 'access on' : 'access off'}</Pill>
      </div>

      <div className="font-mono text-xs flex flex-wrap items-center gap-2 mb-3">
        <span className="text-[#2dd4bf]">{p.code ?? 'no code'}</span>
        {p.code && pilot}
        {p.short_link && (
          <button className="text-[#8b93ad] hover:text-[#f0ece4] underline-offset-2 hover:underline" onClick={copy}>
            {copied ? 'copied' : p.short_link}
          </button>
        )}
      </div>

      <div className="grid grid-cols-4 gap-2 mb-3">
        {(['signed_up', 'asked', 'trial', 'paying'] as const).map((s) => (
          <div key={s} className="rounded-lg bg-[#0a0e1a] border border-white/5 px-2 py-1.5">
            <p className={`font-mono text-[9px] uppercase tracking-wider ${TEXT_MUTED}`}>{STAGE[s].label}</p>
            <p className="font-mono text-lg font-bold text-[#f0ece4] tabular-nums">{p.stages[s] ?? 0}</p>
          </div>
        ))}
      </div>

      <dl className="font-mono text-xs grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 mb-3">
        <dt className={TEXT_MUTED}>Boats paying</dt><dd className="text-[#f0ece4]/85 tabular-nums">{p.boats_paying}</dd>
        <dt className={TEXT_MUTED}>Commission</dt>
        <dd className="text-[#f0ece4]/85">
          {usd(p.commission_this_month)} {monthLabel(thisMonth)} · {usd(p.commission_last_month)} {monthLabel(lastMonth)} · {usd(p.commission_total)} to date
          <span className={TEXT_MUTED}> (on {usd(p.revenue_total)})</span>
        </dd>
        <dt className={TEXT_MUTED}>Leads</dt>
        <dd className="text-[#f0ece4]/85">
          {p.leads_total === 0 ? <span className={TEXT_MUTED}>none yet</span> : (
            <>
              {p.leads_total}: {LEAD_ORDER.filter((s) => p.leads_by_status[s]).map((s) => `${p.leads_by_status[s]} ${s}`).join(', ')}
              {p.leads_overdue > 0 && <span className="text-amber-400"> · {p.leads_overdue} overdue</span>}
            </>
          )}
        </dd>
        <dt className={TEXT_MUTED}>Last lead update</dt><dd className="text-[#f0ece4]/70">{fmtRelative(p.last_lead_update)}</dd>
        <dt className={TEXT_MUTED}>Last signed in</dt><dd className="text-[#f0ece4]/70">{fmtRelative(p.last_seen)}</dd>
      </dl>

      <div className="flex flex-wrap gap-2">
        {p.code && <Link className={btn.quiet} href={`/sales?code=${encodeURIComponent(p.code)}`}>Their view</Link>}
        {p.code && <Link className={btn.quiet} href={`/sales/leads?code=${encodeURIComponent(p.code)}`}>Their leads</Link>}
        <label className={`${btn.quiet} cursor-pointer ${busy ? 'opacity-50 pointer-events-none' : ''}`}>
          {busy ? 'Importing…' : 'Import leads (CSV)'}
          <input type="file" accept=".csv,text/csv" className="sr-only" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) importLeads(f) }} />
        </label>
        <button className={p.access ? btn.danger : btn.secondary}
          onClick={() => {
            if (p.access && !confirm(`Turn off ${p.name ?? p.email}'s sales access? Their code stays theirs: accounts stay credited and commission keeps counting.`)) return
            onAccess(!p.access)
          }}>
          {p.access ? 'Turn access off' : 'Turn access on'}
        </button>
      </div>
    </Card>
  )
}

function AddPerson({ onAdd }: { onAdd: (body: { email: string; code: string; trial_days: number }) => Promise<boolean> }) {
  const [form, setForm] = useState({ email: '', code: '', trial_days: 90 })
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    const ok = await onAdd(form)
    setBusy(false)
    if (ok) setForm({ email: '', code: '', trial_days: 90 })
  }

  return (
    <Card title="Add a salesperson" subtitle="They sign up first (any page). Their code is their link: regknots.com/fleet?src=pilot-<code>.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="font-mono text-xs text-[#f0ece4]/80">Their account email
          <input className={`${INPUT} mt-1`} type="email" required value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="name@example.com" />
        </label>
        <label className="font-mono text-xs text-[#f0ece4]/80">Code
          <input className={`${INPUT} mt-1`} required maxLength={39} value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="jordan" />
        </label>
        <label className="font-mono text-xs text-[#f0ece4]/80">Trial days for fleets from their link
          <input className={`${INPUT} mt-1`} type="number" min={1} max={365} value={form.trial_days}
            onChange={(e) => setForm({ ...form, trial_days: parseInt(e.target.value, 10) || 90 })} />
        </label>
        <p className={`font-mono text-[11px] ${TEXT_MUTED}`}>If the pilot code exists already (Pilots), it is used as is.</p>
        <button type="submit" className={btn.primary} disabled={busy}>{busy ? 'Adding…' : 'Add salesperson'}</button>
      </form>
    </Card>
  )
}

function CreditByEmail({ codes, onCredit }: { codes: string[]; onCredit: (email: string, credit: string) => Promise<boolean> }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  if (codes.length === 0) return null
  return (
    <form className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault()
        if (await onCredit(email, code || codes[0])) setEmail('')
      }}>
      <input className={`${SMALL} w-56`} type="email" required placeholder="credit an account by email"
        value={email} onChange={(e) => setEmail(e.target.value)} />
      <select className={SMALL} value={code || codes[0]} onChange={(e) => setCode(e.target.value)}
        aria-label="Salesperson code">
        {codes.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <button type="submit" className={btn.secondary}>Credit</button>
    </form>
  )
}

function PayoutExport({ payouts, thisMonth, onError }: { payouts: PayoutRow[]; thisMonth: string; onError: (m: string) => void }) {
  const months = useMemo(() => Array.from(new Set([thisMonth, ...payouts.map((p) => p.month)])).sort().reverse(), [payouts, thisMonth])
  const [month, setMonth] = useState(months[0] ?? thisMonth)
  return (
    <div className="flex items-center gap-2">
      <select className={SMALL} value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Payout month">
        {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
      </select>
      <button className={btn.secondary}
        onClick={() => apiDownload(`/admin/sales/payouts.csv?month=${month}`, `sales-payouts-${month}.csv`)
          .catch((e) => onError(errText(e, 'The download failed.')))}>
        Payouts CSV
      </button>
    </div>
  )
}
