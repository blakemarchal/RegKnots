'use client'

// 2026-10-16 UI pass — one top bar for every public page. Each page used to
// carry its own: the landing page had Giving Back and "Get Access", /regs said
// "Try RegKnot free", /pricing showed "Back to app" to people who had never
// signed in. Same links and the same "Start free" button everywhere; a menu on
// phones; "Open RegKnot" for someone already signed in.

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CompassRose } from '@/components/CompassRose'
import { useAuthStore } from '@/lib/auth'
import { useEscapeKey } from '@/lib/useEscapeKey'

const LINKS = [
  { href: '/regs', label: 'Regulations' },
  { href: '/practice', label: 'Exam practice' },
  { href: '/pricing', label: 'Pricing' },
]

export const START_FREE_LABEL = 'Start free'

interface Props {
  /** Draw a spacer the height of the bar, for pages whose content starts at the top. */
  spacer?: boolean
  /** Where "Start free" goes; partner and campaign pages keep their codes. */
  signupHref?: string
}

export function SiteNav({ spacer = false, signupHref = '/register' }: Props) {
  const signedIn = useAuthStore((s) => s.isAuthenticated)
  const pathname = usePathname() ?? ''
  const [open, setOpen] = useState(false)
  useEscapeKey(open, () => setOpen(false))

  const current = (href: string) => pathname === href || pathname.startsWith(href + '/')

  return (
    <>
      <nav aria-label="Main" className="no-print fixed top-0 inset-x-0 z-40 bg-[#0a0e1a]/85 backdrop-blur-md border-b border-white/5">
        <div className="max-w-6xl mx-auto h-14 flex items-center justify-between gap-4 px-5 md:px-10">
          <Link href="/landing" className="flex items-center gap-2 shrink-0" aria-label="RegKnot home">
            <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
            <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">RegKnot</span>
          </Link>

          <div className="hidden md:flex items-center gap-7">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} aria-current={current(l.href) ? 'page' : undefined}
                className={`font-mono text-sm transition-colors duration-150 ${
                  current(l.href) ? 'text-[#f0ece4]' : 'text-[#8a94ad] hover:text-[#f0ece4]'}`}>
                {l.label}
              </Link>
            ))}
          </div>

          <div className="flex items-center gap-3">
            {signedIn ? (
              <Link href="/"
                className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                  transition-[filter] duration-150 rounded-lg px-4 py-1.5">
                Open RegKnot
              </Link>
            ) : (
              <>
                <Link href="/login"
                  className="hidden sm:inline font-mono text-sm text-[#8a94ad] hover:text-[#f0ece4] transition-colors duration-150">
                  Sign in
                </Link>
                <Link href={signupHref}
                  className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf] hover:brightness-110
                    transition-[filter] duration-150 rounded-lg px-4 py-1.5 whitespace-nowrap">
                  {START_FREE_LABEL}
                </Link>
              </>
            )}
            <button type="button" onClick={() => setOpen((o) => !o)}
              aria-expanded={open} aria-controls="site-menu" aria-label={open ? 'Close menu' : 'Open menu'}
              className="md:hidden -mr-2 p-2 rounded-lg text-[#8a94ad] hover:text-[#f0ece4]">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" aria-hidden="true">
                {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
          </div>
        </div>

        {open && (
          <div id="site-menu" className="md:hidden border-t border-white/5 bg-[#0a0e1a] px-5 py-2">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} onClick={() => setOpen(false)}
                aria-current={current(l.href) ? 'page' : undefined}
                className="block py-3 font-mono text-sm text-[#f0ece4]/85 border-b border-white/5">
                {l.label}
              </Link>
            ))}
            {!signedIn && (
              <Link href="/login" onClick={() => setOpen(false)}
                className="block py-3 font-mono text-sm text-[#f0ece4]/85">
                Sign in
              </Link>
            )}
          </div>
        )}
      </nav>
      {spacer && <div aria-hidden="true" className="h-14" />}
    </>
  )
}
