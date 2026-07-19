import type { Metadata, Viewport } from 'next'
import { Barlow_Condensed, IBM_Plex_Mono } from 'next/font/google'
import { Providers } from '@/components/Providers'
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

export const metadata: Metadata = {
  title: 'RegKnot',
  description: 'AI-powered maritime compliance assistant. Cited answers from CFR, SOLAS, STCW, ISM Code, COLREGs, ERG, and USCG guidance.',
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
