'use client'

// 2026-09-29 — moved out of the single-page /admin (app/admin/page.tsx) unchanged
// apart from imports and exports.

import { useEffect, useState } from 'react'
import { apiRequest } from '@/lib/api'

// ── Email catalog section (inside Email tab) ────────────────────────────────

interface EmailCatalogEntry { type: string; label: string }
type EmailCatalog = Record<string, EmailCatalogEntry[]>

export interface EmailCatalogProps {
  emailSending: string | null
  emailToast: { msg: string; ok: boolean } | null
  sendTestEmail: (type: string) => Promise<void>
}

export function EmailCatalogSection({ emailSending, emailToast, sendTestEmail }: EmailCatalogProps) {
  const [catalog, setCatalog] = useState<EmailCatalog>({})

  useEffect(() => {
    apiRequest<EmailCatalog>('/admin/test-email/catalog')
      .then(setCatalog)
      .catch(() => setCatalog({}))
  }, [])

  return (
    <div className="mb-8">
      <h2 className="font-display text-lg font-bold text-[#f0ece4] tracking-wide mb-3">Email Testing</h2>
      <p className="font-mono text-xs text-[#6b7594] mb-4">
        Send test emails to your admin address. Covers all {Object.values(catalog).reduce((n, arr) => n + arr.length, 0)} wired email templates.
      </p>

      <div className="flex flex-col gap-4">
        {Object.entries(catalog).map(([category, entries]) => (
          <div key={category} className="bg-[#111827] rounded-xl border border-white/8 p-4">
            <p className="font-mono text-[10px] text-[#6b7594] uppercase tracking-wider mb-3">{category}</p>
            <div className="flex flex-wrap gap-2">
              {entries.map(({ type, label }) => (
                <button
                  key={type}
                  onClick={() => sendTestEmail(type)}
                  disabled={emailSending === type}
                  className="font-mono text-xs font-bold px-3 py-1.5 rounded-md border border-[#2dd4bf]/30
                    text-[#2dd4bf] hover:bg-[#2dd4bf]/10 disabled:opacity-50
                    disabled:cursor-not-allowed transition-colors"
                >
                  {emailSending === type ? 'Sending…' : label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {emailToast && (
        <div className={`mt-3 font-mono text-xs px-3 py-2 rounded-lg border ${
          emailToast.ok
            ? 'bg-[#2dd4bf]/10 border-[#2dd4bf]/30 text-[#2dd4bf]'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>
          {emailToast.msg}
        </div>
      )}
    </div>
  )
}
