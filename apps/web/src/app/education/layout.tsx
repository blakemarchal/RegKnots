// 2026-10-14 — search metadata for this client page (lib/seo.ts).

import type { Metadata } from 'next'
import { pageMetadata } from '@/lib/seo'

export const metadata: Metadata = pageMetadata({
  title: "USCG Exam Study Tools for Cadets and Instructors",
  description:
    "Generate USCG-format quizzes and study guides on demand. Every answer cites a real regulation, checked against 46 CFR, 33 CFR, COLREGs, SOLAS and STCW.",
  path: '/education',
})

export default function Layout({ children }: { children: React.ReactNode }) {
  return children
}
