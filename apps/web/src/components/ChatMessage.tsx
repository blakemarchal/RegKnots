'use client'

import { useState, type ReactNode } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, CitedRegulation } from '@/types/chat'
import { CitationChip } from './CitationChip'

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
// Walks React string children and replaces CFR patterns with CitationChip nodes.

const CFR_RE = /\(?(\d+)\s+CFR\s+([\d]+(?:\.[\d]+(?:-[\d]+)?)?)\)?/g

function injectChips(
  children: ReactNode,
  citationMap: Map<string, { source: string; title: string }>,
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void,
  prefix: string,
): ReactNode {
  const processString = (text: string, pfx: string): ReactNode => {
    CFR_RE.lastIndex = 0
    const nodes: ReactNode[] = []
    let last = 0
    let m: RegExpExecArray | null
    while ((m = CFR_RE.exec(text)) !== null) {
      if (m.index > last) nodes.push(text.slice(last, m.index))
      const sectionNumber = `${m[1]} CFR ${m[2]}`
      const info = citationMap.get(sectionNumber)
      nodes.push(
        <CitationChip
          key={`${pfx}-${m.index}`}
          sectionNumber={sectionNumber}
          sectionTitle={info?.title ?? ''}
          source={info?.source ?? `cfr_${m[1]}`}
          onTap={onTap}
        />,
      )
      last = m.index + m[0].length
    }
    if (last < text.length) nodes.push(text.slice(last))
    return nodes.length === 0 ? text : nodes
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

  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]">
      {/* Teal accent bar */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-0.5" />

      <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {message.content}
        </ReactMarkdown>

        {/* Citation footer */}
        {message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-1.5">
            {message.citations.map(c => (
              <CitationChip
                key={c.section_number}
                sectionNumber={c.section_number}
                sectionTitle={c.section_title}
                source={c.source}
                onTap={onCitationTap}
              />
            ))}
          </div>
        )}

        {/* Action bar — copy plain-text version of the message */}
        <div className="mt-1 -ml-2.5 flex justify-start">
          <CopyMessageButton content={message.content} />
        </div>
      </div>
    </div>
  )
}
