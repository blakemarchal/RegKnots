'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

// ── System tab: health panel ────────────────────────────────────────────────

interface SystemHealth {
  timestamp: string
  environment: string
  database?: { ok: boolean; size?: string; active_connections?: number; pool_size?: number; pool_free?: number; latest_migration?: string; error?: string }
  redis?: { ok: boolean; used_memory_human?: string; error?: string }
  uploads?: { ok: boolean; path?: string; total_bytes?: number; file_count?: number; disk_free?: number; disk_total?: number; error?: string }
  sentry?: { ok: boolean; org?: string | null }
  api_keys?: { anthropic: boolean; openai: boolean; resend: boolean; stripe: boolean }
}

export function SystemTab() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchHealth = useCallback(async () => {
    setLoading(true)
    try {
      const r = await apiRequest<SystemHealth>('/admin/system/health')
      setHealth(r)
    } catch {
      setHealth(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchHealth() }, [fetchHealth])

  function formatBytes(b: number | undefined): string {
    if (b === undefined || b === null) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    let n = b
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
    return `${n.toFixed(1)} ${units[i]}`
  }

  function Status({ ok }: { ok: boolean | undefined }) {
    return (
      <span className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-[#2dd4bf]' : 'bg-red-400'}`} />
    )
  }

  return (
    <div className="mb-8 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">System Health</h2>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="font-mono text-xs text-[#2dd4bf] hover:underline disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {!health && !loading && (
        <p className="font-mono text-xs text-red-400">Failed to load health</p>
      )}
      {!health && loading && (
        <div className="bg-[#111827] rounded-xl border border-white/8 h-32 animate-pulse" />
      )}

      {health && (
        <>
          <p className="font-mono text-[10px] text-[#6b7594]">
            Snapshot taken {new Date(health.timestamp).toLocaleString()} · env: <strong className="text-[#f0ece4]">{health.environment}</strong>
          </p>

          {/* Database */}
          <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Status ok={health.database?.ok} />
              <p className="font-mono text-xs text-[#f0ece4] uppercase tracking-wider">Database</p>
            </div>
            {health.database?.ok ? (
              <div className="grid grid-cols-2 gap-2 font-mono text-[10px] text-[#f0ece4]/80">
                <div><span className="text-[#6b7594]">Size:</span> {health.database.size}</div>
                <div><span className="text-[#6b7594]">Active connections:</span> {health.database.active_connections}</div>
                <div><span className="text-[#6b7594]">Pool size:</span> {health.database.pool_size}</div>
                <div><span className="text-[#6b7594]">Pool free:</span> {health.database.pool_free}</div>
                <div className="col-span-2"><span className="text-[#6b7594]">Latest migration:</span> {health.database.latest_migration}</div>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-red-400">{health.database?.error || 'unreachable'}</p>
            )}
          </div>

          {/* Redis */}
          <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Status ok={health.redis?.ok} />
              <p className="font-mono text-xs text-[#f0ece4] uppercase tracking-wider">Redis</p>
            </div>
            {health.redis?.ok ? (
              <p className="font-mono text-[10px] text-[#f0ece4]/80">
                <span className="text-[#6b7594]">Memory:</span> {health.redis.used_memory_human}
              </p>
            ) : (
              <p className="font-mono text-[10px] text-red-400">{health.redis?.error || 'unreachable'}</p>
            )}
          </div>

          {/* Uploads / disk */}
          <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Status ok={health.uploads?.ok} />
              <p className="font-mono text-xs text-[#f0ece4] uppercase tracking-wider">Uploads / Disk</p>
            </div>
            {health.uploads?.ok ? (
              <div className="grid grid-cols-2 gap-2 font-mono text-[10px] text-[#f0ece4]/80">
                <div className="col-span-2"><span className="text-[#6b7594]">Path:</span> {health.uploads.path}</div>
                <div><span className="text-[#6b7594]">Upload size:</span> {formatBytes(health.uploads.total_bytes)}</div>
                <div><span className="text-[#6b7594]">Files:</span> {health.uploads.file_count}</div>
                <div><span className="text-[#6b7594]">Disk free:</span> {formatBytes(health.uploads.disk_free)}</div>
                <div><span className="text-[#6b7594]">Disk total:</span> {formatBytes(health.uploads.disk_total)}</div>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-red-400">{health.uploads?.error || 'unreachable'}</p>
            )}
          </div>

          {/* External services */}
          <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
            <p className="font-mono text-xs text-[#f0ece4] uppercase tracking-wider">External Services</p>
            <div className="grid grid-cols-2 gap-2 font-mono text-[10px] text-[#f0ece4]/80">
              <div className="flex items-center gap-2"><Status ok={health.sentry?.ok} /> Sentry {health.sentry?.org ? `(${health.sentry.org})` : ''}</div>
              <div className="flex items-center gap-2"><Status ok={health.api_keys?.anthropic} /> Anthropic API key</div>
              <div className="flex items-center gap-2"><Status ok={health.api_keys?.openai} /> OpenAI API key</div>
              <div className="flex items-center gap-2"><Status ok={health.api_keys?.resend} /> Resend API key</div>
              <div className="flex items-center gap-2"><Status ok={health.api_keys?.stripe} /> Stripe API key</div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
