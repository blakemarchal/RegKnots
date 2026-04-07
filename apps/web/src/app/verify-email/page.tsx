'use client'

import { useEffect, useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { useAuthStore } from '@/lib/auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type Status = 'loading' | 'success' | 'already' | 'invalid' | 'error'

function VerifyEmailInner() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const refreshAuth = useAuthStore((s) => s.refreshAuth)

  const [status, setStatus] = useState<Status>('loading')

  useEffect(() => {
    if (!token) {
      setStatus('invalid')
      return
    }
    let cancelled = false

    async function run() {
      try {
        const res = await fetch(
          `${API_URL}/auth/verify-email?token=${encodeURIComponent(token)}`,
          { method: 'GET' },
        )
        if (cancelled) return

        if (res.status === 400) {
          setStatus('invalid')
          return
        }
        if (!res.ok) {
          setStatus('error')
          return
        }

        const data = await res.json().catch(() => ({}))
        // Refresh auth so the new JWT has email_verified: true
        try { await refreshAuth() } catch {}

        if (cancelled) return
        setStatus(data.already_verified ? 'already' : 'success')
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    run()
    return () => { cancelled = true }
  }, [token, refreshAuth])

  return (
    <div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 flex flex-col gap-4 text-center">
      {status === 'loading' && (
        <>
          <p className="font-mono text-sm text-[--color-off-white]">
            Verifying your email…
          </p>
          <div className="h-2 bg-white/8 rounded animate-pulse mx-auto w-2/3" />
        </>
      )}

      {status === 'success' && (
        <>
          <h2 className="font-display text-2xl font-bold text-[--color-teal]">
            Email verified
          </h2>
          <p className="font-mono text-xs text-[--color-muted]">
            Your RegKnots account is unlocked. Full access restored.
          </p>
          <Link
            href="/"
            className="mt-2 bg-[--color-teal] hover:brightness-110 text-[--color-navy]
              font-bold text-sm uppercase tracking-wider rounded-lg py-2.5
              transition-[filter] font-mono"
          >
            Continue to RegKnots
          </Link>
        </>
      )}

      {status === 'already' && (
        <>
          <h2 className="font-display text-2xl font-bold text-[--color-off-white]">
            Already verified
          </h2>
          <p className="font-mono text-xs text-[--color-muted]">
            This email was already confirmed. You're all set.
          </p>
          <Link
            href="/"
            className="mt-2 bg-[--color-teal] hover:brightness-110 text-[--color-navy]
              font-bold text-sm uppercase tracking-wider rounded-lg py-2.5
              transition-[filter] font-mono"
          >
            Go to Chat
          </Link>
        </>
      )}

      {status === 'invalid' && (
        <>
          <h2 className="font-display text-2xl font-bold text-red-400">
            Invalid link
          </h2>
          <p className="font-mono text-xs text-[--color-muted]">
            This verification link is invalid or has already been used.
            Sign in and use the banner at the top of the chat to request a new one.
          </p>
          <Link
            href="/login"
            className="font-mono text-xs text-[--color-teal] hover:underline"
          >
            Sign in →
          </Link>
        </>
      )}

      {status === 'error' && (
        <>
          <h2 className="font-display text-2xl font-bold text-red-400">
            Something went wrong
          </h2>
          <p className="font-mono text-xs text-[--color-muted]">
            We couldn't verify your email right now. Please try the link again
            in a moment.
          </p>
        </>
      )}
    </div>
  )
}

export default function VerifyEmailPage() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-[--color-navy] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center flex flex-col items-center gap-3">
          <CompassRose className="w-12 h-12 text-[--color-teal]" />
          <div>
            <h1 className="font-display text-3xl font-black tracking-widest uppercase text-[--color-off-white]">
              Reg<span className="text-[--color-teal]">Knots</span>
            </h1>
            <p className="mt-1 text-xs text-[--color-muted] tracking-wider uppercase font-mono">
              Maritime Compliance Co-pilot
            </p>
          </div>
        </div>

        <Suspense
          fallback={
            <div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 h-40 animate-pulse" />
          }
        >
          <VerifyEmailInner />
        </Suspense>
      </div>
    </main>
  )
}
