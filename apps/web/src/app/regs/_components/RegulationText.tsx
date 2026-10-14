// 2026-10-14 — a regulation's own text, paragraph by paragraph, indented by
// its designators: (a) → (1) → (i) → (A). The Navigation Rules' [INTERNATIONAL]
// and [INLAND] markers become labels.

const ROMAN = /^\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv)\)/

function levelOf(text: string, previous: number): number {
  if (/^\([A-Z]\)/.test(text)) return 3
  if (ROMAN.test(text) && previous >= 1) return 2
  if (/^\(\d+\)/.test(text)) return 1
  if (/^\([a-z]{1,2}\)/.test(text)) return 0
  return -1     // not a designated paragraph: keep the previous indent
}

const INDENT = ['', 'pl-4 md:pl-6', 'pl-8 md:pl-12', 'pl-12 md:pl-16']

export function RegulationText({ text }: { text: string }) {
  let level = 0
  const blocks = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  return (
    <div className="font-mono text-[13px] md:text-sm leading-relaxed text-[#f0ece4]/80 space-y-3 break-words">
      {blocks.map((block, i) => {
        const marker = block.match(/^\[(INTERNATIONAL|INLAND)\]\s*/)
        if (marker) {
          level = 0
          const rest = block.slice(marker[0].length)
          return (
            <div key={i} className="pt-2">
              <p className="font-display text-xs font-bold uppercase tracking-widest text-[#2dd4bf] mb-2">
                {marker[1] === 'INLAND' ? 'Inland Rules' : 'International (COLREGs)'}
              </p>
              {rest && <p className="whitespace-pre-line">{rest}</p>}
            </div>
          )
        }
        const next = levelOf(block, level)
        if (next >= 0) level = next
        return (
          <p key={i} className={`whitespace-pre-line ${INDENT[level] ?? ''}`}>{block}</p>
        )
      })}
    </div>
  )
}
