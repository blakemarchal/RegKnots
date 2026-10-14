// 2026-10-14 — one public regulation page (growth plan step 3). The plain-English
// explanation, each requirement with the passage it comes from, common
// questions, and the regulation's own text. Written by app/seo_pages.py and
// served only after its automated checks passed. Cached; refreshed hourly.

import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getPage, regsSignupHref, type RegPage } from '@/lib/regs'
import { OG_IMAGE, SITE_URL } from '@/lib/seo'
import { Breadcrumbs, JsonLd, RegsShell } from '../_components/RegsShell'
import { RegulationText } from '../_components/RegulationText'

export const revalidate = 3600
export const dynamicParams = true

export async function generateStaticParams() {
  return []     // rendered on first request, then cached (no API call at build time)
}

type Params = { params: Promise<{ slug: string }> }

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params
  const page = await getPage(slug)
  if (!page) return { title: 'Regulation not found', robots: { index: false } }
  const description = page.meta_description ?? page.content.summary
  const url = `/regs/${page.slug}`
  return {
    title: page.title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title: page.title, description, url, siteName: 'RegKnot', type: 'article', images: [OG_IMAGE],
    },
    twitter: { card: 'summary_large_image', title: page.title, description, images: [OG_IMAGE.url] },
  }
}

function structuredData(page: RegPage) {
  const url = `${SITE_URL}/regs/${page.slug}`
  const graph: object[] = [
    {
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Regulations', item: `${SITE_URL}/regs` },
        { '@type': 'ListItem', position: 2, name: page.collection_title, item: `${SITE_URL}/regs/c/${page.collection}` },
        { '@type': 'ListItem', position: 3, name: page.display_number, item: url },
      ],
    },
    {
      '@type': 'WebPage',
      '@id': url,
      url,
      name: page.title,
      description: page.meta_description ?? page.content.summary,
      dateModified: page.updated_at,
      about: {
        '@type': 'Legislation',
        name: page.section_title ?? page.content.topic,
        legislationIdentifier: page.display_number,
        legislationJurisdiction: 'US',
        ...(page.source_url ? { url: page.source_url } : {}),
      },
      publisher: { '@type': 'Organization', name: 'RegKnot', url: SITE_URL },
    },
  ]
  if (page.content.faqs.length) {
    graph.push({
      '@type': 'FAQPage',
      mainEntity: page.content.faqs.map((f) => ({
        '@type': 'Question',
        name: f.question,
        acceptedAnswer: { '@type': 'Answer', text: f.answer },
      })),
    })
  }
  return { '@context': 'https://schema.org', '@graph': graph }
}

function fmtDate(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
}

export default async function RegPageView({ params }: Params) {
  const { slug } = await params
  const page = await getPage(slug)
  if (!page) notFound()
  const { content } = page
  const signup = regsSignupHref(page.slug)
  const asOf = fmtDate(page.up_to_date_as_of)

  return (
    <RegsShell signupHref={signup}>
      <JsonLd data={structuredData(page)} />
      <article className="max-w-3xl mx-auto">
        <Breadcrumbs items={[
          { label: 'Regulations', href: '/regs' },
          { label: page.collection_title, href: `/regs/c/${page.collection}` },
          { label: page.display_number },
        ]} />

        <h1 className="font-display font-black text-[#f0ece4] leading-tight text-[clamp(28px,5.5vw,44px)] mb-4">
          {page.title}
        </h1>
        <p className="font-mono text-base md:text-lg text-[#f0ece4]/85 leading-relaxed mb-6">{content.summary}</p>

        {content.applies_to && (
          <div className="rounded-xl border border-white/8 bg-[#111827] px-4 py-3 mb-8">
            <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">
              <span className="font-display font-bold uppercase tracking-wider text-xs text-[#2dd4bf] mr-2">Applies to</span>
              {content.applies_to}
            </p>
          </div>
        )}

        {content.requirements.length > 0 && (
          <section className="mb-10">
            <h2 className="font-display text-2xl font-bold text-[#f0ece4] mb-4">What it says</h2>
            <ol className="space-y-5">
              {content.requirements.map((r, i) => (
                <li key={i} className="border-l-2 border-[#2dd4bf]/40 pl-4">
                  <p className="font-mono text-[15px] text-[#f0ece4]/90 leading-relaxed">{r.statement}</p>
                  <blockquote className="mt-2 font-mono text-[13px] text-[#6b7594] leading-relaxed">
                    {r.paragraph && (
                      <span className="text-[#2dd4bf]/80 mr-1.5">
                        {page.display_number}{r.paragraph.startsWith('(') ? '' : ' '}{r.paragraph}
                      </span>
                    )}
                    &ldquo;{r.quote}&rdquo;
                  </blockquote>
                </li>
              ))}
            </ol>
          </section>
        )}

        <aside className="rounded-2xl border border-[#2dd4bf]/30 bg-[#2dd4bf]/[0.06] p-5 md:p-6 mb-10">
          <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">
            Have a question about {page.display_number}?
          </h2>
          <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed mb-4">
            RegKnot answers compliance questions for your vessel from the full text of the CFR, Coast Guard
            NVICs and policy, and the international conventions, with a citation for every requirement.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href={signup}
              className="font-mono text-sm font-bold bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-5 py-2.5
                hover:brightness-110 transition-[filter] duration-150">
              Ask RegKnot free
            </Link>
            {page.collection === 'mariner-credentials' && (
              <Link href="/practice"
                className="font-mono text-sm font-bold border border-[#2dd4bf]/50 text-[#2dd4bf] rounded-xl px-5 py-2.5
                  hover:bg-[#2dd4bf]/10 transition-colors duration-150">
                Free exam practice
              </Link>
            )}
          </div>
        </aside>

        {content.faqs.length > 0 && (
          <section className="mb-10">
            <h2 className="font-display text-2xl font-bold text-[#f0ece4] mb-4">Common questions</h2>
            <div className="space-y-5">
              {content.faqs.map((f, i) => (
                <div key={i}>
                  <h3 className="font-mono text-[15px] font-bold text-[#f0ece4] mb-1.5">{f.question}</h3>
                  <p className="font-mono text-sm text-[#f0ece4]/80 leading-relaxed">{f.answer}</p>
                  <blockquote className="mt-1.5 font-mono text-[13px] text-[#6b7594] leading-relaxed">
                    &ldquo;{f.quote}&rdquo;
                  </blockquote>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="mb-10">
          <h2 className="font-display text-2xl font-bold text-[#f0ece4] mb-1">
            The text of {page.display_number}
          </h2>
          <p className="font-mono text-xs text-[#6b7594] mb-4">
            {page.source_label}
            {page.source_url && (
              <>
                {' · '}
                <a href={page.source_url} target="_blank" rel="noopener noreferrer"
                  className="text-[#2dd4bf] hover:underline">Read it on eCFR</a>
              </>
            )}
          </p>
          {page.section_title && (
            <p className="font-mono text-sm font-bold text-[#f0ece4]/90 mb-3">{page.section_title}</p>
          )}
          <div className="rounded-xl border border-white/8 bg-[#111827] p-4 md:p-6">
            <RegulationText text={page.source_text} />
          </div>
        </section>

        {page.related.length > 0 && (
          <section className="mb-10">
            <h2 className="font-display text-lg font-bold text-[#f0ece4] mb-3">Sections it refers to</h2>
            <ul className="flex flex-wrap gap-2">
              {page.related.map((r) => (
                <li key={r.section_number}>
                  {r.slug ? (
                    <Link href={`/regs/${r.slug}`}
                      className="inline-block font-mono text-xs rounded-lg border border-[#2dd4bf]/40 text-[#2dd4bf] px-2.5 py-1.5 hover:bg-[#2dd4bf]/10">
                      {r.section_number}
                    </Link>
                  ) : r.url ? (
                    <a href={r.url} target="_blank" rel="noopener noreferrer"
                      className="inline-block font-mono text-xs rounded-lg border border-white/15 text-[#f0ece4]/70 px-2.5 py-1.5 hover:border-white/30">
                      {r.section_number} ↗
                    </a>
                  ) : (
                    <span className="inline-block font-mono text-xs rounded-lg border border-white/10 text-[#6b7594] px-2.5 py-1.5">
                      {r.section_number}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {(page.previous || page.next) && (
          <nav aria-label={`More in ${page.collection_title}`}
            className="grid gap-3 sm:grid-cols-2 mb-10">
            {page.previous ? (
              <Link href={`/regs/${page.previous.slug}`}
                className="rounded-xl border border-white/8 bg-[#111827] p-4 hover:border-[#2dd4bf]/40 transition-colors">
                <span className="font-mono text-[11px] text-[#6b7594]">← Previous</span>
                <span className="block font-mono text-sm text-[#f0ece4]/85 mt-1">{page.previous.title}</span>
              </Link>
            ) : <span />}
            {page.next && (
              <Link href={`/regs/${page.next.slug}`}
                className="rounded-xl border border-white/8 bg-[#111827] p-4 hover:border-[#2dd4bf]/40 transition-colors sm:text-right">
                <span className="font-mono text-[11px] text-[#6b7594]">Next →</span>
                <span className="block font-mono text-sm text-[#f0ece4]/85 mt-1">{page.next.title}</span>
              </Link>
            )}
          </nav>
        )}

        <p className="font-mono text-xs text-[#6b7594] leading-relaxed border-t border-white/5 pt-5">
          The plain-English explanation on this page was written with AI from the regulation text above and
          checked automatically before publishing: every quote appears in the text, every number comes from it,
          and a second model confirmed each statement adds nothing the text doesn&apos;t say.
          {asOf && <> Regulation text current as of {asOf}.</>} The regulation text governs. RegKnot is not
          affiliated with the U.S. Coast Guard.
        </p>
      </article>
    </RegsShell>
  )
}
