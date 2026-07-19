# Hybrid retrieval investigation — verdict (2026-07-19)

**Question (Blake):** the hybrid BM25+RRF path (built D6.71, dark since) —
investigate before flipping. Preference was to flip to the "better" system
and tune that, rather than tuning the incumbent.

**Answer: dense IS the better system. Do not flip hybrid as built.**

## Method

`scripts/eval_retrieval.py` — retrieval-only harness calling `retrieve()`
and `retrieve_hybrid()` directly (no synthesis, no reranker, no web
fallback) over the 62 graded (question × vessel) pairs from the curated
gold set in `eval_rag_baseline.py`. STRONG hit = expected regex matches a
top-8 chunk's section_number/title. Deterministic; embeddings only.

## Results (evidence: `data/eval/retrieval/*.json`)

| arm | strong recall@8 | weak recall@8 | MRR | wrong-sub pairs | p50 ms |
|---|---|---|---|---|---|
| **dense (production)** | **0.790** | **0.903** | **0.627** | 0 | 550 |
| hybrid RRF k=60 | 0.548 | 0.726 | 0.416 | 0 | 653 |
| dense ef_search=100 | 0.790 | 0.903 | 0.627 | 0 | 591 |
| hybrid ef_search=100 | 0.548 | 0.726 | 0.416 | 0 | 636 |

- Hybrid **loses 16 pairs, gains 1** — a 24-point recall regression.
- `hnsw.ef_search` 40→100 changes **nothing** (identical to 4 decimals on
  both arms): the HNSW graph is not the recall bottleneck at our per-group
  fetch sizes. Not shipping that knob.

## Failure mechanism (from `--compare` lost-pair dumps)

RRF is rank-based and magnitude-blind. The lexical lane's per-group
budgets surface chunks that match query WORDS but not the query's topic —
COLREGS Rule 27, WHO IHR articles, MLC standards, flag-state notices —
and RRF fuses them at equal footing with dense's semantically-correct
hits. Concrete case: E1/V5 has the correct section at dense **rank 1**;
in the fused list it is pushed **out of the top 8 entirely** by
lexical-lane chunks. The lexical lane doesn't supplement dense — it
vetoes it, one displaced slot at a time, across every source group.

## Standing decision

1. `hybrid_retrieval_enabled` stays **False**. A ⛔ MEASURED comment now
   sits on the flag in `apps/api/app/config.py` so nobody flips it
   casually. Any future flip must re-run this eval and beat dense.
2. If hybrid is ever revisited, the redesign directions that fit the
   evidence: (a) weighted fusion (dense-dominant, lexical as tiebreak),
   (b) lexical hits feed the RERANKER POOL only (rerank_pool_size=30)
   rather than the fused top-k, so Haiku adjudicates lexical candidates
   instead of RRF trusting them, or (c) gate the lexical lane to
   identifier-shaped / rare-term queries where BM25 actually helps.
3. Per-ingest full REINDEX removed (lock cost, zero recall benefit —
   measured); weekly `REINDEX CONCURRENTLY` via
   `regknots-db-maintenance.timer` handles graph upkeep.
4. The harness is the new gate: **any retrieval change (boost, synonym,
   fusion, index param) runs `eval_retrieval.py` before shipping.**
   Baseline to beat: strong-recall@8 **0.790** / MRR **0.627**.

## Baseline gap worth mining later

Dense's own misses (13/62 pairs lack a strong hit) are the real tuning
target now. `data/eval/retrieval/20260719-050849-dense-ef0-baseline.json`
has per-pair `top` dumps — start there for the next boost-calibration
sprint, and grow the gold set as real user misses accumulate.
