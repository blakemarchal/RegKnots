interface Props {
  /** Optional progress message — when set, replaces the bouncing dots with a
   *  single pulsing teal dot + the status text. Falls back to dots when null. */
  message?: string | null
}

export function TypingIndicator({ message = null }: Props = {}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-[fadeSlideIn_0.2s_ease-out]">
      {/* Teal accent bar matching assistant messages */}
      <div className="w-0.5 self-stretch bg-teal/40 rounded-full flex-shrink-0 mt-1" />
      {message ? (
        <div className="flex items-center gap-2 py-1 min-w-[12rem]">
          <span
            className="w-1.5 h-1.5 rounded-full bg-teal animate-[progressPulse_1.5s_ease-in-out_infinite] flex-shrink-0"
            aria-hidden="true"
          />
          <span
            key={message}
            className="font-mono text-xs text-[#6b7594] animate-[fadeSlideIn_0.25s_ease-out]"
          >
            {message}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0s_infinite]" />
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.2s_infinite]" />
          <span className="w-1.5 h-1.5 rounded-full bg-teal/60 animate-[bounceDot_1.2s_ease-in-out_0.4s_infinite]" />
        </div>
      )}
    </div>
  )
}
