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
   then Opus's first token (5–8 s, it always thinks first). Hardware cannot speed these up.
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
Opus 5.5 takes 5–8 s to its first token. The models are not the regression; the extra stages are.

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
- **The first five group queries on each new pooled connection use the HNSW index instead**
  (custom plans), and 7 of 23 groups then return fewer than k rows. Right after a restart,
  searches differ slightly from steady state.

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

## Scripts

Copied from the session to `scripts/latency/` (run on the VPS from `/opt/RegKnots/apps/api` with
the api venv's python; `PG_CID` is the postgres container id for the CPU counter):

- `timeline.py`: per-question stage timeline from the API journal and `messages`.
- `bench_retrieval.py`: the four-search fan-out, alone and concurrent, pool 10 and 20.
- `bench_phases.py`: Postgres CPU per retrieval phase, per keyword check.
- `bench_plans.py`: the group queries under each plan cache mode.
