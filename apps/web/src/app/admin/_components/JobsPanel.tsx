'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

// ── Jobs tab: one-click Celery triggers ─────────────────────────────────────

export function JobsTab() {
  const [result, setResult] = useState<{ msg: string; ok: boolean } | null>(null)
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [beatSchedule, setBeatSchedule] = useState<Record<string, { task: string; schedule: string }>>({})

  useEffect(() => {
    apiRequest<{ beat_schedule: typeof beatSchedule }>('/admin/jobs/beat-schedule')
      .then((r) => setBeatSchedule(r.beat_schedule || {}))
      .catch(() => {})
  }, [])

  async function run(key: string, path: string, method: string = 'POST') {
    setLoadingKey(key)
    setResult(null)
    try {
      const r = await apiRequest<{ ok: boolean; details?: string; sent?: number }>(path, { method })
      setResult({ msg: r.details || `Sent: ${r.sent ?? ''}`, ok: r.ok !== false })
    } catch (e) {
      setResult({ msg: e instanceof Error ? e.message : 'Failed', ok: false })
    } finally {
      setLoadingKey(null)
    }
  }

  return (
    <div className="mb-8 flex flex-col gap-4">
      {result && (
        <div className={`rounded-xl border p-3 ${result.ok ? 'bg-[#2dd4bf]/5 border-[#2dd4bf]/30' : 'bg-red-500/10 border-red-500/30'}`}>
          <p className={`font-mono text-xs ${result.ok ? 'text-[#2dd4bf]' : 'text-red-400'}`}>{result.msg}</p>
        </div>
      )}

      {/* 2026-09-29 — the Run Ingest button is gone: it spawned the ingest in a
          directory that doesn't exist (apps/packages/ingest), so it never ran,
          and it bypassed scripts/run_ingest.sh, the memory-capped wrapper that
          every ad-hoc ingest must use (CLAUDE.md). */}
      <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
        <p className="font-mono text-[10px] text-[#8b93ad] uppercase tracking-wider">Corpus ingest</p>
        <p className="font-mono text-xs text-[#f0ece4]/80 leading-relaxed">
          Celery Beat refreshes the CFR titles (33, 46, 49 and the scoped parts of 40, 47, 50, 29) and
          NVICs every week, USCG bulletins from the GovDelivery feed daily, and safety alerts, CG-CVC,
          TVNCOE, VTS / waterways and NMC checklists on the 5th of each month. For anything else, run
          {' '}<code className="text-[#2dd4bf]">scripts/run_ingest.sh</code> on the server; it runs the job in a
          memory-capped systemd unit so a runaway can&apos;t take the box down.
        </p>
      </div>

      {/* Celery job triggers */}
      <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
        <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">Scheduled Jobs (manual trigger)</p>
        <JobRow
          label="Credential expiry reminders"
          description="Runs for admin's own credentials only"
          previewPath="/admin/test-job/preview-credential-reminders"
          sendPath="/admin/test-job/credential-reminders"
          loadingKey={loadingKey}
          run={run}
          previewRender={(data: { pending_reminders?: unknown[]; total?: number }) => (
            <p className="font-mono text-[10px] text-[#6b7594]">
              {data.total ?? 0} pending reminders across all users
            </p>
          )}
        />
        <JobRow
          label="Regulation digest"
          description="Sends a digest to admin only"
          previewPath="/admin/test-job/preview-digest"
          sendPath="/admin/test-job/regulation-digest"
          loadingKey={loadingKey}
          run={run}
          previewRender={(data: { notification_count?: number; recipient_count?: number }) => (
            <p className="font-mono text-[10px] text-[#6b7594]">
              {data.notification_count ?? 0} notifications, {data.recipient_count ?? 0} eligible users
            </p>
          )}
        />
        <JobRow
          label="IMO amendment check"
          description="Scrapes IMO sources for new MSC refs"
          previewPath={null}
          sendPath="/admin/jobs/imo-amendment-check"
          loadingKey={loadingKey}
          run={run}
        />
        <JobRow
          label="NMC document check"
          description="Scrapes NMC for new policy letters, memos, credentialing guidance"
          previewPath={null}
          sendPath="/admin/jobs/nmc-check"
          loadingKey={loadingKey}
          run={run}
        />
      </div>

      {/* Beat schedule */}
      <div className="bg-[#111827] rounded-xl border border-white/8 p-4 flex flex-col gap-2">
        <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider">Celery Beat Schedule</p>
        {Object.keys(beatSchedule).length === 0 ? (
          <p className="font-mono text-[10px] text-[#6b7594]">No schedule info available.</p>
        ) : (
          <table className="w-full font-mono text-[10px]">
            <thead>
              <tr className="border-b border-white/8">
                <th className="text-left py-1 text-[#6b7594]">Name</th>
                <th className="text-left py-1 text-[#6b7594]">Task</th>
                <th className="text-left py-1 text-[#6b7594]">Schedule</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(beatSchedule).map(([name, entry]) => (
                <tr key={name} className="border-b border-white/5">
                  <td className="py-1 text-[#f0ece4]/80">{name}</td>
                  <td className="py-1 text-[#2dd4bf]/70">{entry.task}</td>
                  <td className="py-1 text-[#6b7594]">{entry.schedule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

interface JobRowProps {
  label: string
  description: string
  previewPath: string | null
  sendPath: string
  loadingKey: string | null
  run: (key: string, path: string, method?: string) => Promise<void>
  previewRender?: (data: Record<string, unknown>) => React.ReactNode
}

function JobRow({ label, description, previewPath, sendPath, loadingKey, run, previewRender }: JobRowProps) {
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  async function fetchPreview() {
    if (!previewPath) return
    setPreviewLoading(true)
    try {
      const r = await apiRequest<Record<string, unknown>>(previewPath)
      setPreview(r)
    } catch {
      // ignore
    } finally {
      setPreviewLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 py-2 border-b border-white/5 last:border-0">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-col min-w-0 flex-1">
          <p className="font-mono text-sm text-[#f0ece4]">{label}</p>
          <p className="font-mono text-[10px] text-[#6b7594]">{description}</p>
          {preview && previewRender && (
            <div className="mt-1">{previewRender(preview)}</div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {previewPath && (
            <button
              onClick={fetchPreview}
              disabled={previewLoading}
              className="font-mono text-[10px] text-[#6b7594] hover:text-[#2dd4bf] disabled:opacity-40"
            >
              {previewLoading ? '…' : 'Preview'}
            </button>
          )}
          <button
            onClick={() => run(sendPath, sendPath)}
            disabled={loadingKey === sendPath}
            className="font-mono text-[10px] font-bold text-[#2dd4bf]
              border border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10
              disabled:opacity-50 rounded px-3 py-1 transition-colors duration-150"
          >
            {loadingKey === sendPath ? 'Running…' : 'Run'}
          </button>
        </div>
      </div>
    </div>
  )
}
