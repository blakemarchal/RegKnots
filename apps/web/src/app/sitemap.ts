// 2026-10-14 — sitemap.xml: the public pages (src/lib/seo.ts PUBLIC_PAGES) and
// the published regulation pages, read from the API and refreshed hourly. If
// the API can't be read (e.g. at build time) the static pages still go out.

import type { MetadataRoute } from 'next'
import { getCollections, getPages } from '@/lib/regs'
import { PUBLIC_PAGES, SITE_URL } from '@/lib/seo'

export const revalidate = 3600

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const fixed: MetadataRoute.Sitemap = PUBLIC_PAGES.map(([path, changeFrequency, priority]) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency,
    priority,
  }))
  const [collections, pages] = await Promise.all([getCollections(), getPages()])
  const hubs: MetadataRoute.Sitemap = collections.map((c) => ({
    url: `${SITE_URL}/regs/c/${c.slug}`,
    changeFrequency: 'weekly',
    priority: 0.6,
  }))
  const regs: MetadataRoute.Sitemap = pages.map((p) => ({
    url: `${SITE_URL}/regs/${p.slug}`,
    lastModified: p.updated_at,
    changeFrequency: 'monthly',
    priority: 0.5,
  }))
  return [...fixed, ...hubs, ...regs]
}
