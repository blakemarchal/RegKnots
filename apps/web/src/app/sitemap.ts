// 2026-10-14 — sitemap.xml: the public pages (src/lib/seo.ts PUBLIC_PAGES).

import type { MetadataRoute } from 'next'
import { PUBLIC_PAGES, SITE_URL } from '@/lib/seo'

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PAGES.map(([path, changeFrequency, priority]) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency,
    priority,
  }))
}
