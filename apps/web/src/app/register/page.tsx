'use client'

import { useState, useEffect, FormEvent, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
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
  // Wrap in Suspense so useSearchParams() doesn't fail during static
  // prerender. Same pattern the login page uses.
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  )
}

function RegisterForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const register = useAuthStore((s) => s.register)

  // D6.53 — Wheelhouse invite. /invite/<token> sends users here with
  // ?invite=<token>&email=<addr>. We prefill the email and remember
  // the invite so the post-register redirect can land them in the
  // right workspace. The email is locked when an invite token is
  // present — changing it would break the auto-claim match.
  const inviteToken = searchParams.get('invite')
  const inviteEmail = searchParams.get('email')

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState(inviteEmail ?? '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('other')
  const [error, setError] = useState('')
  const [networkDiag, setNetworkDiag] = useState<NetworkDiagnosis | null>(null)
  const [loading, setLoading] = useState(false)

  // If the invite param shows up after first render (rare race with
  // searchParams hydration), keep the email field in sync.
  useEffect(() => {
    if (inviteEmail && !email) setEmail(inviteEmail)
  }, [inviteEmail, email])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setNetworkDiag(null)
    setLoading(true)
    try {
      await register(email, password, fullName, role)
      // Sprint D6.3c — if the user came in via /pricing or /womenoffshore
      // and clicked Subscribe before authenticating, we saved the chosen
      // plan as `pending_checkout_plan` in localStorage. Resume that
      // checkout intent now so they don't have to navigate back manually.
      let pendingPlan: string | null = null
      let referralSource: string | null = null
      try {
        pendingPlan = localStorage.getItem('pending_checkout_plan')
        referralSource = localStorage.getItem('regknot_referral_source')
      } catch {
        // localStorage unavailable — skip resume, go to default landing.
      }
      if (pendingPlan) {
        try { localStorage.removeItem('pending_checkout_plan') } catch {}
        try {
          const { apiRequest } = await import('@/lib/api')
          const data = await apiRequest<{ checkout_url: string }>(
            '/billing/checkout',
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                plan: pendingPlan,
                ...(referralSource && { referral_source: referralSource }),
              }),
            },
          )
          window.location.href = data.checkout_url
          return
        } catch {
          // Checkout call failed (e.g. Stripe not configured for this env).
          // Fall through to the standard post-register landing rather than
          // leaving the user on a broken state.
        }
      }
      // D6.53 — invite-flow short-circuit. If they came in via
      // /invite/<token>, the auth/register handler already auto-
      // claimed any pending invites for this email, so we skip the
      // pricing nag and land them on /workspaces directly. Their
      // wheelhouse_only or individual_with_workspaces shell will be
      // resolved by /me/view-mode on next page load.
      if (inviteToken) {
        router.replace('/workspaces')
        return
      }
      // Vessel onboarding is optional — shore-side users can skip it and
      // add a vessel later from the vessel sheet. Go straight to chat.
      router.replace('/')
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
              Reg<span className="text-[--color-teal]">Knot</span>
            </h1>
            <p className="mt-1 text-xs text-[--color-muted] tracking-wider uppercase font-mono">
              Maritime Compliance Co-pilot
            </p>
          </div>
        </div>

        {inviteToken && (
          <div className="mb-4 rounded-lg border border-[--color-teal]/30
                          bg-[--color-teal]/5 px-4 py-3 text-xs text-[--color-teal]
                          font-mono">
            You&apos;re joining a Wheelhouse. Create your account with the
            invited email and you&apos;ll be added automatically.
          </div>
        )}

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
              readOnly={!!inviteToken}
              className={`font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors ${inviteToken ? 'opacity-70 cursor-not-allowed' : ''}`}
            />
            {inviteToken && (
              <p className="text-[10px] text-[--color-muted] font-mono mt-1">
                Locked &mdash; matches the invite address.
              </p>
            )}
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
