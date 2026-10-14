// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "What's in the Knowledge Base",
  description:
    "Every regulation source RegKnot answers from, by where it sits in the chain of authority: U.S. statutes and CFR, USCG guidance, IMO conventions and codes, and flag-state rules.",
  path: '/coverage',
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
