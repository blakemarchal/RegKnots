# Corpus gap report — 2026-05-09

Surfaced from the post-2026-05-08-audit eval re-run + a programmatic
coverage survey via `scripts/corpus_gap_survey.py`. This document
prioritizes what to fill next, with rough cost/effort estimates, so a
focused ingest sprint can target the highest-leverage gaps.

The TL;DR: **most of the corpus is healthy.** ~77K chunks across 50
sources, eval at 96.8% A-or-A−. The gaps that matter group into three
categories: **two IMO codes entirely missing despite heavy SOLAS
references**, **one foundational IMO convention with a thin partial
ingest**, and **a couple of CFR / NVIC sections that look hallucinated
or really are missing.**

## Ranked gap list

| # | Gap | Severity | Why | Effort | Notes |
|---|---|---|---|---|---|
| 1 | **FSS Code (Fire Safety Systems Code)** entirely missing | High | Referenced extensively by SOLAS Ch.II-2. Every "what fire-fighting equipment do I need" question on a passenger or cargo vessel falls into this. Currently routed to the SOLAS chapter only — no resolution-level detail. | 4-6 hr | Need source acquisition. IMO publishes; not free. Adapter follows the existing `imo_codes.py` pattern. |
| 2 | **LSA Code (Life-Saving Appliances Code)** entirely missing | High | Referenced extensively by SOLAS Ch.III. "What lifejacket / lifeboat / liferaft / immersion suit / EPIRB / SART do I need" all bottom out here. Today routes to the SOLAS chapter alone. | 4-6 hr | Same as FSS — IMO source, adapter pattern exists. |
| 3 | **Load Lines Convention** has only 4 chunks (`imo_loadlines`) | High | Real one is hundreds of pages — Annex I freeboard tables, Annex II zones/seasonal areas, etc. Foundational stability + freeboard reference. | 3-4 hr | Adapter exists (4 chunks already); the source PDF was likely truncated or partially OCR'd. Re-ingest from full text. |
| 4 | **`46 CFR 95.25` family** missing entirely | Medium | Eval question V1/S-033 cited `46 CFR 95.25-1` (charts/publications carriage requirements). Zero rows in `cfr_46` for `95.25`. Either eCFR moved them or our ingest dropped them. | 30 min | `cfr_46 --update` may pick this up. If not, eCFR-direct fetch + `manual_add.py`. |
| 5 | **`imo_hsc` / `imo_igc` / `imo_ibc` chapter granularity** | Medium | Each has 274-339 chunks but **only 1 distinct `section_number`**. The whole code lives under one identifier ("IMO IGC Code MSC.370(93)"), so chapter-specific citations can't be resolved at chapter level. | 6-8 hr | Re-ingest with chapter-level section-numbers. Per-chapter retrieval is a meaningful precision improvement. |
| 6 | **NVIC backfill** — gaps in 2005 / 2006 series | Low-Medium | Eval V1/S-060 cited `NVIC 04-05` which doesn't exist in our corpus (we have 04-03, 04-04, then jump to 04-08). Could be hallucination, could be real ingest gap. | 1 hr | Quick check against USCG NVIC index page; backfill any genuinely-missed NVICs via the existing `nvic` adapter. |
| 7 | **`solas_supplement` / `stcw_supplement` thin ingest** | Low-Medium | 12 chunks across 8 sections (solas_supplement); 4 chunks across 4 sections (stcw_supplement). MSC resolutions referenced by these supplements live elsewhere or aren't ingested at all. | 2-3 hr | Decide which MSC resolutions are actually consulted in real questions, prioritize those. |
| 8 | **Real-time / current-conditions data** | Out of scope | Eval V5/N-P1 ("Mississippi too high today?") and V1/N-V1 ("paperwork for India port") need live data, not corpus. | — | Track separately; web-fallback already partially handles these. Layer C UX inversion (in roadmap) is the right next step. |

## Detail per gap

### #1 — FSS Code (entirely missing)

The International Code for Fire Safety Systems (FSS Code, IMO MSC.98(73)
+ amendments) is what SOLAS Ch.II-2 actually points at for every
fire-system specification. SOLAS says "the fire pumps shall comply with
the FSS Code" — without the FSS Code in our corpus, that pointer goes
nowhere.

What's in it (15 chapters):

- Ch.1: General
- Ch.2: International shore connections
- Ch.3: Personnel protection
- Ch.4: Fire extinguishers
- Ch.5: Fixed gas fire-extinguishing systems (CO₂, halon, inert gas)
- Ch.6: Fixed foam fire-extinguishing systems
- Ch.7: Fixed pressure water-spraying / water-mist systems
- Ch.8: Automatic sprinkler / fire-detection / fire-alarm systems
- Ch.9: Fixed fire-detection and fire-alarm systems
- Ch.10: Sample-extraction smoke-detection systems
- Ch.11: Low-location lighting
- Ch.12: Fixed emergency fire pumps
- Ch.13: Means of escape
- Ch.14: Fixed deck foam systems
- Ch.15: Inert-gas systems

Every "do I need / how do I test / how often do I service the X fire system"
query bottoms out in one of these chapters. Today the model either gets
SOLAS Ch.II-2 generalities or tries to cite `46 CFR 95.X` US equivalent.

Acquisition: IMO Publishing sells it; ~$100. Or there are mirrored
ASCII versions on flagstate sites (some are free).

### #2 — LSA Code (entirely missing)

The International Life-Saving Appliances Code is the IMO performance-
spec backstop for lifejackets, lifeboats, life rafts, MOB recovery
boats, line-throwing apparatus, immersion suits, EPIRBs, SARTs,
pyrotechnics — i.e. every lifesaving item SOLAS Ch.III references.

Same situation as FSS: SOLAS chapters say "the X shall comply with the
LSA Code paragraph Y.Z," and without LSA in the corpus, those pointers
land on nothing more specific than the SOLAS chapter itself.

Maritime glossary now bridges some of this at the slang level
(`lifejacket → lifesaving appliance / personal flotation device / PFD`),
but the model still can't make a precise LSA citation.

Acquisition: same as FSS Code.

### #3 — Load Lines (4 chunks; should be ~150-200)

The 1966 International Convention on Load Lines + 1988 Protocol covers
freeboard, seasonal zone restrictions, structural strength minimums,
hatch covers, freeing ports/scuppers, deckhouses. Foundational document
for stability + structural compliance.

We have 4 chunks under `imo_loadlines`. The actual convention runs to
~140 pages with 20+ regulations and detailed annexes. **Our ingest is
~2% complete.**

This is a clear adapter-ran-incomplete situation — the source path
exists (`packages/ingest/ingest/sources/imo_codes.py` covers IMO codes
generally), but the load lines text we have is a stub.

Effort: 2-3 hr — the work is finding/cleaning the canonical text and
re-running the adapter.

### #4 — 46 CFR 95.25 family — RESOLVED (model hallucination, not corpus gap)

Concrete gap from the eval: V1/S-033 ("nav officer on a containership,
charts in the folio room are a mess — what publications do we have to
keep current") expected `46 CFR 95.25-1`, which doesn't exist in our
corpus.

**Update 2026-05-09 16:48 UTC:** ran `cfr_46 --update` against current
eCFR. Result: **0 new sections, 0 modified sections, 0 net delta.**
8,332 sections parsed, 10,523 chunks identical to current corpus.
eCFR's current Title 46 does not contain `46 CFR 95.25-*` either —
the subpart has been repealed or never existed in this form.

So this F was a model hallucination, not a corpus gap. Either the
model invented the citation under retrieval pressure, or the legacy
text it was trained on referenced a deprecated subpart. Track as a
hallucination pattern rather than a corpus completeness item.

The eval's expected-source pattern for V1/S-033 may also be stale —
if the original test was authored against an older CFR snapshot, the
modern equivalent may live elsewhere. Worth checking when next
revising the eval question set.

**Net finding from this exercise: our `cfr_46` ingest is current and
complete to eCFR.** Same likely true for `cfr_33` and `cfr_49` (worth
running `--update` on those too as confirmation, ~5 min each).

### #5 — IMO HSC/IGC/IBC chapter granularity

This is the technical-debt-of-its-own gap. We have plenty of content
for these three codes:

- `imo_igc`: 300 chunks (IGC = gas carriers)
- `imo_hsc`: 339 chunks (HSC = high-speed craft)
- `imo_ibc`: 274 chunks (IBC = bulk chemical)

But each code's chunks all share a SINGLE `section_number` ("IMO IGC
Code MSC.370(93)" etc.). So when retrieval surfaces them, the citation
is always the whole-code-as-resolution; the model can't cite IGC Ch.17
specifically vs. IGC Ch.4. The 2026-05-09 eval's gas-carrier failures
all bottomed here — model retrieved the right chunks but couldn't
carve a chapter-precise citation.

Fix is conceptually simple but ingest-heavy: re-chunk these three codes
with chapter-level section-numbers (e.g. "IMO IGC Code Ch.17 §17.4")
matching how SOLAS cites them. The text is already in the corpus, just
under a flat identifier. ~6-8 hr including embedding cost (re-embed
the 900 chunks at $0.02/M tokens = trivial).

### #6 — NVIC backfill

We have 158 distinct NVICs. Expected gaps:

- 2005 series — 04-05, 04-06, 04-07 missing between 04-04 (we have)
  and 04-08 (we have).
- Various other potential gaps not yet enumerated.

USCG publishes a complete NVIC index. Quick crawl to confirm the
canonical list, diff against our 158, ingest any genuine gaps via
the existing `nvic` adapter.

Effort: 1-2 hr for the diff + ingest.

### #7 — `solas_supplement` / `stcw_supplement` thin coverage

These supplement tables hold IMO MSC/MEPC resolutions that amend the
parent convention. The eval surfaces hallucinated MSC.X(Y) citations
periodically; some of those are real resolutions we don't have, others
are model fabrication.

Recommended approach: harvest the model's hallucinated MSC IDs from
the past 30 days of `retrieval_misses`/answer logs, look up each
against IMO's official IMODOCS database, ingest the real ones.

Effort: 2-3 hr.

## Recommended sequencing

If a corpus sprint gets prioritized:

1. ~~Run `cfr_46 --update`~~ **DONE 2026-05-09. Confirmed current. cfr_33
   and cfr_49 should be similarly --updated as a 5-min confirmation
   pass each.**
2. **NVIC backfill** (#6, ~1 hr). Smallest lift, clears one eval
   failure pattern, rounds out the most-cited NVIC body.
3. **Load Lines re-ingest** (#3, ~3 hr). Clear win, no source-acquisition
   blockers — text is freely available.
4. **IMO HSC/IGC/IBC chapter granularity** (#5, ~6-8 hr). Lifts citation
   precision for the gas-carrier and high-speed-craft user segment.
5. **FSS Code + LSA Code** (#1 + #2, ~10 hr combined). Highest user
   impact; needs source acquisition. Treat as a separate sprint.

Items #2-4 can be done with current sources at hand. Items #5-7 need
source-acquisition decisions first.

## Budget

Embedding cost across all of the above is trivial — `text-embedding-
3-small` at $0.02/M tokens, the entire backlog probably costs <$5.
The real cost is ingest engineering time.

Karynn-side review cost: minimal. Once an ingest is done, the smoke
indicator is the eval re-run and a few targeted user queries.

## Tracked in roadmap as

- Item #6 in `docs/roadmap.md` Next 1-2 weeks: 46 CFR 95.25 family fix
- Item #15 in `docs/roadmap.md` Within 30 days: corpus-completeness
  audit (this report is its first artifact)
- Items #1, #2, #3, #5, #7 above to be added when prioritized
