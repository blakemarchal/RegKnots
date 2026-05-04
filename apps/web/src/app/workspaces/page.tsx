'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { AppHeader } from '@/components/AppHeader'
import { apiRequest, ApiError } from '@/lib/api'
import { useViewMode } from '@/lib/useViewMode'

// ── Types (mirror packages/rag/rag/models.py and routers/workspaces.py) ────

interface Workspace {
  id: string
  name: string
  owner_user_id: string
  status: 'active' | 'trialing' | 'card_pending' | 'archived' | 'canceled'
  seat_cap: number
  member_count: number
  my_role: 'owner' | 'admin' | 'member'
  created_at: string
  card_pending_started_at: string | null
}

// D6.53 — pending invite addressed to the current user's email.
interface MyInvite {
  id: string
  workspace_id: string
  workspace_name: string | null
  role: 'admin' | 'member'
  invited_by_name: string | null
  expires_at: string
}

const STATUS_LABEL: Record<Workspace['status'], string> = {
  trialing: 'Trial',
  active: 'Active',
  card_pending: 'Card needed',
  archived: 'Archived',
  canceled: 'Canceled',
}

const ROLE_LABEL: Record<Workspace['my_role'], string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
}

function daysSince(iso: string): number {
  return Math.floor(
    (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24)
  )
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function WorkspacesPage() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-[#050811] text-[#f0ece4]">
        <AppHeader />
        <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
          <WorkspacesContent />
        </main>
      </div>
    </AuthGuard>
  )
}

function WorkspacesContent() {
  const router = useRouter()
  const { viewMode, refresh: refreshViewMode } = useViewMode()
  // D6.55 — wheelhouse_only users came in via invite, not as customers,
  // and shouldn't be encouraged to create their own workspace from
  // inside someone else's. Hide the "+ New workspace" CTA for them.
  // (The whitelist still allows the API call for testing, but the UI
  // shouldn't surface the button.)
  const isWheelhouseOnly = viewMode?.mode === 'wheelhouse_only'
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null)
  const [invites, setInvites] = useState<MyInvite[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  useEffect(() => { void load() }, [])

  async function load() {
    setError(null)
    try {
      const [data, myInvites] = await Promise.all([
        apiRequest<Workspace[]>('/workspaces'),
        // /me/invites is best-effort; if it fails (e.g. crew tier off
        // or user has no invites), we still want the workspace list.
        apiRequest<MyInvite[]>('/me/invites').catch(() => [] as MyInvite[]),
      ])
      setWorkspaces(data)
      setInvites(myInvites)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // CREW_TIER_ENABLED=false → endpoint returns 404
        setError(
          'The Wheelhouse / crew workspace tier is not yet available on '
          + 'your account. If you believe this is a mistake, contact '
          + 'support.'
        )
        setWorkspaces([])
      } else if (e instanceof ApiError && e.status === 403) {
        setError(e.message)
        setWorkspaces([])
      } else {
        setError(e instanceof Error ? e.message : 'Failed to load workspaces.')
        setWorkspaces([])
      }
    }
  }

  async function acceptInvite(inv: MyInvite) {
    if (acting) return
    setActing(inv.id)
    try {
      const res = await apiRequest<{ workspace_id: string }>(
        `/me/invites/${inv.id}/accept`,
        { method: 'POST' },
      )
      // Bust the view-mode cache — joining a workspace can flip a
      // free user from `individual` to `wheelhouse_only`.
      await refreshViewMode()
      router.push(`/workspaces/${res.workspace_id}`)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to accept invite.')
    } finally {
      setActing(null)
    }
  }

  async function declineInvite(inv: MyInvite) {
    if (acting) return
    if (!confirm(`Decline the invite to ${inv.workspace_name ?? 'this workspace'}?`)) {
      return
    }
    setActing(inv.id)
    try {
      await apiRequest(`/me/invites/${inv.id}/decline`, { method: 'POST' })
      await load()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to decline invite.')
    } finally {
      setActing(null)
    }
  }

  async function createWorkspace(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim() || creating) return
    setCreating(true)
    setCreateError(null)
    try {
      await apiRequest<Workspace>('/workspaces', {
        method: 'POST',
        body: JSON.stringify({ name: newName.trim() }),
      })
      setShowCreate(false)
      setNewName('')
      await load()
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create workspace.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      <header className="mb-6">
        <h1 className="text-2xl font-bold mb-1">Workspaces</h1>
        <p className="text-sm text-[#6b7594]">
          Vessel-anchored workspaces for crew rotations. One workspace per
          vessel; multiple admins for parity across rotation watches.
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-md border border-amber-400/30 bg-amber-400/5
                        px-4 py-3 text-sm text-amber-200/90">
          {error}
        </div>
      )}

      {invites.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-mono uppercase tracking-wider text-[#6b7594] mb-2">
            Pending invites ({invites.length})
          </h2>
          <ul className="space-y-2">
            {invites.map((inv) => (
              <li
                key={inv.id}
                className="rounded-lg border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 p-4"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-[#f0ece4]">
                      {inv.workspace_name ?? 'A workspace'}
                    </div>
                    <div className="text-xs text-[#6b7594] mt-0.5">
                      {inv.invited_by_name && <>Invited by {inv.invited_by_name} · </>}
                      Join as <span className="text-[#f0ece4]/80">{inv.role}</span>
                      {' '}· expires {new Date(inv.expires_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    <button
                      onClick={() => acceptInvite(inv)}
                      disabled={acting === inv.id}
                      className="px-3 py-1.5 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                                 text-xs font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                                 disabled:opacity-50 disabled:cursor-not-allowed
                                 transition-colors"
                    >
                      {acting === inv.id ? 'Joining…' : 'Accept'}
                    </button>
                    <button
                      onClick={() => declineInvite(inv)}
                      disabled={acting === inv.id}
                      className="px-3 py-1.5 text-xs text-[#6b7594] hover:text-[#f0ece4]
                                 transition-colors disabled:opacity-50"
                    >
                      Decline
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="text-xs font-mono uppercase tracking-wider text-[#6b7594]">
          {workspaces ? `${workspaces.length} workspace${workspaces.length === 1 ? '' : 's'}` : 'Loading…'}
        </div>
        {!isWheelhouseOnly && (
          <button
            onClick={() => setShowCreate(true)}
            className="px-3 py-1.5 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                       text-sm font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                       transition-colors"
          >
            + New workspace
          </button>
        )}
      </div>

      {workspaces !== null && workspaces.length === 0 && !error && (
        <EmptyHint />
      )}

      <ul className="space-y-3">
        {(workspaces ?? []).map(ws => (
          <li key={ws.id}>
            <WorkspaceRow ws={ws} />
          </li>
        ))}
      </ul>

      {showCreate && (
        <CreateWorkspaceModal
          name={newName}
          onChange={setNewName}
          onCancel={() => { setShowCreate(false); setCreateError(null); setNewName('') }}
          onSubmit={createWorkspace}
          submitting={creating}
          error={createError}
        />
      )}
    </>
  )
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function WorkspaceRow({ ws }: { ws: Workspace }) {
  const isCardPending = ws.status === 'card_pending'
  const cardPendingDays = ws.card_pending_started_at
    ? Math.max(0, 30 - daysSince(ws.card_pending_started_at))
    : null

  return (
    <Link
      href={`/workspaces/${ws.id}`}
      className="block rounded-lg border border-white/8 bg-[#0a0e1a]/60
                 hover:border-[#2dd4bf]/30 hover:bg-[#111827] transition-colors p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-[#f0ece4]">{ws.name}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase
                             tracking-wider bg-[#2dd4bf]/10 text-[#2dd4bf]/80
                             border border-[#2dd4bf]/20">
              {ROLE_LABEL[ws.my_role]}
            </span>
            <StatusChip status={ws.status} />
          </div>
          <div className="mt-1 text-xs text-[#6b7594]">
            {ws.member_count}/{ws.seat_cap} members · created {new Date(ws.created_at).toLocaleDateString()}
          </div>
          {isCardPending && cardPendingDays !== null && (
            <div className="mt-2 text-xs text-amber-300/90">
              ⚠ Workspace is read-only — Owner has {cardPendingDays} day{cardPendingDays === 1 ? '' : 's'} to add a card.
            </div>
          )}
        </div>
        <div className="text-[#6b7594] text-lg">→</div>
      </div>
    </Link>
  )
}

function StatusChip({ status }: { status: Workspace['status'] }) {
  const tone =
    status === 'card_pending' ? 'bg-amber-400/10 text-amber-300 border-amber-400/30' :
    status === 'archived' ? 'bg-red-400/10 text-red-300 border-red-400/30' :
    status === 'canceled' ? 'bg-red-400/10 text-red-300 border-red-400/30' :
    status === 'trialing' ? 'bg-yellow-400/10 text-yellow-300 border-yellow-400/30' :
    'bg-emerald-400/10 text-emerald-300 border-emerald-400/30'
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase
                      tracking-wider border ${tone}`}>
      {STATUS_LABEL[status]}
    </span>
  )
}

function EmptyHint() {
  return (
    <div className="rounded-lg border border-dashed border-white/10 p-8 text-center">
      <div className="text-sm text-[#6b7594] mb-2">
        You aren&apos;t in any workspaces yet.
      </div>
      <div className="text-xs text-[#6b7594]/70 max-w-md mx-auto">
        A workspace is shared by your vessel&apos;s crew. Create one to share
        credentials, dossier, and chat history across rotation watches.
        You&apos;ll be the Owner; you can invite others as Admins or Members.
      </div>
    </div>
  )
}

function CreateWorkspaceModal({
  name, onChange, onCancel, onSubmit, submitting, error,
}: {
  name: string
  onChange: (s: string) => void
  onCancel: () => void
  onSubmit: (e: React.FormEvent) => void
  submitting: boolean
  error: string | null
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-lg border border-white/10
                      bg-[#0a0e1a] p-5 shadow-xl">
        <h2 className="text-lg font-semibold mb-1">New workspace</h2>
        <p className="text-xs text-[#6b7594] mb-4">
          You&apos;ll be the Owner. You can rename it later.
        </p>
        <form onSubmit={onSubmit}>
          <label className="block text-xs font-mono uppercase tracking-wider
                            text-[#6b7594] mb-1.5">
            Workspace name
          </label>
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => onChange(e.target.value)}
            placeholder="e.g. MV Karynn-Q"
            maxLength={120}
            className="w-full px-3 py-2 rounded-md bg-[#111827] border border-white/10
                       text-sm text-[#f0ece4] focus:outline-none focus:border-[#2dd4bf]/50"
          />
          {error && (
            <div className="mt-2 text-xs text-red-400">{error}</div>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={submitting}
              className="px-3 py-1.5 text-sm text-[#6b7594] hover:text-[#f0ece4]
                         transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || submitting}
              className="px-3 py-1.5 rounded-md bg-[#2dd4bf]/15 border border-[#2dd4bf]/30
                         text-sm font-medium text-[#2dd4bf] hover:bg-[#2dd4bf]/25
                         disabled:opacity-40 disabled:cursor-not-allowed
                         transition-colors"
            >
              {submitting ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
