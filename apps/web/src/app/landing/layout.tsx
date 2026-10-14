// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "RegKnot — Maritime Compliance Answers, Cited to the Regulation",
  description:
    "Ask a compliance question and get an answer cited to the regulation text: 46 and 33 CFR, USCG NVICs and policy, SOLAS, MARPOL, STCW, COLREGs, the ISM Code and flag-state rules. Free trial, then a free plan.",
  path: '/landing',
  absoluteTitle: true,
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
