'use client'

import { useState, FormEvent, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuthStore } from '@/lib/auth'
import { CompassRose } from '@/components/CompassRose'
import { diagnoseNetworkError, type NetworkDiagnosis } from '@/lib/networkError'
import { NetworkErrorCard } from '@/components/NetworkErrorCard'

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const login = useAuthStore((s) => s.login)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [networkDiag, setNetworkDiag] = useState<NetworkDiagnosis | null>(null)
  const [loading, setLoading] = useState(false)

  const resetSuccess = searchParams.get('reset') === '1'
  // D6.53 — invite redirect. /invite/<token> sends users here with
  // ?invite=<token>. After successful login we forward back so the
  // landing page can show the Accept button with the user signed in.
  const inviteToken = searchParams.get('invite')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setNetworkDiag(null)
    setLoading(true)
    try {
      await login(email, password)
      if (inviteToken) {
        router.replace(`/invite/${inviteToken}`)
        return
      }
      router.replace('/')
    } catch (err) {
      // TypeError means a network-level failure (DNS, firewall, offline, etc.)
      if (err instanceof TypeError) {
        const diag = await diagnoseNetworkError()
        setNetworkDiag(diag)
      } else {
        setError(err instanceof Error ? err.message : 'Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[--color-navy] px-4">
      <div className="w-full max-w-sm">
        {resetSuccess && (
          <p className="font-mono text-xs text-[--color-teal] bg-[--color-teal]/10 border border-[--color-teal]/20 rounded-lg px-3 py-2 mb-4 text-center">
            Password updated — sign in with your new password.
          </p>
        )}

        {/* Logo / wordmark */}
        <div className="mb-8 text-center flex flex-col items-center gap-3">
          <CompassRose className="w-12 h-12 text-[--color-teal]" />
          <div>
            <h1 className="font-display text-3xl font-black tracking-widest uppercase text-[--color-off-white]">
              Reg<span className="text-[--color-teal]">Knot</span>
            </h1>
            <p className="mt-1 text-xs text-[--color-muted] tracking-wider uppercase font-mono">
              Maritime Compliance Co-pilot
            </p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="email" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="password" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
            />
          </div>

          {networkDiag && (
            <NetworkErrorCard
              diagnosis={networkDiag}
              onRetry={() => { setNetworkDiag(null); handleSubmit(new Event('submit') as unknown as FormEvent) }}
            />
          )}

          {error && !networkDiag && (
            <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex items-center justify-between mt-1">
            <button
              type="submit"
              disabled={loading}
              className="bg-[--color-teal] hover:bg-[--color-teal-dark] disabled:opacity-50 disabled:cursor-not-allowed text-[--color-navy] font-bold text-sm uppercase tracking-wider rounded-lg px-6 py-2.5 transition-colors font-mono"
            >
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
            <Link
              href="/forgot-password"
              className="font-mono text-xs text-[--color-muted] hover:text-[--color-teal] transition-colors"
            >
              Forgot password?
            </Link>
          </div>
        </form>

        <p className="mt-4 text-center text-xs text-[--color-muted] font-mono">
          No account?{' '}
          <Link href="/register" className="text-[--color-teal] hover:underline">
            Register
          </Link>
        </p>
      </div>
    </main>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}
