'use client'

// Sprint D6.53 — Wheelhouse invite landing page.
//
// Two flows funnel through here:
//
//   1. New user (no RegKnots account yet): they see the workspace
//      name + inviter, click "Create account & join", which forwards
//      to /register?invite=<token>. The register page reads that
//      query param, prefills the email, and on success the auto-
//      claim hook in /auth/register adds them to the workspace.
//
//   2. Existing user: if signed in with the matching email, we offer
//      Accept/Decline directly. If signed in with a DIFFERENT email,
//      we explain the mismatch and offer "sign in as <invited email>".
//      If not signed in but they have an account, we route to /login
//      with ?invite=<token> so the post-login redirect can land them
//      on /me/invites.
//
// The lookup endpoint is unauthenticated so we can render the page
// before the user signs in. The token is 32 bytes of URL-safe random
// data; treating it as unguessable is safe.

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuthStore } from '@/lib/auth'
import { CompassRose } from '@/components/CompassRose'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

interface InviteLookup {
  workspace_name: string
  inviter_name: string | null
  role: 'admin' | 'member'
  email: string
  expires_at: string
  requires_signup: boolean
}

export default function InvitePage() {
  return <InviteContent />
}

function InviteContent() {
  const params = useParams<{ token: string }>()
  const router = useRouter()
  const token = params?.token

  const { user, isAuthenticated, hydrated, hydrateAuth } = useAuthStore()

  const [invite, setInvite] = useState<InviteLookup | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // Hydrate auth so we know if the visitor is signed in.
  useEffect(() => { void hydrateAuth() }, [hydrateAuth])

  useEffect(() => {
    if (!token) return
    void (async () => {
      try {
        // Unauthenticated lookup — no Authorization header needed.
        const res = await fetch(`${API_URL}/me/invites/lookup/${token}`)
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          setLoadError(body.detail ?? `Invite lookup failed (${res.status})`)
          return
        }
        setInvite(await res.json())
      } catch {
        setLoadError('Could not reach the server. Try again in a moment.')
      }
    })()
  }, [token])

  if (loadError) {
    return (
      <Shell>
        <h1 className="text-xl font-bold mb-2">Invite unavailable</h1>
        <p className="text-sm text-[#6b7594] mb-6">{loadError}</p>
        <Link
          href="/login"
          className="inline-block bg-[--color-teal] text-[--color-navy] font-bold
                     text-sm uppercase tracking-wider rounded-lg py-2.5 px-5"
        >
          Sign in
        </Link>
      </Shell>
    )
  }

  if (!invite || !hydrated) {
    return <Shell><p className="text-sm text-[#6b7594]">Loading invite&hellip;</p></Shell>
  }

  const inviter = invite.inviter_name ?? 'A captain'
  const roleLabel = invite.role === 'admin' ? 'Admin' : 'Member'
  const expiresOn = new Date(invite.expires_at).toLocaleDateString()

  // ── New user path ────────────────────────────────────────────────────
  if (invite.requires_signup) {
    return (
      <Shell>
        <Header workspaceName={invite.workspace_name} />
        <p className="text-sm text-[#6b7594] mb-6 leading-relaxed">
          <strong className="text-[#f0ece4]">{inviter}</strong> invited you to
          join as <strong className="text-[#f0ece4]">{roleLabel}</strong>.
          You don&apos;t have a RegKnot account yet &mdash; create one with the
          email <code className="text-[--color-teal]">{invite.email}</code> and
          you&apos;ll be added to the Wheelhouse automatically.
        </p>
        <Link
          href={`/register?invite=${token}&email=${encodeURIComponent(invite.email)}`}
          className="block text-center bg-[--color-teal] text-[--color-navy]
                     font-bold text-sm uppercase tracking-wider rounded-lg
                     py-2.5 px-5 hover:bg-[--color-teal-dark] transition-colors"
        >
          Create account &amp; join
        </Link>
        <Footer expires={expiresOn} />
      </Shell>
    )
  }

  // ── Existing user, not signed in ────────────────────────────────────
  if (!isAuthenticated) {
    return (
      <Shell>
        <Header workspaceName={invite.workspace_name} />
        <p className="text-sm text-[#6b7594] mb-6 leading-relaxed">
          <strong className="text-[#f0ece4]">{inviter}</strong> invited you to
          join as <strong className="text-[#f0ece4]">{roleLabel}</strong>.
          You already have a RegKnot account at{' '}
          <code className="text-[--color-teal]">{invite.email}</code> &mdash;
          sign in to accept.
        </p>
        <Link
          href={`/login?invite=${token}`}
          className="block text-center bg-[--color-teal] text-[--color-navy]
                     font-bold text-sm uppercase tracking-wider rounded-lg
                     py-2.5 px-5 hover:bg-[--color-teal-dark] transition-colors"
        >
          Sign in to accept
        </Link>
        <Footer expires={expiresOn} />
      </Shell>
    )
  }

  // ── Existing user, signed in but with a DIFFERENT email ─────────────
  if (user && user.email.toLowerCase() !== invite.email.toLowerCase()) {
    return (
      <Shell>
        <Header workspaceName={invite.workspace_name} />
        <p className="text-sm text-amber-300/90 mb-2">
          You&apos;re signed in as <code>{user.email}</code> but this invite
          is addressed to <code className="text-[--color-teal]">{invite.email}</code>.
        </p>
        <p className="text-sm text-[#6b7594] mb-6">
          Sign out and sign in with the invited email to accept, or ask
          {' '}<strong className="text-[#f0ece4]">{inviter}</strong> to
          re-issue the invite to your current address.
        </p>
        <Footer expires={expiresOn} />
      </Shell>
    )
  }

  // ── Existing user, signed in with the right email ───────────────────
  async function accept() {
    if (submitting) return
    setSubmitting(true)
    setActionError(null)
    try {
      // Use the lookup→accept dance: list /me/invites, find the one
      // with matching workspace name + email, then accept by id. We
      // don't expose token-based accept on the server because it'd
      // duplicate the auth check; this two-step flow is one extra
      // RTT and keeps the security model simple.
      const { apiRequest } = await import('@/lib/api')
      type InviteRow = { id: string; workspace_name: string; email: string }
      const all = await apiRequest<InviteRow[]>('/me/invites')
      const target = all.find(
        (i) => i.email.toLowerCase() === invite!.email.toLowerCase()
              && i.workspace_name === invite!.workspace_name,
      )
      if (!target) {
        setActionError('Invite not found in your inbox. It may have just expired.')
        return
      }
      const accepted = await apiRequest<{ workspace_id: string }>(
        `/me/invites/${target.id}/accept`,
        { method: 'POST' },
      )
      router.replace(`/workspaces/${accepted.workspace_id}`)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to accept.')
    } finally {
      setSubmitting(false)
    }
  }

  async function decline() {
    if (submitting) return
    if (!confirm('Decline this invite? You can be re-invited later.')) return
    setSubmitting(true)
    setActionError(null)
    try {
      const { apiRequest } = await import('@/lib/api')
      type InviteRow = { id: string; workspace_name: string; email: string }
      const all = await apiRequest<InviteRow[]>('/me/invites')
      const target = all.find(
        (i) => i.email.toLowerCase() === invite!.email.toLowerCase()
              && i.workspace_name === invite!.workspace_name,
      )
      if (!target) {
        setActionError('Invite not found in your inbox.')
        return
      }
      await apiRequest(`/me/invites/${target.id}/decline`, { method: 'POST' })
      router.replace('/workspaces')
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to decline.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Shell>
      <Header workspaceName={invite.workspace_name} />
      <p className="text-sm text-[#6b7594] mb-6 leading-relaxed">
        <strong className="text-[#f0ece4]">{inviter}</strong> invited you to
        join as <strong className="text-[#f0ece4]">{roleLabel}</strong>.
      </p>
      {actionError && (
        <p className="font-mono text-xs text-red-400 bg-red-400/10
                      border border-red-400/20 rounded-lg px-3 py-2 mb-4">
          {actionError}
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={accept}
          disabled={submitting}
          className="flex-1 bg-[--color-teal] text-[--color-navy] font-bold
                     text-sm uppercase tracking-wider rounded-lg py-2.5
                     hover:bg-[--color-teal-dark] disabled:opacity-50
                     disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? 'Joining…' : 'Accept'}
        </button>
        <button
          onClick={decline}
          disabled={submitting}
          className="px-4 py-2.5 text-sm text-[#6b7594] hover:text-[#f0ece4]
                     transition-colors disabled:opacity-50"
        >
          Decline
        </button>
      </div>
      <Footer expires={expiresOn} />
    </Shell>
  )
}

// ── Layout helpers ────────────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen flex items-center justify-center bg-[--color-navy] px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center flex flex-col items-center gap-3">
          <CompassRose className="w-10 h-10 text-[--color-teal]" />
          <h1 className="font-display text-2xl font-black tracking-widest uppercase text-[--color-off-white]">
            Reg<span className="text-[--color-teal]">Knot</span>
          </h1>
        </div>
        <div className="bg-[--color-surface-mid] border border-white/8 rounded-xl p-6">
          {children}
        </div>
      </div>
    </main>
  )
}

function Header({ workspaceName }: { workspaceName: string }) {
  return (
    <>
      <p className="text-xs font-mono uppercase tracking-wider text-[--color-muted] mb-1">
        You&apos;re invited to
      </p>
      <h2 className="text-xl font-bold mb-3 text-[--color-teal]">
        {workspaceName}
      </h2>
    </>
  )
}

function Footer({ expires }: { expires: string }) {
  return (
    <p className="mt-4 text-center text-[10px] text-[--color-muted] font-mono">
      Invite expires {expires}
    </p>
  )
}
