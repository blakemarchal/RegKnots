export function TypingIndicator() {
  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]">
      {/* Teal accent bar matching assistant messages */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-1" />
      <div className="flex items-center gap-1.5 py-1">
        <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0s_infinite]" />
        <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.2s_infinite]" />
        <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.4s_infinite]" />
      </div>
    </div>
  )
}
