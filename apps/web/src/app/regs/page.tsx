// 2026-10-14 — the regulation library hub: one card per collection of public
// regulation pages (growth plan step 3).

import type { Metadata } from 'next'
import Link from 'next/link'
import { getCollections } from '@/lib/regs'
import { pageMetadata } from '@/lib/seo'
import { Breadcrumbs, RegsShell } from './_components/RegsShell'

export const revalidate = 3600

export const metadata: Metadata = pageMetadata({
  title: 'U.S. Maritime Regulations in Plain English',
  description:
    'Plain-English explanations of 46 and 33 CFR, the Navigation Rules and Coast Guard NVICs, each beside ' +
    'the regulation text: Subchapter M, mariner credentials, pollution prevention and more.',
  path: '/regs',
})

export default async function RegsHub() {
  const collections = await getCollections()
  const total = collections.reduce((n, c) => n + c.pages, 0)
  return (
    <RegsShell signupHref="/register?src=regs&utm_content=hub">
      <div className="max-w-5xl mx-auto">
        <Breadcrumbs items={[{ label: 'Regulations' }]} />
        <h1 className="font-display font-black text-[#f0ece4] leading-tight text-[clamp(30px,6vw,52px)] mb-4">
          U.S. maritime regulations,<br />
          <span className="text-[#2dd4bf]">in plain English.</span>
        </h1>
        <p className="font-mono text-base text-[#6b7594] max-w-2xl leading-relaxed mb-10">
          Each page explains one section of the regulations in plain English, quotes the passage behind every
          requirement, and shows the full text. {total > 0 && <>{total.toLocaleString()} sections so far.</>}
        </p>
        {collections.length === 0 ? (
          <p className="font-mono text-sm text-[#6b7594]">The library is being prepared. Check back soon.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {collections.map((c) => (
              <Link key={c.slug} href={`/regs/c/${c.slug}`}
                className="rounded-xl border border-white/8 bg-[#111827] p-5 hover:border-[#2dd4bf]/40 transition-colors">
                <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-1.5">{c.title}</h2>
                <p className="font-mono text-sm text-[#f0ece4]/70 leading-relaxed mb-3">{c.blurb}</p>
                <span className="font-mono text-xs text-[#2dd4bf]">{c.pages.toLocaleString()} sections →</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </RegsShell>
  )
}
