'use client'
import { useEffect } from 'react'

export function useSwUpdate() {
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return

    navigator.serviceWorker.addEventListener('controllerchange', () => {
      // New SW took control — reload to get fresh chunks
      window.location.reload()
    })
  }, [])
}
