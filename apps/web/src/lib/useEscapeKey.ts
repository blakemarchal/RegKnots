'use client'

// 2026-09-29 — Escape closes the topmost sheet, drawer or modal. None of them
// listened for it. Layers register while open; one keypress closes only the
// newest, so a modal opened from the menu closes before the menu does.

import { useEffect, useRef } from 'react'

const stack: { current: () => void }[] = []

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.isComposing) return
  const top = stack[stack.length - 1]
  if (!top) return
  e.preventDefault()
  top.current()
}

export function useEscapeKey(active: boolean, onEscape: () => void) {
  const handler = useRef(onEscape)
  useEffect(() => {
    handler.current = onEscape
  })
  useEffect(() => {
    if (!active) return
    const entry = handler
    stack.push(entry)
    if (stack.length === 1) window.addEventListener('keydown', onKeyDown)
    return () => {
      const i = stack.lastIndexOf(entry)
      if (i >= 0) stack.splice(i, 1)
      if (stack.length === 0) window.removeEventListener('keydown', onKeyDown)
    }
  }, [active])
}
