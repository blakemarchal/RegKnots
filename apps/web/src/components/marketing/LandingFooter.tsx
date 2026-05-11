'use client'

import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'

// Sprint D6.90 — shared landing-page footer with social-media row.
//
// Before this commit, /landing and /giving each had their own inline
// footer, and /education, /pricing, /captainkarynn, /womenoffshore had
// no footer at all. Blake asked for social links on every landing
// surface, and rather than copy-paste a six-icon row into six pages we
// extract one component.
//
// Page-specific link rows (Coverage on /landing, Home on /giving, etc.)
// flow through the `extraLinks` slot so the four constants stay
// uniform: Terms, Privacy, Giving Back, copyright.
//
// `onContactClick` is for /landing's ContactModal — only that page
// wires it; everywhere else the slot is absent and the button doesn't
// render.

const SOCIAL_LINKS = [
  {
    href: 'https://www.linkedin.com/company/regknots',
    label: 'LinkedIn',
    // Plain LinkedIn glyph — square with "in".
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="w-4 h-4">
        <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.86-3.04-1.86 0-2.14 1.45-2.14 2.95v5.66H9.36V9h3.41v1.56h.05c.48-.9 1.64-1.86 3.38-1.86 3.61 0 4.28 2.38 4.28 5.47v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.23 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.46c.98 0 1.77-.77 1.77-1.72V1.72C24 .77 23.21 0 22.23 0z" />
      </svg>
    ),
  },
  {
    href: 'https://www.instagram.com/reg_knot/',
    label: 'Instagram',
    // Rounded square + lens + dot.
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" className="w-4 h-4">
        <rect x="3" y="3" width="18" height="18" rx="5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="17.5" cy="6.5" r="0.8" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    href: 'https://www.facebook.com/profile.php?id=61560655543438',
    label: 'Facebook',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="w-4 h-4">
        <path d="M22.675 0H1.325C.593 0 0 .593 0 1.325v21.351C0 23.408.593 24 1.325 24h11.494v-9.294H9.692V11.01h3.127V8.41c0-3.099 1.894-4.785 4.659-4.785 1.325 0 2.464.099 2.795.143v3.24h-1.918c-1.504 0-1.795.715-1.795 1.763v2.31h3.587l-.467 3.696h-3.12V24h6.116c.73 0 1.323-.592 1.323-1.324V1.325C24 .593 23.408 0 22.675 0z" />
      </svg>
    ),
  },
  {
    href: 'https://x.com/RegKnot',
    label: 'X (Twitter)',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="w-4 h-4">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
      </svg>
    ),
  },
] as const

interface Props {
  /** Page-specific link slot, rendered before the standard Terms/Privacy/Giving row. */
  extraLinks?: { href: string; label: string }[]
  /** /landing wires this to open ContactModal; absent elsewhere. */
  onContactClick?: () => void
  /** Override the homepage target — /giving uses isAuthenticated ? '/' : '/landing'. */
  homeHref?: string
}

export function LandingFooter({ extraLinks = [], onContactClick, homeHref }: Props) {
  return (
    <footer className="border-t border-white/8 px-5 md:px-10 py-8 mt-auto">
      <div className="max-w-4xl mx-auto flex flex-col items-center gap-6 text-center">
        {/* Top row — wordmark + tagline */}
        <div className="flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
          <div className="flex items-center gap-2">
            <CompassRose className="w-4 h-4 text-[#2dd4bf]/60" />
            <span className="font-display text-base font-bold text-[#f0ece4]/60 tracking-widest uppercase">
              RegKnot
            </span>
          </div>
          <span className="hidden sm:inline text-[#6b7594]/40">·</span>
          <p className="font-mono text-xs text-[#6b7594]">
            Navigation aid only &mdash; not legal advice
          </p>
        </div>

        {/* Social icons row */}
        <nav aria-label="Social media" className="flex items-center gap-5">
          {SOCIAL_LINKS.map(({ href, label, icon }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={label}
              className="text-[#6b7594] hover:text-[#2dd4bf] transition-colors"
            >
              {icon}
            </a>
          ))}
        </nav>

        {/* Link row — page-specific extras + standard set */}
        <div className="flex items-center gap-4 flex-wrap justify-center">
          {onContactClick && (
            <button
              type="button"
              onClick={onContactClick}
              className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors"
            >
              Contact Us
            </button>
          )}
          {extraLinks.map(({ href, label }) => (
            <Link
              key={href + label}
              href={href}
              className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors"
            >
              {label}
            </Link>
          ))}
          <Link href="/terms" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
            Terms
          </Link>
          <Link href="/privacy" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
            Privacy
          </Link>
          <Link href="/giving" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
            Giving Back
          </Link>
          {homeHref && (
            <Link href={homeHref} className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Home
            </Link>
          )}
          <p className="font-mono text-xs text-[#6b7594]">&copy; 2026 RegKnot</p>
        </div>
      </div>
    </footer>
  )
}
