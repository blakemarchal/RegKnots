// 2026-10-14 — one collection of public regulation pages, grouped by CFR part
// (or Rules / Annexes for the Navigation Rules).

import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getCollections, getPages, type RegSummary } from '@/lib/regs'
import { pageMetadata } from '@/lib/seo'
import { Breadcrumbs, RegsShell } from '../../_components/RegsShell'

export const revalidate = 3600
export const dynamicParams = true

export async function generateStaticParams() {
  return []
}

type Params = { params: Promise<{ collection: string }> }

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { collection } = await params
  const c = (await getCollections()).find((x) => x.slug === collection)
  if (!c) return { title: 'Not found', robots: { index: false } }
  return pageMetadata({ title: `${c.title} in Plain English`, description: c.blurb, path: `/regs/c/${c.slug}` })
}

function groupOf(p: RegSummary): string {
  const cfr = p.display_number.match(/^(\d+) CFR (\d+)\./)
  if (cfr) return `${cfr[1]} CFR Part ${cfr[2]}`
  if (/^COLREGs Annex/.test(p.display_number)) return 'Annexes'
  if (/^COLREGs Rule/.test(p.display_number)) return 'Rules'
  return ''
}

export default async function CollectionPage({ params }: Params) {
  const { collection } = await params
  const c = (await getCollections()).find((x) => x.slug === collection)
  if (!c) notFound()
  const pages = await getPages(collection)
  const groups: { name: string; pages: RegSummary[] }[] = []
  for (const p of pages) {
    const name = groupOf(p)
    if (groups.length === 0 || groups[groups.length - 1].name !== name) groups.push({ name, pages: [] })
    groups[groups.length - 1].pages.push(p)
  }

  return (
    <RegsShell signupHref={`/register?src=regs&utm_content=c-${c.slug}`}>
      <div className="max-w-4xl mx-auto">
        <Breadcrumbs items={[{ label: 'Regulations', href: '/regs' }, { label: c.title }]} />
        <h1 className="font-display font-black text-[#f0ece4] leading-tight text-[clamp(28px,5.5vw,44px)] mb-3">
          {c.title}
        </h1>
        <p className="font-mono text-sm md:text-base text-[#6b7594] leading-relaxed mb-8">{c.blurb}</p>
        {groups.map((g) => (
          <section key={g.name || 'all'} className="mb-8">
            {g.name && <h2 className="font-display text-lg font-bold text-[#2dd4bf] mb-3">{g.name}</h2>}
            <ul className="divide-y divide-white/5 rounded-xl border border-white/8 bg-[#111827]">
              {g.pages.map((p) => (
                <li key={p.slug}>
                  <Link href={`/regs/${p.slug}`} className="block px-4 py-3 hover:bg-white/[0.03] transition-colors">
                    <span className="block font-mono text-sm text-[#f0ece4]/90">{p.title}</span>
                    {p.meta_description && (
                      <span className="block font-mono text-xs text-[#6b7594] mt-0.5 leading-relaxed">{p.meta_description}</span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </RegsShell>
  )
}
