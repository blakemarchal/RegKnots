'use client'

// 2026-09-29 — a crash on one admin page stays inside that page. Without this
// boundary it reached global-error, which replaces the whole document, so the
// sidebar went with it and the only way out was a reload.
import * as Sentry from '@sentry/nextjs'
import Link from 'next/link'
import { useEffect } from 'react'
import { TEXT_MUTED, btn } from './_components/ui'

export default function AdminError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { Sentry.captureException(error) }, [error])
  return (
    <div className="px-4 md:px-8 py-6 md:py-8 max-w-[1500px] mx-auto">
      <div className="bg-[#111827] rounded-xl border border-red-500/30 p-5 md:p-6 max-w-2xl">
        <p className="font-mono text-[11px] uppercase tracking-wider text-red-400">This page hit an error</p>
        <p className="font-mono text-sm text-[#f0ece4] mt-2 break-words">{error.message || 'Unknown error'}</p>
        <p className={`font-mono text-xs ${TEXT_MUTED} mt-2`}>
          It has been sent to Sentry{error.digest ? ` (digest ${error.digest})` : ''}. The rest of the admin still works.
        </p>
        <div className="flex flex-wrap gap-2 mt-4">
          <button onClick={reset} className={btn.primary}>Try again</button>
          <Link href="/admin" className={btn.secondary}>Dashboard</Link>
        </div>
      </div>
    </div>
  )
}
