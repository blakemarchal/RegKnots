# Question audit — 2026-09-25

**Scope.** The three most recent real questions: the Captain (MAERSK Kinloss, US-flag containership) on 2026-09-23 at 23:52 and 23:53 UTC, and Karynn (Maersk Seletar, US-flag containership) on 2026-09-25 at 04:49 UTC.

**Method.**
- The answer text, and per-stage timelines from `journalctl -u regknots-api`.
- Corpus inspection on the prod DB.
- Before/after probes run on prod through the full retrieval path (rewrite and rerank on, the users' real vessel profiles). The candidate `rag` package was imported ahead of the deployed one, so prod kept serving `main`.
- Every retrieval change was run through `scripts/eval_retrieval.py`.

## 1. How we did

| | Question | Outcome | Cause |
|---|---|---|---|
| Q1 | "SOLAS Chapter III, Part B, Section I, Regulation 20" | **Partial.** The answer said only the Unified Interpretation of Reg.20.11 had been retrieved and declined to give the weekly and monthly inspection intervals. | The citation parser did not recognise the form, so none of Reg.20's 5 chunks were retrieved (0 of 8). The reranker scored the top 8 at `[4,1,1,1,1,1,1,1]`. The hedge judge said `partial_miss` and named the missing paragraphs; recovery was suppressed (§3.7). |
| Q2 | "…Regulation 20 life boat lowering" | Useful answer, **but Reg.20 itself was not retrieved** (0 of 8). | Same parser bug. The primary retrieval's top 4 were the Chapter III Unified Interpretations stored under two section names, and a stale Part-level row ("SOLAS Ch.III Part B") was cited (§3.5). |
| Q3 | "If a port is asking for a copy of the vessels bunker CLC, what is that?" | **Good.** It identified the Bunkers 2001 Art. 7 certificate, the non-State-Party route, and COFR as the US analogue, and flagged US non-ratification as unverified. | Two blemishes. (1) A reformulation's invented "46 CFR 34" matched any chunk containing "34", and one of those chunks (49 CFR 171.8, hazmat definitions) took one of the 8 context slots (§3.2). (2) The answer closed with an unrelated "Personal note" that her medical certificate had expired (§3.9). |

**Latency** (seconds, from journald):

| | route | rewrite | primary retrieval | reformulation retrievals | rerank | synthesis (Opus 5.5 `low`) | judge |
|---|---|---|---|---|---|---|---|
| Q1 | 0.9 | 0 reformulations | 3.2 | none | 2.2 | ~18 | ~3.5 |
| Q2 | 0.6 | 0.8 | 2.6 | +4.2, started only after the primary finished | 3.3 | ~19 | 4.4 |
| Q3 | 1.1 | 2.6 | 3.1 | +3.6 | 5.5 | ~24.5 | 5.3 |

Pre-synthesis wall time was 5.5, 10.1 and 12.4 s.

## 2. Measured results

**Citation probe.** Share of queries whose cited target reached the final top 8 (full pipeline, prod data). Rewrite and rerank are LLM calls, so single runs vary by a chunk or two.

| probe | deployed | candidate |
|---|---|---|
| 6 SOLAS citation forms (round 1) | 3/6 | **6/6** |
| 12 SOLAS + CFR queries, including Karynn's question twice (round 3) | 6/12 | 8/12 |
| same 12, final candidate (round 4) | 6/12 | 8/12 |
| 4 chapter and regulation checks after holding back the chapter search (round 5) | — | 4/4 |

Chunks of the cited target in the final 8, deployed → final candidate:

| query | deployed | candidate |
|---|---|---|
| The Captain's Q1 (the whole regulation is 5 chunks) | 0 | **5** |
| The Captain's Q2 | 0 | **4** |
| "SOLAS III/20 weekly and monthly LSA inspections" | 1–2 | **5** |
| "33 CFR 138 certificate of financial responsibility" (§3.3) | 0 | **4** |
| "SOLAS II-2/10 fire main" | 2 | **4** |
| "What does 46 CFR 199.180 require" (round 3 / round 4) | 2 | 5 / 2 |

Karynn's question, run twice on the final candidate, drew no identifier lookups, so no invented sections reached the pool. One run still carried `49 CFR 1244.3` (§3.6).

**Exam-bank path** (the quiz's explicit-source retrieval): six topics returned the same 82 rows deployed and candidate. That is 16 of 16 for five topics and 2 for "stability and trim", where one long section fills the per-section cap.

**Retrieval harness** (dense, 62 pairs; baseline `20260924-022839-…-post-shared-buffers-512mb.json`):

| arm | strong recall@8 | MRR | p50 ms |
|---|---|---|---|
| baseline (deployed) | 0.8226 | 0.6881 | 586 |
| skip impossible groups | 0.8226 | 0.6881 | 567 |
| + iterative HNSW scan on the group fan-out | 0.8387 | 0.6614 | 652 |
| **final candidate** (shipped set, §4) | **0.8226** | **0.6795** | **572** |

- The final candidate gained 0 pairs and lost 0.
- Two pairs moved down one rank. `N-C1/V5` fell 5 → 6 because a newly admitted `33 CFR 165.813` took rank 2 (§3.3); `N-E3/V1` fell 1 → 2 on an ERG tie.
- The gold set contains no citation-bearing questions and no pairs that expect 33 or 49 CFR, so neither the citation fixes nor the filter fix can show a gain here.
- The iterative scan's MRR loss is entirely the medical-certificate question on all three vessels (C3/V1, V3, V5 fell from rank 1 to 5). Fuller CFR groups ranked **49 CFR 391 (FMCSA truck-driver medical rules)** above the mariner-medical NVIC 04-08. The scan is therefore not shipped for the fan-out (§3.6).

## 3. Findings

### 3.1 SOLAS citations never resolved — FIXED
The pattern accepted only hyphenated chapters ("II-2") and then searched `full_text` for the chapter string alone. "SOLAS III/20", "SOLAS Ch.III Reg.20" and the Captain's "Chapter III, Part B, Section I, Regulation 20" therefore matched nothing. Q1's own answer suggested the follow-up "SOLAS III/20 weekly and monthly LSA inspections", which also failed.

The corpus names per-Regulation sections "SOLAS Ch.III Reg.20" (D6.97 Sprint B), so a regulation citation now resolves to that exact `section_number`:
- The section's chunks are ranked by similarity to the question, and a cited section may keep up to 5 chunks instead of 2.
- A citation the corpus doesn't have returns nothing.
- A chapter cited without a regulation adds no identifier. The old one returned 5 arbitrary chunks containing the chapter string.
- A within-chapter search was built, measured and **held back**. The only `SOLAS Ch.II-2 …` rows are stale Part-level ones, because the per-Regulation text sits under older `SOLAS Ch.II Reg.N` names (§3.5). Injecting them took "SOLAS II-2 fire detection" from 2 to 0 correct chunks. Revisit after the SOLAS cleanup.

### 3.2 CFR citations matched substrings — FIXED
`cfr_section` searched `full_text ILIKE '%<section>%'`. For a part-only citation such as "46 CFR 34", "33 CFR 138" or "46 CFR 199", that is any chunk containing those digits, and 5 of them entered the pool above every vector result. Now:
- A section citation resolves to the section, falling back to the old substring search only if no section has that exact name.
- A part citation returns the part's chunks nearest the question.
- A bare part of a title we don't carry returns nothing.

### 3.3 The vessel filter dropped 33 and 49 CFR parts — FIXED
The forbidden-part lists in `_VESSEL_TYPE_CFR_APPLICABILITY` are 46 CFR subchapters, but `_filter_by_vessel_applicability` ignored the title. Any 33 or 49 CFR part sharing a number was dropped. For a containership that was **5,137 chunks**, including:
- the Inland Navigation Rules (33 CFR 83–89),
- RNAs and safety zones (33 CFR 165, 902 chunks), traffic separation schemes (167) and ship reporting, including right-whale reporting (169),
- COFR (33 CFR 138),
- hazmat carriage by vessel (49 CFR 176).

The prod log shows 32 retrievals in 30 days dropping such sections (33 CFR 83.xx and 88.xx, 49 CFR 176.xx, 178.xx, 180.417). That is a floor, because each log line lists only 5 sections. The 33 CFR 165–169 range was on every mapped type's list.

### 3.4 Invented citations from the query rewriter — CHANGED, THEN REVERTED 2026-09-26
Reformulations cited sections the user never mentioned. Across the probes: "46 CFR 109", "46 CFR 76", "46 CFR 34", "46 CFR 148.5", "46 CFR 160.35", "46 CFR 199.300", "SOLAS III-2", "SOLAS III-1 Reg.19". About 8 in 10 were wrong: nonexistent, or for another vessel type. An identifier hit enters the pool above every vector result, and "46 CFR 148.5" (bulk solids) reached the final 8 for Karynn's bunker question. Reformulations were switched to run without identifier search. **Reverted on 2026-09-26 after measurement (§6).** On the full-pipeline harness the change cost 4 of 71 pairs: strong recall 1.000 → 0.944, MRR 0.730 → 0.706. The rewriter's citations are mostly right. Since citations now resolve to exact sections (§3.1, §3.2), an invented one finds nothing, which removes most of the harm this change guarded against.

### 3.5 Stale SOLAS rows; the ingest never prunes — PROPOSED (spec needs go)
`store.upsert_chunks` is `ON CONFLICT (source, section_number, chunk_index) DO UPDATE`, so rows that a re-parse no longer produces stay in the corpus and keep being retrieved.

`solas` holds 1,739 chunks from four runs:

| created | chunks | content |
|---|---|---|
| 04-03 | 742 | Part- and chapter-level parse |
| 04-13 | 292 | chapter-level rows, "Unified interpretations for chapter X" naming |
| 05-11 | 300 | per-Regulation rows, including 1-chunk "Ch.II-1 Reg.N" / "Ch.II-2 Reg.N" rows |
| 05-24 | 405 | the current per-Regulation parse |

Consequences:
- Part B of Chapter III is stored twice, once as "SOLAS Ch.III Part B" (45 chunks) and again as Regs 6–37.
- The Chapter III Unified Interpretations are stored under two names; Q2 cited both.
- An older parse merged II-1 and II-2 into "SOLAS Ch.II Reg.N". "SOLAS Ch.II Reg.10" holds 23 chunks of fire-fighting text, while "SOLAS Ch.II-2 Reg.10" is a single chunk.
- Sections also carry stale tail chunks: "Unified interpretations for chapter II" has 38 chunks at the current version plus 19 older ones.
- On Chapter III questions, stale chapter- and Part-level rows filled 2–4 of the final 8 slots in the probes.

**Proposal:**
1. `scripts/diff_source_rows.py` parses and chunks a source with no embedding and no writes, and lists DB rows the current parse doesn't produce.
2. Review the list.
3. Take a backup, then delete those rows in one transaction.
4. Run the harness and the citation probe.
5. Add `--prune` to the pipeline, which deletes not-produced rows after a successful full-source run.
6. After SOLAS, check the IMO codes re-split in Sprint #47 (IBC, CSS, BWM, IGF, Polar).

### 3.6 cfr_49 is all of Title 49 — PROPOSED
15,967 chunks cover rail (200–299), FMCSA (300–399), pipelines (190–199), transit ADA (37/38) and the Surface Transportation Board (1000+) alongside hazmat. In the audited sessions this surfaced:
- `49 CFR 229.125` (locomotive safety) at #2 in a "lifeboat lowering" reformulation,
- `49 CFR 1244.3` (STB waybill sample) in Karynn's pool,
- 49 CFR 391 ahead of the mariner NVIC on the medical-certificate gold pairs.

**Proposal:** scope cfr_49 to maritime-relevant parts: hazmat 105–180, Part 40 (drug testing, which 46 CFR 16 incorporates), 450–453 (CSC container safety), and the NTSB marine parts. Do it in the ingest adapter, not only at retrieval time: Celery Beat refreshes cfr_49 weekly, so excluded rows would come back. Then re-test the group iterative scan.

### 3.7 The judge's "verified citations" gate counts retrieved sections — PROPOSED
- `verified_cited` is every retrieved section that exists in the DB (`build_context` → `verify_citations`), so it is non-empty whenever retrieval returns anything.
- That means `should_fire_fallback = verdict in (complete_miss, partial_miss) and not has_verified_citations` can essentially never fire.
- The last 30 days of logs show 4 suppressions and **0** citation-oracle or web-fallback runs.
- D6.97 Phase 1a (`8d16bdc`) meant "an answer that already carries verified citations". The UI already counts citations from the answer text (`extractFooterCitations`).

**Proposal:**
1. Count the citations the answer text actually makes.
2. Let the corpus-only citation oracle run on `partial_miss` even when the answer has citations. It adds a verified corpus card, not a 🌐 web card, so the trust contract Phase 1a protected is intact.
3. Keep the web card gated as today.

Q1's judge named exactly what was missing; step 2 would have recovered it even before the parser fix.

### 3.8 Latency
**Shipped:**
- Reranker output as `[index, score]` pairs: about half the output tokens, and the 2026-09-24 probe measured −0.54 s median with top-8 agreement within Haiku's own run-to-run noise. The object form also ran near its 800-token cap on a full 54-chunk pool.
- Reformulation retrievals start when the rewrite returns, not after the primary retrieval. On Q2 the rewrite was back 1.2 s before the primary finished.
- Skip source groups that cannot match the jurisdiction filter: identical results, 9 of 31 groups skipped for a US flag.

**Proposed:**
- Take the analytics-only hedge audit and title generation off the path to the stream's `done` event.
- Keep the judge inline once §3.7 makes its verdict matter again.

The latency probes on the shared box were too noisy to rank configurations: the same configuration swung 1.5–4.6 s per `retrieve()`.

### 3.9 Credential "personal note" on an unrelated question — DECISION NEEDED
The credential block says "When relevant, tailor your answer…" and marks an expired certificate `EXPIRED`, so Opus 5.5 closed a bunker-certificate answer with a note about Karynn's medical certificate, adding that "the on-file dates look inconsistent".

Two actions:
- **Karynn:** check the dates on her medical certificate record.
- **Blake:** keep the proactive reminder, limit it to credential and eligibility questions, or move it to a UI banner. A prompt change re-runs `scripts/compare_synthesis_models.py` first.

### 3.10 Corpus gaps (Tier C)
- The Bunkers Convention 2001, CLC 1992 and the Nairobi WRC 2007 are not in the corpus. Q3 worked from a certificate list that quotes Art. 7.
- The Captain's Reg.20 questions and a COFR / Inland Rules pair belong in the gold set (roadmap item 7), so the harness finally covers citation resolution and non-46 CFR retrieval.

## 4. What shipped

Committed to `main`; see the commit messages for detail.

| Change | Files |
|---|---|
| SOLAS and CFR citation resolution (§3.1, 3.2) | `packages/rag/rag/retriever.py` |
| Vessel filter limited to Title 46 (§3.3) | `packages/rag/rag/retriever.py` |
| Reformulations without identifier search (§3.4); reverted 2026-09-26 | `packages/rag/rag/retriever.py` |
| Reformulations overlap the primary retrieval (§3.8) | `packages/rag/rag/retriever.py` |
| Reranker pairs (§3.8) | `packages/rag/rag/reranker.py` |
| From 2026-09-24: group skip, iterative scan on the explicit-source path only, `users.jurisdiction_focus` fallback for flag-Unknown vessels, quiz exam-bank vector retrieval | `packages/rag/rag/{retriever,jurisdiction,engine}.py`, `apps/api/app/routers/study.py` |

Tests: `packages/rag/test_solas_citations.py`, `test_retrieval_fanout.py`, `test_reranker_pairs.py`, `test_jurisdiction_focus.py`, and `apps/api/tests/test_study_quiz.py`. Current totals: rag 180 passed plus 1 pre-existing DB-bound failure (`test_hybrid_retrieve`); api 32 passed.

Commits: `18fb15f` (rag) and `505bde8` (study). Deployed 2026-09-26 with `78a7485` (§6).

## 5. Proposals, in recommended order

| # | Item | Effort | Needs |
|---|---|---|---|
| 1 | SOLAS stale-row cleanup plus a pipeline `--prune` step (§3.5) | ~3 h, plus a review of the diff list | go; deletes prod rows after a backup |
| 2 | Scope cfr_49 to maritime parts, in the adapter (§3.6) | ~2 h | go; changes the weekly refresh |
| 3 | Judge gate on text citations; corpus oracle on `partial_miss` (§3.7) | ~2 h | go |
| 4 | Gold-set pairs for citations and non-46 CFR (the Captain's Reg.20 questions, COFR, Inland Rules) | ~1 h | none |
| 5 | Hedge audit and title off the path to `done` (§3.8) | ~1 h | go |
| 6 | Credential reminder policy (§3.9) | 15 min, plus a compare-harness run | decision |
| 7 | After 1 and 2: a within-chapter SOLAS search, and the group iterative scan, each re-measured | ~1 h | none |

## 6. Follow-up, 2026-09-26 (Blake: "Greenlight all recommended")

### Deployed

- `78a7485`: the §4 batch plus Next.js 15.5.26.
- `2469c73`: the ingest prune tooling, the cfr_49 scope, the SOLAS parser fix and the gold pairs.

Smoke passed on both.

### The Captain's questions, re-run on prod

Run end to end on her vessel profile, in a throwaway conversation:

| | 2026-09-23 | 2026-09-26 |
|---|---|---|
| Reg.20 chunks in context (Q1) | 0 of 5 | all 5 |
| Reranker top-8 (Q1) | `[4,1,1,1,1,1,1,1]` | `[5,5,5,5,5,4,2,2]` |
| Judge (Q1) | `partial_miss` | `precision_callout` |
| Answer (Q1) | declined the intervals | gives the weekly, monthly, annual and 5-year cycle |

Q2 behaves the same way. TTFT was 13 s and 15 s.

### Gold set (item 4, `2469c73`)

Seven questions, nine pairs (A25-1 to A25-7): the Captain's citation, SOLAS III/20, V/19, 46 CFR 199.180, COFR (33 CFR 138), the Inland Rules' towing lights (33 CFR 83.24), and 49 CFR 176 segregation.

Dense arm, expanded set:

| arm | strong recall@8 | MRR |
|---|---|---|
| pre-audit rag | 0.7606 | 0.6337 |
| deployed rag | 0.8451 | 0.7178 |

The deployed rag gains 6 pairs and loses 0.

Full pipeline (`dense-prod`) on the deployed rag: 0.8873 / 0.7029, with 9 of 9 on the new pairs. On the 62 original pairs it read 54/62 against 57/62 on 09-23. The misses were marginal ranks on stale SOLAS rows: a `Ch.II-2 Part G` row at rank 7 and a 1-chunk `Ch.II-2 Reg.14` row at rank 4.

The same-day control and the ablation that would separate today's changes from run-to-run noise could not run: Anthropic credits ran out mid-session (see the incident below), and both runs are discarded. Re-run them with credits.

### SOLAS: the parser was the root cause, not only old rows

`_structural_part` cut header titles at their first hyphen. "Chapter II-1" became "Chapter II" and the Part was lost, so every Part of II-1 and II-2 (and XI-1 / XI-2) shared one section_number, and their chunks overwrote each other on upsert. The II-1 and II-2 Unified Interpretations collided the same way. Hyphenated regulations ("Regulation 3-1") were never split out.

`825c62e` fixes both, with tests on the real `headers.txt` lines, and merges any repeated section_number instead of overwriting it.

### Pruning and the cfr_49 scope (items 1 and 2, `1e41a87`)

`ingest/prune.py` adds `--stale-report`, `--prune-stale` and `--prune`.
- A prune is refused unless the parse yields no duplicate key and every key it yields is stored.
- Removed rows are copied to `data/pruned/<source>-<stamp>.csv.gz` in the same transaction as the DELETE.

cfr_49 now ingests hazmat 105–109, 171–173, 176, 178 and 180; Part 40; CSC 450–453; NTSB 831/850; and TSA 1520/1570/1572.
- Answers had cited 49 CFR 228 (railroad hours of service) twice.
- Until the out-of-scope rows were removed, the weekly update's 50% safeguard would have aborted cfr_49.

### Cleanup applied

Both sources were re-ingested with `run_ingest.sh --source <s> --fresh --prune --no-notify`, then `VACUUM (ANALYZE)`.

| source | before | after | removed | copy |
|---|---|---|---|---|
| SOLAS | 1,739 | 848 | 1,273 | `solas-20260926-003706.csv.gz` |
| cfr_49 | 15,967 | 3,145 | 12,823 | `cfr_49-20260926-003807.csv.gz` |
| corpus | 106,049 | 92,336 | | |

SOLAS details:
- The parse yields 848 chunks across 326 sections, with no duplicate keys.
- II-2 Reg.11 and Reg.19 appear twice in the source text and were merged.
- New names include `SOLAS Ch.II-1 Reg.13-1`.

The stale reports went to `data/pruned/*-report.json` before the apply.

**Dense harness, expanded set, same code, before and after the cleanup:**

| | strong recall@8 | MRR | p50 ms |
|---|---|---|---|
| before | 0.8451 | 0.7178 | 579 |
| after | 0.8592 | 0.6924 | 504 |

Two pairs gained (F1/V5; N-S1/V1, now SOLAS Ch.V Reg.20) and one lost (F1/V1).

The MRR loss sits in three fire-equipment pairs (F1/V1, F2/V1, N-AUTH2/V1). Their rank-1 hit had been a stale short row: the May 1-chunk `SOLAS Ch.II-2 Reg.10` or the `Ch.II-2 Part G` Part-level row. That regulation is now its real 23 chunks, which rank lower before reranking. The containership SCBA top 8 now includes the FSS Code Ch.3 firefighter's-outfit text, which the gold pattern does not list.

### Re-measured on the clean corpus (item 7)

**Chapter-cited SOLAS questions** (dense `retrieve()`, the Captain's vessel profile). With the deployed code and no chapter identifier, **8 of 8** hit:

| question | target | rank |
|---|---|---|
| II-2 fire detection | II-2 Reg.7 | 2 |
| III drill frequency | III Reg.19 | 1 |
| BNWAS | V Reg.19 | 1 |
| bilge pumping | II-1 **Reg.35-1** (a hyphenated regulation, newly split out) | 1 |
| ship security alert system | **XI-2 Reg.6** | 1 |
| steering gear | II-1 Reg.29 | 2 |
| two control questions with no chapter cited | II-2 Reg.7 / III Reg.19 | 1 / 1 |

The within-chapter search variant also got 8 of 8. Two ranks improved (2 to 1), in-chapter noise rose (V/35, V/17 in the BNWAS top 4), and the harness was identical. **Held back.**

**Group iterative HNSW scan**, dense harness on the clean corpus:

| | strong recall@8 | MRR | p50 ms |
|---|---|---|---|
| scan off | 0.8592 | 0.6924 | 504–546 |
| scan on | 0.8592 | 0.6975 | 640 |

Its earlier −0.027 MRR loss (49 CFR 391) went away with the cfr_49 scope, but what remains doesn't pay for the latency. **Still off.**

### Engine changes: verified on prod, then deployed (`51231cc`, first committed as `7080fce`)

The changes:
- The recovery gate counts citations in the answer text (§3.7), and the corpus oracle runs on `partial_miss`. The oracle's synthesis cap rises from 1500 to 8192.
- The precautionary judge and the hedge audit run after the done event (§3.8).
- The credential block applies only to credential questions (§3.9).

Measured on prod once credits were back, deployed engine vs this commit, on a synthetic US-flag containership profile:

| check | deployed | `51231cc` |
|---|---|---|
| last token → `done`, cited answer, no hedge | 3.7 s | **0.0 s** (the judge logs afterwards) |
| last token → `done`, hedged answer | 9.3 s | **4.4 s** (judge inline, audit afterwards) |
| bunker-CLC question, expired medical on file | mentions medical / credentials | **no mention** |
| "Can I sail as Master with my medical cert?" | uses the credential | still uses it |
| hedged `partial_miss` with 8 citations | no recovery | the oracle surfaced a verified 46 CFR 95.50-10 table quote; web card suppressed |

The oracle adds about 12 s before `done` when it runs (Haiku web search plus Sonnet synthesis). Only regex-hedged `partial_miss` answers pay it.

In a direct oracle call, Sonnet's quote failed the verbatim check on one of two runs, so that card was withheld by design (the additive-only contract).

### Full pipeline on the clean corpus (the control that the outage delayed)

`dense-prod` (rewrite + rerank), expanded gold set, 71 pairs, all on the same corpus:

| arm | strong recall@8 | MRR | p50 |
|---|---|---|---|
| pre-audit rag | 0.8732 | 0.6722 | 7.5 s |
| deployed rag, reformulations without identifier search | 0.9437 | 0.7062 | 5.9 s |
| **deployed rag, reformulation identifiers on (shipped)** | **1.0000** | **0.7301** | 6.1 s |

The audit's retrieval work beats the pre-audit code on the same corpus. Turning reformulation identifier search back on (§3.4, reverted) is worth 4 more pairs.

**New baselines to beat** (expanded 71-pair gold set, clean corpus):
- dense 0.8592 / 0.6924
- dense-prod 1.0000 / 0.7301

### Incident: Anthropic credits exhausted, 00:15 to about 02:10 UTC 2026-09-26

Every Claude call returned 400 "credit balance is too low". The GPT-4o fallback served:
- 10.6 s, not streamed;
- the router, rewrite, rerank and judge failed open;
- messages persisted (migration 0115).

No user asked a question during the outage. Credits were restored at about 02:10 UTC.

`eval_retrieval.py`'s `-prod` arms now refuse to run without the API, because two runs during the outage silently measured dense retrieval instead.

## 7. 2026-09-26 evening: MARPOL per regulation, MARPOL citations, IMDG, vessel flag (Blake: "Greenlight all")

No Anthropic calls. Embeddings for the two re-ingests and five dense harness runs cost a few cents of OpenAI.

### MARPOL

The adapter splits each Annex chapter at "Regulation N" headings. A heading has a blank line above it and its title on the next line. The same line with a blank line after it is a page running head, and it is dropped.

The D6.88 post-hoc split (`scripts/split_marpol_to_regulations.py`) had read those running heads as headings. As a result:
- "Annex I Reg.2" was titled "39 Electronic Record Book ...";
- an "Annex VI Reg.11" row existed, though the scan has no Regulation 11;
- 12A's text sat under Reg.12, because the pattern missed "Regulation 12A*".

The scan itself is damaged in five places, each fixed by a fix anchored on a line that occurs once:

| regulation | problem | fix |
|---|---|---|
| Annex I Reg.10 | heading page not scanned | opens at 10.8.3, with a note |
| Annex I Reg.26 | heading page not scanned | opens partway through, before paragraph 5, with a note |
| Annex I Reg.27, Reg.28 | pages out of order | text moved behind their headings |
| Annex VI Reg.13 (NOx) | heading page not scanned | opens at 13.5.1.2, with a note; without it the NOx text is labelled Reg.12 (ODS) |

Also:
- a P&A Manual page filed in the Annex III range moves to Annex II App.IV;
- Annex VI Reg.24's title is fixed.

Annex VI Regs 11, 19 and 20 are not in the scan at all.

Re-ingested with `--enrich-cache-only`:
- 610 rows, replacing 702;
- 251 pruned: 250 chapter rows, plus the D6.88 "Annex VI Reg.11", whose regulation the scan lacks;
- backup `data/pruned/marpol-20260926-171700.csv.gz`.

### Dense harness (79 pairs: the 71 + A26-1..7)

| run | corpus | retriever | strong recall@8 | MRR |
|---|---|---|---|---|
| B0 | chapter rows + D6.88 | text identifiers | 0.8354 | 0.6755 |
| B1 | per regulation | text identifiers | 0.8608 | 0.6793 |
| **B2 (shipped)** | per regulation | exact regulation + annex search | **0.8608** | **0.7046** |
| B2 without annex search | per regulation | exact regulation only | 0.8608 | 0.7046 |

- **B0 → B1:** A26-1 (Reg.14) and A26-2 (Reg.12A) go from no hit to rank 2. A26-6 (sewage, Reg.11) goes from 5 to 2.
- **B1 → B2:** A26-1, A26-2, A26-7 and N-E3 go from rank 2 to rank 1. No pair was lost in either step.

The annex search does not move the strong metric. A26-4 (2ndmate09's "annex V exemptions for throwing plastic overboard") misses Reg 3 and Reg 7 in every run. Its top 8 still differ:

| run | Annex V text in the top 8 |
|---|---|
| without annex search | none: COLREGs Rule 38 twice, 46 CFR 108.597 (line-throwing appliance), IMDG Index, 49 CFR 172.101 — the D6.24 failure |
| B1 (first 5 matching rows, storage order) | Reg.1 twice, Reg.6, Reg.10 |
| B2 (5 chunks nearest the query) | Reg.4, Reg.6, Reg.5 |

**Follow-up:** COLREGs Rule 38 still outranks the annex hits after `_rerank`'s boosts. Why Reg 3 and Reg 7 are not among the 5 nearest is the next thing to check. Neither needs any spend to investigate.

### IMDG

"Foreword" (the Vol.2 front matter) and "Part 3" (a Vol.1 placeholder) each came from two files. The later file overwrote the earlier file's chunks 0 and 1, so the Vol.1 foreword's opening chunks were missing. The parse now merges them.

Re-ingested fresh, no prune: 5 chunks new or changed, net +1.

### Vessel flag

`create_vessel` wrote `flag_state = 'Unknown'` whatever the user did, and no API body accepted a flag. The only writer was the chat's VESSEL_UPDATE side channel. That is why the Captain typed "confirming flag state" into the chat box on 2026-09-09.

Shipped:
- `flag_state` on vessel create, update and list;
- a one-click chat banner while the flag is Unknown, suggesting the flag from `jurisdiction_focus`;
- a Flag field in the vessel editor.

Verified in the deployed web bundle.

