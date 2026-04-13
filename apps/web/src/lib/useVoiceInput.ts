'use client'

import { useState, useCallback, useRef } from 'react'
import { apiUpload } from './api'

/**
 * Voice input hook using Web Speech API with Whisper fallback.
 *
 * Primary: browser-native SpeechRecognition (zero latency, no network).
 * Fallback: MediaRecorder → upload to /transcribe (Whisper API).
 */

interface UseVoiceInputOptions {
  onTranscript: (text: string) => void
  onError?: (msg: string) => void
}

interface UseVoiceInputReturn {
  listening: boolean
  supported: boolean
  start: () => void
  stop: () => void
  toggle: () => void
}

// Check for Web Speech API support — returns the constructor or null.
// The Web Speech API is not typed in all TS environments, so we use `any`.
function getSpeechRecognitionCtor(): (new () => any) | null {
  if (typeof window === 'undefined') return null
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null
}

export function useVoiceInput({ onTranscript, onError }: UseVoiceInputOptions): UseVoiceInputReturn {
  const [listening, setListening] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const usingFallbackRef = useRef(false)

  const SpeechRecognitionClass = getSpeechRecognitionCtor()
  const supported = typeof window !== 'undefined' && (
    !!SpeechRecognitionClass || !!navigator.mediaDevices?.getUserMedia
  )

  const stopFallbackRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return

    return new Promise<void>((resolve) => {
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType })
        chunksRef.current = []
        mediaRecorderRef.current = null

        if (blob.size < 1000) {
          // Too short to transcribe
          resolve()
          return
        }

        try {
          const ext = recorder.mimeType.includes('webm') ? 'webm' : 'mp4'
          const formData = new FormData()
          formData.append('file', blob, `recording.${ext}`)

          const result = await apiUpload<{ text: string }>('/transcribe', formData)
          if (result.text.trim()) {
            onTranscript(result.text.trim())
          }
        } catch {
          onError?.('Transcription failed. Please try again.')
        }
        resolve()
      }
      recorder.stop()
    })
  }, [onTranscript, onError])

  const stop = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
    if (usingFallbackRef.current) {
      stopFallbackRecording()
      usingFallbackRef.current = false
    }
    setListening(false)
  }, [stopFallbackRecording])

  const startFallbackRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType })

      chunksRef.current = []
      mediaRecorderRef.current = recorder
      usingFallbackRef.current = true

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.start(1000) // Collect chunks every second
      setListening(true)
    } catch {
      onError?.('Microphone access denied')
      setListening(false)
    }
  }, [onError])

  const start = useCallback(() => {
    if (listening) return

    // Try Web Speech API first
    if (SpeechRecognitionClass) {
      try {
        const recognition = new SpeechRecognitionClass()
        recognition.continuous = true
        recognition.interimResults = false
        recognition.lang = 'en-US'

        recognition.onresult = (event: any) => {
          const last = event.results[event.results.length - 1]
          if (last.isFinal) {
            onTranscript(last[0].transcript.trim())
          }
        }

        recognition.onerror = (event: any) => {
          if (event.error === 'not-allowed') {
            onError?.('Microphone access denied')
          } else if (event.error === 'no-speech') {
            // Silently ignore — user just didn't speak
          } else {
            // Web Speech API failed — fall back to Whisper
            recognition.stop()
            recognitionRef.current = null
            startFallbackRecording()
            return
          }
          setListening(false)
        }

        recognition.onend = () => {
          if (recognitionRef.current === recognition) {
            recognitionRef.current = null
            setListening(false)
          }
        }

        recognitionRef.current = recognition
        recognition.start()
        setListening(true)
        return
      } catch {
        // Web Speech API instantiation failed — try fallback
      }
    }

    // Fallback: MediaRecorder + Whisper
    startFallbackRecording()
  }, [listening, SpeechRecognitionClass, onTranscript, onError, startFallbackRecording])

  const toggle = useCallback(() => {
    if (listening) stop()
    else start()
  }, [listening, start, stop])

  return { listening, supported, start, stop, toggle }
}
