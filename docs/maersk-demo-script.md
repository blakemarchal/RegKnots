# Maersk demo script — shore-side compliance pitch (15 min)

*2026-07-19. For Karynn (+ Blake on screen-share duty). Audience: a
shore-side compliance / vetting / marine-standards person — Nirmal's
world, not a deck officer's. Every beat below uses features live on
regknots.com today. Run it once end-to-end the day before; the demo
account should have the `shore_side_compliance` persona set and a
Wheelhouse workspace with 2–3 vessels + a couple of crew records
seeded.*

---

## The through-line (say this in the first 60 seconds)

> "Your team answers regulatory questions all day — for vetting prep,
> PSC calls, charterer questionnaires. Today that's a person digging
> through PDFs, and the answer dies in an email. RegKnots gives you the
> answer in seconds **with the citation verified against the primary
> source**, and everything your team asks becomes an auditable,
> exportable record."

Three beats: **trust the answer → fleet posture on demand → the team's
work is a record.**

## Beat 1 — A real vetting question, answered with receipts (4 min)

1. Open chat. Ask: **"What does SIRE 2.0 ask about mooring equipment
   condition?"** (Nirmal-shaped; SIRE 2.0 Question Library is in
   corpus.)
2. While it streams, say: answers stream in seconds, and every citation
   chip you'll see was **resolved against the primary-source text
   before display** — the teal chips are corpus-verified, the green
   badge counts them.
3. Tap a citation chip → the actual regulation text opens. "You are one
   tap from the source, always."
4. Hit **Export answer (PDF)** → a dated, cited, letterheaded artifact.
   "This is what you attach to the vetting response or drop in the
   audit file."
5. Follow up with **"MLC 2006 rest hours — what are the minimums?"**
   to show conversational depth across conventions (MLC ingested).

*If asked "what if it doesn't know":* ask something obscure — the
answer hedges honestly and the amber web-reference card is visually
segregated from verified corpus answers. "We never dress up a guess as
a citation."

## Beat 2 — Fleet posture on demand (4 min)

1. Open the workspace (Wheelhouse) → **Fleet Audit Readiness** →
   *Assess readiness*.
2. It fans out across every vessel and crew member in the workspace:
   one 0–100 score, findings ranked critical → warning → info, each
   naming who/what is affected and the governing citation.
3. **Export report (PDF)** — "Monday-morning fleet posture, one click.
   This is the pre-PSC, pre-vetting self-check."
4. Point at a specific finding: "It's anchored to the actual stored
   records — expirations, missing docs — not generic advice."

## Beat 3 — The team's work is a record (3 min)

1. Same workspace page → **Team activity log**: who asked what, when,
   with the citations behind each answer.
2. **Export CSV** — "When an auditor asks *how does your team verify
   regulatory questions*, this is the answer. Diligence, documented."
3. Mention: chats in a workspace are shared — a question answered once
   is answered for the whole team.

## Beat 4 — The live-data kicker (2 min)

1. In chat: **"Which right-whale zones are active right now?"** — the
   answer uses TODAY's NOAA SMA calendar (50 CFR 224.105) and links the
   live map at /whale-zones.
2. Then: **"What's changed in the regs this month?"** — the answer
   summarizes actual corpus updates with dates. "The corpus refreshes
   weekly on its own; your team doesn't chase Federal Register notices."

## Close (1 min)

> "Everything you saw is live today. We built the corpus a captain
> trusts — Karynn sails on it — and the workflow a compliance
> department needs: verified answers, fleet posture, and an audit
> trail. We'd like to run a 30-day pilot with one of your vetting or
> marine-standards teams."

**Ask:** one team, 30 days, we onboard them personally.

---

## Prep checklist (Blake, day before)

- [ ] Demo account: persona `shore_side_compliance`, Precision Mode ON
      (account page) — stricter refusal posture reads well in front of
      compliance people.
- [ ] Workspace seeded: 2–3 vessels with docs, 2 crew members with
      credentials (one with an expiry inside 90 days so the fleet
      assessment has a real warning finding to show).
- [ ] Ask the four scripted questions once so answers are warm and you
      know their shape.
- [ ] `scripts/smoke.sh` green that morning.
- [ ] Backup fallback: screenshots of each beat in a folder in case of
      conference-room Wi-Fi.

## Objection quick-answers

- **"Is the AI making things up?"** — Citations are verified against the
  primary source before display; unverifiable citations are stripped;
  hedges are visually segregated (amber) from verified answers (teal).
  Precision Mode goes further and refuses rather than speculates.
- **"Our data?"** — Your workspace's questions and records are yours;
  export everything (CSV/PDF) anytime. No training on your data.
- **"What corpus?"** — CFR, SOLAS/MARPOL/MLC + 10 IMO codes, SIRE 2.0
  question library, COSWP, PSC regimes, 9 flag states, NMC/USCG
  policy — refreshed on a weekly cadence (see /corpus in the footer,
  or docs/corpus-status.md for the full inventory).
- **"Price?"** — Pilot free, 30 days, one team. Then per-seat
  Wheelhouse pricing; enterprise agreement when you want SSO and org
  rollout. (Blake fields specifics.)
