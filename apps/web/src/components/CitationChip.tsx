'use client'

interface Props {
  sectionNumber: string
  sectionTitle: string
  source: string
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void
}

// 2026-07-19 trust pack — corpus citations are VERIFIED references
// (the citation verifier strips anything that doesn't resolve against
// the corpus before the answer ships), so they render in the teal
// "authoritative" lane. Amber is reserved exclusively for caution
// surfaces: the web-fallback card, the cancelled badge, and the
// not-in-corpus warning inside the citation sheet. Before this change
// verified citations and "verify this yourself" warnings shared the
// same amber hue — a trust-signal inversion for compliance users.
export function CitationChip({ sectionNumber, sectionTitle, source, onTap }: Props) {
  return (
    <button
      onClick={() => onTap(source, sectionNumber, sectionTitle)}
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
        bg-teal-950/70 text-teal-300 border border-teal-800/60
        hover:bg-teal-900/70 hover:border-teal-500/60 hover:text-teal-200
        transition-colors duration-150 cursor-pointer leading-none align-baseline mx-0.5"
      aria-label={`View verified regulation: ${sectionNumber}`}
    >
      {sectionNumber}
    </button>
  )
}
