interface Props {
  vesselName: string | null
  hasVessels: boolean
  onClick: () => void
}

export function VesselPill({ vesselName, hasVessels, onClick }: Props) {
  // Three states:
  //   1. vesselName present → show vessel name in teal
  //   2. No active vessel but user has vessels → "No vessel — tap to switch"
  //   3. No vessels at all → "General mode — add a vessel"
  const emptyLabel = hasVessels ? 'No vessel — tap to switch' : 'General mode — add a vessel'
  const ariaLabel = vesselName
    ? `Active vessel: ${vesselName}`
    : hasVessels
      ? 'Select a vessel'
      : 'General mode — add a vessel'
  return (
    <div className="px-3 py-1.5 flex items-center">
      <button
        onClick={onClick}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
          border border-white/10 bg-white/5 hover:bg-white/10
          transition-colors duration-150"
        aria-label={ariaLabel}
      >
        {/* Anchor icon */}
        <svg className="w-3 h-3 flex-shrink-0" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1a2 2 0 1 1 0 4A2 2 0 0 1 8 1zm0 1a1 1 0 1 0 0 2A1 1 0 0 0 8 2z"/>
          <path d="M7.5 4.5v7.586l-2.293-2.293-.707.707L8 14l3.5-3.5-.707-.707L8.5 12.086V4.5h-1z"/>
          <path d="M2 8.5h2v1H2.025A4.5 4.5 0 0 0 8 13.5a4.5 4.5 0 0 0 5.975-4H12v-1h2a.5.5 0 0 1 .5.5 6.5 6.5 0 0 1-13 0 .5.5 0 0 1 .5-.5z"/>
        </svg>
        {vesselName ? (
          <span className="text-teal">{vesselName}</span>
        ) : (
          <span className="text-[#6b7594]">{emptyLabel}</span>
        )}
        <svg className="w-3 h-3 text-white/30" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M4.293 5.293a1 1 0 0 1 1.414 0L8 7.586l2.293-2.293a1 1 0 1 1 1.414 1.414l-3 3a1 1 0 0 1-1.414 0l-3-3a1 1 0 0 1 0-1.414z"/>
        </svg>
      </button>
    </div>
  )
}
