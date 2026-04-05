'use client'

import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '@/lib/api'

interface RegulationDetail {
  source: string
  section_number: string
  section_title: string | null
  full_text: string
  effective_date: string | null
  up_to_date_as_of: string | null
  copyrighted: boolean
}

interface Props {
  source: string
  sectionNumber: string
  sectionTitle: string
  onClose: () => void
}

function getSourceLink(source: string, sectionNumber: string): { url: string; label: string } | null {
  if (source.startsWith('cfr_')) {
    const match = source.match(/cfr_(\d+)/)
    if (!match) return null
    const title = match[1]
    const sectionPart = sectionNumber.replace(/^\d+\s+CFR\s+/i, '')
    return {
      url: `https://www.ecfr.gov/current/title-${title}/section-${sectionPart}`,
      label: 'View on eCFR',
    }
  }
  if (source === 'nvic') {
    return { url: 'https://www.dco.uscg.mil/Our-Organization/NVIC/', label: 'View on USCG.mil' }
  }
  if (source === 'colregs') {
    return { url: 'https://www.imo.org/en/About/Conventions/Pages/COLREG.aspx', label: 'View on IMO.org' }
  }
  if (source === 'solas') {
    return { url: 'https://www.imo.org/en/publications', label: 'View official source' }
  }
  if (source === 'solas_supplement') {
    return { url: 'https://www.imo.org/en/publications', label: 'View on IMO.org' }
  }
  return null
}

export function CitationSheet({ source, sectionNumber, sectionTitle, onClose }: Props) {
  const [detail, setDetail] = useState<RegulationDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  // Drag-to-dismiss state
  const sheetRef = useRef<HTMLDivElement>(null)
  const dragStartY = useRef<number | null>(null)
  const dragCurrentY = useRef(0)
  const [dragOffset, setDragOffset] = useState(0)
  const [dismissing, setDismissing] = useState(false)

  useEffect(() => {
    const encoded = encodeURIComponent(sectionNumber)
    apiRequest<RegulationDetail>(`/regulations/${source}/${encoded}`)
      .then((d) => { setDetail(d); setLoading(false) })
      .catch(() => { setError(true); setLoading(false) })
  }, [source, sectionNumber])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  function dismiss() {
    setDismissing(true)
    setTimeout(onClose, 260)
  }

  // Touch drag
  function onTouchStart(e: React.TouchEvent) {
    dragStartY.current = e.touches[0].clientY
    dragCurrentY.current = 0
  }

  function onTouchMove(e: React.TouchEvent) {
    if (dragStartY.current === null) return
    const delta = e.touches[0].clientY - dragStartY.current
    if (delta < 0) return // no upward drag
    dragCurrentY.current = delta
    setDragOffset(delta)
  }

  function onTouchEnd() {
    if (dragCurrentY.current > 80) {
      dismiss()
    } else {
      setDragOffset(0)
    }
    dragStartY.current = null
  }

  const sourceLink = getSourceLink(source, sectionNumber)
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
        ref={sheetRef}
        className={`relative flex flex-col bg-[#111827] border-t border-white/10 rounded-t-2xl
          ${dismissing ? '' : 'animate-[sheetSlideUp_0.3s_ease-out]'}`}
        style={{
          height: '70vh',
          transform: sheetTransform,
          transition: dragOffset === 0 && !dismissing ? 'transform 0.25s ease-out' : undefined,
        }}
      >
        {/* Drag handle zone */}
        <div
          className="flex-shrink-0 flex justify-center pt-3 pb-2 cursor-grab active:cursor-grabbing"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
        >
          <div className="w-9 h-1 rounded-full bg-white/20" />
        </div>

        {/* Header */}
        <div className="flex-shrink-0 px-5 pb-4">
          <p className="font-display text-xl font-bold text-[--color-teal] tracking-wide leading-tight">
            {sectionNumber}
          </p>
          <p className="font-mono text-sm text-[--color-off-white] mt-1 leading-snug">
            {detail?.section_title ?? sectionTitle}
          </p>
        </div>

        <div className="flex-shrink-0 mx-5 border-t border-white/8" />

        {/* Scrollable body */}
        <div className="citation-sheet-content flex-1 overflow-y-auto px-5 py-4 min-h-0">
          {loading && (
            <div className="flex flex-col gap-2.5 pt-2">
              <div className="h-3 bg-white/8 rounded animate-pulse w-full" />
              <div className="h-3 bg-white/8 rounded animate-pulse w-5/6" />
              <div className="h-3 bg-white/8 rounded animate-pulse w-full" />
              <div className="h-3 bg-white/8 rounded animate-pulse w-4/5" />
              <div className="h-3 bg-white/8 rounded animate-pulse w-full" />
              <div className="h-3 bg-white/8 rounded animate-pulse w-3/4" />
            </div>
          )}

          {error && !loading && (
            <p className="font-mono text-sm text-[--color-muted] italic">
              Regulation text unavailable.
            </p>
          )}

          {detail && !loading && detail.copyrighted && (
            <div className="rounded-lg border border-[--color-teal]/20 bg-[--color-teal]/5 px-4 py-4 mt-1">
              <p className="font-display text-sm font-semibold text-[--color-teal] mb-2">
                IMO Copyrighted Content
              </p>
              <p className="font-mono text-xs text-[--color-off-white]/80 leading-relaxed">
                {detail.full_text}
              </p>
            </div>
          )}

          {detail && !loading && !detail.copyrighted && (
            <p className="font-mono text-xs text-[--color-off-white]/80 leading-relaxed whitespace-pre-wrap">
              {detail.full_text}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-white/8 px-5 py-4 flex items-center justify-between gap-4">
          <div>
            {detail?.up_to_date_as_of && (
              <p className="font-mono text-[10px] text-[--color-muted]">
                As of: {detail.up_to_date_as_of}
              </p>
            )}
            <p className="font-mono text-[10px] text-[--color-muted] mt-0.5">
              Navigation aid only — not legal advice
            </p>
          </div>

          {sourceLink && (
            <a
              href={sourceLink.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs text-[--color-teal] hover:underline whitespace-nowrap"
            >
              {sourceLink.label} ↗
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
