# RegKnot Update — What's New for Operators

**April 2026**

Karynn — here's what changed while you were out. Written so you can skim it, use it, and share it. Plain English, no engineer-speak.

---

## The one-line version

RegKnot went from *"great regulation lookup tool"* to *"daily operational companion that also knows about credential paperwork and what's happening on your waterway this week."*

## What got added to the knowledge base

We added ~**2,400 new chunks of USCG content** across three new data sources. For a sense of scale, before these additions the corpus was about 40,000 chunks covering CFR + international conventions. Now it's about 42,400, and the new 2,400 are the most operationally relevant of the whole set.

### 1. NMC Policy Letters — 13 documents

CG-MMC, CG-CVC, and CG-OES policy letters covering:

- ROUPV (Restricted Operator of Uninspected Passenger Vessels) endorsement rules
- Polar Code training requirements for deck officers
- Military sea service crediting toward MMC
- Medical certificate harmonization
- Liftboat-specific credential policy
- MMC renewal process interpretations

**Why it matters:** these are the interpretive documents the NMC actually applies when they review an application. Ask RegKnot "can I credit my Coast Guard Reserve time toward my MMC?" and it now has the actual policy letter to cite — not just the CFR section the policy letter interprets.

### 2. NMC Application Checklists — 6 documents

- The CG-719B Application Guide (step-by-step instructions for filling out the main MMC application)
- MCP-FM-NMC5-01 — MMC Renewal Application Checklist
- Application Acceptance Checklist
- Three more form-instruction guides

**Why it matters:** mariners filling out an MMC renewal or raise-of-grade application now have a companion that walks them through exactly what the NMC expects on each supporting document.

### 3. USCG GovDelivery Bulletins — 1,658 operational bulletins, 3 years of history

This is the big one. Think of this as "what the Coast Guard has been telling mariners in real time, filtered down to the operationally useful stuff." Includes:

- **263 Marine Safety Information Bulletins (MSIBs)** — port conditions, lock closures, waterway restrictions, high-water advisories, security zones, vessel safety alerts.
- **503 operational ALCOASTs and ACNs** — fire extinguisher recalls, enforcement campaigns, medical standards updates, color vision testing policy, environmental compliance notices.
- **884 navigation safety advisories** — Local Notice to Mariners releases, GPS operational advisories, VTS restrictions, aids-to-navigation status.
- A handful of NMC announcements (medical certificate backlog updates, new MMC format rollouts).

**How we filtered:** the raw GovDelivery feed is a firehose — maybe 15% regulatory content, 85% press releases / rescue reports / internal personnel matters. We now use Claude (the AI model) to classify every bulletin as regulatory-operational-content or not-regulatory, and only the first category gets added to the knowledge base. Cost us about $0.60 one time for the whole history. Result: the corpus doesn't get cluttered with "Coast Guard rescues 3 fishermen" news releases.

---

## What got better at finding answers

### Vocabulary enrichment

Every chunk of the new NMC + bulletin content has domain-relevant aliases attached to its title — things like `MMC`, `credential renewal`, `STCW endorsement`, `sea service crediting`, `MARSEC`, `port security`, `PSC campaign`, `medical certificate`. This is because mariners don't always phrase questions using the formal regulation language. You'd say "can I renew my MMC" not "application for credential continuation under 46 CFR 10.227." The aliases let the search engine find the right chunk either way.

### Retrieval precision

When you ask a credential question, RegKnot now tilts its search toward the NMC sources first. When you ask about port conditions, it tilts toward bulletins. When you ask about a specific rule number (like "NVIC 04-08" or "MSIB 168-22"), it recognizes that as a document identifier and pulls that specific document. Previously it was doing more generic vector similarity and could miss obvious matches.

### Tailored starter questions

The new-chat screen now suggests 4 questions relevant to the specific vessel on your account. Passenger vessel captain sees "What manning do I need for my route?" — Tanker captain sees "OPA 90 vessel response plan requirements" — Towing captain sees "Subchapter M TSMS audit prep." Not one-size-fits-all anymore.

---

## Impact on the "compliance tool" rating

Here's my honest assessment of what moved:

| Capability | Before | Now |
|---|---|---|
| Answer formal regulation questions (CFR, SOLAS, COLREGs) | Strong | Strong |
| Answer credential lifecycle questions (renewal, raise of grade, medical) | Weak — only had CFR Title 46 Parts 10-16. Missed NMC policy interpretation. | **Strong.** NVIC 04-08 medical guidance, all major NMC policy letters, application checklists. |
| Answer "what's happening on my waterway this week" | None — we had no operational bulletin data at all | **Available.** 263 MSIBs + 884 nav advisories spanning 2023-2026. |
| Answer "has the Coast Guard issued recall guidance for X equipment?" | None | **Available.** Fire extinguisher recalls, safety alerts, equipment defects are searchable. |
| Answer in real-time | Closer to static — our ingest runs weekly | Partial — the bulletin backfill is static at 3 years. Next priority is wiring up the live email feed so new bulletins appear within hours. |

Where we're not yet strong:
- **Live bulletin ingest is not on yet.** The 1,658 bulletins stop at the Wayback snapshot date — roughly end of March 2026 for most IDs. New bulletins issued this month aren't in yet. (Fix is queued — Priority 1.)
- **Retrieval still can't filter by "current" vs "expired" bulletins.** The data is captured but we don't yet suppress expired safety advisories at query time. (Also queued — Priority 1.)
- **CFR Title 50 (fisheries) still absent.** Pure commercial-fishing captains would miss this.

My read: this moves us from a **6/10** reference tool to an **8/10 daily companion** for mariners in the passenger/towing/offshore-supply segments. Still a 6/10 for pure commercial fishing until we add Title 50.

---

## Testing I need you to do

Try these real-world queries against regknots.com with your captain hat on. I want to know where the answers are wrong, vague, or surprisingly good. Flag anything that seems hallucinated — the new bulletin corpus especially is worth stress-testing.

### Credential lifecycle

1. *"What do I need to submit to renew my MMC?"*
2. *"Can I use my Navy sea service toward my MMC if I was a Coxswain?"*
3. *"What are the medical standards for an MMC if I have type 2 diabetes?"*
4. *"I'm upgrading from Mate 500 GRT to Master 1600 GRT. What does the NMC need to see?"*
5. *"What's the policy on Polar Code training for officers?"*
6. *"Can I get a restricted operator endorsement for a specific lake?"*

### Operational / bulletin-era

7. *"Are there any port conditions or closures on the Lower Mississippi right now?"* (Expected: hits MSIBs about Carrollton Gauge, Port Condition NORMAL updates, high/low water advisories.)
8. *"What's the current guidance on the Elizabeth River / Norfolk Southern bridge?"* (Expected: SEC VA MSIBs.)
9. *"Has the Coast Guard issued a safety alert for fire extinguishers lately?"* (Expected: ACN 013/18 Kidde recall, ACN 002/22 Fire Protection for Recreational Vessels.)
10. *"What MSIB covers fireworks safety zones?"*
11. *"What's the Coast Guard's current enforcement priority for tanker operations?"*

### Edge-case sanity checks

12. *"What's today's date and the source of your most recent bulletin?"* — you'll expose the "bulletins stop at March 2026" issue. Expected answer should be candid about the 3-year backfill cutoff, not pretend to know about April 2026 bulletins.
13. *"Can I operate a passenger vessel with 50 people on an inland route without a COI?"* — checks that ROUPV vs. inspected-passenger distinction is clear.
14. *"What's the difference between NVIC 04-08 and CFR 46 Part 10 Subpart C?"* — should correctly distinguish interpretive guidance from binding regulation.

### UI / UX checks

15. **Login to the app.** You should see at most one banner notification per source, not a stack of four "CFR Title 33 Updated" banners. If you see stacked duplicates, the collapse-per-source fix didn't take effect for you — let me know.
16. **Check the Coming Up widget.** It should show only user-specific things: your expiring credentials, your COI dates, PSC checklist progress. It should NOT duplicate regulation-update banners anymore. Previously it was double-showing them.
17. **Open a fresh chat with a vessel selected.** The 4 starter prompt suggestions should mention your vessel name + type-relevant topics (not generic COLREGs/ballast-water).

### What to flag back

- Anything the chat says that sounds wrong.
- Anything it claims confidently but can't cite a source for.
- Anything that feels out-of-date (bulletin from 2023 but it sounds like current news).
- UI issues — double-surfacing, missing sources, stale dates.
- Topics that would be valuable but where it says "I don't have information about X" — helps me prioritize next sources.

---

## What we need from you for data

RegKnot's utility scales with the corpus it has. Three things you as a Captain (and our maritime-community connection) can help source:

### Priority 1: live GovDelivery subscription

I need the go-ahead to subscribe a RegKnot-controlled email address to the USDHSCG GovDelivery feed (the Coast Guard's public bulletin distribution). That's what I'd wire up next — every new MSIB, NMC announcement, operational ALCOAST will flow in automatically and be classified / ingested within the hour.

**What I need from you:** approval to create `alerts@regknots.com` and subscribe it. No private data involved; this is the same public feed any mariner can sign up for.

### Priority 2: operator-specific PDFs you can only get from industry

Some USCG guidance lives on dco.uscg.mil behind the same Akamai firewall that keeps our server from fetching it directly. I've worked around it for a handful of documents by downloading from mirrors (Seamen's Church Institute has a surprising amount). But the Coast Guard periodically publishes:

- **NVIC updates** — when a new NVIC comes out (or a Change to an existing one)
- **Commandant Instructions (COMDTINSTs)** — binding internal direction that sometimes affects mariners
- **USCG Marine Safety Manual volumes** — the authoritative reference mariners rarely see directly

**What I need from you:** if you come across any of these documents via AMO, your captain network, or USCG portal access, drop them in a shared folder and I'll ingest them. Each document adds real signal. We can't crawl for these automatically.

### Priority 3: real-world question bank

Right now I write synthetic test queries and run them against RegKnot. Those tests pass, but they're not the questions mariners actually ask. If you can collect questions from your captain network (even just "what did the NMC want from me last week?") I can use them as our regression test set — every new ingest gets validated against real questions, not my hypothetical ones.

**What I need from you:** a shared document (or just text me when they come up) with real questions + what you'd consider a good answer.

---

## Starter marketing campaign

### Positioning

Don't lead with "AI tool." Lead with **"The compliance companion that actually knows what's happening on your waterway this week."** The new bulletin corpus is the differentiator. Every other mariner-facing regulation tool is a glorified CFR viewer. We're the only one that can answer "what MSIB should I know about for my route today?"

### Proof-point demos (record these once, reuse everywhere)

Short (30-60 second) screen-recorded demos showing:

1. **"What port conditions affect my current route?"** — live query, RegKnot returns a cited MSIB with specific river-mile boundaries and safety-zone details. Captain reads it, says "that's the one from Tuesday I missed in my email."
2. **"I'm renewing my MMC — walk me through what I need to submit."** — RegKnot responds with application guide + checklist + specific form numbers. No guessing, no googling.
3. **"Is there a current recall on Kidde fire extinguishers?"** — RegKnot pulls the ACN 013/18 enforcement guidance immediately. Compare that to the current alternative (calling USCG sector office and leaving a voicemail).
4. **"What medical standards apply if I have [condition]?"** — RegKnot pulls NVIC 04-08 Ch-2 directly. No mariner has time to read a 94-page PDF looking for their condition.

### Soft-launch channels (in your network)

- **LinkedIn** — one "here's what I've been working on with my brother" post. Tag your captain contacts. Keep it personal, not corporate.
- **Captain's forums you already post on** — PaxStar, Professional Mariner, Workboat, MarPro comments. Not spam — genuine "I tried this for my renewal prep and it worked" anecdotes.
- **Maritime Facebook groups** — Tug & Barge, Passenger Vessel operators, USCG Licensed Mariners. Post one of the proof-point demos; mention free tier.
- **Direct outreach to 15-20 captains** — the ones you trust to give honest feedback. "Hey, my brother and I built a thing, try it and tell me where it's dumb." Ideal target: 5 Subchapter T passenger-vessel operators, 5 towing captains, 3 tankers, 2 OSVs.

### Hard-launch readiness check

Before a wider campaign, we need:
- ✅ NMC credential content (done)
- ✅ Bulletin backfill (done)
- ⏳ **Live bulletin feed active** (1 week of work — waiting on your GovDelivery approval above)
- ⏳ **Retrieval-side "show current, not expired" filter** (1 session)
- ⏳ **Pilot feedback from 10+ captains** (2-4 weeks of real-world usage)
- ⏳ **2FA on accounts** (nice-to-have for the trust story)

### Messaging what NOT to say

- Don't promise "legal advice." Keep the "navigation aid only" disclaimer prominent. We're a search + synthesis tool; the mariner is still the decision-maker.
- Don't overclaim currency. If a user asks about a bulletin issued last week, we can't answer it yet (live feed pending). Be honest about the backfill cutoff.
- Don't target the general public or recreational boaters in phase 1. Commercial mariners and licensed captains get deeper value from the corpus we have.

---

## Questions for you

1. **GovDelivery subscription OK?** (Priority 1 data pull.)
2. **Anyone in your network you'd nominate as a pilot-user #1?** I'd love a captain who'll bang on this for a week and tell me everything that's broken.
3. **Comfortable with the "8/10 daily companion" framing?** If that's overclaiming, say so — I'd rather be honest and have the product earn up to that rating than make a claim I'll have to walk back.
4. **Any big gap** in the "what got added" list that makes you go "wait, but what about…"? That's the signal I need before the marketing push.

Talk soon.
