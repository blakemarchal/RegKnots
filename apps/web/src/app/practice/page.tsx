// 2026-10-02 — /practice: free USCG exam practice, public, no sign-up.
//
// The questions are the National Maritime Center's published sample exams
// (public domain), parsed into exam_questions by
// packages/ingest/ingest/exam_questions.py and served by the API's
// /practice/topics and /practice/quiz. Questions that need an illustration
// or a reference book are not served. Many answers carry the nearest corpus
// section, precomputed, so the page costs nothing per view.
//
// A server page so the metadata and the hero render without JavaScript; the
// quiz itself is the client component below. Sign-up links carry
// src=practice, which /admin counts under Growth.

import type { Metadata } from 'next'
import Link from 'next/link'
import { OG_IMAGE } from '@/lib/seo'
import { LandingFooter } from '@/components/marketing/LandingFooter'
import { PracticeQuiz } from './PracticeQuiz'
import { signupHref } from './links'
import { SiteNav } from '@/components/marketing/SiteNav'

const TITLE = 'Free USCG License Exam Practice Questions | RegKnot'
const DESCRIPTION =
  'Practice for your U.S. Coast Guard merchant mariner exam for free. Official NMC sample questions ' +
  'for Rules of the Road, deck general, navigation, stability, engineering, QMED and endorsements, ' +
  'with instant answers. No sign-up.'

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: 'https://regknots.com/practice' },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: 'https://regknots.com/practice',
    siteName: 'RegKnot',
    type: 'website',
    images: [OG_IMAGE],
  },
  twitter: { card: 'summary_large_image', title: TITLE, description: DESCRIPTION, images: [OG_IMAGE.url] },
}

const ABOUT = [
  {
    title: 'Where the questions come from',
    body:
      'Every question is from the U.S. Coast Guard National Maritime Center’s published sample ' +
      'exams, with the NMC’s answer key. Questions that need an illustration, a chart or a ' +
      'reference book are left out for now.',
  },
  {
    title: 'The rule behind the answer',
    body:
      'Where an answer comes from a regulation, we show the closest section: 46 CFR, 33 CFR, the ' +
      'COLREGs, STCW and Coast Guard guidance. RegKnot can then answer follow-up questions about it, ' +
      'with citations.',
  },
  {
    title: 'Independent',
    body:
      'RegKnot is not affiliated with the U.S. Coast Guard or the National Maritime Center. A practice ' +
      'score does not predict your exam result; check the NMC for current exam requirements.',
  },
]

export default function PracticePage() {
  return (
    <div className="min-h-screen bg-[#0a0e1a] overflow-x-hidden">
      {/* 2026-10-16 UI pass — the shared site bar (components/marketing/SiteNav). */}
      <SiteNav signupHref={signupHref('nav')} />

      <main>
        <section className="relative px-5 text-center pt-28 pb-8 md:pt-32 md:pb-10">
          <div className="absolute inset-0 pointer-events-none"
            style={{
              backgroundImage: `
                repeating-linear-gradient(0deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px),
                repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(45,212,191,0.025) 47px, rgba(45,212,191,0.025) 48px)
              `,
            }}
          />
          <div className="relative z-10 max-w-3xl mx-auto">
            <div className="inline-flex items-center gap-2 mb-6 px-3 py-1.5 rounded-full
              bg-[#2dd4bf]/10 border border-[#2dd4bf]/30">
              <span className="font-mono text-xs uppercase tracking-wider text-[#2dd4bf]">
                Free &middot; No sign-up
              </span>
            </div>
            <h1 className="font-display font-black text-[#f0ece4] leading-tight text-[clamp(34px,7vw,60px)] mb-5">
              USCG exam practice.<br />
              <span className="text-[#2dd4bf]">The official questions, free.</span>
            </h1>
            <p className="font-mono text-base md:text-lg text-[#6b7594] max-w-xl mx-auto leading-relaxed">
              Pick a topic and take 10 questions from the National Maritime Center&apos;s sample exams:
              Rules of the Road, deck general, navigation, stability, engineering, QMED and the
              endorsements. Where an answer comes from a regulation, we show you which one.
            </p>
          </div>
        </section>

        <PracticeQuiz />

        <section className="px-5 md:px-10 pb-16 md:pb-20">
          <div className="max-w-5xl mx-auto grid gap-4 md:grid-cols-3">
            {ABOUT.map((a) => (
              <article key={a.title} className="rounded-xl border border-white/8 bg-[#111827] p-5">
                <h2 className="font-display text-base font-bold text-[#2dd4bf] tracking-wide mb-2">{a.title}</h2>
                <p className="font-mono text-sm text-[#f0ece4]/75 leading-relaxed">{a.body}</p>
              </article>
            ))}
          </div>
        </section>
      </main>

      <LandingFooter />
    </div>
  )
}
