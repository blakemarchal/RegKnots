import type { Metadata, Viewport } from 'next'
import { Barlow_Condensed, IBM_Plex_Mono } from 'next/font/google'
import { Providers } from '@/components/Providers'
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE, OG_IMAGE, SITE_NAME, SITE_URL } from '@/lib/seo'
import './globals.css'

const barlow = Barlow_Condensed({
  subsets: ['latin'],
  weight: ['600', '700'],
  variable: '--font-barlow',
  display: 'swap',
})

const ibm = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-ibm',
  display: 'swap',
})

// 2026-10-14 — search basics: metadataBase + a title template, so a page's
// title reads "<page> | RegKnot"; Open Graph defaults and the share image
// (opengraph-image.tsx); search-console verification tags when their env vars
// are set at build time. Per-page metadata uses pageMetadata() in lib/seo.ts.
const googleVerification = process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION
const bingVerification = process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: DEFAULT_TITLE, template: `%s | ${SITE_NAME}` },
  description: DEFAULT_DESCRIPTION,
  applicationName: SITE_NAME,
  openGraph: {
    siteName: SITE_NAME,
    type: 'website',
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    images: [OG_IMAGE],
  },
  twitter: { card: 'summary_large_image', title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION },
  ...(googleVerification || bingVerification
    ? {
        verification: {
          ...(googleVerification ? { google: googleVerification } : {}),
          ...(bingVerification ? { other: { 'msvalidate.01': bingVerification } } : {}),
        },
      }
    : {}),
  manifest: '/manifest.json',
  icons: {
    icon: [
      { url: '/favicon.svg', type: 'image/svg+xml' },
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
    ],
    apple: [
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
    ],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'RegKnot',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // 2026-07-19 trust pack — maximumScale:1 removed. Pinch-zoom lockout
  // is a WCAG 1.4.4 failure and hostile to anyone reading dense reg
  // text on a phone. iOS input-focus auto-zoom (the usual reason for
  // the lock) is already prevented by 16px+ input font sizes.
  themeColor: '#0a0e1a',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${ibm.variable}`}>
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
