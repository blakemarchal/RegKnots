'use client'

import { useEffect, useRef, useState } from 'react'

export type ExtractionPhase = 'idle' | 'uploading' | 'reading' | 'extracting' | 'done' | 'error'

const PHASE_LABELS: Record<ExtractionPhase, string> = {
  idle: '',
  uploading: 'Uploading document...',
  reading: 'Reading your document...',
  extracting: 'Extracting vessel details...',
  done: 'Done!',
  error: 'Extraction failed',
}

const PHASE_PROGRESS: Record<ExtractionPhase, number> = {
  idle: 0,
  uploading: 25,
  reading: 55,
  extracting: 85,
  done: 100,
  error: 0,
}

export function ExtractionProgress({ phase }: { phase: ExtractionPhase }) {
  if (phase === 'idle') return null
  return (
    <div className="space-y-2">
      <div className="h-1.5 w-full rounded-full bg-white/8 overflow-hidden">
        <div
          className="h-full rounded-full bg-[#2dd4bf] transition-all duration-700 ease-out"
          style={{ width: `${PHASE_PROGRESS[phase]}%` }}
        />
      </div>
      <p className="font-mono text-xs text-[#2dd4bf] animate-pulse">{PHASE_LABELS[phase]}</p>
    </div>
  )
}

/** React hook that drives phase transitions during a long extraction call. */
export function useExtractionPhase() {
  const [phase, setPhase] = useState<ExtractionPhase>('idle')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function start() {
    clear()
    setPhase('uploading')
    timerRef.current = setTimeout(() => {
      setPhase('reading')
      timerRef.current = setTimeout(() => setPhase('extracting'), 3000)
    }, 2000)
  }

  function finish(success: boolean) {
    clear()
    setPhase(success ? 'done' : 'error')
    timerRef.current = setTimeout(() => setPhase('idle'), success ? 1500 : 3000)
  }

  function reset() {
    clear()
    setPhase('idle')
  }

  function clear() {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  useEffect(() => () => clear(), [])

  return { phase, start, finish, reset }
}
