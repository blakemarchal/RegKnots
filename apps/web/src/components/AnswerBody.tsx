'use client'

// 2026-10-16 UI pass — the answer renderer, moved verbatim out of
// ChatMessage.tsx so the free answer on public pages (GuestAsk) renders
// exactly like chat: the same markdown components, citation chips, verified
// badge and web-source footer.

import type { ReactNode } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { CitedRegulation, WebSourceRef } from '@/types/chat'
import { CitationChip } from './CitationChip'
import { scanCitations, extractFooterCitations } from '@/lib/parseMessage'

// ── Inline citation injection ──────────────────────────────────────────────────
// The patterns and the scanner live in lib/parseMessage.ts (tested there).

// 2026-10-08 — a web source (answer pipeline phase 2) is a link to the page,
// sky-blue so it never reads as a corpus-verified chip.
function WebSourceChip({ label, source }: { label: string; source?: WebSourceRef }) {
  const text = label.replace(/^Web:\s*/, '')
  const cls = 'inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 rounded-md text-[11px] font-mono align-baseline ' +
    'bg-sky-950/50 text-sky-300 border border-sky-800/50'
  const icon = (
    <svg className="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  )
  if (!source?.url) return <span className={cls} title="From an official website">{icon}{text}</span>
  return (
    <a href={source.url} target="_blank" rel="noopener noreferrer" className={cls + ' hover:bg-sky-900/50'}
      title={`Opens ${source.domain}: not RegKnot's library${source.verified ? '' : ' (quote not matched on the page)'}`}>
      {icon}{text}
    </a>
  )
}

function findWebSource(label: string, webSources: WebSourceRef[]): WebSourceRef | undefined {
  const exact = webSources.find(w => w.label === label)
  if (exact) return exact
  const domain = label.replace(/^Web:\s*/, '').split(/\s+[—-]\s+/)[0]?.trim()
  return webSources.find(w => w.domain === domain)
}

function injectChips(
  children: ReactNode,
  citationMap: Map<string, { source: string; title: string }>,
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void,
  prefix: string,
  webSources: WebSourceRef[] = [],
): ReactNode {
  const processString = (text: string, pfx: string): ReactNode => {
    const hits = scanCitations(text)
    if (hits.length === 0) return text
    const nodes: ReactNode[] = []
    let last = 0
    for (const hit of hits) {
      if (hit.index > last) nodes.push(text.slice(last, hit.index))
      if (hit.sourceHint === 'web') {
        nodes.push(<WebSourceChip key={`${pfx}-${hit.index}`} label={hit.sectionNumber}
          source={findWebSource(hit.sectionNumber, webSources)} />)
        last = hit.index + hit.length
        continue
      }
      const info = citationMap.get(hit.sectionNumber)
      nodes.push(
        <CitationChip
          key={`${pfx}-${hit.index}`}
          sectionNumber={hit.sectionNumber}
          label={hit.label}
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

// ── Markdown component map ─────────────────────────────────────────────────────

export function makeAnswerComponents(
  citations: CitedRegulation[],
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void,
  webSources: WebSourceRef[] = [],
): Components {
  const citationMap = new Map(
    citations.map(c => [c.section_number, { source: c.source, title: c.section_title }]),
  )

  function Inline({ children, prefix }: { children: ReactNode; prefix: string }) {
    return <>{injectChips(children, citationMap, onTap, prefix, webSources)}</>
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


// ── AnswerBody ────────────────────────────────────────────────────────────────

/** An assistant answer's markdown, its corpus-citation footer and its web-source
 *  footer. ChatMessage wraps it with the cancelled badge, the web fallback card
 *  and the action bar; GuestAsk renders it on its own. */
export function AnswerBody({ content, citations, webSources = [], onCitationTap, isStreaming = false, cancelled = false }: {
  content: string
  citations: CitedRegulation[]
  webSources?: WebSourceRef[]
  onCitationTap: (source: string, sectionNumber: string, sectionTitle: string) => void
  isStreaming?: boolean
  cancelled?: boolean
}) {
  const components = makeAnswerComponents(citations, onCitationTap, webSources)

  // Sprint D6.87 — footer chips are derived from the actual answer
  // text (post-render) so they mirror what's visually highlighted
  // inline. The DB-verified message.citations list is used as a
  // lookup for source/title attribution but does NOT drive what gets
  // rendered. This eliminates the prior mismatch where the footer
  // would show "SOLAS Ch.VI Part A" (DB parent) while the body cited
  // "SOLAS Ch.VI Reg.2, para.6" (granular subsection).
  const citationMapForFooter = new Map(
    citations.map(c => [c.section_number, { source: c.source, title: c.section_title }]),
  )
  // 2026-10-08 — web sources get their own footer below, never a corpus chip.
  const footerCitations = extractFooterCitations(content, citationMapForFooter).filter(c => c.source !== 'web')
  const citedWeb = webSources.filter(w => content.includes(w.label))
  // 2026-10-05 — the "Corpus-verified" count covers regulations only: a
  // citation of the user's own document ([Doc: …]) or the fleet's ([Company: …])
  // is not checked against the regulation corpus.
  const verifiedCount = footerCitations.filter(c => c.source !== 'doc' && c.source !== 'company').length

  return (
    <>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>

      {/* Citation footer — D6.87 sources chips from the rendered
          answer text so the list mirrors what's visually highlighted
          inline. message.citations remains the lookup hint for
          source/title; the rendered set is the union of all
          inline-cited regulations, deduplicated. */}
      {footerCitations.length > 0 && (
        <div className="mt-3 pt-3 border-t border-white/5">
          {/* 2026-07-19 trust pack — verification badge. Honest by
              construction: the engine's citation verifier resolves
              every citation against the corpus and STRIPS the ones
              that fail before the answer ships, so the chips below
              are corpus-verified by definition. Green lane = trust;
              the amber lane is reserved for web-fallback cautions. */}
          {!cancelled && !isStreaming && verifiedCount > 0 && (
            <div className="mb-2">
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium
                  bg-emerald-950/60 text-emerald-300 border border-emerald-800/50"
                title="Each citation below was resolved against the primary-source text in RegKnot's library before this answer was shown."
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
                Corpus-verified · {verifiedCount} citation{verifiedCount === 1 ? '' : 's'}
              </span>
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
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
        </div>
      )}

      {/* 2026-10-08 — answer pipeline phase 2: the official pages this answer
          cites, apart from the corpus-verified chips. */}
      {citedWeb.length > 0 && !isStreaming && (
        <div className="mt-3 pt-3 border-t border-white/5">
          <p className="font-mono text-[11px] text-sky-300/80 mb-1.5">From official websites (not RegKnot&apos;s library)</p>
          <ul className="space-y-1">
            {citedWeb.map(w => (
              <li key={w.label} className="font-mono text-[11px] leading-snug">
                <a href={w.url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">
                  {w.domain}: {w.title}
                </a>
                {!w.verified && <span className="text-[#6b7594]"> · quote not matched on the page</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
