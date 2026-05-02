'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest, ApiError } from '@/lib/api'

// ── Types (mirror routers/workspaces.py) ────────────────────────────────────

interface Member {
  user_id: string
  email: string
  full_name: string | null
  role: 'owner' | 'admin' | 'member'
  joined_at: string
  invited_by: string | null
}

interface WorkspaceDetail {
  id: string
  name: string
  owner_user_id: string
  status: 'active' | 'trialing' | 'card_pending' | 'archived' | 'canceled'
  seat_cap: number
  member_count: number
  my_role: 'owner' | 'admin' | 'member'
  created_at: string
  card_pending_started_at: string | null
  members: Member[]
}

const STATUS_LABEL: Record<WorkspaceDetail['status'], string> = {
  trialing: 'Trial',
  active: 'Active',
  card_pending: 'Card needed',
  archived: 'Archived',
  canceled: 'Canceled',
}

function daysSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24))
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function WorkspaceDetailPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#050811] text-[#f0ece4]">
        <AppHeader />
        <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
          <DetailContent />
        </main>
      </div>
    </AuthGuard>
  )
}

function DetailContent() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const workspaceId = params?.id

  const [ws, setWs] = useState<WorkspaceDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showInvite, setShowInvite] = useState(false)
  const [showTransfer, setShowTransfer] = useState(false)

  useEffect(() => {
    if (workspaceId) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId])

  async function load() {
    if (!workspaceId) return
    setError(null)
    try {
      const data = await apiRequest<WorkspaceDetail>(`/workspaces/${workspaceId}`)
      setWs(data)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError('Workspace not found, or you no longer have access.')
      } else {
        setError(e instanceof Error ? e.message : 'Failed to load workspace.')
      }
    }
  }

  async function removeMember(member: Member) {
    if (!ws) return
    const isSelf = member.user_id === ws.owner_user_id && ws.my_role === 'owner'
    const label = isSelf ? 'leave the workspace' : `remove ${member.email}`
    if (!confirm(`Are you sure you want to ${label}?`)) return
    try {
      await apiRequest(
        `/workspaces/${ws.id}/members/${member.user_id}`,
        { method: 'DELETE' },
      )
      // If the user removed themselves, kick to list page.
      if (member.user_id === ws.members.find(m => m.role === ws.my_role && ws.my_role !== 'owner')?.user_id) {
        router.push('/workspaces')
      } else {
        await load()
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to remove member.')
    }
  }

  async function changeRole(member: Member, newRole: 'admin' | 'member') {
    if (!ws) return
    try {
      await apiRequest(
        `/workspaces/${ws.id}/members/${member.user_id}`,
        { method: 'PATCH', body: JSON.stringify({ role: newRole }) },
      )
      await load()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to change role.')
    }
  }

  if (error) {
    return (
      <>
        <div className="mb-4">
          <Link href="/workspaces" className="text-sm text-[#2dd4bf] hover:underline">
            ← Back to workspaces
          </Link>
        </div>
        <div className="rounded-md border border-amber-400/30 bg-amber-400/5 px-4 py-3 text-sm text-amber-200/90">
          {error}
        </div>
      </>
    )
  }

  if (!ws) {
    return <div className="text-sm text-[#6b7594]">Loading…</div>
  }

  const cardPendingDays = ws.card_pending_started_at
    ? Math.max(0, 30 - daysSince(ws.card_pending_started_at))
    : null
  const canManageMembers = ws.my_role === 'owner' || ws.my_role === 'admin'
  const canManageRoles = ws.my_role === 'owner'
  const canTransfer = ws.my_role === 'owner'
  const adminCount = ws.members.filter(m => m.role === 'admin').length

  return (
    <>
      <div className="mb-4">
        <Link href="/workspaces" className="text-sm text-[#2dd4bf] hover:underline">
          ← Back to workspaces
        </Link>
      </div>

      <header className="mb-6">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <h1 className="text-2xl font-bold">{ws.name}</h1>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase
                            tracking-wider border ${
            ws.status === 'card_pending' ? 'bg-amber-400/10 text-amber-300 border-amber-400/30' :
            ws.status === 'archived' ? 'bg-red-400/10 text-red-300 border-red-400/30' :
            ws.status === 'trialing' ? 'bg-yellow-400/10 text-yellow-300 border-yellow-400/30' :
            'bg-emerald-400/10 text-emerald-300 border-emerald-400/30'
          }`}>
            {STATUS_LABEL[ws.status]}
          </span>
          {/* D6.49 — open chat in this workspace context. Activates only
              when explicitly clicked; personal chat (no ?workspace= URL
              param) is always available at /. */}
          {ws.status !== 'archived' && ws.status !== 'canceled' && (
            <Link
              href={`/?workspace=${ws.id}`}
              className="ml-auto px-2.5 py-1 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                         text-xs font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                         whitespace-nowrap transition-colors"
              title="Opens chat in workspace context — chats are shared with members"
            >
              Open chat →
            </Link>
          )}
        </div>
        <div className="text-xs text-[#6b7594]">
          You are <span className="text-[#f0ece4]/80 font-mono">{ws.my_role.toUpperCase()}</span> ·
          {ws.member_count}/{ws.seat_cap} seats used ·
          created {new Date(ws.created_at).toLocaleDateString()}
        </div>
      </header>

      {ws.status === 'card_pending' && cardPendingDays !== null && (
        <div className="mb-6 rounded-md border border-amber-400/40 bg-amber-400/8 p-4">
          <div className="flex items-center gap-2 mb-1 text-sm font-semibold text-amber-300">
            <span>⚠ Workspace is read-only — card needed</span>
          </div>
          <p className="text-xs text-amber-200/80">
            The Owner must add a payment card within{' '}
            <strong>{cardPendingDays} day{cardPendingDays === 1 ? '' : 's'}</strong>.
            New chats, dossier edits, and member changes are paused until then.
            After the grace period, the workspace will be archived (90-day
            recovery window before purge).
          </p>
          {ws.my_role === 'owner' && (
            <button
              disabled
              title="Stripe billing wires up next sprint"
              className="mt-3 px-3 py-1.5 rounded-md bg-amber-400/15 border border-amber-400/30
                         text-xs font-medium text-amber-200 disabled:opacity-50 cursor-not-allowed"
            >
              Add payment card (coming soon)
            </button>
          )}
        </div>
      )}

      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-mono uppercase tracking-wider text-[#6b7594]">
            Members ({ws.member_count})
          </h2>
          {canManageMembers && ws.member_count < ws.seat_cap && (
            <button
              onClick={() => setShowInvite(true)}
              className="px-2.5 py-1 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                         text-xs font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                         transition-colors"
            >
              + Invite
            </button>
          )}
        </div>
        <ul className="space-y-2">
          {ws.members.map(m => (
            <li
              key={m.user_id}
              className="rounded-lg border border-white/8 bg-[#0a0e1a]/60 p-3 flex items-center justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">
                  {m.full_name ?? m.email}
                </div>
                <div className="text-xs text-[#6b7594] truncate">{m.email}</div>
              </div>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase
                                tracking-wider border ${
                m.role === 'owner' ? 'bg-[#2dd4bf]/15 text-[#2dd4bf] border-[#2dd4bf]/30' :
                m.role === 'admin' ? 'bg-blue-400/10 text-blue-300 border-blue-400/30' :
                'bg-white/5 text-[#6b7594] border-white/10'
              }`}>
                {m.role}
              </span>
              {/* Member actions */}
              {(canManageRoles && m.role !== 'owner') && (
                <select
                  value={m.role}
                  onChange={(e) => changeRole(m, e.target.value as 'admin' | 'member')}
                  className="text-xs bg-[#111827] border border-white/10 rounded px-1.5 py-0.5
                             text-[#f0ece4] hover:border-[#2dd4bf]/50 cursor-pointer"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
              )}
              {canManageMembers && m.role !== 'owner' && (
                <button
                  onClick={() => removeMember(m)}
                  title="Remove from workspace"
                  className="text-xs text-red-400/70 hover:text-red-400 transition-colors px-1"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {canTransfer && adminCount > 0 && (
        <section className="mb-8 rounded-lg border border-white/8 p-4">
          <h3 className="text-sm font-semibold mb-1">Transfer ownership</h3>
          <p className="text-xs text-[#6b7594] mb-3">
            Move Owner role to an existing Admin. You&apos;ll be demoted to
            Admin. The new Owner has 30 days to add a payment card before the
            workspace becomes read-only.
          </p>
          <button
            onClick={() => setShowTransfer(true)}
            className="px-3 py-1.5 rounded-md border border-white/10
                       text-xs font-medium text-[#f0ece4]/80 hover:bg-white/5
                       transition-colors"
          >
            Transfer to an Admin
          </button>
        </section>
      )}

      {canTransfer && adminCount === 0 && (
        <section className="mb-8 rounded-lg border border-dashed border-white/10 p-4">
          <h3 className="text-sm font-semibold mb-1">Transfer ownership</h3>
          <p className="text-xs text-[#6b7594]">
            Promote a member to Admin first. Only Admins can become the new
            Owner.
          </p>
        </section>
      )}

      {showInvite && (
        <InviteModal
          workspaceId={ws.id}
          seatsLeft={ws.seat_cap - ws.member_count}
          onCancel={() => setShowInvite(false)}
          onSuccess={() => { setShowInvite(false); void load() }}
        />
      )}
      {showTransfer && (
        <TransferModal
          workspaceId={ws.id}
          admins={ws.members.filter(m => m.role === 'admin')}
          onCancel={() => setShowTransfer(false)}
          onSuccess={() => { setShowTransfer(false); void load() }}
        />
      )}
    </>
  )
}

// ── Invite modal ────────────────────────────────────────────────────────────

function InviteModal({
  workspaceId, seatsLeft, onCancel, onSuccess,
}: {
  workspaceId: string
  seatsLeft: number
  onCancel: () => void
  onSuccess: () => void
}) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'admin' | 'member'>('member')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await apiRequest(
        `/workspaces/${workspaceId}/members`,
        {
          method: 'POST',
          body: JSON.stringify({ email: email.trim().toLowerCase(), role }),
        },
      )
      onSuccess()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to invite.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-lg border border-white/10 bg-[#0a0e1a] p-5 shadow-xl">
        <h2 className="text-lg font-semibold mb-1">Invite member</h2>
        <p className="text-xs text-[#6b7594] mb-4">
          The user must already have a RegKnots account. {seatsLeft} seat{seatsLeft === 1 ? '' : 's'} remaining.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-1.5">
              Email
            </label>
            <input
              autoFocus type="email" value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="captain@example.com"
              className="w-full px-3 py-2 rounded-md bg-[#111827] border border-white/10
                         text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/50"
            />
          </div>
          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-1.5">
              Role
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as 'admin' | 'member')}
              className="w-full px-3 py-2 rounded-md bg-[#111827] border border-white/10
                         text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/50"
            >
              <option value="member">Member — read+write to dossier and chat</option>
              <option value="admin">Admin — manage members + dossier (rotation captain, chief)</option>
            </select>
          </div>
          {error && <div className="text-xs text-red-400">{error}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button" onClick={onCancel} disabled={submitting}
              className="px-3 py-1.5 text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit" disabled={!email.trim() || submitting}
              className="px-3 py-1.5 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                         text-sm font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Sending…' : 'Send invite'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Transfer ownership modal ────────────────────────────────────────────────

function TransferModal({
  workspaceId, admins, onCancel, onSuccess,
}: {
  workspaceId: string
  admins: Member[]
  onCancel: () => void
  onSuccess: () => void
}) {
  const [selectedId, setSelectedId] = useState(admins[0]?.user_id ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedId || !confirmed || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await apiRequest(
        `/workspaces/${workspaceId}/transfer`,
        {
          method: 'POST',
          body: JSON.stringify({ new_owner_user_id: selectedId }),
        },
      )
      onSuccess()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to transfer.')
    } finally {
      setSubmitting(false)
    }
  }

  const target = admins.find(a => a.user_id === selectedId)

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-lg border border-white/10 bg-[#0a0e1a] p-5 shadow-xl">
        <h2 className="text-lg font-semibold mb-1">Transfer ownership</h2>
        <p className="text-xs text-[#6b7594] mb-4">
          You&apos;ll be demoted to Admin. The new Owner has 30 days to add a
          payment card; otherwise the workspace becomes read-only.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-1.5">
              Promote to Owner
            </label>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-[#111827] border border-white/10
                         text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/50"
            >
              {admins.map(a => (
                <option key={a.user_id} value={a.user_id}>
                  {a.full_name ?? a.email} ({a.email})
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-start gap-2 text-xs text-[#f0ece4]/80 cursor-pointer">
            <input
              type="checkbox" checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              I understand: I&apos;ll be demoted to Admin, the workspace
              enters card-pending state for 30 days, and{' '}
              <strong>{target?.email}</strong> will need to add a payment
              card during that window.
            </span>
          </label>
          {error && <div className="text-xs text-red-400">{error}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button" onClick={onCancel} disabled={submitting}
              className="px-3 py-1.5 text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit" disabled={!confirmed || submitting}
              className="px-3 py-1.5 rounded-md bg-amber-400/15 border border-amber-400/30
                         text-sm font-medium text-amber-200 hover:bg-amber-400/25
                         disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Transferring…' : 'Transfer ownership'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
