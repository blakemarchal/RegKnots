'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiRequest } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'

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
}

export function VesselSheet({ onClose }: Props) {
  const router = useRouter()
  const { vessels, activeVesselId, setActiveVessel, setVessels } = useAuthStore()

  const [detail, setDetail] = useState<VesselDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [dismissing, setDismissing] = useState(false)

  // Drag-to-dismiss
  const dragStartY = useRef<number | null>(null)
  const dragCurrentY = useRef(0)
  const [dragOffset, setDragOffset] = useState(0)

  // Fetch fresh vessel list on open
  useEffect(() => {
    apiRequest<VesselDetail[]>('/vessels')
      .then(rows => {
        setDetail(rows)
        // Sync summary list into store (catches vessels added via onboarding)
        setVessels(rows.map(v => ({ id: v.id, name: v.name })))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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

          {/* Vessel rows */}
          {!loading && detail.map(v => {
            const isActive = v.id === activeVesselId
            return (
              <button
                key={v.id}
                onClick={() => selectVessel(v.id)}
                className={`w-full flex items-center justify-between gap-3 px-5 py-3.5 text-left
                  transition-colors duration-150
                  ${isActive ? 'bg-[#2dd4bf]/8 hover:bg-[#2dd4bf]/12' : 'hover:bg-white/5'}`}
              >
                <div className="min-w-0">
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
            )
          })}

          {/* Divider */}
          {!loading && <div className="mx-5 border-t border-white/8 my-1" />}

          {/* No vessel option */}
          {!loading && (
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

          {/* Add another vessel */}
          {!loading && (
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
