'use client'

// 2026-10-16 — the salesperson's overview: their link, the accounts that came
// through it and where each is, and what those accounts have paid (× rate).

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { useSales } from './_lib/context'

interface Fleet { id: string; name: string; status: string; created_at: string; trial_ends_at: string | null; paying: boolean; boats: number }
interface Signup { id: string; full_name: string | null; email: string; created_at: string; questions: number; fleets: Fleet[]; stage: string }
interface Commission { rate: number; months: { month: string; revenue: number; commission: number }[]; total_revenue: number; total_commission: number }

const STAGE: Record<string, { label: string; cls: string }> = {
  signed_up: { label: 'Signed up', cls: 'bg-white/10 text-[#f0ece4]/80' },
  asked: { label: 'Asked a question', cls: 'bg-sky-950/60 text-sky-300' },
  trial: { label: 'Fleet trial', cls: 'bg-amber-950/60 text-amber-300' },
  paying: { label: 'Paying', cls: 'bg-emerald-950/60 text-emerald-300' },
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : ''
}
function money(n: number): string {
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
}

export default function SalesOverview() {
  const { me, codeQuery } = useSales()
  const [signups, setSignups] = useState<Signup[] | null>(null)
  const [commission, setCommission] = useState<Commission | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!me) return
    apiRequest<Signup[]>(`/sales/signups${codeQuery}`).then(setSignups).catch(() => setSignups([]))
    apiRequest<Commission>(`/sales/commission${codeQuery}`).then(setCommission).catch(() => setCommission(null))
  }, [me, codeQuery])

  if (!me) return <p className="font-mono text-sm text-[#8a94ad]">Loading…</p>

  const counts = { all: signups?.length ?? 0, trial: 0, paying: 0, boats: 0 }
  for (const s of signups ?? []) {
    if (s.stage === 'trial') counts.trial++
    if (s.stage === 'paying') counts.paying++
    counts.boats += s.fleets.filter((f) => f.paying).reduce((a, f) => a + f.boats, 0)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(`https://${me!.short_link}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked */ }
  }

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-[#2dd4bf]/30 bg-[#0d1225] p-5">
        <p className="font-mono text-[10px] text-[#2dd4bf] uppercase tracking-[0.25em] mb-2">Your link</p>
        <div className="flex flex-wrap items-center gap-3">
          <code className="font-mono text-lg text-[#f0ece4]">{me.short_link}</code>
          <button onClick={copy} className="font-mono text-xs font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-lg px-3 py-1.5 hover:brightness-110">
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <p className="font-mono text-xs text-[#6b7594] mt-2">
          Every fleet that starts here is yours{me.trial_days ? `, with ${me.trial_days} days free` : ''}. Commission: {Math.round(me.rate * 100)}% of what they pay, for as long as they pay.
        </p>
      </section>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          ['Signups', counts.all], ['In a fleet trial', counts.trial], ['Paying', counts.paying], ['Boats paying', counts.boats],
        ].map(([label, n]) => (
          <div key={label as string} className="rounded-xl border border-white/8 bg-[#111827] px-4 py-3">
            <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">{label}</p>
            <p className="font-display text-3xl font-bold text-[#f0ece4]">{signups ? n : '–'}</p>
          </div>
        ))}
      </section>

      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-3">Signups from your link</h2>
        {!signups ? <p className="font-mono text-sm text-[#8a94ad]">Loading…</p> : signups.length === 0 ? (
          <p className="font-mono text-sm text-[#8a94ad]">Nobody yet. The first one is probably you: sign up through your own link to test it.</p>
        ) : (
          <div className="rounded-xl border border-white/8 overflow-auto">
            <table className="w-full text-left font-mono text-xs" style={{ minWidth: 720 }}>
              <thead><tr className="bg-[#1a1d24] text-[#2dd4bf]">
                {['Signed up', 'Who', 'Stage', 'Questions', 'Fleets'].map((h) => <th key={h} className="px-3 py-2.5 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {signups.map((s, i) => (
                  <tr key={s.id} className={`border-t border-white/5 align-top ${i % 2 ? 'bg-[#0f1629]' : 'bg-[#111827]'}`}>
                    <td className="px-3 py-2 whitespace-nowrap text-[#8b93ad]">{fmtDate(s.created_at)}</td>
                    <td className="px-3 py-2"><div className="text-[#f0ece4]/90">{s.full_name ?? '—'}</div><div className="text-[#8b93ad]">{s.email}</div></td>
                    <td className="px-3 py-2 whitespace-nowrap"><span className={`rounded px-2 py-0.5 ${STAGE[s.stage]?.cls ?? ''}`}>{STAGE[s.stage]?.label ?? s.stage}</span></td>
                    <td className="px-3 py-2 text-[#8b93ad]">{s.questions}</td>
                    <td className="px-3 py-2">
                      {s.fleets.length === 0 ? <span className="text-[#6b7594]">none yet</span> : s.fleets.map((f) => (
                        <div key={f.id} className="mb-1">
                          <span className="text-[#f0ece4]/90">{f.name}</span>
                          <span className="text-[#8b93ad]"> · {f.boats} boat{f.boats === 1 ? '' : 's'} · {f.paying ? 'paying' : f.trial_ends_at ? `trial to ${fmtDate(f.trial_ends_at)}` : f.status}</span>
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-1">Commission</h2>
        <p className="font-mono text-xs text-[#6b7594] mb-3">What accounts from your link have paid us, by month, times {commission ? Math.round(commission.rate * 100) : 25}%. Refunds are netted in the monthly statement.</p>
        {!commission || commission.months.length === 0 ? (
          <p className="font-mono text-sm text-[#8a94ad]">Nothing paid yet.</p>
        ) : (
          <table className="font-mono text-sm">
            <thead><tr className="text-[#2dd4bf] text-xs"><th className="text-left pr-6 py-1">Month</th><th className="text-right pr-6">Revenue</th><th className="text-right">Commission</th></tr></thead>
            <tbody>
              {commission.months.map((m) => (
                <tr key={m.month}><td className="pr-6 py-1 text-[#f0ece4]/85">{m.month}</td><td className="text-right pr-6 text-[#8b93ad]">{money(m.revenue)}</td><td className="text-right text-[#f0ece4]">{money(m.commission)}</td></tr>
              ))}
              <tr className="border-t border-white/10 font-bold"><td className="pr-6 py-1">Total</td><td className="text-right pr-6 text-[#8b93ad]">{money(commission.total_revenue)}</td><td className="text-right text-[#2dd4bf]">{money(commission.total_commission)}</td></tr>
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
