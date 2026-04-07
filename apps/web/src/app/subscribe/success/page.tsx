'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { useAuthStore } from '@/lib/auth'
import type { BillingStatus } from '@/lib/auth'
import { apiRequest } from '@/lib/api'

export default function SubscribeSuccessPage() {
  const refreshAuth = useAuthStore(s => s.refreshAuth)
  const setBilling = useAuthStore(s => s.setBilling)
  const [ready, setReady] = useState(false)
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    refreshAuth()

    let attempts = 0
    const maxAttempts = 10
    const interval = setInterval(async () => {
      attempts++
      try {
        const status = await apiRequest<BillingStatus>('/billing/status')
        if (status.tier === 'pro') {
          setBilling(status)
          setReady(true)
          clearInterval(interval)
        }
      } catch {}

      if (attempts >= maxAttempts) {
        clearInterval(interval)
        setTimedOut(true)
        setReady(true)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [refreshAuth, setBilling])

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col items-center justify-center px-5">
      <CompassRose className={`w-16 h-16 text-[#2dd4bf] mb-6 ${!ready ? 'animate-spin' : ''}`} />

      {!ready && (
        <>
          <h1 className="font-display font-black text-[#f0ece4] text-3xl mb-3">
            Processing...
          </h1>
          <p className="font-mono text-[#6b7594] text-center max-w-sm mb-8">
            Activating your Pro subscription. This usually takes just a few seconds.
          </p>
        </>
      )}

      {ready && !timedOut && (
        <>
          <h1 className="font-display font-black text-[#f0ece4] text-3xl mb-3">
            Welcome to Pro
          </h1>
          <p className="font-mono text-[#6b7594] text-center max-w-sm mb-8">
            Your subscription is active. You now have unlimited access to RegKnot.
          </p>
          <Link
            href="/"
            className="font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
              hover:brightness-110 transition-[filter] duration-150"
          >
            Start Chatting
          </Link>
        </>
      )}

      {ready && timedOut && (
        <>
          <h1 className="font-display font-black text-[#f0ece4] text-3xl mb-3">
            Almost There
          </h1>
          <p className="font-mono text-[#6b7594] text-center max-w-sm mb-8">
            Your subscription is being processed. If your Pro features don&apos;t appear within a
            few minutes, please contact{' '}
            <span className="text-[#2dd4bf]">support@regknots.com</span>.
          </p>
          <Link
            href="/"
            className="font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
              hover:brightness-110 transition-[filter] duration-150"
          >
            Go to App
          </Link>
        </>
      )}
    </div>
  )
}
