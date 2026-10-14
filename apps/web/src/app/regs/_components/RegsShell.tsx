// 2026-10-14 — the frame around the public regulation pages: the public nav
// (as on /practice), the page body and the marketing footer.

import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { LandingFooter } from '@/components/marketing/LandingFooter'

export function RegsShell({ signupHref, children }: { signupHref: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">
      <nav className="fixed top-0 inset-x-0 z-40 flex items-center justify-between
        px-4 md:px-10 py-4 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
        <Link href="/landing" className="flex items-center gap-2">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
            RegKnot
          </span>
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/regs"
            className="hidden sm:inline font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Regulations
          </Link>
          <Link href="/login"
            className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Sign In
          </Link>
          <Link href={signupHref}
            className="hidden sm:inline-block font-mono text-xs font-bold uppercase tracking-wider
              border border-[#2dd4bf]/40 text-[#2dd4bf] hover:bg-[#2dd4bf]/10
              rounded-lg py-2 px-3 transition-colors duration-150">
            Try RegKnot free
          </Link>
        </div>
      </nav>
      <main className="px-4 md:px-10 pt-24 md:pt-28 pb-16">{children}</main>
      <LandingFooter />
    </div>
  )
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="font-mono text-xs text-[#6b7594] mb-4">
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-center gap-1.5">
            {i > 0 && <span aria-hidden="true">›</span>}
            {item.href ? (
              <Link href={item.href} className="hover:text-[#2dd4bf] transition-colors">{item.label}</Link>
            ) : (
              <span className="text-[#f0ece4]/70">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export function JsonLd({ data }: { data: unknown }) {
  // JSON-LD for search engines. "<" is escaped so page text can't close the script tag.
  const json = JSON.stringify(data).replace(/</g, '\\u003c')
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />
}
