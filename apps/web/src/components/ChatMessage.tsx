import type { ReactNode } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import type { Message, CitedRegulation } from '@/types/chat'
import { CitationChip } from './CitationChip'

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
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChatMessage({ message, onCitationTap }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-1.5 animate-[fadeSlideIn_0.2s_ease-out]">
        <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed">
          {message.content}
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
        <ReactMarkdown components={components}>
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
      </div>
    </div>
  )
}
