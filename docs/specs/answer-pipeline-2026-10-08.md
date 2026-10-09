# Answer pipeline: library first, then the web, then a useful "couldn't find it" (spec, 2026-10-08)

**Status:** Phase 1 **live since 2026-10-09** (`4a7d26d`; results below). Phase 2 proposed.
Blake, 2026-10-08: "User prompt > do we have the data? yes - answer; no - check the internet
via a regular Claude chat type question > did we find an answer? yes - answer; no - we say
that we cannot find it with smart and useful dialogue. If our prompt builder is off, let's
refactor. If the database is not organized right, let's refactor." Greenlit the same day.

## Why

- **7 of 18 external answers in the last 60 days** told the user what the search did not find
  ("didn't surface", "not in the excerpts retrieved here", whole "What I didn't retrieve"
  sections). The hedge judge rated almost all of them `precision_callout`: correct answers,
  wrapped in search narration.
- The web fallback ran **twice in 90 days**, both times in a test. It fires only after the
  answer has streamed, only when a regex finds hedge wording, the Haiku judge calls it a miss,
  and the answer cites nothing. Almost every answer cites something, so it almost never runs.
- 2026-10-08/09, the Captain's pilot-ladder thread:
  - "Solas ch v reg 23 pilot ladder": the regulation has 4 chunks; the model read 3 and said
    paragraphs 4-6 "did not surface". Paragraphs 4-8 were in chunk 3, in the database.
  - "Pilot ladder step thickness": answered exactly, then "IMO Res. A.1045(27) … didn't
    surface, verify it there". A.1045(27) was not in the corpus.
  - The Reg.23 answer also said the 2023 amendments were MSC.532(107), in force around 2028.
    Wrong: MSC 110 adopted them on 26 June 2025 as MSC.572(110), with Performance Standards
    MSC.576(110), in force 1 January 2028. Memory is not a source for numbers and dates.

## What the pipeline does today

| Blake's flow | What runs |
|---|---|
| Do we have the data? | Retrieve 8 chunks; the answer model reads at most 6,000 tokens of them |
| Yes → answer | Opus 5.5 answers; five overlapping prompt rules tell it to narrate gaps |
| No → search the web | After the answer: regex on the wording → Haiku judge → web only if the answer cites nothing → a separate card |
| Not found → say so usefully | Not designed; the narration is the fallback |

About 1,500 lines of the engine (hedge regex, judge, citation oracle, the three-provider web
ensemble, Layer C answer inversion, the hedge-audit classifier) patch answers after the fact.

## Phase 1 — built 2026-10-08 (`e5699f0`), behind flags, off until measured

1. **Read whole sections** (`WHOLE_SECTIONS_ENABLED`, `packages/rag/rag/sections.py`).
   Retrieval still picks the sections; the model reads every chunk of each, in document order,
   within 20K tokens (was 6K of loose chunks). A section the user names (the retriever's
   identifier parse: "Solas ch v reg 23" → `SOLAS Ch.V Reg.23`) goes first and is read in full
   up to 10K tokens. A section longer than 4K tokens keeps its retrieved chunks and their
   neighbours. Retrieved chunks are reserved before siblings. Fail-open. Sections average
   3 chunks (median 1, p90 4), ~380 tokens a chunk.
2. **One sources-and-gaps rule** (`PROVENANCE_PROMPT_ENABLED`, `rag.prompts.PROVENANCE_*`).
   Replaces the base grounding bullets, COVERAGE, NO HALLUCINATED RECOMMENDATIONS, the
   COVERAGE ANTI-PATTERN and the model-led patches: cite the library where it covers a point;
   answer confidently from knowledge where it doesn't; never invent a number; never describe
   the search ("retrieved", "excerpts", "surfaced", "in this query"); never assert
   non-existence. The UN-number rule keeps its strictness, reworded. Precision Mode and the
   flags-off prompt are byte-identical to before. The prompt is ~1,200 tokens shorter.
3. **IMO pilot transfer instruments** into `imo_msc`: A.1045(27), MSC.572(110), MSC.576(110)
   (`ingest/sources/imo_codes.py`), ingested after the A/B so it doesn't move mid-run.

**Measurement:** `scripts/compare_synthesis_models.py --phase1-ab` (16 questions: 6 gold, the
Captain's 2, 4 earlier hedges, this week's 4), each captured twice through the real engine
("today" / "phase1"), Opus 5.5 low, two blind judges on the phase-1 context. New metric
`plumbing`: answers that describe the search. Ship if plumbing drops, judge accuracy and
errors-flagged don't get worse, and nothing new turns up unverified. Watch item: with the
narration gone, does the model state numbers from memory more readily (the MSC.532 error)?
Phase 2's web step is the structural answer to that.

**Result (2026-10-09, `data/eval/model_compare/20261009-011747-phase1-ab/`, $4.13):**

| | today | phase 1 |
|---|---|---|
| answers describing the search | 15 / 16 | 0 (the metric's 3 hits are "non-skid surface") |
| hedge phrases (`detect_hedge`) | 7 | 1 |
| Opus judge overall / accuracy | 6.81 / 6.81 | 8.44 / 8.31 |
| GPT-4o judge overall / accuracy | 9.44 / 9.69 | 9.56 / 10.0 |
| errors flagged (Opus / GPT-4o) | 39 / 5 | 13 / 0 |
| judged best (Opus / GPT-4o) | 4 / 7 | 12 / 9 |
| first token median / p90 | 6.1 / 15.4 s | 6.8 / 8.7 s |
| cost per answer, warm cache | $0.064 | $0.083 |
| unverified citations | 3 | 3 |

- One regression, F5 (fixed CO2, inland towboat): phase 1 no longer names 46 CFR 142.240 from
  memory. Retrieval never returns 142.240 for that question in either configuration (4 of 4
  runs return SOLAS, the FSS Code, ABS and the HSC Code for an inland Sub M towboat): a
  retrieval gap phase 1 exposes. Follow-up: Sub M fire-protection retrieval for towing vessels;
  phase 2's coverage check would research it.
- The Reg.23 answer now has no errors per either judge and names A.1045(27) correctly, but
  dates the amendments "2024" (MSC 110 adopted them on 26 June 2025). The Opus judge believed
  "MSC.550(108), 2024" too. Model memory of recent instruments is stale; grounding fixes it.
- **Found while ingesting the pilot-transfer resolutions:** the IMO chapter / paragraph
  splitters dropped the text before the first chapter and every short chapter. MSC.572(110)
  kept 6% of its text, the STCW amendments MSC.503(105) 41%, MEPC.353(78) 50%, MSC.402(96)
  83%, and ~12 more lost their preamble (entry-into-force clauses). Fixed (`5aeeebb`); all 15
  `imo_codes` sources re-ingested.

## Phase 2 — proposed: check before writing, research the gaps, answer once

```
question → retrieve (+ whole sections)
         → coverage check (Haiku 5.5, structured)        ~1 s, every question
              full   → write the answer from the library
              partly/none → web research on the missing items   ~5-10 s, only then
                            → write once: library chips + web sources
                            → anything still missing: a designed "couldn't find" reply
         → log every gap to corpus_gaps (the ingest queue)
```

1. **Coverage check** (`rag/coverage.py`). Input: the question (with `router_context` for a
   follow-up), the vessel profile line, the library text. Output (structured):
   `{coverage: full | partial | none, missing: [{item, search_query}] (≤ 3)}`. Haiku 5.5 at
   $0.10/M input: ~$0.002 on a 20K-token context.
2. **Web research** (`rag/web_research.py`), one call per missing item, in parallel, 10 s
   budget each. Reuses `rag/web_fallback.py`'s search primitive (the basic
   `web_search_20250305` tool; the 2026 dynamic-filtering tool took 40 s with nothing usable
   on 2026-09-22) and its hostname allowlist and quote check. Output per item:
   `{found, answer, quotes: [{text, url, publisher}]}`. One provider (Claude); the GPT / Grok
   ensemble is retired.
3. **One answer** (Opus 5.5 as now). The context carries the library sections and a
   WEB FINDINGS block (publisher, URL, verified quote). Library statements cite as today
   (verified chips). Web statements cite as `[Web: uscg.mil — title]`, a new chip that opens
   the page; the footer lists them apart from library citations, and "Corpus-verified · N"
   stays library-only. An item neither source answers gets one plain sentence and the next
   step (who to ask, what to pull, a narrower question).
4. **Gap log** (`corpus_gaps`, migration 0122): question, missing item, search query, web
   found?, URLs, status (open / ingested / dismissed). An admin page replaces hedge audits.
   A web hit on a public document is an ingest candidate (A.1045(27) would have landed here).
   One-time: classify the 208 open hedge audits (121 `CORPUS_GAP`) into it, ~$0.05 on Haiku 5.5.
5. **Remove from the hot path:** the regex-gated judge, the citation oracle, the web ensemble
   card, Layer C inversion, the hedge-audit classifier. The judge can keep running in the
   background for two weeks as a cross-check; then delete the code.
6. **Flag:** `ANSWER_PIPELINE_V2` (off / on), rollback without a deploy.

**Measurement before turning it on:** a `--pipeline-ab` harness mode on the phase-1 set plus a
gap set (questions whose answer is known to be outside the corpus, e.g. the A.1045 and MSC.572
questions run before their ingest, CG-835, a local VTS rule): plumbing, judge accuracy and
errors, unverified citations, web-used rate, latency p50 / p90, cost. ~$8-10.

**Latency / cost:** +~1 s on every question (coverage check); +5-10 s only on questions with a
gap, under a "Checking Coast Guard and IMO sources…" status (the current fallback already adds
10 s+ after the answer on the rare runs it fires). Web: ~$0.02-0.05 per researched item
(model + $10 per 1,000 searches). Per-user daily and global monthly caps carry over from
`web_fallback`.

**Risks:** web pages can be wrong or stale (allowlist, verified quotes, labelled as web, never
as library); prompt injection from pages (quotes only, treated as data); cost (caps above).

**Decisions (Blake, 2026-10-09):** "We can be liberal with the sites. Web search for free, they
need to be convinced to convert. Good with recommendation, I think we ingest a legit hit."

**Built 2026-10-09 (`7c21cff`, `0122`), behind `ANSWER_PIPELINE_V2_ENABLED` until the A/B:**
- `rag/coverage.py`, `rag/web_research.py` (Haiku 5.5 + `web_search_20250305`, 3 searches per
  item, 25 s budget, quotes checked on the page with an 8 s cap), engine wiring, the verifier
  exemption for web-sourced citations, the post-answer machinery off the hot path under v2.
- Allowlist (`rag/web_fallback.py`) widened: ILO, EU, UN bodies, more flag administrations and
  registries, P&I clubs, industry bodies, more government suffixes. Free plan included.
- Caps: 30 researched items per user per day, 2,000 a month across users (`WEB_RESEARCH_*`).
- Auto-ingest (`app/web_ingest.py`, Celery `ingest_web_gaps` every 15 min, 25 a day): a found
  gap whose verified quote is on an official domain (regulators, IMO / ILO / IACS / EU, flags and
  registries, class societies; not commentary, not the CFR, which is already complete) is fetched,
  re-checked, chunked, embedded and added as source `web_ingest`, jurisdictions by domain.
- Migration 0122: `corpus_gaps`, `messages.web_sources`, the `web_ingest` source.
- Web: `[Web: domain — title]` link chips (sky blue), a "From official websites (not RegKnot's
  library)" footer; admin > Answers > Corpus gaps (dismiss, remove an ingested document).
- Live check on prod (Mediterranean ECA question): coverage 4.0 s found 3 missing facts;
  research 11.0 s found IMO's page (1 May 2025, quote verified), flagged a conflicting secondary
  reading, and returned NOT FOUND for the U.S. implementation item rather than guessing.

**A/B 2026-10-09 (`--pipeline-ab`, `data/eval/model_compare/*-pipeline-ab/`), 15 of 21 scored:**
the Anthropic credit balance ran out at question 16, so WEEK4 and all five gap questions failed.

| | phase 1 (live) | v2 |
|---|---|---|
| Opus judge overall / accuracy | 7.47 / 7.20 | 8.53 / 8.53 |
| GPT-4o judge overall / accuracy | 9.40 / 9.87 | 9.67 / 9.93 |
| errors flagged (Opus / GPT-4o) | 37 / 1 | 17 / 0 |
| judged best (Opus / GPT-4o) | 3 / 6 | 12 / 9 |
| web research used | 0 / 15 | 13 / 15 |
| question → synthesis call, median | 7.8 s | **30.4 s** |
| first token after synthesis starts, median | 6.5 s | 5.6 s |
| cost per answer, warm | $0.086 | $0.093 (+ research, not counted) |

Better answers, but the coverage check called 13 of 15 questions partial and each paid ~22 s of
research before the first token. **Not switched on.** Tuned (no spend): the check now judges only
the core of the question (`full` is the usual case; related details don't count), at most 2
items; research budget 25 → 15 s, quote check 8 → 6 s. Re-run `--pipeline-ab` when credits are
back (~$8-10) to measure the web-used rate, the latency and the gap questions before turning it on.

## Database

No structural refactor needed: `regulations` (source, section_number, chunk_index) already
supports whole-section reads. Two fixes:
- **Tag drift:** COSWP carried `['intl']` for four months because the code map gained
  `coswp → ["uk"]` after its only ingest (fixed 2026-10-08). Add a test / nightly check that
  stored jurisdiction tags match `ingest.store._SOURCE_TO_JURISDICTIONS`.
- **Content gaps** are the real organization problem: 121 open `CORPUS_GAP` audits nobody
  triaged. Phase 2's gap queue makes that a working list.
