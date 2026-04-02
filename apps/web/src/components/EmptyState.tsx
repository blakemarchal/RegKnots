import { CompassRose } from './CompassRose'

const SUGGESTED = [
  'Lifeboat inspection checklist',
  'SOLAS certificate requirements',
  'Watch schedule regulations',
]

interface Props {
  onPrompt: (text: string) => void
}

export function EmptyState({ onPrompt }: Props) {
  return (
    <div className="flex flex-col items-center justify-center min-h-full px-6 py-12 text-center select-none">
      {/* Compass rose */}
      <div className="relative mb-8">
        <CompassRose className="w-28 h-28 text-teal opacity-20" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-6 h-6 rounded-full bg-teal/10 border border-teal/30" />
        </div>
      </div>

      {/* Logo wordmark */}
      <h1 className="font-display text-5xl font-bold tracking-wide text-[#f0ece4] mb-1">
        RegKnots
      </h1>
      <p className="text-[11px] text-[#6b7594] tracking-[0.25em] uppercase mb-2 font-semibold">
        CFR Co-Pilot
      </p>
      <p className="text-sm text-[#6b7594] max-w-xs mb-10 leading-relaxed">
        Ask anything about federal maritime regulations. Cite-referenced answers from Titles 33, 46 &amp; 49.
      </p>

      {/* Suggested prompts */}
      <div className="flex flex-col gap-2 w-full max-w-xs">
        <p className="text-[10px] text-[#6b7594] uppercase tracking-widest mb-1">Try asking</p>
        {SUGGESTED.map(prompt => (
          <button
            key={prompt}
            onClick={() => onPrompt(prompt)}
            className="px-4 py-2.5 rounded-xl text-sm text-left
              bg-white/5 border border-white/8 text-[#f0ece4]/80
              hover:bg-white/10 hover:border-teal/30 hover:text-[#f0ece4]
              transition-all duration-150"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}
