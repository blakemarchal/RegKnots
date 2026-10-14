// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "Pricing",
  description:
    "Plans for individual mariners and whole crews: a free trial, a free plan of 10 questions a month, and paid plans from $9.99 a month. Wheelhouse puts the crew of a vessel on one account.",
  path: '/pricing',
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
