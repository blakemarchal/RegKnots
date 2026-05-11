'use client'

import { useState, type ReactNode } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, CitedRegulation } from '@/types/chat'
import { CitationChip } from './CitationChip'
import { TierChip, TierWebDisclaimer } from './TierChip'

// ── Copy-to-clipboard helpers ──────────────────────────────────────────────────

/**
 * Strip common markdown syntax so the copied text reads as clean prose
 * when pasted into email, notes, or another chat. We deliberately keep
 * line breaks and list structure intact — only the formatting markers
 * (asterisks, backticks, headings, links, blockquote arrows, etc.) are
 * removed.
 */
function stripMarkdown(md: string): string {
  return md
    // Fenced code blocks: keep contents, drop fences
    .replace(/```[a-zA-Z0-9_-]*\n?/g, '')
    .replace(/```/g, '')
    // Inline code: keep contents
    .replace(/`([^`]+)`/g, '$1')
    // Images: keep alt text only
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    // Links: keep label only
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    // Headings: drop leading #
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    // Bold / italic markers
    .replace(/\*\*\*([^*]+)\*\*\*/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '$1')
    .replace(/___([^_]+)___/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/(?<!_)_([^_\n]+)_(?!_)/g, '$1')
    // Strikethrough
    .replace(/~~([^~]+)~~/g, '$1')
    // Blockquote markers
    .replace(/^\s{0,3}>\s?/gm, '')
    // Horizontal rules
    .replace(/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/gm, '')
    // Unordered list markers → keep bullet for readability
    .replace(/^(\s*)[-*+]\s+/gm, '$1• ')
    // Ordered list markers stay as "1. "
    // Collapse 3+ blank lines into 2
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/**
 * Copy text to the clipboard. Prefers the modern async API, falls back
 * to a hidden textarea + execCommand for older browsers and any
 * environment where navigator.clipboard is unavailable (e.g. older iOS
 * Safari, non-secure contexts).
 */
async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.top = '0'
    textarea.style.left = '-9999px'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

// ── Icons ──────────────────────────────────────────────────────────────────────

function ClipboardIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyMessageButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    const ok = await copyTextToClipboard(stripMarkdown(content))
    if (!ok) return
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={copied ? 'Copied to clipboard' : 'Copy message'}
      title={copied ? 'Copied!' : 'Copy message'}
      className={`w-11 h-11 flex items-center justify-center rounded-lg
        transition-colors duration-150
        ${copied
          ? 'text-[#2dd4bf]'
          : 'text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5 active:bg-white/10'}`}
    >
      {copied ? <CheckIcon /> : <ClipboardIcon />}
    </button>
  )
}

interface Props {
  message: Message
  onCitationTap: (source: string, sectionNumber: string, sectionTitle: string) => void
}

// ── Inline citation injection ──────────────────────────────────────────────────
//
// Sprint D6.87 — expanded from CFR-only to all maritime citation
// patterns the model actually writes. Before D6.87, only `\d+ CFR ...`
// strings rendered as inline chips; everything else (SOLAS Ch.VI Reg.2,
// IMDG Ch.7.4, MSC.1/Circ.1440, NVIC 10-97, STCW Code A-II/3, ISM 1.2.3,
// 46 USC 7101) stayed as plain text. Blake's 2026-05-11 VGM screenshot
// made the problem visible: the answer cited SOLAS Reg.2, para.6 ten
// times and rendered zero chips for it.
//
// Each pattern is paired with a `sourceHint` so a click on a chip the
// DB doesn't know about still produces a sensible source attribution.
// The DB citation_map (passed via `citations`) still wins on exact
// section_number match — sourceHint is only the fallback.

interface CitationPattern {
  re: RegExp
  sourceHint: string
  /** Extract the canonical section_number from the regex match. */
  toSection: (m: RegExpExecArray) => string
}

const CITATION_PATTERNS: CitationPattern[] = [
  // 46 CFR 91.60-10 / (33 CFR 153) / 49 CFR 172.101
  {
    re: /\(?(\d+)\s+CFR\s+(\d+(?:\.\d+(?:-\d+)?)?)\)?/g,
    sourceHint: 'cfr',
    toSection: m => `${m[1]} CFR ${m[2]}`,
  },
  // 46 USC 7101 / 46 USC 11102
  {
    re: /\b(\d+)\s+USC\s+(\d+)\b/g,
    sourceHint: 'usc',
    toSection: m => `${m[1]} USC ${m[2]}`,
  },
  // SOLAS Ch.VI Reg.2, para.6 / SOLAS Ch.II-2 Reg.10 / SOLAS Ch.VI Part A
  {
    re: /\bSOLAS\s+Ch\.?\s*([IVX]+(?:-\d+)?)\s+(Reg\.?\s*\d+(?:[,.]\s*para\.?\s*\d+(?:\.\d+)?)?|Part\s+[A-Z])/g,
    sourceHint: 'solas',
    toSection: m => `SOLAS Ch.${m[1]} ${m[2].replace(/\s+/g, ' ')}`,
  },
  // IMDG Ch.7.4 / IMDG Chapter 7.4 / IMDG 7.3 / IMDG 7.3.1
  {
    re: /\bIMDG\s+(?:Ch\.?|Chapter)?\s*(\d+(?:\.\d+)*)\b/g,
    sourceHint: 'imdg',
    toSection: m => `IMDG ${m[1]}`,
  },
  // MSC.1/Circ.1440 / MSC.520(106) / MSC.97(73)
  {
    re: /\bMSC\.(\d+(?:\(\d+\)|\/Circ\.\d+)?)/g,
    sourceHint: 'imo_supplement',
    toSection: m => `MSC.${m[1]}`,
  },
  // NVIC 10-97 / NVIC 10-97 §5 / NVIC 01-20
  {
    re: /\bNVIC\s+(\d{2}-\d{2})(?:\s+§\s*(\d+))?\b/g,
    sourceHint: 'nvic',
    toSection: m => m[2] ? `NVIC ${m[1]} §${m[2]}` : `NVIC ${m[1]}`,
  },
  // STCW Code A-II/3 / STCW Code B-I/2 / STCW Reg.II/1
  // The STCW corpus stores Convention regulations under the canonical
  // form 'STCW Ch.<chapter> Reg.<chapter>/<number>' (e.g.,
  // 'STCW Ch.II Reg.II/1'). The model commonly writes the abbreviated
  // 'STCW Reg.II/1'; we expand the abbreviation into the canonical
  // section_number here so chip clicks resolve. The chapter is the
  // Roman-numeral portion before the '/'.
  {
    re: /\bSTCW\s+(?:(Code\s+[AB])-([IVX]+\/\d+)|Reg\.?\s*([IVX]+\/\d+))/g,
    sourceHint: 'stcw',
    toSection: m => {
      if (m[1]) return `STCW ${m[1]}-${m[2]}`  // STCW Code A-II/3
      const chapter = m[3].split('/')[0]      // 'II/1' -> 'II'
      return `STCW Ch.${chapter} Reg.${m[3]}` // -> STCW Ch.II Reg.II/1
    },
  },
  // ISM Code 1.2.3 / ISM 1.2 / ISM Code 5
  {
    re: /\bISM(?:\s+Code)?\s+(\d+(?:\.\d+)*)/g,
    sourceHint: 'ism',
    toSection: m => `ISM ${m[1]}`,
  },
]

/** Scan a string for all maritime citations across every pattern.
 *  Returns matches in document order, deduplicated by span. */
function scanCitations(text: string): Array<{
  index: number
  length: number
  sectionNumber: string
  sourceHint: string
}> {
  const found: Array<{ index: number; length: number; sectionNumber: string; sourceHint: string }> = []
  for (const p of CITATION_PATTERNS) {
    p.re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = p.re.exec(text)) !== null) {
      found.push({
        index: m.index,
        length: m[0].length,
        sectionNumber: p.toSection(m),
        sourceHint: p.sourceHint,
      })
    }
  }
  // Sort by position; collapse overlapping spans (keep earliest).
  found.sort((a, b) => a.index - b.index || b.length - a.length)
  const merged: typeof found = []
  let cursor = 0
  for (const hit of found) {
    if (hit.index < cursor) continue
    merged.push(hit)
    cursor = hit.index + hit.length
  }
  return merged
}

function injectChips(
  children: ReactNode,
  citationMap: Map<string, { source: string; title: string }>,
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void,
  prefix: string,
): ReactNode {
  const processString = (text: string, pfx: string): ReactNode => {
    const hits = scanCitations(text)
    if (hits.length === 0) return text
    const nodes: ReactNode[] = []
    let last = 0
    for (const hit of hits) {
      if (hit.index > last) nodes.push(text.slice(last, hit.index))
      const info = citationMap.get(hit.sectionNumber)
      nodes.push(
        <CitationChip
          key={`${pfx}-${hit.index}`}
          sectionNumber={hit.sectionNumber}
          sectionTitle={info?.title ?? ''}
          source={info?.source ?? hit.sourceHint}
          onTap={onTap}
        />,
      )
      last = hit.index + hit.length
    }
    if (last < text.length) nodes.push(text.slice(last))
    return nodes
  }

  if (typeof children === 'string') return processString(children, prefix)

  if (Array.isArray(children)) {
    return children.map((child, i) => {
      if (typeof child === 'string') return processString(child, `${prefix}-${i}`)
      return child
    })
  }

  return children
}

/** Extract a deduplicated, ordered list of citations from the full
 *  rendered message text. Used by the footer to mirror what's inline.
 *  Sprint D6.87 — previously the footer rendered message.citations
 *  directly (the DB-verified parent corpus entries), which often
 *  didn't match what the model actually wrote inline. Now both
 *  surfaces share the same source of truth: the answer text itself. */
export function extractFooterCitations(
  text: string,
  citationMap: Map<string, { source: string; title: string }>,
): Array<{ sectionNumber: string; source: string; title: string }> {
  const seen = new Set<string>()
  const result: Array<{ sectionNumber: string; source: string; title: string }> = []
  for (const hit of scanCitations(text)) {
    if (seen.has(hit.sectionNumber)) continue
    seen.add(hit.sectionNumber)
    const info = citationMap.get(hit.sectionNumber)
    result.push({
      sectionNumber: hit.sectionNumber,
      source: info?.source ?? hit.sourceHint,
      title: info?.title ?? '',
    })
  }
  return result
}

// ── Markdown component map ─────────────────────────────────────────────────────

function makeComponents(
  citations: CitedRegulation[],
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void,
): Components {
  const citationMap = new Map(
    citations.map(c => [c.section_number, { source: c.source, title: c.section_title }]),
  )

  function Inline({ children, prefix }: { children: ReactNode; prefix: string }) {
    return <>{injectChips(children, citationMap, onTap, prefix)}</>
  }

  return {
    // ── Headings ────────────────────────────────────────────────────────────
    h1: ({ children }) => (
      <h1 className="font-display text-xl font-bold text-[#f0ece4] mt-5 mb-2 first:mt-0">
        <Inline prefix="h1">{children}</Inline>
      </h1>
    ),
    h2: ({ children }) => (
      <h2 className="font-display text-lg font-bold text-[#f0ece4] mt-4 mb-1.5 first:mt-0">
        <Inline prefix="h2">{children}</Inline>
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="font-display text-base font-bold text-[#f0ece4] mt-3 mb-1 first:mt-0">
        <Inline prefix="h3">{children}</Inline>
      </h3>
    ),

    // ── Paragraph ───────────────────────────────────────────────────────────
    p: ({ children }) => (
      <p className="mb-2 last:mb-0 leading-relaxed">
        <Inline prefix="p">{children}</Inline>
      </p>
    ),

    // ── Inline styles ────────────────────────────────────────────────────────
    strong: ({ children }) => (
      <strong className="font-semibold text-[#2dd4bf]">
        <Inline prefix="strong">{children}</Inline>
      </strong>
    ),
    em: ({ children }) => (
      <em className="italic text-[#f0ece4]/80">
        <Inline prefix="em">{children}</Inline>
      </em>
    ),

    // ── Lists ────────────────────────────────────────────────────────────────
    ul: ({ children }) => (
      <ul className="list-disc list-outside pl-4 mb-2 space-y-1">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal list-outside pl-4 mb-2 space-y-1">{children}</ol>
    ),
    li: ({ children }) => (
      <li className="leading-relaxed text-[#f0ece4]/90">
        <Inline prefix="li">{children}</Inline>
      </li>
    ),

    // ── Code ─────────────────────────────────────────────────────────────────
    code: ({ children, className }) => {
      const isBlock = className?.startsWith('language-')
      if (isBlock) {
        return (
          <code className="block bg-[#0d1225] border border-white/8 rounded-lg px-3 py-2 text-xs font-mono text-[#f0ece4]/80 overflow-x-auto my-2">
            {children}
          </code>
        )
      }
      return (
        <code className="bg-[#0d1225] border border-white/8 rounded px-1 py-0.5 text-xs font-mono text-[#2dd4bf]">
          {children}
        </code>
      )
    },

    // ── Block quote ──────────────────────────────────────────────────────────
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-[#2dd4bf]/40 pl-3 my-2 text-[#f0ece4]/70 italic">
        {children}
      </blockquote>
    ),

    // ── Horizontal rule ──────────────────────────────────────────────────────
    hr: () => <hr className="border-white/10 my-3" />,

    // ── Tables (GFM) ─────────────────────────────────────────────────────────
    // Wrapper div with overflow-x-auto enables horizontal scroll on narrow
    // viewports so wide tables stay readable on mobile instead of breaking
    // the layout or leaking raw pipe characters.
    table: ({ children }) => (
      <div className="overflow-x-auto my-3 -mx-1 rounded-lg border border-white/8">
        <table className="min-w-full text-xs font-mono border-collapse">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-[#0d1225] border-b border-white/10">
        {children}
      </thead>
    ),
    tbody: ({ children }) => (
      <tbody className="divide-y divide-white/8">
        {children}
      </tbody>
    ),
    tr: ({ children }) => (
      <tr className="hover:bg-white/[0.03]">
        {children}
      </tr>
    ),
    th: ({ children }) => (
      <th className="px-3 py-2 text-left text-[10px] uppercase tracking-wider text-[#2dd4bf] font-bold whitespace-nowrap">
        <Inline prefix="th">{children}</Inline>
      </th>
    ),
    td: ({ children }) => (
      <td className="px-3 py-2 text-[#f0ece4]/85 align-top">
        <Inline prefix="td">{children}</Inline>
      </td>
    ),
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChatMessage({ message, onCitationTap }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    // Sprint D6.23c — Karynn requested copy-on-question so she can re-ask
    // or rephrase without retyping. Copy button lives below the bubble,
    // right-aligned to mirror the message's right-alignment.
    return (
      <div className="flex flex-col items-end px-4 py-1.5 animate-[fadeSlideIn_0.2s_ease-out]">
        <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed">
          {message.content}
        </div>
        <div className="mt-0.5 -mr-2.5">
          <CopyMessageButton content={message.content} />
        </div>
      </div>
    )
  }

  const components = makeComponents(message.citations, onCitationTap)

  // Sprint D6.87 — footer chips are derived from the actual answer
  // text (post-render) so they mirror what's visually highlighted
  // inline. The DB-verified message.citations list is used as a
  // lookup for source/title attribution but does NOT drive what gets
  // rendered. This eliminates the prior mismatch where the footer
  // would show "SOLAS Ch.VI Part A" (DB parent) while the body cited
  // "SOLAS Ch.VI Reg.2, para.6" (granular subsection).
  const citationMapForFooter = new Map(
    message.citations.map(c => [c.section_number, { source: c.source, title: c.section_title }]),
  )
  const footerCitations = extractFooterCitations(message.content, citationMapForFooter)

  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]">
      {/* Teal accent bar */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-0.5" />

      <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
        {/* Sprint D6.84 — confidence tier chip. Renders ABOVE the
            answer so the epistemic status is the first signal the
            user sees. Only present when CONFIDENCE_TIERS_MODE=live
            on the backend; null in shadow / off modes. */}
        {message.tier_metadata && <TierChip metadata={message.tier_metadata} />}
        {message.tier_metadata?.label === 'relaxed_web' && (
          <TierWebDisclaimer confidence={message.tier_metadata.web_confidence} />
        )}

        {/* Sprint D6.85 Fix C — cancelled badge for user-stopped
            generations. Sits above the partial content so the user
            knows at a glance that this answer is incomplete. */}
        {message.cancelled && (
          <div className="mb-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium
              bg-amber-950/50 text-amber-300 border border-amber-700/50">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1.5" /></svg>
              Stopped — incomplete
            </span>
          </div>
        )}

        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {message.content}
        </ReactMarkdown>

        {/* Citation footer — D6.87 sources chips from the rendered
            answer text so the list mirrors what's visually highlighted
            inline. message.citations remains the lookup hint for
            source/title; the rendered set is the union of all
            inline-cited regulations, deduplicated. */}
        {footerCitations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-1.5">
            {footerCitations.map(c => (
              <CitationChip
                key={c.sectionNumber}
                sectionNumber={c.sectionNumber}
                sectionTitle={c.title}
                source={c.source}
                onTap={onCitationTap}
              />
            ))}
          </div>
        )}

        {/* Sprint D6.48 Phase 2 — Web fallback yellow card. Visually
            distinct from corpus answers above. Renders only when the
            assistant hedged AND a verified verbatim quote was found
            on a trusted regulator domain. */}
        {message.web_fallback && (
          <WebFallbackCardView card={message.web_fallback} />
        )}

        {/* Action bar — copy plain-text version of the message */}
        <div className="mt-1 -ml-2.5 flex justify-start">
          <CopyMessageButton content={message.content} />
        </div>
      </div>
    </div>
  )
}


// ── Web fallback yellow card ─────────────────────────────────────────────
// Sprint D6.48 Phase 2. The card is intentionally visually distinct
// from corpus citations: amber/yellow accent, "Web reference" header,
// permanent disclaimer footer. We never blend this with the cited_
// regulations chips above — they live in different lanes for a reason.

function WebFallbackCardView({ card }: { card: import('@/types/chat').WebFallbackCard }) {
  const [feedback, setFeedback] = useState<'helpful' | 'not_helpful' | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submitFeedback(value: 'helpful' | 'not_helpful') {
    if (submitting || feedback) return
    setSubmitting(true)
    try {
      // Best-effort fire — errors don't surface to user.
      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || ''}/web-fallback/${card.fallback_id}/feedback`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ feedback: value }),
        }
      )
      setFeedback(value)
    } catch {
      // swallow
    } finally {
      setSubmitting(false)
    }
  }

  // D6.58 Slice 1 + Slice 3 — three-tier rendering. The renderer
  // picks badge text + tone from `surface_tier`. Default to
  // 'verified' for back-compat with old payloads that don't carry
  // the field.
  const tier = card.surface_tier ?? 'verified'
  const isReference = tier === 'reference'
  const isConsensus = tier === 'consensus'
  const badgeText = isConsensus
    ? 'AI consensus'
    : isReference
      ? 'External reference'
      : 'Web reference'
  const badgeSubtext = isConsensus
    ? '(Claude + GPT + Grok agreed — not in RegKnots corpus)'
    : isReference
      ? '(found via web — please verify)'
      : '(not in RegKnots corpus)'

  return (
    <div className="mt-4 border-l-2 border-amber-400/70 bg-amber-400/5 rounded-r-md p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-mono uppercase tracking-wider text-amber-300/90">
          {badgeText}
        </span>
        <span className="text-[10px] font-mono text-amber-200/50">
          {badgeSubtext}
        </span>
      </div>
      {card.quote && (
        <blockquote className="border-l-2 border-amber-400/40 pl-3 italic text-sm text-[#f0ece4]/85 mb-2">
          &ldquo;{card.quote}&rdquo;
        </blockquote>
      )}
      {card.summary && (
        <div className="text-sm text-[#f0ece4]/80 mb-2">{card.summary}</div>
      )}
      <div className="text-xs font-mono text-amber-200/60 mb-3 break-all">
        Source:{' '}
        <a
          href={card.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-amber-200"
        >
          {card.source_domain}
        </a>
      </div>
      <div className="flex items-center justify-between border-t border-amber-400/15 pt-2">
        <div className="text-[11px] text-amber-200/50 italic">
          {isConsensus
            ? 'Three frontier models agreed on this answer — verify against the primary source before relying on it for compliance.'
            : isReference
              ? "We didn't fully verify this — open the source and confirm before acting on it."
              : 'Verify against the primary regulator before relying on this for compliance.'}
        </div>
        <div className="flex items-center gap-1.5 ml-2">
          {feedback === null ? (
            <>
              <button
                aria-label="Helpful"
                onClick={() => submitFeedback('helpful')}
                disabled={submitting}
                className="px-1.5 py-0.5 text-xs hover:bg-amber-400/15 rounded transition-colors text-amber-200/70 disabled:opacity-40"
              >👍</button>
              <button
                aria-label="Not helpful"
                onClick={() => submitFeedback('not_helpful')}
                disabled={submitting}
                className="px-1.5 py-0.5 text-xs hover:bg-amber-400/15 rounded transition-colors text-amber-200/70 disabled:opacity-40"
              >👎</button>
            </>
          ) : (
            <span className="text-[10px] font-mono text-amber-200/60">
              {feedback === 'helpful' ? 'thanks' : 'noted'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
