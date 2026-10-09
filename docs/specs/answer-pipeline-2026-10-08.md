# Answer pipeline: library first, then the web, then a useful "couldn't find it" (spec, 2026-10-08)

**Status:** Phase 1 built and deployed behind flags (off), A/B running. Phase 2 proposed.
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

**Open questions for Blake:**
1. Allowlist: Coast Guard, eCFR / Federal Register / GovInfo, IMO, EPA, NOAA, PHMSA, OSHA, FCC,
   MARAD, MCA, AMSA, MPA. Add class societies (ABS, DNV, LR) and flag registries (IRI, LISCR)?
2. Web research for free-plan users too, or paid plans only?
3. Should a web hit on a public document queue an automatic ingest, or wait for review?

**Effort:** 2-3 days, then the A/B.

## Database

No structural refactor needed: `regulations` (source, section_number, chunk_index) already
supports whole-section reads. Two fixes:
- **Tag drift:** COSWP carried `['intl']` for four months because the code map gained
  `coswp → ["uk"]` after its only ingest (fixed 2026-10-08). Add a test / nightly check that
  stored jurisdiction tags match `ingest.store._SOURCE_TO_JURISDICTIONS`.
- **Content gaps** are the real organization problem: 121 open `CORPUS_GAP` audits nobody
  triaged. Phase 2's gap queue makes that a working list.
