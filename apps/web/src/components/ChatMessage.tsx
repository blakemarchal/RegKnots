'use client'

import { apiRequest } from '@/lib/api'
import { useState } from 'react'
import type { Message } from '@/types/chat'
// 2026-10-16 UI pass — the markdown, chips and citation footers live in
// AnswerBody, shared with the free answer on public pages (GuestAsk).
import { AnswerBody } from './AnswerBody'
// 2026-07-19 Wk2 — per-answer export (copy-with-citations + print-to-PDF)
import { buildAnswerClipboardText, exportAnswerToPdf } from '@/lib/answerExport'
// D6.97 — TierChip + TierWebDisclaimer no longer imported; tier_router
// was removed and tier_metadata is always null. Component file stays
// in tree (unused) until Track B does the broader pipeline cleanup.

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
  // 2026-07-19 trust pack — true only for the assistant message that is
  // actively streaming. Drives aria-live (screen readers hear the answer
  // as it arrives) and suppresses the verified badge until the citation
  // verifier has actually run (badge appears when streaming completes).
  isStreaming?: boolean
  // 2026-07-19 Wk2 — the user question this assistant message answers
  // (nearest preceding user message). Gives the copy/PDF exports their
  // Q context. Undefined for user messages / unknown.
  precedingUserContent?: string | null
  // Active vessel name, stamped into export artifacts.
  vesselName?: string | null
}

// ── Export buttons (2026-07-19 Wk2) ───────────────────────────────────────────
// A compliance officer's endgame for a good answer is getting it into an
// audit file or an email. Copy-with-citations and print-to-PDF sit beside
// the plain copy button on every completed assistant answer.

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" />
      <polyline points="7 11 12 16 17 11" />
      <path d="M5 21h14" />
    </svg>
  )
}

function CopyCitedIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      <path d="M13 14h5M13 17h5" />
    </svg>
  )
}

function AnswerExportButtons({ message, question, vesselName }: {
  message: Message
  question?: string | null
  vesselName?: string | null
}) {
  const [copiedCited, setCopiedCited] = useState(false)

  async function handleCopyCited() {
    const text = buildAnswerClipboardText({
      question,
      answer: stripMarkdown(message.content),
      citations: message.citations,
      createdAt: message.created_at,
      vesselName,
    })
    const ok = await copyTextToClipboard(text)
    if (!ok) return
    setCopiedCited(true)
    setTimeout(() => setCopiedCited(false), 2000)
  }

  function handleExportPdf() {
    exportAnswerToPdf({
      question,
      answer: message.content,
      citations: message.citations,
      createdAt: message.created_at,
      vesselName,
    })
  }

  const btnCls = (active: boolean) => `w-11 h-11 flex items-center justify-center rounded-lg
    transition-colors duration-150
    ${active ? 'text-[#2dd4bf]' : 'text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5 active:bg-white/10'}`

  return (
    <>
      <button
        type="button"
        onClick={handleCopyCited}
        aria-label={copiedCited ? 'Copied with citations' : 'Copy with citations'}
        title={copiedCited ? 'Copied!' : 'Copy with citations'}
        className={btnCls(copiedCited)}
      >
        {copiedCited ? <CheckIcon /> : <CopyCitedIcon />}
      </button>
      <button
        type="button"
        onClick={handleExportPdf}
        aria-label="Export answer as PDF"
        title="Export answer as PDF"
        className={btnCls(false)}
      >
        <DownloadIcon />
      </button>
    </>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

// 2026-07-19 trust pack — compact HH:MM timestamp with full date on
// hover. Rendered in the action-bar row of both message kinds.
function MessageTime({ iso }: { iso?: string }) {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  return (
    <time
      dateTime={iso}
      title={d.toLocaleString()}
      className="text-[11px] text-[#8a94ad] tabular-nums select-none"
    >
      {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
    </time>
  )
}

export function ChatMessage({
  message, onCitationTap, isStreaming = false,
  precedingUserContent = null, vesselName = null,
}: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    // Sprint D6.23c — Karynn requested copy-on-question so she can re-ask
    // or rephrase without retyping. Copy button lives below the bubble,
    // right-aligned to mirror the message's right-alignment.
    //
    // Sprint D6.97 Phase 2 — image attachments render as a thumbnail
    // strip above the text bubble, right-aligned to match the bubble's
    // alignment. Clicking a thumbnail opens it full-size in a new tab
    // (simplest UX; no lightbox needed for v1).
    const imageAttachments = message.image_attachments ?? []
    const documents = message.documents ?? []
    return (
      <div className="flex flex-col items-end px-4 py-1.5 animate-[fadeSlideIn_0.2s_ease-out]">
        {/* 2026-10-05 — documents attached to this turn */}
        {documents.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end max-w-[82%]">
            {documents.map((d) => (
              <span
                key={d.id}
                className="inline-flex items-center gap-1.5 max-w-full rounded-lg border border-white/15 bg-black/30
                  px-2.5 py-1 font-mono text-xs text-[#f0ece4]"
              >
                <svg className="w-3.5 h-3.5 shrink-0 text-[#2dd4bf]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <path d="M14 2v6h6" />
                </svg>
                <span className="truncate max-w-[200px]">{d.title}</span>
                {d.pages ? <span className="text-[#6b7594]">{d.pages} pp</span> : null}
              </span>
            ))}
          </div>
        )}
        {imageAttachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end max-w-[82%]">
            {imageAttachments.map((img, idx) => (
              <a
                key={idx}
                href={img.data_url}
                target="_blank"
                rel="noopener noreferrer"
                className="block"
              >
                <img
                  src={img.data_url}
                  alt={`Attached image ${idx + 1}`}
                  className="h-24 w-24 object-cover rounded-lg border border-white/15 bg-black/40
                    hover:border-teal/40 transition-colors"
                />
              </a>
            ))}
          </div>
        )}
        {message.content && (
          <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-tr-sm bg-[#1a3254] text-[#f0ece4] text-sm leading-relaxed">
            {message.content}
          </div>
        )}
        <div className="mt-0.5 -mr-2.5">
          <CopyMessageButton content={message.content} />
        </div>
      </div>
    )
  }

  return (
    <div
      className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]"
      // 2026-07-19 trust pack — announce the streaming answer to screen
      // readers. Only the actively-streaming message is live; historical
      // messages render silent so loading a conversation doesn't shout.
      aria-live={isStreaming ? 'polite' : undefined}
      aria-busy={isStreaming || undefined}
    >
      {/* Teal accent bar */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-0.5" />

      <div className="flex-1 min-w-0 text-sm text-[#f0ece4] leading-relaxed">
        {/* D6.97 — TierChip render removed. tier_router killed; even
            historical messages with tier_metadata populated no longer
            display a chip. The data in the messages table is preserved
            but no longer surfaces to the user. */}

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

        <AnswerBody
          content={message.content}
          citations={message.citations}
          webSources={message.web_sources ?? []}
          onCitationTap={onCitationTap}
          isStreaming={isStreaming}
          cancelled={message.cancelled}
        />

        {/* Sprint D6.48 Phase 2 — Web fallback yellow card. Visually
            distinct from corpus answers above. Renders only when the
            assistant hedged AND a verified verbatim quote was found
            on a trusted regulator domain. */}
        {message.web_fallback && (
          <WebFallbackCardView card={message.web_fallback} />
        )}

        {/* Action bar — copy / copy-with-citations / export-PDF + timestamp
            (2026-07-19 trust pack + Wk2 export) */}
        <div className="mt-1 -ml-2.5 flex items-center justify-between gap-2">
          <div className="flex items-center">
            <CopyMessageButton content={message.content} />
            {!message.cancelled && !isStreaming && message.content && (
              <AnswerExportButtons
                message={message}
                question={precedingUserContent}
                vesselName={vesselName}
              />
            )}
          </div>
          <MessageTime iso={message.created_at} />
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
      // 2026-09-29 — through apiRequest, which sends the Bearer token. The
      // plain fetch here had none, so every vote got a 401 while the card
      // still said thanks; the admin thumbs-up/down counts never filled.
      await apiRequest(`/web-fallback/${card.fallback_id}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ feedback: value }),
      })
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
