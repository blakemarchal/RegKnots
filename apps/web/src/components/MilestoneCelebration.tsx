'use client'

// Sprint D6.10 — admin paid-user milestone celebration.
//
// Watches AdminStats.paid_users_alltime and fires a one-shot confetti
// burst + flavor toast the first time the count crosses a milestone.
// Per-device gating via localStorage so each admin sees each milestone
// exactly once on their own machine.
//
// Design choices (see prior thread):
//  - Cumulative count (never decreases): the count on the backend is
//    inclusive of paused/past-due. If it dips below a celebrated
//    threshold, we don't re-fire — `lastMilestoneSeen` is the highest
//    threshold ever celebrated, never decremented.
//  - On first-ever load, fire only the HIGHEST threshold ≤ current
//    count, not every threshold below it. Avoids a 5-burst spam if a
//    new admin loads the page with the count already at 100.
//  - No sound (toggle complexity, surprise-blast risk on quiet
//    workplaces). Animation only.
//  - No blocking modal. Toast auto-dismisses in 6s; user can dismiss
//    earlier by clicking the X.

import { useEffect, useRef, useState } from 'react'
import confetti from 'canvas-confetti'

const STORAGE_KEY = 'regknot_milestone_seen'

// Each entry: count threshold + flavor copy. Tuned to be celebratory
// but not saccharine; tone matches the rest of the brand voice.
//
// Sprint D6.92 — every paid signup #1 through #10 fires its own
// celebration (Blake's call: "I'd actually like the confetti for every
// paid sign up until 10, then back to our original system"). After 10,
// the original milestone cadence (25, 50, 100, 250, ...) resumes.
// Rationale: the first 10 paying users are the highest-signal validation
// in the company's life; each one deserves an earned beat. Past 10 the
// noise-to-signal of "another one" drops, and the larger thresholds do
// the celebrating.
const MILESTONES: { count: number; title: string; body: string }[] = [
  { count:     1, title: 'Paid user #1',
    body: 'The first one. There is only one #1 — and you got there. Pour something.' },
  { count:     2, title: 'Paid user #2',
    body: 'Two paying mariners. Whoever signed up second saw what #1 saw. The signal isn’t a coincidence.' },
  { count:     3, title: 'Paid user #3',
    body: 'Three. The first ones aren’t a fluke anymore. Whatever happened to draw them in, it’s repeatable.' },
  { count:     4, title: 'Paid user #4',
    body: 'Four. Past the first hand of fingers. Pattern turning into traction.' },
  { count:     5, title: 'Five paying mariners',
    body: 'Five. The hardest five. Word of mouth is the only marketing channel that matters.' },
  { count:     6, title: 'Paid user #6',
    body: 'Six. The first five proved a thing exists. The sixth proves it’s not just early adopters.' },
  { count:     7, title: 'Paid user #7',
    body: 'Seven mariners trust this. A standing watch rotation — paid.' },
  { count:     8, title: 'Paid user #8',
    body: 'Eight. Closing in on double digits. Whatever’s working, keep doing it.' },
  { count:     9, title: 'Paid user #9',
    body: 'Nine. One short of the badge. The next one is the milestone — bring it home.' },
  { count:    10, title: 'Double digits',
    body: 'RegKnot is officially A Thing. People you don’t know are paying you for it.' },
  { count:    25, title: 'A quarter-hundred',
    body: '25 paying captains and mates. The product is real. The business is real.' },
  { count:    50, title: 'Half a hundred',
    body: 'Halfway to triple digits. Whatever you’re doing, do more of it.' },
  { count:   100, title: 'Triple digits',
    body: 'One hundred. This is no longer a side project. Someone owes you a round.' },
  { count:   250, title: '250 paying mariners',
    body: 'A vessel’s crew, several times over. Names you don’t recognize, in ports you’ve never been to.' },
  { count:   500, title: 'Half a thousand',
    body: 'Five hundred mariners trust this. Take a day. Don’t answer Slack tomorrow.' },
  { count:  1000, title: 'Four digits',
    body: '1,000. RegKnot is now a small fleet. Take a real day off. Two days.' },
  { count:  2500, title: '2,500',
    body: 'Twenty-five hundred. Fleet operators. Hire someone if you haven’t already.' },
  { count:  5000, title: 'Five thousand',
    body: 'Five thousand. You are now competing with the established players. Be that.' },
  { count: 10000, title: 'Ten thousand mariners',
    body: 'Ten thousand. We can stop counting now. Send the team somewhere with a beach.' },
]

interface Props {
  paidUsersAlltime: number | null
}

export function MilestoneCelebration({ paidUsersAlltime }: Props) {
  const [showing, setShowing] = useState<{ title: string; body: string } | null>(null)
  // Track last fire to dedup if /admin/stats polls before component
  // unmounts after a celebration fires (the count won't change but
  // useEffect's dependency comparison + the stored milestone guard
  // both prevent re-fire).
  const fireGuard = useRef(false)

  useEffect(() => {
    if (paidUsersAlltime == null) return
    if (fireGuard.current) return

    let lastSeen = 0
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      lastSeen = raw ? parseInt(raw, 10) || 0 : 0
    } catch {
      // localStorage unavailable — bail. The celebration is a delight
      // not a feature; don't error if private-browsing or SSR fallback.
      return
    }

    // Find the HIGHEST threshold not yet celebrated and ≤ current count.
    // If three milestones cross simultaneously (e.g., admin opens the
    // page on a pre-existing count of 250 with no prior milestones
    // seen), fire only #250 — not #1, #5, #10, ..., #250.
    const eligible = MILESTONES
      .filter((m) => m.count > lastSeen && m.count <= paidUsersAlltime)
      .sort((a, b) => b.count - a.count)
    const next = eligible[0]
    if (!next) return

    fireGuard.current = true
    setShowing({ title: next.title, body: next.body })
    try {
      localStorage.setItem(STORAGE_KEY, String(next.count))
    } catch { /* see above */ }

    // Burst confetti from both sides — feels more "filling the room"
    // than a single center burst.
    const fire = (originX: number) => {
      confetti({
        particleCount: 80,
        spread: 70,
        startVelocity: 45,
        origin: { x: originX, y: 0.7 },
        colors: ['#2dd4bf', '#fbbf24', '#f0ece4', '#a78bfa'],
        disableForReducedMotion: true,
      })
    }
    fire(0.1)
    fire(0.9)
    // Second wave 250ms later so the burst has presence
    window.setTimeout(() => { fire(0.5) }, 250)

    // Sprint D6.92 — auto-dismiss bumped 6s → 15s. Blake reported the
    // 6s window was too tight to read the flavor copy in a real
    // workflow (he caught Nate's #1 celebration but the toast cleared
    // before he finished reading). 15s gives a leisurely read without
    // making the toast feel sticky; the manual × dismiss is still
    // wired for an admin who wants to clear it sooner.
    const dismissTimer = window.setTimeout(() => setShowing(null), 15000)
    return () => window.clearTimeout(dismissTimer)
  }, [paidUsersAlltime])

  if (!showing) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-20 left-1/2 -translate-x-1/2 z-50
        max-w-md w-[calc(100%-2rem)] pointer-events-auto
        rounded-2xl border border-[#2dd4bf]/40 bg-[#0a0e1a]/95 backdrop-blur-md
        shadow-[0_0_60px_rgba(45,212,191,0.25)]
        px-5 py-4 flex items-start gap-4
        animate-[milestoneIn_0.5s_cubic-bezier(0.34,1.56,0.64,1)]"
    >
      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[#2dd4bf]/15
        border border-[#2dd4bf]/40 flex items-center justify-center text-2xl">
        🎉
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-display text-lg font-bold text-[#2dd4bf] tracking-wide leading-tight">
          {showing.title}
        </p>
        <p className="font-mono text-xs text-[#f0ece4]/80 mt-1.5 leading-relaxed">
          {showing.body}
        </p>
      </div>
      <button
        onClick={() => setShowing(null)}
        aria-label="Dismiss"
        className="flex-shrink-0 text-[#6b7594] hover:text-[#f0ece4] transition-colors text-lg leading-none px-1"
      >
        ×
      </button>
    </div>
  )
}
