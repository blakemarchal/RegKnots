import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'

const CHARITIES = [
  {
    name: 'Mercy Ships',
    tag: 'Maritime',
    description:
      'Mercy Ships operates the world\u2019s largest civilian hospital ships, bringing free surgeries and medical care to communities where healthcare is nearly nonexistent. A floating testament to what the maritime industry can accomplish beyond commerce.',
    url: 'https://www.mercyships.org/',
    linkText: 'Visit mercyships.org',
  },
  {
    name: 'Waves of Impact',
    tag: 'Community',
    description:
      'Waves of Impact uses surf therapy and ocean-based programs to support veterans, first responders, and at-risk youth. Co-founder Karynn serves as an active volunteer \u2014 this is personal, not performative.',
    url: 'https://www.wavesofimpact.com/',
    linkText: 'Visit wavesofimpact.com',
  },
  {
    name: 'Elijah Rising',
    tag: 'Houston \u00b7 Anti-Trafficking',
    description:
      'Based in Houston, Elijah Rising fights human trafficking \u2014 much of which flows through the Port of Houston. As a Houston-based company, supporting the fight against trafficking in our own backyard is a responsibility we take seriously.',
    url: 'https://elijahrising.org/',
    linkText: 'Visit elijahrising.org',
  },
]

export default function GivingPage() {
  return (
    <div className="min-h-screen bg-[#0a0e1a]">

      {/* ── Nav ───────────────────────────────────────────────────────── */}
      <nav className="fixed top-0 inset-x-0 z-40 flex items-center justify-between
        px-5 md:px-10 py-4 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
        <Link href="/landing" className="flex items-center gap-2">
          <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
          <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
            RegKnots
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <Link href="/login"
            className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4] transition-colors duration-150">
            Sign In
          </Link>
          <Link href="/register"
            className="font-mono text-sm font-bold text-[#0a0e1a] bg-[#2dd4bf]
              hover:brightness-110 transition-[filter] duration-150
              rounded-lg px-4 py-1.5">
            Get Access
          </Link>
        </div>
      </nav>

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className="flex flex-col items-center justify-center px-5 pt-32 pb-16 text-center">
        <CompassRose className="w-12 h-12 text-[#2dd4bf] mb-6 opacity-60" />

        <h1 className="font-display font-black text-[#f0ece4] text-3xl md:text-5xl tracking-tight mb-4">
          Every Dollar Has a Purpose
        </h1>
        <p className="font-display font-bold text-[#2dd4bf] text-lg md:text-xl mb-8">
          10% of all revenue goes directly to charity
        </p>
        <p className="font-mono text-sm text-[#6b7594] max-w-xl leading-relaxed">
          RegKnots was built by mariners, for mariners. We believe the tools you trust
          should reflect the values you carry. That&apos;s why 10% of every dollar &mdash; not profit,
          revenue &mdash; goes directly to organizations making a real difference in maritime
          communities and beyond.
        </p>
        <p className="font-mono text-sm text-[#6b7594] mt-4 italic">
          &mdash; Blake &amp; Karynn Marchal, Co-founders
        </p>
      </section>

      {/* ── Charity cards ─────────────────────────────────────────────── */}
      <section className="px-5 md:px-10 pb-20">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display font-black text-[#f0ece4] text-2xl md:text-3xl mb-8 text-center">
            Our Partners
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {CHARITIES.map((c) => (
              <div
                key={c.name}
                className="bg-[#111827] rounded-xl border border-white/8 p-6 flex flex-col"
              >
                <h3 className="font-display text-lg font-bold text-[#f0ece4] mb-2">{c.name}</h3>
                <span className="inline-block self-start font-mono text-[10px] font-bold text-[#2dd4bf]
                  bg-[#2dd4bf]/10 border border-[#2dd4bf]/30 rounded px-2 py-0.5
                  uppercase tracking-wider mb-4">
                  {c.tag}
                </span>
                <p className="font-mono text-sm text-[#6b7594] leading-relaxed flex-1 mb-4">
                  {c.description}
                </p>
                <a
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-sm text-[#2dd4bf] hover:underline"
                >
                  {c.linkText} &rarr;
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Suggest a charity ─────────────────────────────────────────── */}
      <section className="px-5 md:px-10 pb-20">
        <div className="max-w-xl mx-auto text-center">
          <h2 className="font-display font-black text-[#f0ece4] text-xl md:text-2xl mb-3">
            Know a Cause That Belongs Here?
          </h2>
          <p className="font-mono text-sm text-[#6b7594] mb-6 leading-relaxed">
            We review charity partner suggestions annually. If you know an organization making
            a difference in maritime communities, we&apos;d love to hear about it.
          </p>
          <a
            href="mailto:hello@regknots.com?subject=Charity%20Suggestion%20for%20RegKnots"
            className="inline-block font-mono font-bold text-sm uppercase tracking-wider
              bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
              hover:brightness-110 transition-[filter] duration-150"
          >
            Suggest a Charity
          </a>
          <p className="font-mono text-xs text-[#6b7594] mt-4">
            We review all suggestions and announce new partners annually.
          </p>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <footer className="border-t border-white/8 px-5 md:px-10 py-8">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center
          justify-between gap-4 text-center md:text-left">
          <div className="flex items-center gap-2">
            <CompassRose className="w-4 h-4 text-[#2dd4bf]/60" />
            <span className="font-display text-base font-bold text-[#f0ece4]/60 tracking-widest uppercase">
              RegKnots
            </span>
          </div>
          <p className="font-mono text-xs text-[#6b7594]">
            Navigation aid only &mdash; not legal advice
          </p>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Terms
            </Link>
            <Link href="/privacy" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Privacy
            </Link>
            <Link href="/landing" className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Home
            </Link>
            <p className="font-mono text-xs text-[#6b7594]">
              &copy; 2026 RegKnots
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
