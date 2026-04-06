'use client'

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuthStore } from '@/lib/auth'
import { CompassRose } from '@/components/CompassRose'
import { diagnoseNetworkError, type NetworkDiagnosis } from '@/lib/networkError'
import { NetworkErrorCard } from '@/components/NetworkErrorCard'

const ROLES = [
  { value: 'captain', label: 'Captain / Master' },
  { value: 'mate', label: 'Chief Mate / Officer' },
  { value: 'engineer', label: 'Engineer' },
  { value: 'chief_engineer', label: 'Chief Engineer' },
  { value: 'other', label: 'Other / Shore-side' },
]

export default function RegisterPage() {
  const router = useRouter()
  const register = useAuthStore((s) => s.register)

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('other')
  const [error, setError] = useState('')
  const [networkDiag, setNetworkDiag] = useState<NetworkDiagnosis | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setNetworkDiag(null)
    setLoading(true)
    try {
      await register(email, password, fullName, role)
      router.replace('/onboarding')
    } catch (err) {
      if (err instanceof TypeError) {
        const diag = await diagnoseNetworkError()
        setNetworkDiag(diag)
      } else {
        setError(err instanceof Error ? err.message : 'Registration failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-[--color-navy] px-4">
      <div className="w-full max-w-sm">
        {/* Logo / wordmark */}
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

        <form
          onSubmit={handleSubmit}
          className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="full_name" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
              Full Name
            </label>
            <input
              id="full_name"
              type="text"
              autoComplete="name"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
            />
          </div>

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
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor="role" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
              Role
            </label>
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="font-mono border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-[--color-teal] transition-colors"
              style={{ backgroundColor: '#111827', color: '#f0ece4' }}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value} style={{ backgroundColor: '#111827', color: '#f0ece4' }}>
                  {r.label}
                </option>
              ))}
            </select>
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

          <button
            type="submit"
            disabled={loading}
            className="mt-1 bg-[--color-teal] hover:bg-[--color-teal-dark] disabled:opacity-50 disabled:cursor-not-allowed text-[--color-navy] font-bold text-sm uppercase tracking-wider rounded-lg py-2.5 transition-colors font-mono"
          >
            {loading ? 'Creating account…' : 'Create Account'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-[--color-muted] font-mono">
          Already have an account?{' '}
          <Link href="/login" className="text-[--color-teal] hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  )
}
