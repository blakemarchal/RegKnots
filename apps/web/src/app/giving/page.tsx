'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CompassRose } from '@/components/CompassRose'
import { AppHeader } from '@/components/AppHeader'
import { useAuthStore } from '@/lib/auth'
import { apiRequest } from '@/lib/api'

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

function CharitySuggestionSection() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [suggestionOpen, setSuggestionOpen] = useState(false)
  const [orgName, setOrgName] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<{ ok: boolean; msg: string } | null>(null)

  async function handleSubmitSuggestion() {
    setSubmitting(true)
    setSubmitResult(null)
    try {
      await apiRequest('/support/charity-suggestion', {
        method: 'POST',
        body: JSON.stringify({ org_name: orgName.trim(), reason: reason.trim() }),
      })
      setSubmitResult({ ok: true, msg: 'Thank you! Your suggestion has been received.' })
      setOrgName('')
      setReason('')
      setTimeout(() => { setSuggestionOpen(false); setSubmitResult(null) }, 3000)
    } catch {
      setSubmitResult({ ok: false, msg: 'Something went wrong. Please try again.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="px-5 md:px-10 pb-20">
      <div className="max-w-xl mx-auto text-center">
        <h2 className="font-display font-black text-[#f0ece4] text-xl md:text-2xl mb-3">
          Know a Cause That Belongs Here?
        </h2>
        <p className="font-mono text-sm text-[#6b7594] mb-6 leading-relaxed">
          We review charity partner suggestions annually. If you know an organization making
          a difference in maritime communities, we&apos;d love to hear about it.
        </p>

        {!isAuthenticated ? (
          <>
            <Link
              href="/login"
              className="inline-block font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
                hover:brightness-110 transition-[filter] duration-150"
            >
              Sign In to Suggest a Charity
            </Link>
            <p className="font-mono text-xs text-[#6b7594] mt-4">
              We review all suggestions and announce new partners annually.
            </p>
          </>
        ) : !suggestionOpen ? (
          <>
            <button
              onClick={() => setSuggestionOpen(true)}
              className="inline-block font-mono font-bold text-sm uppercase tracking-wider
                bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
                hover:brightness-110 transition-[filter] duration-150"
            >
              Suggest a Charity
            </button>
            <p className="font-mono text-xs text-[#6b7594] mt-4">
              We review all suggestions and announce new partners annually.
            </p>
          </>
        ) : (
          <div className="bg-[#111827] rounded-xl border border-white/8 p-6 text-left space-y-4">
            <div>
              <label className="block font-mono text-xs text-[#6b7594] mb-1.5">Organization name *</label>
              <input
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
                  font-mono text-sm text-[#f0ece4] placeholder:text-[#6b7594]/50
                  focus:outline-none focus:border-[#2dd4bf]/50 transition-colors"
                placeholder="e.g. Mercy Ships"
              />
            </div>
            <div>
              <label className="block font-mono text-xs text-[#6b7594] mb-1.5">
                Why should RegKnot partner with this organization? *
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                className="w-full bg-[#0d1225] border border-white/10 rounded-lg px-3 py-2
                  font-mono text-sm text-[#f0ece4] placeholder:text-[#6b7594]/50
                  focus:outline-none focus:border-[#2dd4bf]/50 transition-colors resize-none"
                placeholder="Tell us why this charity should be a RegKnot partner..."
              />
            </div>
            {submitResult && (
              <p className={`font-mono text-xs ${submitResult.ok ? 'text-green-400' : 'text-red-400'}`}>
                {submitResult.msg}
              </p>
            )}
            <div className="flex gap-3">
              <button
                onClick={handleSubmitSuggestion}
                disabled={submitting || !orgName.trim() || !reason.trim()}
                className="flex-1 font-mono font-bold text-sm uppercase tracking-wider
                  bg-[#2dd4bf] text-[#0a0e1a] rounded-xl px-6 py-3
                  hover:brightness-110 transition-[filter] duration-150
                  disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Sending...' : 'Submit'}
              </button>
              <button
                onClick={() => { setSuggestionOpen(false); setSubmitResult(null) }}
                className="font-mono text-sm text-[#6b7594] hover:text-[#f0ece4]
                  transition-colors duration-150 px-4"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

export default function GivingPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col">

      {/* ── Nav ───────────────────────────────────────────────────────── */}
      {isAuthenticated ? (
        <AppHeader title="Giving Back" />
      ) : (
        <nav className="fixed top-0 inset-x-0 z-40 flex items-center justify-between
          px-5 md:px-10 py-4 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
          <Link href="/landing" className="flex items-center gap-2">
            <CompassRose className="w-5 h-5 text-[#2dd4bf]" />
            <span className="font-display text-xl font-bold text-[#f0ece4] tracking-widest uppercase">
              RegKnot
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
      )}

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className={`flex flex-col items-center justify-center px-5 pb-16 text-center ${isAuthenticated ? 'pt-10' : 'pt-32'}`}>
        <CompassRose className="w-12 h-12 text-[#2dd4bf] mb-6 opacity-60" />

        <h1 className="font-display font-black text-[#f0ece4] text-3xl md:text-5xl tracking-tight mb-4">
          Every Dollar Has a Purpose
        </h1>
        <p className="font-display font-bold text-[#2dd4bf] text-lg md:text-xl mb-8">
          10% of all revenue goes directly to charity
        </p>
        <p className="font-mono text-sm text-[#6b7594] max-w-xl leading-relaxed">
          RegKnot was built by mariners, for mariners. We believe the tools you trust
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
      <CharitySuggestionSection />

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <footer className="border-t border-white/8 px-5 md:px-10 py-8 mt-auto">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center
          justify-between gap-4 text-center md:text-left">
          <div className="flex items-center gap-2">
            <CompassRose className="w-4 h-4 text-[#2dd4bf]/60" />
            <span className="font-display text-base font-bold text-[#f0ece4]/60 tracking-widest uppercase">
              RegKnot
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
            <Link href={isAuthenticated ? '/' : '/landing'} className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors">
              Home
            </Link>
            <p className="font-mono text-xs text-[#6b7594]">
              &copy; 2026 RegKnot
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
