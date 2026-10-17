# Answer latency audit, 2026-10-17

Blake: "We are a bit slow. I'm not sure if that's the nature of RAG, or if our new models are
noticeably faster. At a minimum, I'd like to know where and why we are slow. Is it a hardware
issue? Droplet too small?"

Everything here was measured on production without Claude calls: the API journal, the
`messages` table, `sar` history, and three read-only benchmarks against the live database
(OpenAI embeddings only). Scripts: `scripts/latency/` (see the end).

## The answer

A question takes **30 to 65 seconds to finish** and roughly **20 to 45 seconds before the first
word appears**. Three things make it slow, in this order:

1. **Model steps that run one after another before the answer starts:** rerank (2.5 s), the
   coverage check (3–5 s), web research when it runs (up to 15 s, about 4 questions in 10),
   then Opus's first token (about 6 s, up to 9 s; it always thinks first). Hardware cannot speed
   these up.
2. **The search stage (5–10 s), which is CPU-bound and does about four times more work than it
   needs to.** Each question runs four searches (the question plus three rewrites). After a
   connection's first few queries, Postgres stops using the vector index for the 23 source-group
   queries and computes the distance to every stored vector instead, so every search reads the
   whole library. Keyword checks then scan text one keyword at a time. One question costs
   Postgres 10–14 CPU-seconds, which takes at least 5–7 s on 2 vCPUs.
3. **Answers start later than in September:** about 7 s later without web research and about
   25 s later with it. The answer pipeline added the coverage check (every question) and web
   research (when coverage is partial) on 2026-10-09, and the searches slowed down: each of the
   four took 2.5–4 s in September and 5–10 s since 10-11, as the library grew to 111,700
   passages and gained source groups and the vessel lane.

**Hardware:** the droplet is not overloaded. It is 90% idle across the day, CPU steal averages
0.5%, and memory is not under pressure while answering. But during the search stage both cores
are pegged. Twice the cores would roughly halve the search stage (5–10 s to 3–5 s) and change
nothing else. Fixing the wasted search work is free and gains more.

**The models:** Haiku 5.5 made each sidecar call about 0.5 s faster (2026-10-07 measurement).
Opus 5.5 takes about 6 s to its first token (p90 8.7 s). The models are not the regression; the
extra stages are.

## Evidence

### Production timelines (API journal, last 45 days)

Seconds from the moment the answer stream opened. "Synth" is when the Opus call starts; "done" is
when the answer was saved (after streaming).

| when (UTC) | route | rewrite | search done | rerank done | coverage | web | synth | done | the 4 searches (s) |
|---|---|---|---|---|---|---|---|---|---|
| 09-10 16:51 | 0.8 | 1.9 | 7.0 | 12.2 | – | – | 12.2 | 26.1 | 2.6–3.6 |
| 09-25 04:49 | 1.1 | 2.7 | 6.8 | 12.3 | – | – | 12.4 | 42.3 | 3.1–3.6 |
| 10-02 02:50 | 1.3 | 2.8 | 7.0 | 9.5 | – | – | 9.5 | 31.5 | 2.5–4.1 |
| 10-08 00:50 | 1.8 | 2.0 | 7.6 | 12.4 | – | – | 12.5 | 30.7 | 5.0–6.0 |
| 10-09 00:02 | 1.7 | 1.8 | 4.5 | 6.5 | – | – | 6.5 | 32.4 | 1.8–2.6 |
| 10-11 04:05 | 2.5 | 2.8 | 10.3 | 12.9 | 17.7 | – | 17.7 | 30.5 | 6.0–8.5 |
| 10-16 19:08 | 1.5 | 3.2 | 12.9 | 15.4 | 20.6 | 35.6 | 35.6 | 65.2 | 8.2–10.3 |

The 10-16 question (Blake's free question, the first after a deploy) in full:

| stage | seconds | what |
|---|---|---|
| Turnstile + preflight | 0.3 | |
| distill (long first questions only) ∥ router | 1.3 | Haiku; distill runs before the search starts |
| query rewrite | 1.9 | Haiku, beside the first search |
| four searches, 23 groups each | 9.7 | Postgres; all four end within 1.5 s of each other |
| rerank | 2.6 | Haiku |
| whole sections | 0.05 | Postgres |
| coverage check | 5.1 | Haiku, reads ~20K tokens of library text |
| web research | 15.0 | hit the 15 s budget, found nothing |
| Opus, call to end of stream | 29.6 | 4,505 characters; first token not logged |
| **total** | **65.2** | first word at roughly 41–44 s |

First-token time is not logged anywhere. The 2026-10-09 A/B measured Opus's first token at a
median 5.6–6.5 s after the call starts (p90 8.7 s).

### Answer times in the database (question saved → answer saved)

| week of | answers | median s | p90 s |
|---|---|---|---|
| 09-07 | 6 | 25.9 | 41.3 |
| 09-14 | 4 | 47.9 | 49.7 |
| 09-21 | 3 | 36.9 | 41.3 |
| 09-28 | 5 | 27.1 | 29.8 |
| 10-05 | 8 | 26.5 | 37.2 |
| 10-12 | 2 | 65.2 | 65.2 |

### Hardware (`sar`, 8 days; `vmstat`; `free`)

- Droplet: Basic Premium Intel, 2 vCPU, 4 GB, 120 GB ($32/month), shared with five other
  tenants' sites.
- CPU across each day: user 4–6%, system 4%, **steal 0.5% average (max 3.4%)**, idle ~90%.
  The 19:00 sample on 10-16 (the free question) shows user 21%.
- Memory: 3.9 GB total, ~1.9 GB available, 0.9 GB of idle pages in swap, no paging during
  answers. Postgres `shared_buffers` 512 MB against an 873 MB HNSW index and ~700 MB of stored
  vectors; the rest sits in the OS page cache. I/O wait ~0%.
- API pool: asyncpg 2–10 connections.

### Retrieval benchmark on the live database (`scripts/latency/bench_retrieval.py`)

The four searches of the 10-16 question and a SOLAS III/20 set, warm:

| scenario | wall | Postgres CPU | host CPU busy |
|---|---|---|---|
| one search alone | 1.1–1.5 s | 2.1 CPU-s | 90% |
| four searches at once, pool 10 (production) | 5.2–7.0 s | 10–14 CPU-s (1.5–1.8 cores) | 88–99% |
| four searches at once, pool 20 | 5.2–6.4 s | 8–12 CPU-s | 99% |

Where one search's Postgres CPU goes (`scripts/latency/bench_phases.py`):

| phase | Postgres CPU per search |
|---|---|
| 23 group queries | 1.7–2.0 s |
| keyword frequency checks + keyword fetch (sequential) | 0.2–1.7 s ("towing" alone 0.40–0.45 s: a full-text scan) |
| vessel lane | 0.04 s |
| identifier search | 0.02 s |

### Why the group queries are expensive (`scripts/latency/bench_plans.py`)

The 23 group queries of one search, on one connection, under each plan mode:

| plan mode | Postgres CPU | rows returned | groups short of k | HNSW index scans |
|---|---|---|---|---|
| default, after the first round (production steady state) | 1.7 s | 144 | 0 | **0** |
| forced custom plan (uses the HNSW index) | 0.36–0.41 s | 109 | 7 | 8 |
| forced generic plan | 1.9–2.0 s | 144 | 0 | 0 |

asyncpg prepares each statement once per connection. After five executions Postgres caches a
generic plan, which filters by source and jurisdiction through the other indexes and sorts every
matching row by distance: an exact scan of the group. Every group of every search, four searches
per question, so each question reads all ~111,000 stored vectors four times. The vectors are
stored out of line (TOAST), which makes each read more expensive.

Two consequences:

- **The search is exact, which is why recall is good,** and nearly every query behind the
  dense-harness baselines ran this way. Any change must re-run the harness.
- **The first five group queries on each new pooled connection are planned one by one**
  (custom plans). When such a plan uses the HNSW index, the group can come back short: forcing
  custom plans on all 23 groups left 7 of them short of k. Right after a restart, searches
  differ slightly from steady state.

## What to do, ranked

| # | change | gain | cost / risk |
|---|---|---|---|
| 1 | Cache keyword frequency counts in the process (the same words are checked in all four searches and in most questions). | 0.2–1.7 CPU-s per search, about 1–5 s of wall time per question | Free. Identical results. |
| 2 | Choose the group-query plan on purpose. Measure on the dense harness: (a) the HNSW index with pgvector 0.8's iterative scan, forced custom plans; (b) keep exact scans but store vectors so they read faster (`halfvec` or in-line storage, a table rewrite). | Search stage from 5–10 s to roughly 2–3 s | Free to measure (dense arm, OpenAI only). (a) is a code change; (b) is a migration. Either removes the restart difference. |
| 3 | Web research: shorter budget (8 s), or only when coverage is "none", or answer first and add web findings after. | Up to 7–15 s on about 4 questions in 10 | Answer-quality A/B, about $4. |
| 4 | Coverage check on titles + first paragraphs instead of ~20K tokens of text. | 2–3 s on every question | A/B, about $4. |
| 5 | Log stage timings and first-token time per answer; show p50/p90 on the admin dashboard. | Makes this a number we watch | Free; small change in the engine and chat router. |
| 6 | Resize to Premium Intel 4 vCPU / 8 GB ($64/month, +$32). | Search stage roughly halved (only that stage) | Reboots the droplet and every tenant on it; the disk grows to 240 GB unless "CPU and RAM only" is chosen. Re-measure after 1–2 first. |

Fixes 1 and 2 should bring a typical question's first word from ~24 s to ~18–19 s without web
research. Getting near 10 s needs 3 and 4 as well (the sequential model steps).

## Shipped the same day (Blake: "greenlighting any speedups that don't negatively effect accuracy")

Droplet upgrade on hold (Blake). Every change below returns the same results; each was checked
before it shipped. Commits `bba1441`, `ef734a5`, `71cb7a7`; migration **0131**.

| change | how it was checked |
|---|---|
| **`regulation_vectors`** (migration 0131): the embeddings stored in-line, kept in step by a trigger + ON DELETE CASCADE. Group queries with a jurisdiction filter read it. | 92 of 92 group results identical on a scratch copy; dense harness 85 of 85 top-8 lists identical to the morning's baseline (0.9529 / 0.9765 / 0.7839). |
| Keyword lane: frequency checks and the per-keyword pick cached per process (6 h), one lookup in flight per keyword; rows re-read by id with the query's similarity. | Harness 85 of 85 identical sets (one tie reordered); 5 unit tests. |
| One OpenAI client per event loop (warm HTTPS). | Same API call; first embedding 1.3–1.9 s → 0.2–0.6 s. |
| Retriever caches loaded at API startup. | No change to results. |
| **The answer call starts while the coverage check runs** (`rag.engine._SpeculativeAnswer`) and is used only when coverage / web research leave the library text unchanged, i.e. when it is the very request the engine would send afterwards; otherwise cancelled. Kill switch `SPECULATIVE_ANSWER_ENABLED=false`. | 5 unit tests; two real questions on prod (~$0.25), both paths. |
| One `answer timing:` log line per answer (route, retrieval, context, coverage, web, synth_start, first_token, stream_end, done, speculative). | — |

**Measured and rejected:** the HNSW index with pgvector's iterative scan for the group queries,
three variants (relaxed / relaxed ef 100 / strict ef 100): recall unchanged but MRR 0.7718 / 0.7714
/ 0.7818 against 0.7839, and slower single searches (p50 1.9 / 1.1 / 1.0 s against 0.74 s).

**Found on the way:** without a jurisdiction filter the old group query's cached plan *does* use
the HNSW index (fast, approximate); the exact side table there changed results (MRR 0.7839 →
0.7714 when every group read it, the same pattern as the HNSW variants), so those groups keep the
old query. Real questions almost always carry a filter (every U.S.-flag vessel; flag-Unknown
vessels fall back to the user's jurisdiction focus).

**Results on prod:**

| | before | after |
|---|---|---|
| dense harness, strong / weak / MRR | 0.9529 / 0.9765 / 0.7839 | identical, 85 of 85 lists |
| one search, p50 / p95 (harness) | 738 / 1,566 ms | 629 / 1,133 ms |
| four searches at once (bench) | 6.5–9.5 s, 10–14 CPU-s | 1.9–2.8 s, 3–4.5 CPU-s |
| retrieval step incl. rewrite + rerank | 12–15 s | 5.4–5.9 s (warm) |
| first word, question the library covers | ~24 s (10-11, estimated: not logged then) | **13.5 s** |
| first word, question that needs web research | 41–44 s (10-16, estimated) | 31.2 s |
| finished answer, same two | 30.5 s / 65.2 s | 28.2 s / 44.0 s |

**What is left before the first word** (covered question): router ∥ rewrite ~2 s, the three
rewritten searches ~1.5–2 s, rerank ~2 s, Opus's first token ~5 s (it thinks first). All are model
calls whose output would change with any trim, so the next steps need an answer-quality A/B:
items 3 and 4 above, or a smaller rewrite / rerank. Raising Postgres `shared_buffers` so the
873 MB side table stays in Postgres's own cache could take a little more off the searches (a
Postgres restart, ~15 s of API downtime; the box is shared).

## Toward 10 seconds (Blake: "I'm ok with some A/B testing in an effort to speed up further")

**Where the first word's ~10 s goes on a warm API, question the library covers:** rewrite ~1.4 s,
the three rewritten searches ~1.7 s, rerank ~1.8 s, context ~0.1 s, Opus's first word ~4.7–5.1 s
(the coverage check runs beside it).

**Model settings, probed on captured real requests (`scripts/latency/ttft_probe.py`,
`thinking_probe.py`; ~$1.5, each answer replay stopped at its first word):**

| call | as sent | what else the API accepts | result |
|---|---|---|---|
| Opus 5.5 answer | effort `low`: first word 4.2–5.1 s, thinking starts at ~0.6–1.1 s | nothing lower: `minimal` / `none` effort, `thinking: disabled` and a thinking budget are all rejected | ~1 s is reading the input, ~3.5–4 s is thinking. Fixed at `low`. |
| Opus, prompt uncached | 4.65 s | — | The prompt cache doesn't change the first word, so keeping it warm buys nothing. |
| Opus, half the library text | 3.70 s | — | −0.5 to −1 s, but cutting the text needs an answer-quality A/B (whole sections were the 10-09 accuracy win). |
| Haiku 5.5 rewrite / rerank / coverage | effort `low`: 1.0–1.4 / 1.3–1.8 / 0.6–1.4 s | `thinking: disabled` (not `between_tools`, not `minimal`) | Thinking off is *slower* (1.7–2.3 / 1.7–2.3 / 1.2–1.9 s). Keep `low`. |

**Postgres:** a side-table scan costs ~8 µs a row even fully cached; the buffer cache saves ~30%
(268 → 185 ms on the cfr group). Raising `shared_buffers` to hold the 873 MB table would be worth
~0.3 s a question and needs a Postgres restart; not done.

**Retrieval A/B, dense-prod arm** (rewrite + rerank on, 85 pairs, three runs per arm, ~$2 of
Haiku; `data/eval/retrieval/*-dense-prod-ef0-ab-*.json`):

| arm | strong recall, mean (range) | weak recall | MRR, mean (range) | retrieval p50 / p90 |
|---|---|---|---|---|
| single rerank (as shipped) | 0.9765 (0.9765–0.9765) | 0.9882 | 0.8302 (0.8180–0.8406) | 4.60 / 5.94 s |
| **pipelined rerank** | 0.9765 (0.9647–0.9882) | 0.9765 | 0.8277 (0.8207–0.8319) | **3.98 / 5.54 s** |
| pipelined + 2 rewrites instead of 3 | 0.9529 (0.9412–0.9647) | 0.9765 | 0.8245 (0.8080–0.8347) | 3.53 / 4.70 s |

- **Pipelined rerank SHIPPED** (`d6caf26`): the primary search's ~30 candidates are scored while
  the rewritten searches run; only the candidates they add are scored after. Per pair, strong
  hits differed on two pairs and cancelled out (F1/V1 3→2 of 3 runs, N-M1/V1 2→3). The weak-recall
  dip is X4/V1 ("Is NFPA 1981 required"): NFPA isn't in the corpus and the weak pattern is any
  chunk mentioning "SOLAS".
- **Two rewrites rejected:** strong recall below the single arm in every run.
- **An answer call started on the primary search's context** (used only if the final context
  matched) can't pay off: the final context differed in 40 of 40 gold pairs
  (`scripts/latency/primary_context_probe.py`).

**Warm API, three real questions after the pipelined rerank** (`answer_e2e.py`, ~$0.45):
first word 12.9 / 9.9 / 9.6 s; retrieval 4.7–6.0 s; Opus's first word 3.6–7.8 s after its call
starts. Opus is now the long pole, and its thinking can't be shortened.

**Answer model, first word on captured requests** (`answer_model_probe.py`, ~$0.5): Opus 5.5 low
5.0–6.0 s; **Sonnet 5.5 low 0.5–0.9 s**; Sonnet 5.5 thinking off 0.6–1.0 s. (A smaller section
budget barely changes the input: contexts are mostly under 12K tokens already.)

**Answer-model A/B** (`compare_synthesis_models.py --model-ab --session-judge`, 24 questions:
14 gold, the Captain's 2, 4 hedged, this month's 4; each captured once with the production flags
and replayed under all three; $4.13 API; grading by 8 blind subagents on the subscription, labels
shuffled per question; `data/eval/model_compare/20261017-182446-model-ab/`):

| | Opus 5.5 low (shipped) | Sonnet 5.5 low | Sonnet 5.5 medium |
|---|---|---|---|
| first word, median / p90 | 6.3 / 8.8 s | **0.8 / 1.1 s** | 0.9 / 3.6 s |
| finished, median | 20.6 s | 10.0 s | 10.6 s |
| overall (blind) | **8.50** | 7.67 | 7.71 |
| accuracy (blind) | **8.42** | 8.04 | 7.88 |
| errors flagged | **23** | 30 | 33 |
| judged best | **16 of 24** | 4 | 4 |
| $ per answer, cold / warm cache | 0.165 / 0.090 | 0.076 / 0.040 | 0.078 / 0.042 |
| gold citation hit | 93% | 93% | 93% |

**Decision: Opus stays.** The rule set before grading was: switch only if Sonnet's accuracy is
not lower beyond noise, it has no more errors, and no question shows a serious Sonnet error that
Opus avoided. Sonnet fails all three (e.g. V1q ballast water, N-E4 hydrogen peroxide ERG,
WEEK2 pilot-ladder step measurement). Restricting Sonnet to the router's score-1 questions doesn't
rescue it (7.75 vs 8.50 on those 16). Caveat: the graders are Claude models; blind labels and
concrete error lists limit self-preference, and the 2026-09-23 run's GPT-4o judge also preferred
Opus.

**Where that leaves the first word:** ~10 s on a question the library covers (9.6–12.9 s measured
on a warm process), down from ~24 s this morning; ~5 s of retrieval (rewrite, searches, rerank,
each shown by the A/Bs to carry accuracy) and ~5 s of Opus thinking at its lowest effort.
Sub-10 reliably needs one of: a faster Opus-class model or a lower Opus effort if Anthropic adds
one; more CPU for the searches (4 vCPUs would take ~0.7–0.9 s off; droplet on hold); or accepting
Sonnet's quality drop.

**Found by the graders, not part of this work:** the hand-added IMDG row "IMDG 3.2 UN 2014
(manual)" says stowage category A; the 49 CFR 172.101 table shows vessel stowage D for UN2014.

## Scripts

Copied from the session to `scripts/latency/` (run on the VPS from `/opt/RegKnots/apps/api` with
the api venv's python; `PG_CID` is the postgres container id for the CPU counter):

- `timeline.py`: per-question stage timeline from the API journal and `messages`.
- `bench_retrieval.py`: the four-search fan-out, alone and concurrent, pool 10 and 20.
- `bench_phases.py`: Postgres CPU per retrieval phase, per keyword check.
- `bench_plans.py`: the group queries under each plan cache mode.
- `retrieval_phases.py`: rewrite, the four searches and rerank of one question, timed (Haiku only, ~$0.002).
- `answer_e2e.py`: one real answer through the production engine, timed, on a throwaway conversation (~$0.10–0.15 per question).
