'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { useAuthStore } from '@/lib/auth'

export default function SubscribeSuccessPage() {
  const refreshAuth = useAuthStore(s => s.refreshAuth)

  useEffect(() => {
    // Refresh the JWT so tier claim updates immediately
    refreshAuth()
  }, [refreshAuth])

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col items-center justify-center px-5">
      <CompassRose className="w-16 h-16 text-[#2dd4bf] mb-6" />
      <h1 className="font-display font-black text-[#f0ece4] text-3xl mb-3">
        Welcome to Pro
      </h1>
      <p className="font-mono text-[#6b7594] text-center max-w-sm mb-8">
        Your subscription is active. You now have unlimited access to RegKnots.
      </p>
      <Link
        href="/"
        className="font-mono font-bold text-sm uppercase tracking-wider
          bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
          hover:brightness-110 transition-[filter] duration-150"
      >
        Start Chatting
      </Link>
    </div>
  )
}
