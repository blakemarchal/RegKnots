'use client'

import { useState, FormEvent, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { apiRequest } from '@/lib/api'

function ResetPasswordForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    setLoading(true)
    try {
      await apiRequest('/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: newPassword }),
      })
      router.replace('/login?reset=1')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid or expired reset link')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 text-center">
        <p className="font-mono text-sm text-red-400">Invalid reset link. Please request a new one.</p>
        <Link href="/forgot-password" className="font-mono text-xs text-[--color-teal] hover:underline mt-3 inline-block">
          Request new link
        </Link>
      </div>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 flex flex-col gap-4"
    >
      <div>
        <p className="font-mono text-sm text-[--color-off-white] mb-1">Choose a new password</p>
        <p className="font-mono text-xs text-[--color-muted]">Must be at least 8 characters.</p>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="new-password" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
          New Password
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          required
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="confirm-password" className="text-xs text-[--color-muted] uppercase tracking-wider font-mono">
          Confirm Password
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          required
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="font-mono bg-[--color-surface-dim] border border-white/10 rounded-lg px-3 py-2 text-sm text-[--color-off-white] outline-none focus:border-[--color-teal] transition-colors"
        />
      </div>

      {error && (
        <p className="font-mono text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="bg-[--color-teal] hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-[--color-navy] font-bold text-sm uppercase tracking-wider rounded-lg py-2.5 transition-[filter] font-mono"
      >
        {loading ? 'Updating…' : 'Set New Password'}
      </button>
    </form>
  )
}

export default function ResetPasswordPage() {
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

        <Suspense fallback={<div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6 h-48 animate-pulse" />}>
          <ResetPasswordForm />
        </Suspense>

        <p className="mt-4 text-center text-xs text-[--color-muted] font-mono">
          <Link href="/login" className="text-[--color-teal] hover:underline">
            ← Back to Sign In
          </Link>
        </p>
      </div>
    </main>
  )
}
