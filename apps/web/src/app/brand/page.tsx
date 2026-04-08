/* Internal brand asset preview — visit /brand to verify all variants. */

interface Asset {
  name: string
  file: string
  ext: 'svg' | 'png'
  bg: 'dark' | 'light' | 'check'
}

const ASSETS: Asset[] = [
  // Logo marks
  { name: 'Mark — Teal', file: 'logo-mark-teal-transparent', ext: 'svg', bg: 'dark' },
  { name: 'Mark — Navy', file: 'logo-mark-navy-transparent', ext: 'svg', bg: 'light' },
  { name: 'Mark — White', file: 'logo-mark-white-transparent', ext: 'svg', bg: 'check' },
  // Full horizontal
  { name: 'Full — Dark BG', file: 'logo-full-dark', ext: 'svg', bg: 'dark' },
  { name: 'Full — Light BG', file: 'logo-full-light', ext: 'svg', bg: 'light' },
  { name: 'Full — White (photo)', file: 'logo-full-white', ext: 'svg', bg: 'check' },
  // Tagline
  { name: 'Tagline — Dark BG', file: 'logo-tagline-dark', ext: 'svg', bg: 'dark' },
  { name: 'Tagline — Light BG', file: 'logo-tagline-light', ext: 'svg', bg: 'light' },
  // Stacked
  { name: 'Stacked — Dark BG', file: 'logo-stacked-dark', ext: 'svg', bg: 'dark' },
  { name: 'Stacked — Light BG', file: 'logo-stacked-light', ext: 'svg', bg: 'light' },
]

const SOCIAL = [
  { name: 'OG Image (1200×630)', file: 'og-image' },
  { name: 'Twitter Card (1200×600)', file: 'twitter-card' },
]

const BG_STYLE: Record<Asset['bg'], string> = {
  dark: 'bg-[#0a0e1a]',
  light: 'bg-[#f0ece4]',
  check:
    'bg-[length:20px_20px] bg-[image:linear-gradient(45deg,#1a2030_25%,transparent_25%),linear-gradient(-45deg,#1a2030_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#1a2030_75%),linear-gradient(-45deg,transparent_75%,#1a2030_75%)] bg-[#0f1525]',
}

export default function BrandPage() {
  return (
    <div className="min-h-screen bg-[#0a0e1a] text-[#f0ece4] py-10 px-6">
      <div className="max-w-5xl mx-auto">
        <h1 className="font-display text-4xl font-bold tracking-wide mb-2">RegKnot Brand Assets</h1>
        <p className="font-mono text-sm text-[#6b7594] mb-10">
          Internal reference. All files live in <code className="text-[#2dd4bf]">/brand/</code>.
        </p>

        <section className="mb-12">
          <h2 className="font-display text-xl font-bold tracking-wide mb-4 text-[#2dd4bf]">Logos</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {ASSETS.map((a) => (
              <div key={a.file} className="rounded-xl border border-white/8 overflow-hidden">
                <div className={`${BG_STYLE[a.bg]} px-6 py-8 flex items-center justify-center min-h-[180px]`}>
                  <img
                    src={`/brand/${a.file}.${a.ext}`}
                    alt={a.name}
                    className="max-h-32 w-auto"
                  />
                </div>
                <div className="bg-[#111827] px-4 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-xs text-[#f0ece4]/85 truncate">{a.name}</p>
                    <p className="font-mono text-[10px] text-[#6b7594] truncate">{a.file}</p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <a
                      href={`/brand/${a.file}.svg`}
                      download
                      className="font-mono text-[10px] font-bold uppercase tracking-wider
                        px-2 py-1 rounded border border-[#2dd4bf]/30 text-[#2dd4bf]/80
                        hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10 transition-colors"
                    >
                      SVG
                    </a>
                    <a
                      href={`/brand/${a.file}.png`}
                      download
                      className="font-mono text-[10px] font-bold uppercase tracking-wider
                        px-2 py-1 rounded border border-[#2dd4bf]/30 text-[#2dd4bf]/80
                        hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10 transition-colors"
                    >
                      PNG
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mb-12">
          <h2 className="font-display text-xl font-bold tracking-wide mb-4 text-[#2dd4bf]">Social</h2>
          <div className="grid grid-cols-1 gap-4">
            {SOCIAL.map((a) => (
              <div key={a.file} className="rounded-xl border border-white/8 overflow-hidden">
                <div className="bg-[#0a0e1a] px-6 py-6 flex items-center justify-center">
                  <img src={`/brand/${a.file}.png`} alt={a.name} className="max-w-full h-auto" />
                </div>
                <div className="bg-[#111827] px-4 py-3 flex items-center justify-between">
                  <p className="font-mono text-xs text-[#f0ece4]/85">{a.name}</p>
                  <a
                    href={`/brand/${a.file}.png`}
                    download
                    className="font-mono text-[10px] font-bold uppercase tracking-wider
                      px-2 py-1 rounded border border-[#2dd4bf]/30 text-[#2dd4bf]/80
                      hover:text-[#2dd4bf] hover:bg-[#2dd4bf]/10 transition-colors"
                  >
                    Download
                  </a>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="font-display text-xl font-bold tracking-wide mb-4 text-[#2dd4bf]">Color tokens</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { hex: '#0a0e1a', name: 'Navy' },
              { hex: '#2dd4bf', name: 'Teal' },
              { hex: '#f0ece4', name: 'Bone' },
              { hex: '#94a3b8', name: 'Tagline gray' },
            ].map((c) => (
              <div key={c.hex} className="rounded-xl border border-white/8 overflow-hidden">
                <div className="h-20" style={{ backgroundColor: c.hex }} />
                <div className="bg-[#111827] px-3 py-2">
                  <p className="font-mono text-xs text-[#f0ece4]/85">{c.name}</p>
                  <p className="font-mono text-[10px] text-[#6b7594]">{c.hex}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
