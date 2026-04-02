import type { CitedRegulation } from '@/types/chat'

export type MessagePart =
  | { type: 'text'; content: string }
  | { type: 'citation'; sectionNumber: string; sectionTitle: string; source: string }

// Matches (46 CFR 199.261), 46 CFR 199.261, (33 CFR 1.01-1), etc.
// Outer parens are optional so inline citations without wrapping are also caught.
const CFR_RE = /\(?(\d+)\s+CFR\s+([\d]+(?:\.[\d]+(?:-[\d]+)?)?)\)?/g

export function parseContent(
  content: string,
  citations: CitedRegulation[],
): MessagePart[] {
  // Build lookup: "46 CFR 133.45" → { source, section_title }
  const detailMap = new Map(
    citations.map(c => [c.section_number, { source: c.source, title: c.section_title }])
  )

  const parts: MessagePart[] = []
  let last = 0

  CFR_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = CFR_RE.exec(content)) !== null) {
    if (m.index > last) {
      parts.push({ type: 'text', content: content.slice(last, m.index) })
    }
    // m[1] = title number ("46"), m[2] = section number ("133.45")
    // Canonical form stored in DB: "46 CFR 133.45"
    const sectionNumber = `${m[1]} CFR ${m[2]}`
    const info = detailMap.get(sectionNumber)
    // Derive source from title number if not found in citations map
    const source = info?.source ?? `cfr_${m[1]}`
    parts.push({
      type: 'citation',
      sectionNumber,
      sectionTitle: info?.title ?? '',
      source,
    })
    last = m.index + m[0].length
  }
  if (last < content.length) {
    parts.push({ type: 'text', content: content.slice(last) })
  }
  return parts
}
