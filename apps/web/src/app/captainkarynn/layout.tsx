// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { noindexMetadata } from '@/lib/seo'

export const metadata: Metadata = noindexMetadata("Welcome Aboard")

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
