'use client'

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { apiRequest } from '@/lib/api'


// Sprint D6.88 Phase 1.5 — render the regulation body as Markdown.
// Corpus chunks store pipe-tables, **bold** for callouts, and
// `* bullet` lists; rendering as plain whitespace-pre-wrap turned
// these into a wall of raw syntax (Blake's IMDG 7.4 screenshot).
// Components are sized for the citation sheet (smaller than chat
// body; monospace to match the regulatory text aesthetic).
const citationMdComponents: Components = {
  p: ({ children }) => (
    <p className="font-mono text-xs text-[--color-off-white]/80 leading-relaxed mb-2 last:mb-0 whitespace-pre-wrap">
      {children}
    </p>
  ),
  h1: ({ children }) => (
    <h1 className="font-display text-sm font-bold text-[--color-off-white] mt-3 mb-1.5 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="font-display text-xs font-bold text-[--color-off-white] mt-2.5 mb-1 first:mt-0 uppercase tracking-wider">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="font-display text-xs font-semibold text-[--color-off-white]/90 mt-2 mb-1 first:mt-0">
      {children}
    </h3>
  ),
  strong: ({ children }) => <strong className="text-[--color-off-white] font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic text-[--color-off-white]/85">{children}</em>,
  ul: ({ children }) => <ul className="list-disc list-outside pl-4 mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-outside pl-4 mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }) => (
    <li className="font-mono text-xs text-[--color-off-white]/80 leading-relaxed">{children}</li>
  ),
  // Tables — the canonical reason this Markdown pipeline exists.
  // IMDG segregation tables, SOLAS applicability tables, etc.
  // Wrap in an overflow-x container so wide tables can scroll
  // horizontally rather than blowing out the sheet.
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded border border-white/10">
      <table className="min-w-full text-[10px] font-mono border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-b border-white/5 last:border-b-0">{children}</tr>,
  th: ({ children }) => (
    <th className="px-2 py-1 text-left font-semibold text-[--color-off-white]/90 border-r border-white/5 last:border-r-0 align-top">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-2 py-1 text-[--color-off-white]/80 border-r border-white/5 last:border-r-0 align-top whitespace-pre-wrap">
      {children}
    </td>
  ),
  hr: () => <hr className="border-white/10 my-2" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-[--color-teal]/40 pl-2 italic text-[--color-off-white]/70 my-2">
      {children}
    </blockquote>
  ),
  code: ({ children, className }) => {
    if (className?.startsWith('language-')) {
      return (
        <pre className="block bg-black/30 border border-white/10 rounded px-2 py-1.5 text-[10px] font-mono text-[--color-off-white]/80 overflow-x-auto my-2 whitespace-pre">
          {children}
        </pre>
      )
    }
    return <code className="bg-black/30 border border-white/10 rounded px-1 py-0.5 text-[10px] font-mono">{children}</code>
  },
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-[--color-teal] underline">
      {children}
    </a>
  ),
}

// Sprint D6.90 — references fallback. When the cited identifier
// doesn't exist as its own row (e.g. MSC.1/Circ.1432, MARPOL Annex I,
// NVIC 10-97 bare), the backend returns full_text='' plus up to 8
// `references` — corpus rows whose body mentions the identifier.
// The sheet renders these as clickable cards so the user can pivot
// to the surrounding context.
interface RegulationReference {
  source: string
  section_number: string
  section_title: string | null
}

interface RegulationDetail {
  source: string
  section_number: string
  section_title: string | null
  full_text: string
  effective_date: string | null
  up_to_date_as_of: string | null
  copyrighted: boolean
  references?: RegulationReference[]
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
    return { url: 'https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Commercial-Regulations-standards-CG-5PS/NVIC/', label: 'View on USCG.mil' }
  }
  if (source === 'colregs') {
    return { url: 'https://www.imo.org/en/About/Conventions/Pages/COLREG.aspx', label: 'View on IMO.org' }
  }
  if (source === 'solas') {
    return { url: 'https://www.imo.org/en/publications/Pages/default.aspx', label: 'View official source' }
  }
  if (source === 'solas_supplement') {
    return { url: 'https://www.imo.org/en/publications/Pages/default.aspx', label: 'View on IMO.org' }
  }
  if (source === 'stcw') {
    return { url: 'https://www.imo.org/en/OurWork/HumanElement/Pages/STCW-Conv-LINK.aspx', label: 'View on IMO.org' }
  }
  if (source === 'stcw_supplement') {
    return { url: 'https://www.imo.org/en/OurWork/HumanElement/Pages/STCW-Conv-LINK.aspx', label: 'View on IMO.org' }
  }
  if (source === 'ism') {
    return { url: 'https://www.imo.org/en/OurWork/HumanElement/Pages/ISMCode.aspx', label: 'View on IMO.org' }
  }
  return null
}

export function CitationSheet({ source, sectionNumber, sectionTitle, onClose }: Props) {
  // Sprint D6.90 — references-fallback navigation.
  //
  // The sheet now tracks "currently viewed" state internally. When the
  // initial lookup returns references mode (no row for the cited
  // identifier, but corpus rows that mention it), the user can click
  // a reference card to swap the sheet contents in-place. The props
  // serve as the initial view; subsequent navigation lives in state.
  // Back button restores the previous entry from the stack.
  const [viewing, setViewing] = useState({ source, sectionNumber, sectionTitle })
  const [navStack, setNavStack] = useState<typeof viewing[]>([])
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
    // Use the query-param lookup endpoint so section_numbers containing
    // forward slashes (e.g. "STCW Ch.II Reg.II/2") aren't mangled by the
    // reverse proxy into extra path segments.
    setLoading(true)
    setError(false)
    const qs = new URLSearchParams({
      source: viewing.source,
      section_number: viewing.sectionNumber,
    })
    apiRequest<RegulationDetail>(`/regulations/lookup?${qs.toString()}`)
      .then((d) => { setDetail(d); setLoading(false) })
      .catch(() => { setError(true); setLoading(false) })
  }, [viewing.source, viewing.sectionNumber])

  /** Navigate to a referenced regulation. Pushes current view onto
   *  the back stack so the user can return. */
  function openReference(ref: RegulationReference) {
    setNavStack((prev) => [...prev, viewing])
    setViewing({
      source: ref.source,
      sectionNumber: ref.section_number,
      sectionTitle: ref.section_title ?? '',
    })
  }

  function navigateBack() {
    setNavStack((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      const last = next.pop()!
      setViewing(last)
      return next
    })
  }

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

  // D6.90 — use viewing.* not the original props so the source link
  // updates when the user navigates to a reference.
  const sourceLink = getSourceLink(viewing.source, viewing.sectionNumber)
  const isReferencesMode = !!detail?.references && detail.references.length > 0 && !detail.full_text
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

        {/* Header — D6.90 shows back button + viewing.* state so the
            header updates as user navigates through references. */}
        <div className="flex-shrink-0 px-5 pb-4">
          {navStack.length > 0 && (
            <button
              type="button"
              onClick={navigateBack}
              className="font-mono text-[11px] text-[--color-teal]/80 hover:text-[--color-teal]
                         transition-colors mb-2 flex items-center gap-1.5"
              aria-label="Back to previous citation"
            >
              <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M7.5 2L3.5 6l4 4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back
            </button>
          )}
          <p className="font-display text-xl font-bold text-[--color-teal] tracking-wide leading-tight">
            {viewing.sectionNumber}
          </p>
          <p className="font-mono text-sm text-[--color-off-white] mt-1 leading-snug">
            {detail?.section_title ?? viewing.sectionTitle}
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

          {/* D6.90 — references mode: cited identifier isn't a row in
              our corpus, but is referenced by other regulations. Render
              clickable cards for each. Sorted server-side by authority
              tier (CFR/IMO first, flag-state last). */}
          {detail && !loading && isReferencesMode && (
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-3">
                <p className="font-mono text-xs text-amber-300/90 leading-snug">
                  Full text of <span className="font-bold">{viewing.sectionNumber}</span> isn&apos;t
                  in our corpus directly.
                </p>
                <p className="font-mono text-[11px] text-[--color-off-white]/60 leading-snug mt-1.5">
                  Found {detail.references!.length} document{detail.references!.length === 1 ? '' : 's'} in our index
                  that cite it — open one to read the surrounding context.
                </p>
              </div>
              <ul className="flex flex-col gap-2">
                {detail.references!.map((ref) => (
                  <li key={`${ref.source}::${ref.section_number}`}>
                    <button
                      type="button"
                      onClick={() => openReference(ref)}
                      className="w-full text-left px-3 py-2.5 rounded-lg
                                 bg-white/5 border border-white/8
                                 hover:bg-white/10 hover:border-[--color-teal]/30
                                 transition-colors"
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="font-display text-sm font-semibold text-[--color-teal]">
                          {ref.section_number}
                        </span>
                        <span className="font-mono text-[10px] text-[--color-off-white]/40 uppercase tracking-wider">
                          {ref.source}
                        </span>
                      </div>
                      {ref.section_title && (
                        <p className="font-mono text-xs text-[--color-off-white]/70 leading-snug mt-1 line-clamp-2">
                          {ref.section_title}
                        </p>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {detail && !loading && !isReferencesMode && detail.copyrighted && (
            <div className="rounded-lg border border-[--color-teal]/20 bg-[--color-teal]/5 px-4 py-4 mt-1">
              <p className="font-display text-sm font-semibold text-[--color-teal] mb-2">
                IMO Copyrighted Content
              </p>
              {/* D6.88 Phase 1.5 — Markdown renders regulation tables,
                  bold callouts, bullet lists, etc. The corpus stores
                  these in Markdown (pipe-tables, *bullets, **bold**);
                  rendering as plain text turned IMDG segregation
                  tables into a wall of pipes. */}
              <div className="text-[--color-off-white]/80">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={citationMdComponents}>
                  {detail.full_text}
                </ReactMarkdown>
              </div>
              <p className="font-mono text-[10px] text-[--color-off-white]/50 mt-3 italic">
                Excerpt shown to support compliance verification. Official text and the
                latest amendments are available from your flag state, classification
                society, or IMO Publishing.
              </p>
            </div>
          )}

          {detail && !loading && !isReferencesMode && !detail.copyrighted && (
            <div className="text-[--color-off-white]/80">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={citationMdComponents}>
                {detail.full_text}
              </ReactMarkdown>
            </div>
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

          {sourceLink && !isReferencesMode && (
            <button
              onClick={() => window.open(sourceLink.url, '_blank', 'noopener')}
              className="font-mono text-xs text-[--color-teal] hover:underline whitespace-nowrap"
            >
              {sourceLink.label} ↗
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
