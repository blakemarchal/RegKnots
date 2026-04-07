'use client'

import { useState } from 'react'
import Link from 'next/link'
import type { NetworkDiagnosis } from '@/lib/networkError'
import { getNetworkErrorMessage, WHITELIST_TEXT } from '@/lib/networkError'

interface Props {
  diagnosis: NetworkDiagnosis
  onRetry?: () => void
}

/**
 * Branded error card shown when a network-level failure is detected.
 * For `firewall_blocked`, renders an expandable whitelist section with
 * copy-to-clipboard and email-support buttons.
 */
export function NetworkErrorCard({ diagnosis, onRetry }: Props) {
  const { title, message } = getNetworkErrorMessage(diagnosis)
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  function copyWhitelist() {
    navigator.clipboard.writeText(WHITELIST_TEXT).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  function emailSupport() {
    const subject = encodeURIComponent('Firewall Whitelist Request — RegKnot')
    const body = encodeURIComponent(WHITELIST_TEXT)
    window.open(`mailto:?subject=${subject}&body=${body}`, '_self')
  }

  return (
    <div className="rounded-xl border border-red-400/20 bg-red-400/5 p-4 flex flex-col gap-3">
      {/* Title row */}
      <div className="flex items-start gap-2.5">
        <span className="text-red-400 text-base leading-none mt-0.5" aria-hidden="true">⚠</span>
        <div className="min-w-0">
          <p className="font-display text-sm font-bold text-red-400 leading-tight">{title}</p>
          <p className="font-mono text-xs text-[--color-off-white]/70 mt-1.5 leading-relaxed">
            {message}
          </p>
        </div>
      </div>

      {/* Firewall-specific expandable section */}
      {diagnosis === 'firewall_blocked' && (
        <div className="ml-6 flex flex-col gap-2">
          <Link
            href="/whitelisting"
            className="font-mono text-[11px] text-[--color-teal] hover:underline"
          >
            View full whitelisting request →
          </Link>

          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="font-mono text-[11px] text-[--color-teal] hover:underline flex items-center gap-1 self-start"
          >
            <span className={`inline-block transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}>
              ▸
            </span>
            Quick whitelisting instructions
          </button>

          {expanded && (
            <div className="mt-1 bg-[--color-surface-dim] border border-white/8 rounded-lg p-3 flex flex-col gap-2.5">
              <pre className="font-mono text-[10px] text-[--color-off-white]/60 whitespace-pre-wrap leading-relaxed">
                {WHITELIST_TEXT}
              </pre>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={copyWhitelist}
                  className="font-mono text-[10px] text-[--color-teal] border border-[--color-teal]/30
                    hover:bg-[--color-teal]/10 rounded px-2.5 py-1 transition-colors"
                >
                  {copied ? 'Copied ✓' : 'Copy to clipboard'}
                </button>
                <button
                  type="button"
                  onClick={emailSupport}
                  className="font-mono text-[10px] text-[--color-muted] border border-white/10
                    hover:border-white/20 rounded px-2.5 py-1 transition-colors"
                >
                  Email to IT
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Retry button */}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="ml-6 self-start font-mono text-xs text-[--color-teal] hover:underline"
        >
          Try again →
        </button>
      )}
    </div>
  )
}
