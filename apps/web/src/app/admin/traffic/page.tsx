'use client'

// Sprint D6.7 — Traffic analytics page. Reads from /admin/traffic which
// rolls up Caddy access logs server-side. No GeoIP, no client tracking,
// no third-party services. Cost: $0.

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

interface PageRow { path: string; count: number; unique_ips: number }
interface ApiRow { path: string; count: number; unique_ips: number }
interface RefRow { host: string; count: number; unique_ips: number }
interface UtmRow { source: string; count: number; unique_ips: number }
interface CampaignRow { campaign: string; count: number }
interface StatusRow { status: number; count: number }
interface DayRow { day: string; human: number; bot: number }
interface SlowRow { ts: string; uri: string; duration_ms: number; status: number }

interface TrafficSummary {
  since: string
  until: string
  log_files_scanned: string[]
  total_requests: number
  bot_requests: number
  human_requests: number
  unique_human_ips: number
  top_pages: PageRow[]
  top_api: ApiRow[]
  top_referrers: RefRow[]
  utm_sources: UtmRow[]
  utm_campaigns: CampaignRow[]
  status_codes: StatusRow[]
  by_day: DayRow[]
  slow_requests: SlowRow[]
}

const DAY_OPTIONS: number[] = [1, 7, 14, 30]

export default function AdminTrafficPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#0a0e1a] text-[#f0ece4]">
        <AppHeader />
        <TrafficContent />
      </div>
    </AuthGuard>
  )
}

function TrafficContent() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)
  const isAdmin = user?.is_admin ?? false

  const [days, setDays] = useState(7)
  const [summary, setSummary] = useState<TrafficSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (hydrated && !isAdmin) {
      router.replace('/')
    }
  }, [hydrated, isAdmin, router])

  useEffect(() => {
    if (!hydrated || !isAdmin) return
    setLoading(true)
    setError(null)
    apiRequest<TrafficSummary>(`/admin/traffic?days=${days}`)
      .then((s) => { setSummary(s); setLoading(false) })
      .catch((e) => { setError(String(e?.message ?? e)); setLoading(false) })
  }, [days, hydrated, isAdmin])

  if (!hydrated || !isAdmin) return null

  return (
    <main className="max-w-7xl mx-auto px-5 py-6">
      <div className="flex items-baseline justify-between mb-5 gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-wide">Traffic</h1>
          <p className="font-mono text-xs text-[#6b7594] mt-1">
            Caddy access-log rollup. Refreshes every 5 minutes server-side.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/admin" className="font-mono text-xs text-[#2dd4bf] hover:underline">
            ← Admin
          </Link>
          <div className="flex gap-1">
            {DAY_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`font-mono text-xs px-3 py-1.5 rounded border transition-colors ${
                  days === d
                    ? 'bg-[#2dd4bf]/15 border-[#2dd4bf]/40 text-[#2dd4bf]'
                    : 'border-white/10 text-[#9ca5be] hover:bg-white/5'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <div className="font-mono text-sm text-[#6b7594] py-8 text-center">Loading…</div>
      )}
      {error && !loading && (
        <div className="font-mono text-sm text-red-400 py-4 px-4 bg-red-500/8 rounded border border-red-500/20">
          {error}
        </div>
      )}
      {!loading && summary && (
        <div className="flex flex-col gap-6">
          <Totals s={summary} />
          <ByDayChart rows={summary.by_day} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card title="Top pages (humans)">
              <CountTable
                rows={summary.top_pages.map(r => ({ key: r.path, count: r.count, sub: `${r.unique_ips} IP${r.unique_ips !== 1 ? 's' : ''}` }))}
                empty="No human page-views in this window."
              />
            </Card>
            <Card title="Top API (humans)">
              <CountTable
                rows={summary.top_api.map(r => ({ key: r.path, count: r.count, sub: `${r.unique_ips} IP${r.unique_ips !== 1 ? 's' : ''}` }))}
                empty="No API hits."
              />
            </Card>
            <Card title="External referrers">
              <CountTable
                rows={summary.top_referrers.map(r => ({ key: r.host, count: r.count, sub: `${r.unique_ips} IP${r.unique_ips !== 1 ? 's' : ''}` }))}
                empty="No external referrers — direct/in-app only."
              />
            </Card>
            <Card title="UTM sources">
              <CountTable
                rows={summary.utm_sources.map(r => ({ key: r.source, count: r.count, sub: `${r.unique_ips} IP${r.unique_ips !== 1 ? 's' : ''}` }))}
                empty="No tagged campaigns yet."
              />
            </Card>
            <Card title="UTM campaigns">
              <CountTable
                rows={summary.utm_campaigns.map(r => ({ key: r.campaign, count: r.count }))}
                empty="No tagged campaigns yet."
              />
            </Card>
            <Card title="Status codes">
              <CountTable
                rows={summary.status_codes.map(r => ({ key: String(r.status), count: r.count, sub: statusName(r.status) }))}
              />
            </Card>
          </div>
          <Card title="Slow human requests (>2s)">
            <SlowTable rows={summary.slow_requests} />
          </Card>
          <div className="font-mono text-[10px] text-[#6b7594] mt-2">
            Files scanned: {summary.log_files_scanned.join(', ') || '(none)'} ·{' '}
            Window: {fmtTs(summary.since)} → {fmtTs(summary.until)}
          </div>
        </div>
      )}
    </main>
  )
}

function Totals({ s }: { s: TrafficSummary }) {
  const cells = [
    { label: 'Human requests', value: s.human_requests.toLocaleString() },
    { label: 'Unique human IPs', value: s.unique_human_ips.toLocaleString() },
    { label: 'Bot requests', value: s.bot_requests.toLocaleString() },
    { label: 'Total requests', value: s.total_requests.toLocaleString() },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {cells.map(c => (
        <div key={c.label} className="bg-white/3 border border-white/8 rounded-lg px-4 py-3">
          <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b7594]">
            {c.label}
          </div>
          <div className="font-display text-2xl font-bold text-[#f0ece4] mt-1">
            {c.value}
          </div>
        </div>
      ))}
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white/3 border border-white/8 rounded-lg overflow-hidden">
      <header className="px-4 py-2.5 border-b border-white/8">
        <h2 className="font-mono text-xs uppercase tracking-wider text-[#9ca5be]">{title}</h2>
      </header>
      <div>{children}</div>
    </section>
  )
}

interface CountRow { key: string; count: number; sub?: string }

function CountTable({ rows, empty }: { rows: CountRow[]; empty?: string }) {
  if (rows.length === 0) {
    return (
      <div className="font-mono text-xs text-[#6b7594] px-4 py-6 text-center">
        {empty ?? 'No data.'}
      </div>
    )
  }
  const max = Math.max(...rows.map(r => r.count))
  return (
    <ul className="divide-y divide-white/5">
      {rows.map(r => (
        <li key={r.key} className="px-4 py-2.5 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="font-mono text-xs text-[#f0ece4] truncate">{r.key}</div>
            {r.sub && <div className="font-mono text-[10px] text-[#6b7594] mt-0.5">{r.sub}</div>}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-24 h-1 bg-white/5 rounded-full overflow-hidden">
              <div
                className="h-full bg-[#2dd4bf]/60 rounded-full"
                style={{ width: `${Math.max(4, (r.count / max) * 100)}%` }}
              />
            </div>
            <span className="font-mono text-xs text-[#f0ece4] tabular-nums w-10 text-right">
              {r.count}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}

function ByDayChart({ rows }: { rows: DayRow[] }) {
  if (rows.length === 0) {
    return null
  }
  const max = Math.max(...rows.map(r => r.human + r.bot), 1)
  return (
    <Card title="Daily volume (human / bot)">
      <div className="px-4 py-4 flex items-end gap-2 h-44 overflow-x-auto">
        {rows.map(r => {
          const totalH = (r.human / max) * 140
          const totalB = (r.bot / max) * 140
          return (
            <div key={r.day} className="flex flex-col items-center gap-1 flex-shrink-0 min-w-[44px]">
              <div className="flex flex-col-reverse w-7 h-[140px] justify-end">
                <div
                  className="w-full bg-[#2dd4bf]"
                  style={{ height: `${totalH}px` }}
                  title={`${r.human} human`}
                />
                <div
                  className="w-full bg-white/15"
                  style={{ height: `${totalB}px` }}
                  title={`${r.bot} bot`}
                />
              </div>
              <span className="font-mono text-[9px] text-[#6b7594]">
                {r.day.slice(5)}
              </span>
            </div>
          )
        })}
      </div>
      <div className="px-4 pb-3 flex gap-4 font-mono text-[10px] text-[#6b7594]">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 bg-[#2dd4bf] inline-block" /> human
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 bg-white/15 inline-block" /> bot
        </span>
      </div>
    </Card>
  )
}

function SlowTable({ rows }: { rows: SlowRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="font-mono text-xs text-[#6b7594] px-4 py-6 text-center">
        No slow requests in this window.
      </div>
    )
  }
  return (
    <ul className="divide-y divide-white/5">
      {rows.map((r, i) => (
        <li key={`${r.ts}-${i}`} className="px-4 py-2 flex items-center gap-3">
          <span className="font-mono text-[10px] text-[#6b7594] w-32 flex-shrink-0">
            {fmtTs(r.ts)}
          </span>
          <span className="font-mono text-xs text-[#f0ece4] flex-1 truncate">{r.uri}</span>
          <span className="font-mono text-[10px] text-[#6b7594] w-12 text-right">{r.status}</span>
          <span className="font-mono text-xs text-amber-300 w-16 text-right tabular-nums">
            {(r.duration_ms / 1000).toFixed(1)}s
          </span>
        </li>
      ))}
    </ul>
  )
}

function fmtTs(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function statusName(s: number): string {
  if (s >= 500) return 'server error'
  if (s >= 400) return 'client error'
  if (s >= 300) return 'redirect'
  if (s >= 200) return 'ok'
  return ''
}
