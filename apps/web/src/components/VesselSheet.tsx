'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useViewMode } from '@/lib/useViewMode'

interface VesselDetail {
  id: string
  name: string
  vessel_type: string
  route_types: string[]
  cargo_types: string[]
  gross_tonnage: number | null
}

const ROUTE_LABEL: Record<string, string> = { inland: 'Inland', coastal: 'Coastal', international: 'Intl' }

function routeSummary(routes: string[]) {
  if (routes.length === 0) return 'No route'
  if (routes.length === 1) return ROUTE_LABEL[routes[0]] ?? routes[0]
  return 'Multiple routes'
}

interface Props {
  onClose: () => void
  /** D6.55 — when set, the sheet shows the WORKSPACE's vessels and
   *  hides "Add vessel" for non-Owner/Admin members. Without it the
   *  sheet behaves as before (personal-tier vessels). */
  workspaceId?: string | null
  /** Caller's role in the workspace, used to gate the Add Vessel button.
   *  Owner/Admin can add a workspace vessel; members can't. */
  workspaceRole?: 'owner' | 'admin' | 'member' | null
}

export function VesselSheet({ onClose, workspaceId, workspaceRole }: Props) {
  const router = useRouter()
  const { vessels, activeVesselId, setActiveVessel, setVessels, removeVessel } = useAuthStore()
  const { viewMode } = useViewMode()
  const isWheelhouseOnly = viewMode?.mode === 'wheelhouse_only'

  // D6.55 — Add Vessel button visibility:
  //   - Personal context (no workspaceId): show, unless wheelhouse_only
  //     (those users have no personal-tier surface and shouldn't be
  //     told to add a personal vessel)
  //   - Workspace context: only show for Owner/Admin
  const canAddVessel = workspaceId
    ? workspaceRole === 'owner' || workspaceRole === 'admin'
    : !isWheelhouseOnly

  const [detail, setDetail] = useState<VesselDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [dismissing, setDismissing] = useState(false)
  // Sprint D6.5 — inline confirm-delete (no modal). Pilot complaint:
  // edit/delete were buried in the Account tab; My Vessels is now the
  // single source of truth.
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Drag-to-dismiss
  const dragStartY = useRef<number | null>(null)
  const dragCurrentY = useRef(0)
  const [dragOffset, setDragOffset] = useState(0)

  // D6.55 — fetch from the right scope. Workspace context → workspace
  // vessels; personal → user's personal vessels (legacy behavior).
  useEffect(() => {
    const url = workspaceId
      ? `/vessels?workspace_id=${workspaceId}`
      : '/vessels'
    apiRequest<VesselDetail[]>(url)
      .then(rows => {
        setDetail(rows)
        // Only sync the auth-store summary list when in personal scope —
        // workspace vessels aren't personal-tier and shouldn't show up
        // in the user's personal vessel store.
        if (!workspaceId) {
          setVessels(rows.map(v => ({ id: v.id, name: v.name })))
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  function dismiss() {
    setDismissing(true)
    setTimeout(onClose, 260)
  }

  function selectVessel(id: string | null) {
    setActiveVessel(id)
    dismiss()
  }

  function goToOnboarding() {
    dismiss()
    setTimeout(() => router.push('/onboarding'), 280)
  }

  function goToOnboardingAdd() {
    dismiss()
    setTimeout(() => router.push('/onboarding?add=true'), 280)
  }

  function editVessel(id: string) {
    // Re-use the existing /account/vessel/[id] full editor (1010 lines,
    // well-tested). No need to rebuild inside the sheet.
    dismiss()
    setTimeout(() => router.push(`/account/vessel/${id}`), 280)
  }

  async function deleteVessel(id: string) {
    setDeletingId(id)
    try {
      await apiRequest(`/vessels/${id}`, { method: 'DELETE' })
      setDetail(prev => prev.filter(v => v.id !== id))
      setVessels(detail.filter(v => v.id !== id).map(v => ({ id: v.id, name: v.name })))
      removeVessel(id)
      // If the deleted vessel was active, deselect.
      if (activeVesselId === id) {
        setActiveVessel(null)
      }
    } catch {
      // Silent — rare path; UI doesn't need a global error toast here.
    } finally {
      setDeletingId(null)
      setConfirmDeleteId(null)
    }
  }

  // Touch drag
  function onTouchStart(e: React.TouchEvent) {
    dragStartY.current = e.touches[0].clientY
    dragCurrentY.current = 0
  }
  function onTouchMove(e: React.TouchEvent) {
    if (dragStartY.current === null) return
    const delta = e.touches[0].clientY - dragStartY.current
    if (delta < 0) return
    dragCurrentY.current = delta
    setDragOffset(delta)
  }
  function onTouchEnd() {
    if (dragCurrentY.current > 80) dismiss()
    else setDragOffset(0)
    dragStartY.current = null
  }

  const sheetTransform = dismissing
    ? 'translateY(100%)'
    : dragOffset > 0
    ? `translateY(${dragOffset}px)`
    : 'translateY(0)'

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/60 transition-opacity duration-300 ${dismissing ? 'opacity-0' : 'opacity-100'}`}
        onClick={dismiss}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        className={`relative flex flex-col bg-[#111827] border-t border-white/10 rounded-t-2xl
          ${dismissing ? '' : 'animate-[sheetSlideUp_0.3s_ease-out]'}`}
        style={{
          height: '60vh',
          transform: sheetTransform,
          transition: dragOffset === 0 && !dismissing ? 'transform 0.25s ease-out' : undefined,
        }}
      >
        {/* Drag handle */}
        <div
          className="flex-shrink-0 flex justify-center pt-3 pb-2 cursor-grab active:cursor-grabbing"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
        >
          <div className="w-9 h-1 rounded-full bg-white/20" />
        </div>

        {/* Header */}
        <div className="flex-shrink-0 px-5 pb-3">
          <h2 className="font-display text-xl font-bold text-[#f0ece4] tracking-wide">My Vessels</h2>
        </div>

        <div className="flex-shrink-0 mx-5 border-t border-white/8" />

        {/* Scrollable vessel list */}
        <div className="citation-sheet-content flex-1 overflow-y-auto py-2 min-h-0">

          {/* Loading skeleton */}
          {loading && (
            <div className="flex flex-col gap-1 px-5 pt-2">
              {[1, 2].map(i => (
                <div key={i} className="flex flex-col gap-1.5 py-3">
                  <div className="h-3.5 bg-white/8 rounded animate-pulse w-2/3" />
                  <div className="h-2.5 bg-white/5 rounded animate-pulse w-1/3" />
                </div>
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && detail.length === 0 && (
            <div className="flex flex-col items-center text-center px-6 pt-6 pb-4 gap-4">
              {/* Anchor icon */}
              <div className="w-14 h-14 rounded-full bg-[#2dd4bf]/10 flex items-center justify-center">
                <svg className="w-7 h-7 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="5" r="3" />
                  <line x1="12" y1="22" x2="12" y2="8" />
                  <path d="M5 12H2a10 10 0 0 0 20 0h-3" />
                </svg>
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="font-display text-lg font-bold text-[#f0ece4] tracking-wide">
                  {workspaceId ? 'No vessel yet' : 'No vessels yet'}
                </p>
                <p className="font-mono text-xs text-[#6b7594] leading-relaxed max-w-[260px]">
                  {workspaceId && !canAddVessel
                    ? 'Ask your captain to set up the workspace vessel.'
                    : 'Add a vessel to get compliance answers tailored to your specific ship.'}
                </p>
              </div>
              <div className="flex flex-col gap-2 w-full max-w-xs mt-1">
                {/* D6.55 — Add Vessel only shown when allowed by scope/role.
                    Wheelhouse-only members and non-owner/admin workspace
                    members both fall through to "Close" only. */}
                {canAddVessel && (
                  <button
                    onClick={goToOnboardingAdd}
                    className="w-full bg-[#2dd4bf] hover:brightness-110 text-[#0a0e1a]
                      font-mono font-bold text-sm uppercase tracking-wider
                      rounded-lg py-2.5 transition-[filter] duration-150"
                  >
                    Add a vessel
                  </button>
                )}
                <button
                  onClick={dismiss}
                  className="w-full border border-white/10 hover:bg-white/5
                    text-[#f0ece4]/80 font-mono text-sm rounded-lg py-2.5
                    transition-colors duration-150"
                >
                  {canAddVessel ? 'Continue without a vessel' : 'Close'}
                </button>
              </div>
            </div>
          )}

          {/* Vessel rows — Sprint D6.5: name-area selects, side actions
              cluster handles edit/delete with inline confirmation. */}
          {!loading && detail.length > 0 && detail.map(v => {
            const isActive = v.id === activeVesselId
            const isConfirming = confirmDeleteId === v.id
            const isDeleting = deletingId === v.id
            return (
              <div
                key={v.id}
                className={`w-full flex items-center gap-2 px-5 py-3.5
                  transition-colors duration-150
                  ${isActive ? 'bg-[#2dd4bf]/8' : ''}`}
              >
                {/* Selectable name area */}
                <button
                  onClick={() => selectVessel(v.id)}
                  className="flex-1 min-w-0 flex items-center gap-3 text-left"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-sm text-[#f0ece4] truncate">{v.name}</p>
                    <p className="font-mono text-xs text-[#2dd4bf]/70 mt-0.5">
                      {v.vessel_type} · {routeSummary(v.route_types)}
                    </p>
                  </div>
                  {isActive && (
                    <svg className="w-4 h-4 text-[#2dd4bf] flex-shrink-0" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                      <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                    </svg>
                  )}
                </button>

                {/* Action cluster — edit / delete (with inline confirm) */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  {isConfirming ? (
                    <>
                      <button
                        onClick={() => deleteVessel(v.id)}
                        disabled={isDeleting}
                        className="font-mono text-xs text-red-400 hover:underline disabled:opacity-50 px-1.5 py-1"
                      >
                        {isDeleting ? '…' : 'Confirm'}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        disabled={isDeleting}
                        className="font-mono text-xs text-[#6b7594] hover:underline px-1.5 py-1"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => editVessel(v.id)}
                        className="font-mono text-xs text-[#2dd4bf] hover:underline px-1.5 py-1"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(v.id)}
                        className="font-mono text-xs text-red-400/70 hover:text-red-400 px-1.5 py-1"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })}

          {/* Divider */}
          {!loading && detail.length > 0 && (
            <div className="mx-5 border-t border-white/8 my-1" />
          )}

          {/* No vessel option */}
          {!loading && detail.length > 0 && (
            <button
              onClick={() => selectVessel(null)}
              className={`w-full flex items-center justify-between gap-3 px-5 py-3.5 text-left
                transition-colors duration-150
                ${activeVesselId === null ? 'bg-[#2dd4bf]/8 hover:bg-[#2dd4bf]/12' : 'hover:bg-white/5'}`}
            >
              <p className="font-mono text-sm text-[#6b7594]">No vessel</p>
              {activeVesselId === null && (
                <svg className="w-4 h-4 text-[#2dd4bf] flex-shrink-0" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                  <path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/>
                </svg>
              )}
            </button>
          )}

          {/* Add another vessel — only when allowed (D6.55) */}
          {!loading && detail.length > 0 && canAddVessel && (
            <button
              onClick={goToOnboarding}
              className="w-full flex items-center gap-2 px-5 py-3.5 text-left
                text-[#2dd4bf] hover:bg-white/5 transition-colors duration-150"
            >
              <span className="font-mono text-sm">+ Add another vessel</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
