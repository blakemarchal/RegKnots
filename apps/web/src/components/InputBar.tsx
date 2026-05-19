'use client'

import { useRef, useEffect, type KeyboardEvent, type ChangeEvent } from 'react'
import { useVoiceInput } from '@/lib/useVoiceInput'
import type { ResizedImage } from '@/utils/image_resize'

// Sprint D6.34 / D6.52 — verbosity selection type. Always one of the
// three concrete values. ChatInterface initializes from the user's
// account preference and snaps back to it after each successful send.
//
// Sprint D6.77 — moved the verbosity UI out of InputBar to a compact
// dropdown next to the VesselPill / Log pill (see VerbosityDropdown).
// The type is still exported here so the dropdown component can import
// it; InputBar itself no longer renders verbosity chrome.
export type VerbosityOverride = 'brief' | 'standard' | 'detailed'

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  loading: boolean
  // Sprint D6.85 Fix C — when loading, the send button transforms into
  // a Stop button. onStop is fired when clicked. Optional for callers
  // that don't need cancellation (e.g., one-shot prefill flows).
  onStop?: () => void
  // Sprint D6.97 Phase 2 — image upload. ChatInterface owns the
  // pendingImages array; InputBar just renders + dispatches.
  // imagesEnabled false hides the paperclip entirely; on true the
  // button is shown and clicking opens the file picker.
  imagesEnabled?: boolean
  pendingImages?: ResizedImage[]
  onAddImages?: (files: FileList) => void
  onRemoveImage?: (index: number) => void
}

const MAX_IMAGES = 5

export function InputBar({
  value, onChange, onSend, loading, onStop,
  imagesEnabled = false,
  pendingImages = [],
  onAddImages,
  onRemoveImage,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { listening, supported, toggle } = useVoiceInput({
    onTranscript: (text) => {
      onChange(value ? `${value} ${text}` : text)
    },
  })

  // Auto-resize textarea
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!loading && value.trim()) onSend()
    }
  }

  function openFilePicker() {
    if (loading) return
    if (pendingImages.length >= MAX_IMAGES) return
    fileInputRef.current?.click()
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (files && files.length > 0 && onAddImages) {
      onAddImages(files)
    }
    // Reset value so picking the same file twice still fires onChange.
    e.target.value = ''
  }

  // D6.97 Phase 2 — allow send when there's text OR at least one image.
  // Image-only queries are valid ("what is this?" implied by the image).
  const canSend = !loading && (value.trim().length > 0 || pendingImages.length > 0)
  const imagesAtCap = pendingImages.length >= MAX_IMAGES

  return (
    <div className="px-3 pb-3 pt-1">
      {/* D6.97 Phase 2 — image preview strip (above the textarea row). */}
      {imagesEnabled && pendingImages.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2 px-1">
          {pendingImages.map((img, idx) => (
            <div key={idx} className="relative group">
              <img
                src={img.data_url}
                alt={`Attached image ${idx + 1}`}
                className="h-16 w-16 object-cover rounded-lg border border-white/15 bg-black/40"
              />
              <button
                onClick={() => onRemoveImage?.(idx)}
                aria-label={`Remove image ${idx + 1}`}
                className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full
                  bg-[#0a0e1a] border border-white/30 text-[#f0ece4]
                  flex items-center justify-center text-[10px] leading-none
                  hover:bg-red-500/30 hover:border-red-400/60
                  transition-colors duration-150"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2 px-3 py-2 rounded-2xl
        bg-[#0d1225] border border-white/10
        focus-within:border-teal/40 transition-colors duration-150">

        {/* Voice input button */}
        {supported && (
          <button
            onClick={toggle}
            disabled={loading}
            aria-label={listening ? 'Stop recording' : 'Start voice input'}
            className={`flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
              transition-all duration-150
              ${listening
                ? 'bg-red-500/20 text-red-400 animate-pulse'
                : 'text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5'
              }
              disabled:opacity-30 disabled:cursor-not-allowed`}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="1" width="6" height="14" rx="3" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>
        )}

        {/* D6.97 Phase 2 — image upload button (paperclip).
            Hidden when the feature flag is off so the user doesn't see
            a control that would 400 on submit. */}
        {imagesEnabled && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              onChange={handleFileChange}
              className="hidden"
            />
            <button
              onClick={openFilePicker}
              disabled={loading || imagesAtCap}
              aria-label={
                imagesAtCap
                  ? `Image cap reached (${MAX_IMAGES} max)`
                  : 'Attach images'
              }
              title={
                imagesAtCap
                  ? `Up to ${MAX_IMAGES} images per question`
                  : 'Attach images (don\'t upload IDs or personal info)'
              }
              className="flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
                text-[#6b7594] hover:text-[#2dd4bf] hover:bg-white/5
                transition-all duration-150
                disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
          </>
        )}

        <textarea
          ref={ref}
          value={value}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
          onKeyDown={onKey}
          disabled={loading}
          rows={1}
          placeholder={listening ? 'Listening...' : 'Ask a regulation question…'}
          className="flex-1 bg-transparent text-sm text-[#f0ece4] placeholder:text-[#6b7594]/60
            resize-none outline-none leading-relaxed py-1
            disabled:opacity-50"
          style={{ minHeight: '28px' }}
        />

        {/* Send / Stop button.
            D6.85 Fix C — while loading, this button transforms into
            a Stop control so users can cancel long-running generations
            without navigating away (which used to silently drop the
            answer + tokens). Click while loading → onStop(); otherwise
            click → onSend(). */}
        {loading && onStop ? (
          <button
            onClick={onStop}
            aria-label="Stop generation"
            className="flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
              bg-red-500/15 text-red-400 border border-red-500/40 font-bold
              hover:bg-red-500/25 active:scale-95
              transition-all duration-150"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="1.5" />
            </svg>
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={!canSend}
            aria-label="Send message"
            className="flex-shrink-0 w-8 h-8 mb-0.5 rounded-xl flex items-center justify-center
              bg-teal text-[#0a0e1a] font-bold
              disabled:opacity-30 disabled:cursor-not-allowed
              hover:enabled:bg-teal/90 active:enabled:scale-95
              transition-all duration-150"
          >
            {loading ? (
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            )}
          </button>
        )}
      </div>

      <p className="text-center text-[10px] text-[#6b7594]/50 mt-1.5 leading-none">
        Navigation aid only — not legal advice
      </p>
    </div>
  )
}
