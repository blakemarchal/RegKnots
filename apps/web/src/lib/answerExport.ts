// 2026-07-19 (Wk2 trust pack) — per-answer export for compliance
// defensibility. A shore-side compliance officer's core workflow is
// dropping a cited answer into an audit file, an email to a vessel, or
// a vetting response. Two surfaces, both fed from the SAME verified
// data the chat rendered:
//
//   1. copyAnswerWithCitations() — plain-text answer + "Verified
//      citations" block + timestamp + attribution, for pasting into
//      email/Word/Teams.
//   2. exportAnswerToPdf() — opens a print-formatted standalone window
//      and invokes the browser's native print → Save as PDF. Zero
//      bundle weight (no jspdf), consistent output everywhere, and the
//      print CSS gives a letterhead-shaped artifact with the question,
//      answer, verified citations, generation timestamp, and the
//      not-legal-advice disclaimer.
//
// The citations passed in are the message's verified set (the citation
// verifier strips non-resolving cites server-side before the answer
// ships) — so both artifacts are honest by construction.

import type { CitedRegulation } from '@/types/chat'

function fmtWhen(iso?: string): string {
  const d = iso ? new Date(iso) : new Date()
  if (isNaN(d.getTime())) return iso ?? ''
  return d.toLocaleString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  })
}

function citationLines(citations: CitedRegulation[]): string[] {
  return citations.map((c) =>
    c.section_title ? `${c.section_number} — ${c.section_title}` : c.section_number,
  )
}

// ── 1. Copy with citations ──────────────────────────────────────────────

export function buildAnswerClipboardText(opts: {
  question?: string | null
  answer: string
  citations: CitedRegulation[]
  createdAt?: string
  vesselName?: string | null
}): string {
  const lines: string[] = []
  if (opts.question) {
    lines.push(`Q: ${opts.question.trim()}`, '')
  }
  lines.push(opts.answer.trim(), '')
  if (opts.citations.length > 0) {
    lines.push('Verified citations:')
    for (const c of citationLines(opts.citations)) lines.push(`  • ${c}`)
    lines.push('')
  }
  const ctx = opts.vesselName ? ` · Vessel: ${opts.vesselName}` : ''
  lines.push(`— RegKnots (regknots.com) · ${fmtWhen(opts.createdAt)}${ctx}`)
  lines.push('Verify against the official text before acting. Not legal advice.')
  return lines.join('\n')
}

// ── 2. Print-to-PDF ─────────────────────────────────────────────────────

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Minimal markdown → print HTML. The chat renders full GFM; for the
// export we cover what answers actually contain (headings, bold, lists,
// paragraphs). Tables degrade to text rows — acceptable for v1.
function mdToPrintHtml(md: string): string {
  const blocks = md.trim().split(/\n{2,}/)
  return blocks
    .map((block) => {
      const t = block.trim()
      if (/^#{1,4}\s/.test(t)) {
        return `<h3>${inline(t.replace(/^#{1,4}\s+/, ''))}</h3>`
      }
      if (/^[-*•]\s/m.test(t)) {
        const items = t.split('\n').filter((l) => /^[-*•]\s/.test(l.trim()))
          .map((l) => `<li>${inline(l.trim().replace(/^[-*•]\s+/, ''))}</li>`)
        if (items.length > 0) return `<ul>${items.join('')}</ul>`
      }
      if (/^\d+\.\s/m.test(t)) {
        const items = t.split('\n').filter((l) => /^\d+\.\s/.test(l.trim()))
          .map((l) => `<li>${inline(l.trim().replace(/^\d+\.\s+/, ''))}</li>`)
        if (items.length > 0) return `<ol>${items.join('')}</ol>`
      }
      return `<p>${inline(t).replace(/\n/g, '<br/>')}</p>`
    })
    .join('\n')

  function inline(s: string): string {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
  }
}

export function buildAnswerPrintHtml(opts: {
  question?: string | null
  answer: string
  citations: CitedRegulation[]
  createdAt?: string
  vesselName?: string | null
}): string {
  const when = fmtWhen(opts.createdAt)
  const cites = opts.citations
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RegKnots — Cited Answer</title>
<style>
  @page { margin: 22mm 18mm; }
  * { box-sizing: border-box; }
  body { font: 11pt/1.55 Georgia, 'Times New Roman', serif; color: #16202e; margin: 0; }
  .head { display: flex; justify-content: space-between; align-items: baseline;
          border-bottom: 2.5px solid #0d9488; padding-bottom: 8px; margin-bottom: 18px; }
  .brand { font: 700 16pt 'Segoe UI', Arial, sans-serif; letter-spacing: 0.04em; color: #0f172a; }
  .brand span { color: #0d9488; }
  .meta { font: 9pt 'Segoe UI', Arial, sans-serif; color: #475569; text-align: right; }
  h2 { font: 600 10pt 'Segoe UI', Arial, sans-serif; text-transform: uppercase;
       letter-spacing: 0.08em; color: #0d9488; margin: 18px 0 6px; }
  .q { background: #f1f5f9; border-left: 3px solid #94a3b8; padding: 8px 12px;
       font-style: italic; margin: 0 0 6px; }
  h3 { font: 600 11.5pt 'Segoe UI', Arial, sans-serif; color: #0f172a; margin: 14px 0 4px; }
  p { margin: 0 0 9px; }
  ul, ol { margin: 0 0 9px; padding-left: 20px; }
  li { margin-bottom: 3px; }
  code { font: 9.5pt Consolas, monospace; background: #f1f5f9; padding: 0 3px; }
  .cites { border: 1px solid #cbd5e1; border-radius: 4px; padding: 10px 14px; margin-top: 4px; }
  .cites ul { margin: 0; padding-left: 18px; }
  .verified { font: 600 8.5pt 'Segoe UI', Arial, sans-serif; color: #047857;
              text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
  .foot { margin-top: 24px; border-top: 1px solid #cbd5e1; padding-top: 8px;
          font: 8.5pt 'Segoe UI', Arial, sans-serif; color: #64748b; }
</style>
</head>
<body>
  <div class="head">
    <div class="brand">Reg<span>Knots</span></div>
    <div class="meta">
      Generated ${esc(when)}${opts.vesselName ? `<br/>Vessel: ${esc(opts.vesselName)}` : ''}
    </div>
  </div>
  ${opts.question ? `<h2>Question</h2><p class="q">${esc(opts.question.trim())}</p>` : ''}
  <h2>Answer</h2>
  ${mdToPrintHtml(opts.answer)}
  ${cites.length > 0 ? `
  <h2>Citations</h2>
  <div class="cites">
    <div class="verified">✓ Verified against the RegKnots regulatory corpus</div>
    <ul>${citationLines(cites).map((c) => `<li>${esc(c)}</li>`).join('')}</ul>
  </div>` : ''}
  <div class="foot">
    RegKnots · regknots.com · Maritime compliance co-pilot.
    Citations were resolved against primary-source text at generation time.
    Verify against the official text before acting — this document is an aid, not legal advice.
  </div>
  <script>window.addEventListener('load', function () { setTimeout(function () { window.print() }, 150) })</script>
</body>
</html>`
}

export function exportAnswerToPdf(opts: {
  question?: string | null
  answer: string
  citations: CitedRegulation[]
  createdAt?: string
  vesselName?: string | null
}): boolean {
  // Must be called synchronously from a click handler or the popup
  // blocker eats it.
  const w = window.open('', '_blank', 'noopener,width=880,height=1000')
  if (!w) return false
  w.document.open()
  w.document.write(buildAnswerPrintHtml(opts))
  w.document.close()
  return true
}

// ── 3. Audit-readiness report export (2026-07-19 Wk3) ───────────────────
// The fleet audit-readiness assessment is the artifact a DPA hands to
// management (or an auditor) — it needs to leave the app as a dated,
// scored, cited document. Same print-window approach as answers.

export interface AuditExportFinding {
  severity: 'critical' | 'warning' | 'info'
  area: string
  headline: string
  detail: string
  affected: string
  citation: string | null
}

export function exportAuditToPdf(opts: {
  scopeLabel: string           // "Fleet: Maersk Atlantic Ops" | "Personal record"
  scorePercent: number
  scoreLabel: string
  narrative: string
  findings: AuditExportFinding[]
  counts: { critical?: number; warning?: number; info?: number }
}): boolean {
  const sevColor: Record<string, string> = {
    critical: '#be123c', warning: '#b45309', info: '#475569',
  }
  const sevLabel: Record<string, string> = {
    critical: 'CRITICAL', warning: 'WARNING', info: 'INFO',
  }
  const scoreColor =
    opts.scorePercent >= 85 ? '#047857' : opts.scorePercent >= 65 ? '#b45309' : '#be123c'
  const when = fmtWhen()

  const findingsHtml = opts.findings.map((f) => `
    <div class="finding" style="border-left-color:${sevColor[f.severity] ?? '#475569'}">
      <div class="frow">
        <span class="sev" style="color:${sevColor[f.severity] ?? '#475569'}">${sevLabel[f.severity] ?? 'INFO'}</span>
        <span class="area">${esc(f.area)}</span>
        ${f.citation ? `<span class="cite">${esc(f.citation)}</span>` : ''}
      </div>
      <div class="fhead">${esc(f.headline)}</div>
      <div class="fdetail">${esc(f.detail)}</div>
      ${f.affected ? `<div class="faffected">Affected: ${esc(f.affected)}</div>` : ''}
    </div>`).join('')

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RegKnots — Audit Readiness Report</title>
<style>
  @page { margin: 20mm 18mm; }
  body { font: 10.5pt/1.5 'Segoe UI', Arial, sans-serif; color: #16202e; margin: 0; }
  .head { display: flex; justify-content: space-between; align-items: baseline;
          border-bottom: 2.5px solid #0d9488; padding-bottom: 8px; margin-bottom: 16px; }
  .brand { font-weight: 700; font-size: 16pt; letter-spacing: 0.04em; color: #0f172a; }
  .brand span { color: #0d9488; }
  .meta { font-size: 9pt; color: #475569; text-align: right; }
  h1 { font-size: 13pt; margin: 0 0 2px; }
  .scope { font-size: 10pt; color: #475569; margin-bottom: 14px; }
  .scorebox { display: flex; align-items: center; gap: 16px; border: 1px solid #cbd5e1;
              border-radius: 6px; padding: 12px 16px; margin-bottom: 14px; }
  .scorenum { font-size: 30pt; font-weight: 800; color: ${scoreColor}; line-height: 1; }
  .scoreof { font-size: 8pt; color: #64748b; text-transform: uppercase; }
  .scorelabel { font-size: 12pt; font-weight: 700; color: ${scoreColor}; }
  .countline { font-size: 9pt; color: #475569; margin-top: 3px; }
  .narrative { margin: 0 0 16px; white-space: pre-wrap; }
  h2 { font-size: 9.5pt; text-transform: uppercase; letter-spacing: 0.08em;
       color: #0d9488; margin: 16px 0 8px; }
  .finding { border: 1px solid #e2e8f0; border-left-width: 4px; border-radius: 4px;
             padding: 8px 12px; margin-bottom: 8px; page-break-inside: avoid; }
  .frow { display: flex; gap: 10px; align-items: baseline; font-size: 8.5pt; margin-bottom: 3px; }
  .sev { font-weight: 800; letter-spacing: 0.05em; }
  .area { color: #475569; }
  .cite { color: #0d9488; font-weight: 600; margin-left: auto; }
  .fhead { font-weight: 700; margin-bottom: 2px; }
  .fdetail { font-size: 9.5pt; }
  .faffected { font-size: 8.5pt; color: #64748b; margin-top: 3px; }
  .foot { margin-top: 22px; border-top: 1px solid #cbd5e1; padding-top: 8px;
          font-size: 8.5pt; color: #64748b; }
</style>
</head>
<body>
  <div class="head">
    <div class="brand">Reg<span>Knots</span></div>
    <div class="meta">Generated ${esc(when)}</div>
  </div>
  <h1>Audit Readiness Report</h1>
  <div class="scope">${esc(opts.scopeLabel)}</div>
  <div class="scorebox">
    <div style="text-align:center">
      <div class="scorenum">${Math.max(0, Math.min(100, Math.round(opts.scorePercent)))}</div>
      <div class="scoreof">/ 100</div>
    </div>
    <div>
      <div class="scorelabel">${esc(opts.scoreLabel)}</div>
      <div class="countline">
        ${opts.counts.critical ?? 0} critical · ${opts.counts.warning ?? 0} warning · ${opts.counts.info ?? 0} info
      </div>
    </div>
  </div>
  <p class="narrative">${esc(opts.narrative)}</p>
  ${opts.findings.length > 0 ? `<h2>Findings</h2>${findingsHtml}` : ''}
  <div class="foot">
    RegKnots · regknots.com · Assessment generated from stored credentials, vessel
    documents, and sea-time records at the timestamp above. Citations reference the
    governing regulation where a finding is regulation-gated. Verify against official
    text before acting — this report is an aid, not legal advice.
  </div>
  <script>window.addEventListener('load', function () { setTimeout(function () { window.print() }, 150) })</script>
</body>
</html>`

  const w = window.open('', '_blank', 'noopener,width=880,height=1000')
  if (!w) return false
  w.document.open()
  w.document.write(html)
  w.document.close()
  return true
}
