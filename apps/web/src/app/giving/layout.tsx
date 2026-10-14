// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "Giving: 10% of Revenue to Maritime Charities",
  description:
    "RegKnot was built by mariners, for mariners. 10% of every dollar of revenue goes to organizations supporting maritime communities.",
  path: '/giving',
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
