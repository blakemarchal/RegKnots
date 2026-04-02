export function CompassRose({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 120 120"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Outer dashed ring */}
      <circle cx="60" cy="60" r="56" stroke="currentColor" strokeWidth="0.5" strokeDasharray="3 7" />
      {/* Inner ring */}
      <circle cx="60" cy="60" r="34" stroke="currentColor" strokeWidth="0.5" />
      {/* Crosshair lines */}
      <line x1="60" y1="4" x2="60" y2="116" stroke="currentColor" strokeWidth="0.5" />
      <line x1="4" y1="60" x2="116" y2="60" stroke="currentColor" strokeWidth="0.5" />
      {/* Diagonal lines */}
      <line x1="20" y1="20" x2="100" y2="100" stroke="currentColor" strokeWidth="0.3" />
      <line x1="100" y1="20" x2="20" y2="100" stroke="currentColor" strokeWidth="0.3" />
      {/* North point — filled */}
      <path d="M60 6 L65 52 L60 57 L55 52 Z" fill="currentColor" />
      {/* South point */}
      <path d="M60 114 L65 68 L60 63 L55 68 Z" fill="currentColor" fillOpacity="0.45" />
      {/* East point */}
      <path d="M114 60 L68 65 L63 60 L68 55 Z" fill="currentColor" fillOpacity="0.45" />
      {/* West point */}
      <path d="M6 60 L52 65 L57 60 L52 55 Z" fill="currentColor" fillOpacity="0.45" />
      {/* NE */}
      <path d="M98 22 L68 56 L64 52 L71 45 Z" fill="currentColor" fillOpacity="0.25" />
      {/* NW */}
      <path d="M22 22 L52 56 L56 52 L49 45 Z" fill="currentColor" fillOpacity="0.25" />
      {/* SE */}
      <path d="M98 98 L68 64 L64 68 L71 75 Z" fill="currentColor" fillOpacity="0.25" />
      {/* SW */}
      <path d="M22 98 L52 64 L56 68 L49 75 Z" fill="currentColor" fillOpacity="0.25" />
      {/* Center */}
      <circle cx="60" cy="60" r="4" fill="currentColor" />
      <circle cx="60" cy="60" r="9" stroke="currentColor" strokeWidth="0.8" />
      {/* N label */}
      <text x="60" y="3.5" textAnchor="middle" fontSize="7" fill="currentColor" fontWeight="700">N</text>
    </svg>
  )
}
