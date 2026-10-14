// 2026-10-14 — robots.txt. The app behind sign-in, the API and one-time
// links (invites, shared answers, resets) are kept out; public pages and the
// sitemap are in.

import type { MetadataRoute } from 'next'
import { SITE_URL } from '@/lib/seo'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: [
          '/api/', '/admin', '/account', '/brand', '/invite/', '/shared/', '/onboarding', '/welcome',
          '/reset-password', '/verify-email', '/forgot-password', '/subscribe', '/history', '/log',
          '/workspaces', '/study', '/credentials', '/certificates', '/sea-time', '/sea-service-letter',
          '/psc-checklist', '/vessel-dossier', '/support',
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  }
}
