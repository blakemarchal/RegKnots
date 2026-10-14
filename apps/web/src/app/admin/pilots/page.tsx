'use client'

// 2026-10-14 — Wheelhouse pilots (apps/api/app/routers/admin_pilots.py).
// A pilot code is a sign-up link: an owner who registers from it gets the
// code's trial length on the workspace they create. Workspaces lists every
// fleet with its trial end; "Set trial" changes one directly.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'
import { fmtDate } from '../_lib/format'
import { Card, Empty, Page, Pill, Section, Skeleton, TEXT_MUTED, btn } from '../_components/ui'

interface PilotCode {
  code: string
  label: string
  trial_days: number
  active: boolean
  notes: string | null
  created_at: string
  link: string
  signups: number
  workspaces: number
}

interface AdminWorkspace {
  id: string
  name: string
  owner_email: string
  status: string
  internal_only: boolean
  created_at: string
  trial_ends_at: string
  trial_custom: boolean
  members: number
  pilot_code: string | null
}

const INPUT = 'w-full rounded-lg bg-[#0a0e1a] border border-white/15 focus:border-[#2dd4bf]/60 outline-none ' +
  'px-3 py-2 font-mono text-base md:text-sm text-[#f0ece4] placeholder:text-[#6b7594]'

export default function PilotsPage() {
  const [codes, setCodes] = useState<PilotCode[] | null>(null)
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[] | null>(null)
  const [form, setForm] = useState({ code: '', label: '', trial_days: 90, notes: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState<string | null>(null)

  function load() {
    apiRequest<PilotCode[]>('/admin/pilots').then(setCodes).catch(() => setCodes([]))
    apiRequest<AdminWorkspace[]>('/admin/workspaces').then(setWorkspaces).catch(() => setWorkspaces([]))
  }
  useEffect(load, [])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await apiRequest('/admin/pilots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, notes: form.notes || null }),
      })
      setForm({ code: '', label: '', trial_days: 90, notes: '' })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the code.')
    } finally {
      setBusy(false)
    }
  }

  async function toggle(c: PilotCode) {
    await apiRequest(`/admin/pilots/${c.code}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !c.active }),
    }).catch(() => alert('Could not update the code.'))
    load()
  }

  async function setTrial(w: AdminWorkspace) {
    const answer = prompt(`Trial length for "${w.name}", in days from creation (${fmtDate(w.created_at)}):`, '90')
    const days = answer ? parseInt(answer, 10) : NaN
    if (!days || days < 1 || days > 365) return
    await apiRequest(`/admin/workspaces/${w.id}/trial`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days }),
    }).catch((err) => alert(err instanceof Error ? err.message : 'Could not set the trial.'))
    load()
  }

  async function copy(link: string) {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(link)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      prompt('Copy the link:', link)
    }
  }

  return (
    <Page title="Pilots"
      description="A pilot code is a sign-up link. The owner who registers from it gets the code's trial on the Wheelhouse they create (the standard trial is 30 days). Set trial changes an existing workspace.">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] mb-8">
        <Card title="Pilot codes">
          {codes === null ? <Skeleton className="h-[120px] border-0" /> : codes.length === 0 ? (
            <Empty>No pilot codes yet.</Empty>
          ) : (
            <ul className="flex flex-col divide-y divide-white/5">
              {codes.map((c) => (
                <li key={c.code} className="py-3 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-sm text-[#f0ece4]">
                      {c.label} <span className={TEXT_MUTED}>· {c.code} · {c.trial_days} days</span>
                    </p>
                    <p className={`font-mono text-[11px] ${TEXT_MUTED} break-all mt-0.5`}>{c.link}</p>
                    <p className={`font-mono text-[11px] ${TEXT_MUTED} mt-0.5`}>
                      {c.signups} signed up · {c.workspaces} workspaces · created {fmtDate(c.created_at)}
                      {c.notes ? ` · ${c.notes}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Pill tone={c.active ? 'teal' : 'gray'}>{c.active ? 'active' : 'paused'}</Pill>
                    <button className={btn.quiet} onClick={() => copy(c.link)}>
                      {copied === c.link ? 'Copied' : 'Copy link'}
                    </button>
                    <button className={btn.quiet} onClick={() => toggle(c)}>{c.active ? 'Pause' : 'Resume'}</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="New pilot code">
          <form onSubmit={create} className="flex flex-col gap-3">
            <label className="font-mono text-xs text-[#f0ece4]/80">Company or campaign
              <input className={`${INPUT} mt-1`} value={form.label} required maxLength={120}
                onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Gulf Coast Towing" />
            </label>
            <label className="font-mono text-xs text-[#f0ece4]/80">Code (in the link)
              <input className={`${INPUT} mt-1`} value={form.code} required maxLength={39}
                onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="gulf-coast-towing" />
            </label>
            <label className="font-mono text-xs text-[#f0ece4]/80">Trial days
              <input className={`${INPUT} mt-1`} type="number" min={1} max={365} value={form.trial_days}
                onChange={(e) => setForm({ ...form, trial_days: parseInt(e.target.value, 10) || 90 })} />
            </label>
            <label className="font-mono text-xs text-[#f0ece4]/80">Notes (optional)
              <input className={`${INPUT} mt-1`} value={form.notes} maxLength={500}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Met at the TVNCOE meeting" />
            </label>
            {error && <p className="font-mono text-xs text-red-400">{error}</p>}
            <button type="submit" className={btn.primary} disabled={busy}>{busy ? 'Creating…' : 'Create code'}</button>
          </form>
        </Card>
      </div>

      <Section title="Workspaces" description="Every Wheelhouse, newest first, with when its trial ends.">
        {workspaces === null ? <Skeleton className="h-[160px]" /> : workspaces.length === 0 ? (
          <Empty>No workspaces yet.</Empty>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/8">
            <table className="w-full font-mono text-xs">
              <thead className={`text-left ${TEXT_MUTED}`}>
                <tr className="border-b border-white/8">
                  <th className="px-3 py-2 font-normal">Workspace</th>
                  <th className="px-3 py-2 font-normal">Owner</th>
                  <th className="px-3 py-2 font-normal">Status</th>
                  <th className="px-3 py-2 font-normal">Trial ends</th>
                  <th className="px-3 py-2 font-normal">Members</th>
                  <th className="px-3 py-2 font-normal" />
                </tr>
              </thead>
              <tbody>
                {workspaces.map((w) => (
                  <tr key={w.id} className="border-b border-white/5 last:border-0">
                    <td className="px-3 py-2 text-[#f0ece4]/90">
                      {w.name}
                      {w.internal_only && <span className={TEXT_MUTED}> · internal</span>}
                      {w.pilot_code && <span className="text-[#2dd4bf]"> · pilot {w.pilot_code}</span>}
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/70">{w.owner_email}</td>
                    <td className="px-3 py-2"><Pill tone={w.status === 'active' ? 'teal' : w.status === 'trialing' ? 'amber' : 'gray'}>{w.status}</Pill></td>
                    <td className="px-3 py-2 text-[#f0ece4]/70">
                      {w.status === 'trialing' || w.status === 'card_pending' ? fmtDate(w.trial_ends_at) : '—'}
                      {w.trial_custom && <span className={TEXT_MUTED}> (set)</span>}
                    </td>
                    <td className="px-3 py-2 text-[#f0ece4]/70">{w.members}</td>
                    <td className="px-3 py-2 text-right">
                      {(w.status === 'trialing' || w.status === 'card_pending') && (
                        <button className={btn.quiet} onClick={() => setTrial(w)}>Set trial</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </Page>
  )
}
