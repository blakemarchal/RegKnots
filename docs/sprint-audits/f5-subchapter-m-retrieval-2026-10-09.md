# F5 / V5: Subchapter M fire rules never retrieved for a towboat — 2026-10-09

**Trigger.** The answer-pipeline phase-1 A/B (`docs/specs/answer-pipeline-2026-10-08.md`): gold question F5, "Do I need a fixed CO2 system on my vessel?", for gold vessel V5 (Mississippi Hauler: Towing / Tugboat, 198 GT, inland, U.S. flag, Subchapter M). `retrieve_enhanced` returned SOLAS, the FSS Code, ABS and the HSC Code in 4 of 4 runs, with no towing rule.

**Method.** Read-only SQL and embedding probes on prod. The candidate code ran from a sandbox copy (`/tmp/f5`; the deployed tree was not touched) through `scripts/eval_retrieval.py --arm dense`. A 4 + 4 run `retrieve_enhanced` replay checked the production path. Spend: OpenAI embeddings (~$0.01 per harness run, 8 runs) and ~$0.02 of Haiku 5.5 rewrite + rerank for the replay.

## 1. The section in question

- **46 CFR 142.240 is not the fixed-system rule.** It is "Inspection, testing, maintenance, and records" (Table 142.240: weigh the CO2 cylinders, recharge above 10% loss). The answer the A/B scored higher named it from memory, citing the wrong section for "do I need one".
- **The rule is 46 CFR 142.315.**
  - (a): a towing vessel certificated for rivers, lakes, bays and sounds (or within 3 nm on the Great Lakes), or older ocean / coastwise boats, needs **either** a 160-B semi-portable extinguisher **or** a fixed system for the engine room.
  - (b): ocean / coastwise boats contracted on or after 2003-08-27 need **both**.
  - 142.300: excepted vessels (§136.110) need not comply with 142.315–142.330.
  - Part 27 (27.303 / 27.305) is the same rule for uninspected towing vessels.
- All 22 Part 142 chunks are in `regulations` (cfr_46, tagged `us`, embedded). Nothing was missing from the corpus.

## 2. Why the right rule never surfaced

1. **The CFR group was empty for a towing profile.**
   - The cfr group's HNSW fetch (k = 12; 10 rows came back at ef_search 40) returned only parallel CO2 rules from other subchapters: 95.05-10 ×2, 169.564, 167.45-1, 167.45-45, 76.05-20, 118.410, 28.320, 181.410 and 193.05-10.
   - `_filter_by_vessel_applicability` runs after the fetch and dropped all ten.
   - With no CFR rows left, the next-nearest material was BV, IGC, FSS, NVIC 09-00 and SOLAS.
   - By exact cosine across the cfr sources, the first Subchapter M row ranked 133rd and 142.240 235th: the question says "my vessel", and Subchapter M's text does not embed near a generic CO2 question.
2. **The towing map forbade Subchapter M's own parts.** Parts 136–139 (certification, vessel compliance, TSMS, TPOs) were on the towing "forbidden" list under a "Subchapter L" label; Subchapter L is Parts 125–134.
   - Every towing profile lost Part 138 (TSMS), even with the D6.69 "tsms" boost firing.
   - Example: "What does our TSMS have to include?" for V5 returned no 46 CFR 138 row.
3. **Nothing lifts Part 142 for a towing profile.**
   - D6.69's Subchapter M affinity is query-text only ("subchapter m", "tsms", …), and it boosts the whole cfr group, which was empty.
   - The map's `applicable` sets were never read.
   - The +0.05 profile-term boost looked for the literal "towing / tugboat", which no chunk contains (same for "osv / offshore support").
4. **Nothing demotes international or class material.**
   - A U.S. flag or a `us` focus allows `{us, intl}`, so SOLAS, FSS, HSC and IGC pass the jurisdiction filter.
   - BV and ABS rows are not demoted for a U.S.-flag vessel either.
   - No step reads route or tonnage for applicability.
   - Prod sends `route_types` (a list); `_rerank` reads `route_type`, so the route boost the harness measures never fires in prod.

## 3. Did the gold set measure it? No.

- F5/V5 expected `46 CFR 144\.240` (no such section; 0 rows), "Subchapter M", or SOLAS II-2.
- N-F1/V5 ("What kind of fire suppression does my engine room need?") expected `46 CFR 144\.` (construction; no fire-suppression rule), "Subchapter M", SOLAS II-2 or "fixed fire". It **passed at rank 1 on SOLAS Ch.II-2 Reg.10** with no towing rule in the top 8.
- F5/V5 failed in every run, but the failure pointed at a section that doesn't exist.

**Corrected** (`scripts/eval_rag_baseline.py`):
- F5/V5: `46 CFR 142\.3(00|15)`, `46 CFR 27\.30[35]`, `Subchapter M`.
- N-F1/V5: `46 CFR 142\.3(00|15|25)`, `46 CFR 27\.30[35]`, `Subchapter M`.
- SOLAS was dropped from both: it does not apply to an inland 198 GT towboat.
- New pair A27-1/V5, "What does our TSMS have to include?" → `46 CFR 138\.`.
- 80 pairs. Both gold sets were run below.

## 4. The fix (`packages/rag/rag/retriever.py`)

- **Map fix.**
  - Towing: Parts 136–139 move from forbidden to applicable.
  - OSV: `applicable` is now 125–134 (was 125–139); 136–139 are forbidden.
- **Vessel lane.** For a vessel type with an applicability entry (and a `us` jurisdiction scope), one more fetch runs per `retrieve()`:
  - It is an exact cosine search over the type's applicable 46 CFR parts, k = 8, through a `MATERIALIZED` CTE (towing: 294 rows, ~30 ms via the `(source, section_number, chunk_index)` index).
  - When the question says "my / our / this vessel | boat | ship", the lane searches with that phrase replaced by the type's noun ("my towing vessel"), embedded in the same OpenAI call as the question. Otherwise it searches with the question as asked.
  - A lane row the cfr group already holds keeps the higher similarity.
- **Profile term.** "towing / tugboat" and "osv / offshore support" match the regulations' nouns ("towing vessel", "offshore supply vessel") for the existing +0.05 boost.
- `retrieve_hybrid` is unchanged (hybrid is off; ⛔ measured 2026-07-19).

## 5. Measured

Dense harness, prod DB, 2026-10-09 (files `data/eval/retrieval/20261009-02*`). "Orig" is the 79-pair gold set as it was; "new" is the corrected 80-pair set.

| code | orig strong / weak / MRR | new strong / weak / MRR |
|---|---|---|
| deployed (`5aeeebb`) | 0.9367 / 0.9620 / 0.7563 | 0.9125 / 0.9375 / 0.7343 |
| A: lane, vessel noun appended to every question | 0.9367 / 0.9494 / 0.7276 | 0.9500 / 0.9625 / 0.7473 |
| B: lane, noun only for "my vessel" | 0.9367 / 0.9620 / 0.7563 | 0.9375 / 0.9625 / 0.7531 |
| **C: B + profile-term fix (shipped candidate)** | **0.9367 / 0.9620 / 0.7616** | **0.9375 / 0.9625 / 0.7646** |

**C, per pair** (no pair lost on either set):

| pair | deployed → C | C's top rows |
|---|---|---|
| F5/V5 (new) | miss → 1 | 27.303, 27.305, BV, BV, 136.205, NVIC 09-00 … |
| A27-1/V5 (new) | miss → 1 | 138.220, 138.205, 138.220, 138.215, 138.210 |
| F1/V5 | 3 → 1 | **142.226 Firefighter's outfit** (Subchapter M) first |
| A25-6/V5 | 4 → 3 | |
| E1/V5 | 2 → 6 | 141.305 "Survival craft requirements for towing vessels" and 141.370 now outrank the 160.156 design standard. For a towboat that's the more useful answer; 140.801 (towing gear) and 143.225 are noise. |
| N-F1/V5 (new) | miss → miss | 142.330 (fire detection) at 3; 142.315 not in the top 10. The question says "my engine room", not "my vessel", so the lane uses the plain question. |

- **A was rejected.** Appending "(tank vessel)" / "(containership)" to questions that never mention the user's vessel lifted generic Subchapter D / I rows over the right answers:
  - N-S2/V2 1 → 5 (35.35-70 cargo-hose maintenance first);
  - N-S2/V1 3 → 6;
  - N-E2/V2 1 → 2 (154.1760 above the ERG guide);
  - N-M1/V1 lost its weak hit (ammonia transfer rules for an HRA question).
- **B moved no pair on the original set.** In B's run on the new set, N-E3/V1 went 1 → 2. That is an ERG tie flipping: the same code and question did not move in B's orig-set run.

**Production path** (`retrieve_enhanced`, rewrite + rerank, `jurisdiction_focus='us'`, F5/V5, 4 runs each):

| | towing rule in the rerank pool | 142.315 in the final 8 | 27.305 / 27.303 in the final 8 |
|---|---|---|---|
| deployed | 0 / 4 | 0 / 4 | 0 / 4 |
| C | 4 / 4 | **4 / 4** (ranks 3, 5, 5, 4; rerank 4) | 4 / 4 (27.305 at 1 twice, rerank 5) |

- The deployed answers were SOLAS II-2 Reg.10, FSS Ch.5, NVIC 09-00 / 06-72, HSC Ch.7 and BV.
- C keeps SOLAS / FSS at rerank 4 next to the towing rules: the reranker doesn't know the vessel type (§6).
- One C run put 33 CFR 175.315 (recreational boats) first. It is not a lane row (the lane is cfr_46 only); it came from a reformulation's retrieval, and the vessel filter covers Title 46 only.

**Latency.** `retrieve()`, 6 questions × 5, warm, base and C interleaved: p50 449 → 538, 409 → 442 and 591 → 1,153 ms. The third round ran while the box was busy (base rose to 591 too). Expect +30–90 ms per `retrieve()`. In prod, `retrieve_enhanced` runs four `retrieve()` calls, so that is four ~30 ms exact scans added to ~124 group queries.

## 6. Not done / next

- **The reranker doesn't see the vessel.** It scored SOLAS II-2 Reg.10 and the FSS Code 4, the same as 142.315, because "my vessel" carries no type. Passing the vessel type and route to `rerank_chunks` (or the "my towing vessel" phrasing) would order them. That is a prompt change, so it needs `--arm dense-prod` before and after (~$0.30 at Haiku 5.5 prices).
- **N-F1/V5** stays a miss on the dense arm. Widening the "my vessel" substitution to "my engine room" and similar phrases would reach it, but the same rule hit containership and tanker pairs in variant A. Not done.
- **`route_types` vs `route_type`**: measured and resolved; see §7.
- **Applicability by route / tonnage** (SOLAS for an inland 198 GT towboat) is not attempted. N1/V5 expects COLREGS, which is tagged `intl` too, so a blanket `intl` demotion for inland routes would lose it.
- The other vessel types' forbidden lists still label 125–139 "Subchapter L". 136–139 are forbidden for those types either way, so this is cosmetic.

## 7. The route boost prod never had (follow-up, same day)

`_rerank` gave +0.05 to chunks containing the profile's `route_type`. Chat sends `route_types` (the `vessels` column, a list) and never `route_type`, so prod never had the boost. The eval harnesses sent `route_type` (`eval_rag_baseline.VesselProfile.profile_dict`; `compare_synthesis_models` sends both keys), so every dense baseline before this one measured a boost prod didn't apply.

Dense harness, 80-pair corrected set, lane fix in place (`data/eval/retrieval/20261009-03*`):

| profiles | route boost | strong / weak / MRR |
|---|---|---|
| harness shape (`route_type`) | on | 0.9375 / 0.9625 / 0.7646 |
| prod shape (`route_types`), retriever ignores it | off | **0.9500 / 0.9750 / 0.7874** |
| prod shape, retriever reads `route_types` too | on | 0.9375 / 0.9625 / 0.7646 |

- Turning the boost on for prod measured worse: F1/V1 lost (4 → miss), N-AUTH2/V1 1 → 6, N-C1/V5 1 → 4, N-V2/V1 4 → 7; gains N-C2/V5 4 → 1 and N-S1/V1 4 → 2.
- The route term "international" adds 0.05 to every IMO and foreign-flag chunk, ahead of the U.S. rule a U.S. containership needs.
- **Change:** `_rerank` no longer reads a route at all. Prod is unchanged; the harnesses now measure what prod does, whichever key they send.
- `eval_rag_baseline` now sends `route_types`, as chat does.

**The honest before / after for this whole change**, with prod-shaped profiles:

| gold set | deployed (`db76a13`) | after | pairs |
|---|---|---|---|
| corrected, 80 pairs | 0.9250 / 0.9500 / 0.7582 | **0.9500 / 0.9750 / 0.7874** | F5/V5 and A27-1/V5 miss → 1, F1/V5 3 → 1, E1/V5 2 → 6 |
| original, 79 pairs | 0.9494 / 0.9747 / 0.7804 | 0.9494 / 0.9747 / 0.7847 | F1/V5 3 → 1, E1/V5 2 → 6 |

- No pair lost on either set.
- The final code gives identical numbers with the old `route_type` profiles.
- **New dense baseline: 0.9500 / 0.9750 / 0.7874 (80 pairs).** Earlier baselines include the route boost.
