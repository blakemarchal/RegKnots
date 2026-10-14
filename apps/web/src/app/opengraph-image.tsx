// 2026-10-14 — the share card for links to regknots.com (1200x630), built
// once at build time from the brand mark in public/brand.

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { ImageResponse } from 'next/og'

export const alt = 'RegKnot: maritime compliance answers, cited to the regulation'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default async function OpengraphImage() {
  const mark = await readFile(join(process.cwd(), 'public/brand/logo-mark-teal-transparent.png'))
  const src = `data:image/png;base64,${mark.toString('base64')}`
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center',
          padding: '72px 88px', background: '#0a0e1a', color: '#f0ece4',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} width={120} height={120} alt="" />
          <div style={{ fontSize: 76, fontWeight: 800, letterSpacing: -1 }}>RegKnot</div>
        </div>
        <div style={{ marginTop: 44, fontSize: 52, fontWeight: 700, lineHeight: 1.15, maxWidth: 1000 }}>
          Maritime compliance answers, cited to the regulation.
        </div>
        <div style={{ marginTop: 28, fontSize: 30, color: '#2dd4bf' }}>
          46 &amp; 33 CFR · USCG NVICs · SOLAS · MARPOL · STCW · COLREGs
        </div>
      </div>
    ),
    size,
  )
}
