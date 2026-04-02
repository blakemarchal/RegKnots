'use client'

interface Props {
  sectionNumber: string
  sectionTitle: string
  source: string
  onTap: (source: string, sectionNumber: string, sectionTitle: string) => void
}

export function CitationChip({ sectionNumber, sectionTitle, source, onTap }: Props) {
  return (
    <button
      onClick={() => onTap(source, sectionNumber, sectionTitle)}
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium
        bg-amber-950/70 text-amber-400 border border-amber-800/50
        hover:bg-amber-900/70 hover:border-amber-600/60 hover:text-amber-300
        transition-colors duration-150 cursor-pointer leading-none align-baseline mx-0.5"
      aria-label={`View regulation: ${sectionNumber}`}
    >
      {sectionNumber}
    </button>
  )
}
