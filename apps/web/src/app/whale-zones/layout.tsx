// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "North Atlantic Right Whale Speed Zones Map",
  description:
    "Map of NOAA Fisheries Seasonal Management Areas for North Atlantic right whales (50 CFR 224.105): where the 10-knot speed rule applies and which zones are active on any date.",
  path: '/whale-zones',
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
