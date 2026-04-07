// Shared chat-history export helpers used by the Account page (bulk export)
// and the History page (single-conversation export).

export interface ExportCitedReg {
  source: string
  section_number: string
  section_title: string | null
}

export interface ExportMessage {
  role: string
  content: string
  timestamp: string
  cited_regulations: ExportCitedReg[]
}

export interface ExportConversation {
  id: string
  title: string
  vessel_name: string | null
  created_at: string
  updated_at: string
  messages: ExportMessage[]
}

export interface ExportAllResponse {
  exported_at: string
  user_email: string
  conversation_count: number
  conversations: ExportConversation[]
}

// ── Formatting ────────────────────────────────────────────────────────────────

function formatLongDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function roleLabel(role: string): string {
  if (role === 'user') return '[You]'
  if (role === 'assistant') return '[RegKnot]'
  return `[${role}]`
}

function formatCitations(cited: ExportCitedReg[]): string {
  if (!cited.length) return ''
  const parts = cited.map((c) =>
    c.section_title ? `${c.section_number} — ${c.section_title}` : c.section_number,
  )
  return `Citations: ${parts.join(', ')}`
}

function formatConversationAsText(conv: ExportConversation): string {
  const lines: string[] = []
  lines.push(`CONVERSATION: ${conv.title}`)
  if (conv.vessel_name) lines.push(`Vessel: ${conv.vessel_name}`)
  lines.push(`Date: ${formatLongDate(conv.updated_at)}`)
  lines.push('')

  for (const m of conv.messages) {
    lines.push(`${roleLabel(m.role)} (${formatTimestamp(m.timestamp)})`)
    lines.push(m.content.trim())
    const citations = formatCitations(m.cited_regulations)
    if (citations) lines.push(citations)
    lines.push('')
  }

  return lines.join('\n')
}

export function formatExportAsText(data: ExportAllResponse): string {
  const header = [
    'RegKnot — Chat Export',
    `Exported: ${formatLongDate(data.exported_at)}`,
    `Account: ${data.user_email}`,
    `Conversations: ${data.conversation_count}`,
    '',
    '────────────────────────────────────────',
    '',
  ].join('\n')

  const body = data.conversations
    .map(formatConversationAsText)
    .join('\n────────────────────────────────────────\n\n')

  return header + body
}

export function formatSingleConversationAsText(conv: ExportConversation): string {
  const header = [
    'RegKnot — Chat Export',
    `Exported: ${formatLongDate(new Date().toISOString())}`,
    '',
    '────────────────────────────────────────',
    '',
  ].join('\n')
  return header + formatConversationAsText(conv)
}

// ── Download trigger ──────────────────────────────────────────────────────────

export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Give the browser a tick to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 100)
}
