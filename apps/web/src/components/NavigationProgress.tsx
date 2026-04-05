'use client'

import { useEffect, useState, useCallback, useRef, Suspense } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'

/**
 * Dispatch this from any component before a programmatic router.push()
 * so the progress bar starts immediately (anchor clicks are auto-detected).
 */
export function signalNavigation() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('nav:start'))
  }
}

function ProgressBar() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [progress, setProgress] = useState(0)
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const keyRef = useRef(pathname + searchParams.toString())

  const start = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    setVisible(true)
    setProgress(15)
    let p = 15
    timerRef.current = setInterval(() => {
      p += (85 - p) * 0.08
      if (p > 85) p = 85
      setProgress(p)
    }, 120)
  }, [])

  const complete = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setProgress(100)
    setTimeout(() => { setVisible(false); setProgress(0) }, 250)
  }, [])

  // Complete when route changes
  useEffect(() => {
    const key = pathname + searchParams.toString()
    if (keyRef.current !== key) {
      complete()
      keyRef.current = key
    }
  }, [pathname, searchParams, complete])

  // Listen for <a> clicks + custom nav:start event
  useEffect(() => {
    function onAnchorClick(e: MouseEvent) {
      const a = (e.target as HTMLElement).closest('a')
      if (!a) return
      const href = a.getAttribute('href')
      if (!href || href.startsWith('http') || href.startsWith('#') || href.startsWith('mailto:')) return
      if (a.target === '_blank' || e.metaKey || e.ctrlKey || e.shiftKey) return
      start()
    }
    function onNavStart() { start() }

    document.addEventListener('click', onAnchorClick, { capture: true })
    window.addEventListener('nav:start', onNavStart)
    return () => {
      document.removeEventListener('click', onAnchorClick, { capture: true })
      window.removeEventListener('nav:start', onNavStart)
    }
  }, [start])

  if (!visible) return null

  return (
    <div className="fixed top-0 left-0 right-0 z-[9999] h-[2px] pointer-events-none">
      <div
        className="h-full bg-[#2dd4bf] transition-all ease-out"
        style={{
          width: `${progress}%`,
          opacity: progress >= 100 ? 0 : 1,
          transitionDuration: progress >= 100 ? '250ms' : '150ms',
          boxShadow: '0 0 8px rgba(45, 212, 191, 0.4)',
        }}
      />
    </div>
  )
}

export function NavigationProgress() {
  return (
    <Suspense fallback={null}>
      <ProgressBar />
    </Suspense>
  )
}
