// 2026-10-14 — the frame around the public regulation pages: the public nav
// (as on /practice), the page body and the marketing footer.

import Link from 'next/link'
import { LandingFooter } from '@/components/marketing/LandingFooter'
import { SiteNav } from '@/components/marketing/SiteNav'

export function RegsShell({ signupHref, children }: { signupHref: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">
      {/* 2026-10-16 UI pass — the shared site bar (components/marketing/SiteNav). */}
      <SiteNav signupHref={signupHref} />
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
