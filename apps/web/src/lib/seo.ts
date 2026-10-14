// 2026-10-14 — search basics: one helper so every public page carries the
// same canonical URL, Open Graph card and share image. The root layout sets
// metadataBase (SITE_URL) and the "%s | RegKnot" title template.

import type { Metadata } from 'next'

export const SITE_URL = 'https://regknots.com'
export const SITE_NAME = 'RegKnot'
export const DEFAULT_TITLE = 'RegKnot — Maritime Compliance Answers, Cited to the Regulation'
export const DEFAULT_DESCRIPTION =
  'Cited answers from the actual regulation texts: 46 and 33 CFR, USCG NVICs and policy, SOLAS, ' +
  'MARPOL, STCW, COLREGs, the ISM Code and flag-state rules. Built for U.S. mariners and vessel operators.'
export const OG_IMAGE = { url: '/opengraph-image', width: 1200, height: 630, alt: 'RegKnot' }

/** Public pages listed in the sitemap: [path, change frequency, priority]. */
export const PUBLIC_PAGES: Array<[string, 'weekly' | 'monthly' | 'yearly', number]> = [
  ['/landing', 'weekly', 1.0],
  ['/practice', 'weekly', 0.9],
  ['/regs', 'weekly', 0.9],
  ['/pricing', 'monthly', 0.8],
  ['/education', 'monthly', 0.7],
  ['/coverage', 'monthly', 0.7],
  ['/reference', 'monthly', 0.6],
  ['/whale-zones', 'monthly', 0.6],
  ['/giving', 'yearly', 0.4],
  ['/privacy', 'yearly', 0.2],
  ['/terms', 'yearly', 0.2],
]

interface PageMeta {
  title: string
  description: string
  path: string
  /** Use the title as written, without the " | RegKnot" suffix. */
  absoluteTitle?: boolean
  noindex?: boolean
}

export function pageMetadata({ title, description, path, absoluteTitle, noindex }: PageMeta): Metadata {
  const fullTitle = absoluteTitle ? title : `${title} | ${SITE_NAME}`
  return {
    title: absoluteTitle ? { absolute: title } : title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title: fullTitle,
      description,
      url: path,
      siteName: SITE_NAME,
      type: 'website',
      images: [OG_IMAGE],
    },
    twitter: { card: 'summary_large_image', title: fullTitle, description, images: [OG_IMAGE.url] },
    ...(noindex ? { robots: { index: false, follow: true } } : {}),
  }
}

/** For pages that should stay out of search results (sign-in, partner promo pages). */
export function noindexMetadata(title: string): Metadata {
  return { title, robots: { index: false, follow: true } }
}
