# LLM Surface Audit — 2026-09-22

**Scope.** Every Anthropic call site in the app (`apps/api`, `packages/rag`, `packages/ingest`, `scripts`) — which model, how it is called, how the response is read, what it costs — against the current Claude API surface (Opus 5.5 / Sonnet 5 / Haiku 4.5; SDK 1.8.0 on PyPI). Triggered by Blake's "the full app could use an audit — suggest upgrades" alongside the Opus 5.5 rollout. Every number below is from the repo, the prod journal, the prod database, or a live API call today; nothing is from memory.

**Headline.** The model choices are current (Haiku 4.5 sidecars, Sonnet 5 everywhere else, Opus 5.5 as of today). What is *dated* is how the calls are made: **no prompt caching** on a ~9K-token static system prompt that is re-sent on every question, **no structured outputs** (JSON is scraped out of prose with regex in six places), **every sidecar runs sequentially** (5.7 API round trips per question, one after another), and the SDK is a **major version behind** (0.86.0 vs 1.8.0). None of this is broken today at ~10 questions/month. All of it is what makes the product slower and more expensive than it needs to be the moment Karynn's push works. Ranked upgrade list in §3; effort estimates assume the eval harness runs before and after each.

---

## 1. Inventory — 35 call sites

| Model | Where | Calls / question | Notes |
|---|---|---|---|
| **Haiku 4.5** (`claude-haiku-4-5-20251001`) | router (`max_tokens=10`), query_distill, query_rewrite, reranker, hedge_judge, citation_oracle, hedge_audit, chat title (`max_tokens=24`), support reply, study quiz + fast guide, `uscg_bulletin` ingest classifier | 4–5 | The right model for these. The only `cache_control` in the repo is on the bulletin classifier. |
| **Sonnet 5** (`claude-sonnet-5`) | synthesis (score 2), citation-oracle synthesis, web_fallback ×2, checklists, credentials, documents, `me.py` ×6 co-pilots, study deep guide, ingest enricher, ISM/STCW vision, three OCR scripts, `generate_sailor_queries` | 1 | Verified live today: with `thinking` omitted, Sonnet 5 returns `['text']` only — so `response.content[0].text` is safe *on Sonnet* (see F4). |
| **Opus 5.5** (`claude-opus-5-5`) | synthesis (score 3 + every followup turn), regeneration | 0–1 | Shipped today; `_opus_kwargs()` sends explicit effort + 16K cap, `_text_of()` reads by block type, refusal → GPT-4o fallback. |
| GPT-4o (OpenAI) | `fallback.py` — Claude-outage fallback and web-fallback ensemble member | 0 | Unchanged. Its `max_tokens` shares `_MAX_TOKENS = 8192`. |

**Per question, measured (30 days of journal):** 57 Anthropic POSTs / 10 questions = **5.7 calls**, all awaited in sequence (`asyncio.gather` appears nowhere in `engine.py`). Order: router → distill → rewrite → *retrieval* → rerank → synthesis → judge → oracle.

**Token profile, measured (prod DB):** synthesis input averages **17,789 tokens** (`retrieval_misses`, n=111, range 6.1K–35.4K), output 1,504. Assistant messages: Haiku p50 10.3K / p90 17.0K tokens, Sonnet p50 11.4K / p90 22.6K, Opus p50 18.6K / p90 25.6K (`tokens_used` = in+out). Input outweighs output ~12:1.

**The static prefix, measured:** `assemble_system_prompt()` = 39,110 chars / **8,944 cl100k tokens** (9,381 with Precision Mode) — Anthropic's tokenizer runs ~1.1–1.3× that, so **~10–11.5K tokens**, i.e. **55–65% of every synthesis call's input**. It is byte-identical across users for a given `precision_mode` flag: vessel profile, document extractions, credential context and jurisdiction priors are all injected into the *user turn* by `_build_chat_messages()`, never into `system`.

**SDK:** `anthropic==0.86.0` (prod, both local venvs; `>=0.49.0` in three pyprojects). PyPI: **1.8.0** latest, 0.125.0 newest 0.x. 0.86 already exposes `output_config.format`, `messages.parse()`, `web_search_tool_20260209`, `cache_control` with `ttl`, adaptive thinking — every upgrade in §3 except the SDK bump itself is implementable today. It lacks typed `stop_details` and the `xhigh` effort literal.

---

## 2. Findings (ranked by leverage)

### F1 — Zero prompt caching on a 10K-token static system prompt
One `cache_control` in the whole repo, on the bulletin ingest classifier. The synthesis call re-sends the same ~10K-token `system` string on every question at full price. With `system` split into two blocks and `cache_control: {type: "ephemeral"}` on the static first block, reads bill at **0.1× input** — Sonnet 5 $2.00 → $0.20/MTok, Opus 5.5 $4.00 → **$0.20** (its cache-read discount is 0.05×). Per synthesis call that is ~$0.018 (Sonnet) to ~$0.038 (Opus) of a ~$0.04–0.08 call, plus a shorter prefill before the first token.

**The honest caveat:** the 5-minute TTL only pays when questions arrive within five minutes of each other across *any* user (the prefix is shared), and the first write costs 1.25× (2× for the 1-hour TTL). At today's ~10 questions/month the cache is cold on nearly every call and the saving is ~zero. At one question every few minutes — a classroom of cadets, a fleet's compliance officers, a demo — it is 40–60% off the largest line item. Cheap to ship now, pays on the push. The system prompt must stay byte-stable (it does — no timestamps or per-user text in it) and the breakpoint must sit before the first volatile byte.

### F2 — JSON scraped from prose instead of structured outputs
`_parse_json` is copy-pasted in six files (18 hits); `json.loads` on model output appears 67 times, mostly wrapped in "strip the code fence, regex for `{.*}`" fallbacks (reranker, query_rewrite, citation_oracle, hedge_judge, study, documents, `me.py`). The May roadmap's item 13 — the transient `list index out of range` crash on regen retries that "couldn't reproduce" — is the classic symptom of this pattern. `output_config: {format: {type: "json_schema", ...}}` (or `client.messages.parse()` with a Pydantic model) makes the API guarantee the shape; the SDK in use already supports it. This also removes the need for `strict`-less prompt begging ("Return ONLY a JSON object…") in the sidecar prompts.

### F3 — 5.7 sequential round trips per question
Router, distill and rewrite are independent of each other (all take only the query); judge and oracle are independent of each other (both take the answer + chunks). Two `asyncio.gather` calls would collapse ~4 serial Haiku latencies (each ~1–3 s) into 2, an estimated **2–4 s off every answer** — a bigger TTFT win than any model change. A later step folds router + distill + rewrite into a single structured-output Haiku call (one round trip, one prompt to maintain).

### F4 — Positional text reads in five API routers
`response.content[0].text` at `checklists.py:529`, `credentials.py:695`, `documents.py:185`, `support.py:103`, `chat.py:1500`, `router.py:66`. Safe today (verified: Sonnet 5 and Haiku 4.5 return a lone `text` block), and fatal the day any of them is pointed at Opus 5.5 — exactly the bug the regen path had. `_text_of()` now exists in `engine.py`; promote it to the shared helper (F8) and use it everywhere. Ten minutes of hardening.

### F5 — No refusal handling outside the chat engine
Sonnet 5 and Opus 5.5 run safety classifiers (`cyber`, `bio`, `reasoning_extraction`) that return **HTTP 200** with `stop_reason: "refusal"` and empty content — no exception. As of today the streaming synthesis path logs it and falls back to GPT-4o; `documents.py` (certificate photos), `credentials.py`, `checklists.py` and the six `me.py` co-pilots would return an empty string to the user. This corpus carries WHO IHR sanitation, fumigant (IMDG/ERG) and ballast-water-organism material, which is where a `bio` false positive would come from. A 4-line guard per site, or one guard in the shared helper.

### F6 — Web fallback on the 2025 search tool
`web_fallback.py` declares `web_search_20250305` twice and then post-filters results against a domain whitelist in Python. `web_search_20260209` (supported on Sonnet 5 and Opus 5.5) does dynamic filtering server-side and takes `allowed_domains` natively — fewer irrelevant hits reaching the whitelist, and less code. Note: it runs code execution under the hood, so `code_execution` must not also be declared.

### F7 — PDFs rasterized to PNG before vision
`documents.py:154–165` converts uploaded PDFs to PNG pages and sends them as `image` blocks. A COI or CSC plate that arrives as a *text* PDF loses its text layer in the round trip and gets OCR'd from pixels. The API accepts PDFs directly as `document` blocks (base64, up to 32 MB / 600 pages, no beta); keep the image path for photos. Pairs naturally with F2 (structured extraction of the fields the vessel profile needs).

### F8 — SDK 0.86.0 → 1.8.0
A full major version behind. Blockers in this codebase: none found — no `with_raw_response`, no Text Completions, no `output_format`; the one `chat.completions` hit is the OpenAI client. The 1.x changes are httpx 2, awaited async raw responses, removed deprecated aliases, Python ≥ 3.10 (prod is 3.12). What it buys: typed `stop_details`, `xhigh` effort, current model constants, two years of fixes. Its own session with the skill's `sdk-upgrade.md` guide; do it before F2 so the structured-output types are the current ones. Also the moment to extract `app/llm_helpers.py` (May roadmap #9 — the Sonnet boilerplate copy-pasted 6× in `me.py`).

### F9 — Corpus enrichment runs online
`ingest/enricher.py` calls Sonnet 5 once per chunk (8–12 aliases each) with rate-limit pacing. The Message Batches API is **50% off** and has no per-minute ceiling; enrichment has no latency requirement. The Tier A IMO plan in `docs/roadmap.md` is ~29 engineering hours of ingest ahead — every one of those runs should batch.

### F10 — OCR on Sonnet 5 vision
The three OCR scripts (`ocr_scanned_nmc.py`, `ocr_imdg_screenshots.py`, `ocr_marpol_screenshots.py`) and the ISM/STCW adapters use Sonnet 5 vision. Per Anthropic's Opus 5.5 migration notes, Opus 5.5 reads dense charts, tables and scans more accurately at *every* effort level than earlier Opus at its highest, at roughly a tenth of the output tokens — and at `low` effort it costs $4/$20. Candidates: the 7 scanned NVICs that still resist OCR, and the scanned pages in the Tier A IMO instruments.

### F11 — Study quiz generation on Haiku 4.5
`study.py`: quizzes and the fast guide on Haiku (6 quizzes so far, ~3.3K in / 2.4K out each). Exam-prep questions are the one place a cadet will notice a wrong answer key. Sonnet 5 at the same token counts is ~$0.03/quiz. Product call, not an engineering one.

### F12 — Tier-aware model floor is now cheap
Roadmap item 8 (a model floor for Captain) was priced at Opus 4.8 rates. Opus 5.5 at `low` effort on a typical 18K-in / 1.5K-out question is ~**$0.10** — for a $39/month user asking a handful of questions a day, well inside margin. Still a product decision; the number just moved.

---

## 3. Upgrade list

| # | Upgrade | Effort | Payoff | When |
|---|---|---|---|---|
| U1 | **Sidecar parallelism** — `gather(router, distill, rewrite)` and `gather(judge, oracle)` (F3) | ½ day | −2–4 s per answer; no model change | Now |
| U2 | **Harden positional reads + refusal guard** in the five routers via a shared `_text_of` (F4, F5) | ½ day | Removes the Opus-5.5 landmine and silent empty answers | Now |
| U3 | **Prompt caching** on the static system block (F1) | ½ day | ~0 today; 40–60% of synthesis input cost at push volume; faster prefill | Now (cheap), pays later |
| U4 | **SDK 0.86 → 1.8** with the migration guide; extract `llm_helpers.py` in the same pass (F8) | 1 day | Prerequisite for clean U5; kills the 6× boilerplate | Before U5 |
| U5 | **Structured outputs** for reranker, rewrite, oracle, judge, study, documents, `me.py` (F2) | 2 days | Deletes six `_parse_json` copies and the regex fallbacks; ends the transient parse crashes | After U4 |
| U6 | **`web_search_20260209`** + native `allowed_domains` in web fallback (F6) | ½ day | Better fallback hits, less post-filter code | Any time |
| U7 | **Native PDF `document` blocks** + structured extraction in `documents.py` (F7) | 1 day | Better COI/CSC extraction; fewer "review the extracted data" corrections | With U5 |
| U8 | **Batch API for enrichment** (F9) | ½ day | 50% off every corpus sprint from here on | Before Tier A IMO ingest |
| U9 | **Opus 5.5 `low` vision** for the OCR scripts (F10) | ½ day | The 7 stuck NVICs; better IMO scans | With Tier A |
| U10 | Quiz generation → Sonnet 5 (F11) | 1 h | Exam-key accuracy | Karynn's call — **shipped 2026-09-23 on Blake's go; see §6** |
| U11 | Captain model floor at Opus 5.5 `low` (F12) | 1 h | Best model for the paying tier at ~$0.10/question | Blake's call |

**Sequencing that respects the standing rules:** U1–U3 are each a spec-then-go and each gets a before/after on `scripts/eval_retrieval.py` (retrieval is untouched, so the check is that the score *doesn't move*) plus a five-question answer-quality spot check. U4 first, then U5. U8 before the next ingest sprint.

**Not recommended:** moving the Haiku sidecars up a tier (they are classification/ranking tasks and Haiku 4.5 is the current Haiku); the embedding model (twice audited as not the bottleneck); re-enabling hybrid retrieval (measured, 2026-07-19). Fast mode on Opus 5.5 ($8/$40) — time to first token is dominated by retrieval (8–19 s of DB fan-out + rerank before synthesis starts, measured §4 U1 and §5), not by output speed. *(This line originally blamed the sequential sidecars; U1 measured otherwise.)*

---

## 4. Outcome — shipped the same day (Blake: "greenlight all recommended items")

Commits `f64bbfc` (rag), `cb7cf27` (api), `25eabf5` (ingest/scripts); deployed via `scripts/deploy.sh`, smoke OK. U10 and U11 stay product calls. What the measurements changed about the plan:

| # | Result | Measured |
|---|---|---|
| U1 | **Rescoped, shipped.** The audit's premise was wrong twice: the oracle consumes the judge's verdict and `missing_topic` (dependent, not parallel), and `retrieve_enhanced` already runs its rewrite + per-reformulation searches concurrently. The only independent pair was router ∥ retrieval: the Haiku router now runs as a task beside retrieval; off-topic cancels the in-flight retrieval, a client disconnect cancels both. | Prod: router 0.5–1.0 s fully hidden under retrieval (7.6–11.6 s). **~0.6 s per answer, not 2–4 s.** Pre-synthesis time is the DB fan-out (31 source-group queries × 4 `retrieve()` calls on a 2-vCPU box, 128 MB `shared_buffers` against an 828 MB HNSW index) plus the 2.7–3.4 s rerank. Overlapping reformulation searches measured no gain at pool 10; with a 30-connection pool they saved ~1.2 s but put ~124 concurrent vector queries on 2 shared cores — not shipped. That is a DB decision (shared_buffers / fan-out), not a code one. |
| U2 | Shipped. `rag/llm.py` `text_of()` everywhere a response is read; refusals and max_tokens logged. | — |
| U3 | Shipped on the synthesis stream and both regeneration calls. | **The static prefix is 14,559 tokens, not ~10K** (cl100k undercounted). Prod: Sonnet stream wrote 14,560; the Opus followup stream wrote 14,559 and **the next two Opus regenerations read 14,559 from cache** — stream and regen share the prefix. Cold calls pay 1.25× on the prefix (~$0.007 Sonnet / ~$0.015 Opus) at today's volume. |
| U4 | Shipped. `anthropic` 1.8.0 in all three projects; no code needed changing for the major. | — |
| U5 | Shipped: reranker, rewrite, judge, hedge audit, citation oracle (+ its synthesis), six `me.py` co-pilots, quiz, guide, PSC checklist, credentials, documents, bulletin classifier. 18 schemas validated against the live API before deploy. | The first documents schema (20 nullable fields) was **rejected by the API** — too many union-typed parameters. Redesigned to 2 unions with `""`/`[]` sentinels mapped back by `_flatten_extraction`; `apps/api/tests` now caps unions at 8 per schema. |
| U6 | **Not shipped.** | `web_search_20260209` on a real fallback query: 40.1 s, 7 code-execution rounds, no usable answer; `allowed_domains` cannot express the `*.gov` / `*.mil` suffix whitelist and 400s the whole call on a domain the crawler cannot reach. The 2025 tool + Python whitelist stays. |
| U7 | Shipped: credentials (2 pages) and documents (3 pages) send native `document` blocks, trimmed with pypdf. | Prod smoke on a synthetic 2-page COI: every field correct incl. page-2 conditions, 8.4 s, 6.1K input tokens. Found and fixed: a COI printing "IMO Number: None" came back as the string `"None"`; placeholders now map to null. |
| U8 | Shipped: enrichment pre-fills its cache through one Message Batch when ≥50 chunks are pending; online loop covers the rest. `REGKNOTS_ENRICH_MODE=online` reverts. | First live run (3 synthetic chunks, threshold patched): the batch took **35 min** to end (3/3 succeeded); the probe's 25-min ceiling fell back to online and produced correct aliases. Enrichment is opt-in (`--enrich`) and the scheduled refreshes pass `--no-enrich`, so only manual corpus sprints wait on a batch (production ceiling 24 h) — use `REGKNOTS_ENRICH_MODE=online` when speed matters more than the 50%. |
| U9 | Shipped: four OCR scripts + ISM/STCW adapters on `claude-opus-5-5`, effort `low`, 16K cap, block-type reads. | Not exercised live (ad-hoc scripts); call shape validated in the Opus 5.5 rollout. |
| — | Opus stream effort `medium` → `low` (Blake's go). | Followup turn on prod: synthesis TTFT 5.9 s, 1,760 output tokens, 8 citations, 0 unverified. |

**Retrieval harness after deploy** (`data/eval/retrieval/20260923-*-postdeploy-20260922.json`): dense strong-recall@8 **0.823** (unchanged), MRR 0.688 (0.658 on 09-10 — the dense arm is embeddings + SQL only, untouched by this batch; the MRR drift is the weekly Celery CFR/NVIC refresh changing the corpus). **First baseline of the `dense-prod` arm** — rewrite + rerank, now on structured outputs: **0.919 / MRR 0.737**, p50 6.9 s. Rewrite + rerank are worth +0.097 strong recall; that is the number to beat for any sidecar change.

**New finding — Sonnet 5 thinks by default on real synthesis requests (resolved 2026-09-23, §5).** The Sonnet synthesis stream sends no `thinking` parameter. A short question gets a lone `text` block in ~1 s, but the real payload (14.5K-token system prompt + ~17K chars of context) gets adaptive thinking first. Replaying the exact captured request on prod:

| Variant | First text token | Blocks |
|---|---|---|
| As sent today (cache hit) | 25.6 s / 30.7 s | thinking → text, 3,376 output tokens |
| System as plain string (no cache) | 25.8 s | thinking → text |
| `thinking: {"type": "disabled"}` | **4.1 s** | text |

Live turn on the Captain's profile: synthesis TTFT 24.0 s. This predates today's batch — the plain-string replay (the pre-U3 request shape) thinks just the same, so it has most likely been there since the 07-18 Sonnet 5 refresh — and it is the biggest latency item left on the Sonnet path — larger than all of U1. The thinking also counts toward `_MAX_TOKENS` (8192). Options: disable thinking on the stream, or send `effort: "low"` as Opus already does. Either is a one-line change in `_opus_kwargs()` (generalised to Sonnet); run a five-question answer spot check before and after.

**Side findings.** (1) The bulletin classifier's `cache_control` never worked — its prompt is below Haiku 4.5's 4,096-token caching minimum. (2) Retrieval is nondeterministic end to end: two identical `retrieve_enhanced` calls share only 2–6 of their 8 final chunks, from Haiku rewrite + rerank variance — any single-run A/B on the `-prod` arms is noise. (3) The chat title generator, support replies and `generate_sailor_queries` were also positional readers; all fixed.

---

## 5. Default answer model: Opus 5.5 at effort low (2026-09-23)

Blake: "Go ahead with the Sonnet effort low test … I'm ok with a push to make Opus 5.5 the default … Greenlight all recommended." Commits `3a5e9b6`, `f51cdbe`, `5f0ebb5`; deployed via `scripts/deploy.sh`, smoke OK.

**Method.** `scripts/compare_synthesis_models.py` ran 16 questions: 14 gold-set pairs across five vessel types, plus the Captain's two real questions on her vessel profile. Each went through the real engine (routing, retrieval, rewrite, rerank, prompt assembly) and was stopped at the synthesis call. That exact request was then replayed under six configurations, so model and thinking were the only variables. Two blind judges scored all six answers per question, each in its own shuffled order: Opus 5.5 (effort medium) and GPT-4o. Opus grading Opus answers is a self-preference risk, which is why GPT-4o judges too. GPT-4o compresses its scores into 8–9.3 but agrees on the worst answers. Evidence: `data/eval/model_compare/20260923-175735/`; spend ≈ $5.70.

| Configuration | First token after retrieval, median / p90 | Opus judge | GPT-4o judge | Errors flagged, Opus / GPT-4o | Gold citation hit | $ per answer, cold / warm cache |
|---|---|---|---|---|---|---|
| Router mix — what production sent (10/16 Haiku, 6/16 Sonnet) | 0.8 / 16.4 s | 5.06 | 8.31 | 53 / 9 | 93% | 0.041 / 0.020 |
| Haiku 4.5 | 0.6 / 0.9 s | 4.25 | 8.19 | 69 / 9 | 86% | 0.021 / 0.009 |
| Sonnet 5 as sent (adaptive thinking, default `high`) | 2.7 / 27.2 s | 6.19 | 9.19 | 38 / 4 | 93% | 0.065 / 0.031 |
| Sonnet 5, effort `low` | 2.3 / 2.8 s | 5.88 | 8.88 | 41 / 5 | 93% | 0.057 / 0.023 |
| Sonnet 5, thinking disabled | 2.2 / 2.7 s | 6.38 | 9.00 | 43 / 6 | 86% | 0.059 / 0.026 |
| **Opus 5.5, effort `low`** | **4.5 / 7.9 s** | **8.62** | **9.25** | **9 / 3** | **100%** | **0.130 / 0.060** |
| Opus 5.5, effort `medium` | 9.3 / 13.8 s | 8.75 | 9.31 | 8 / 3 | 100% | 0.144 / 0.074 |

**What the errors were.** Both judges flagged these, and all came from the model the router actually picked:

- **Drill schedule, containership (Haiku):** called 46 CFR 199.250, a passenger-vessel section, controlling, and said weekly drills are required.
- **ROUPV for a 65 GT T-boat (Haiku):** treated an inspected Subchapter T vessel as uninspected and cited a nonexistent 46 CFR 11.467(a)(4).
- **Firefighter's outfits (Sonnet):** filed 46 CFR 96.35-10 under tank vessels and told the mariner not to rely on it.
- **Hydrogen peroxide ERG (Haiku):** cited an "ISM Code Part C", which does not exist.

Opus low's worst flags were two ballast-water misreadings. It read the alternatives in 33 CFR 151.2025(a)(2) as cumulative, and it applied a Subpart C sediment rule where 151.2050(c) governs.

**Decision.** Opus 5.5 at `low` answers every question: `SYNTHESIS_MODEL_FLOOR=claude-opus-5-5` is the default, and an empty value restores pure routing. The Haiku router still runs as the off-topic gate and its score is still logged. `medium` bought nothing measurable for twice the first-token time. When Sonnet does answer (router-only mode), the stream now sends effort `low`: Sonnet thought adaptively on 38% of questions, and `low` removes that 27 s tail. The quality cost is about 0.3 points on both judges' scales, within the noise of 16 questions.

**Checked before shipping.**

- **Refusals:** eight sensitive-but-legitimate questions got 0 refusals on Opus 5.5 low and on Sonnet. They covered IMDG 6.2 infectious substances, WHO IHR, cholera, D-2 ballast organisms, phosphine fumigation, HCN, H2S tank entry and 33 CFR 101 cyber. The GPT-4o path still catches a refusal if one happens.
- **Gap callouts:** Opus trips the hedge regex on 9 of 16 answers (router mix 2 of 16). They are precise callouts after a full answer, such as "I didn't retrieve Rule 34(c); check it directly." The UI shows nothing for a hedge alone, and the judge labels most of them `precision_callout`, which skips web fallback. The extra `retrieval_misses` rows each name the missing section, which is useful retrieval signal.
- **Sonnet JSON routes:** at the default effort, the vessel-analysis co-pilot used 2,721–2,871 of its 3,000 cap on thinking plus JSON. The six co-pilots now share an 8,000 cap, and the web-fallback calls went from 2,048 to 8,192. The oracle synthesis does not think on its payload (500–600 tokens) and was left alone.

**Post-deploy smoke** (prod, flags as `chat.py` passes them):

- **Drill question:** the router picked Haiku and Opus 5.5 low answered. First token came 5.0 s after retrieval, the answer was correct (monthly drills, the 25% rule), and the judge returned `precision_callout`.
- **Towboat fixed-CO2 question:** Opus answered with a 14,559-token cache hit in 5.4 s. The judge returned `partial_miss` on "Subchapter M fixed fire-extinguishing requirements".
- **Web fallback, called directly:** Sonnet 5 with web search surfaced a verified eCFR quote in 15.4 s. It used 1,491 output tokens, 73% of the old cap.
- **Off-topic question:** no synthesis call.

**What this changes.**

- **Cost:** about $0.13 per answer on a cold cache ($0.06 warm), against about $0.04 before. At today's ~10–100 questions a month that is $1–13. If every message were used cold, the worst cases per plan are: Cadet 25 × $0.13 = $3.25 of $9.99; Mate $13 of $19.99. Captain is uncapped, so 10 questions a day costs about $39 against its $39.99 price. A tier-aware floor is a one-line change if that ever matters.
- **Latency:** retrieval is now the long pole. It takes 8–10 s warm and 19 s on the first question after a restart, before Opus's 5 s first token. The DB headroom decision (`shared_buffers` or fan-out, §4 U1) is the next latency lever.
- **Corpus gap:** Subchapter M (46 CFR 144) fire-protection text does not reach a towboat's CO2 question. Gold pair F5/V5 is the test case.
- **Evaluation:** any change to the synthesis model, its effort or the synthesis prompt re-runs `scripts/compare_synthesis_models.py` first, the way retrieval changes re-run `scripts/eval_retrieval.py`.

---

## 6. U10 — quiz generation on Sonnet 5 (2026-09-23)

Blake: "quiz generation can move to sonnet." Measured first on prod. Four real historical topics, 10 questions each, went through the router's own retrieval, prompt, schema and citation check. Opus 5.5 then audited every answer key against the same passages.

| Quiz model | Median time | Answer key correct | Single best answer | Citations resolving to the corpus | $ per quiz |
|---|---|---|---|---|---|
| Haiku 4.5 (before) | 23.3 s | 95% | 95% | 38% (50% without COLREGs) | 0.014 |
| **Sonnet 5, effort `high`** | 35.6 s | 95% | 97% | **72% (97%)** | 0.050 |
| Sonnet 5, `medium` | 26.9 s | 97% | 95% | 60% (80%) | 0.037 |
| Sonnet 5, `low` | 23.1 s | 95% | 100% | 55% (73%) | 0.034 |

- **Answer keys:** the reason in F11 did not hold up. Haiku's answer keys were as good as Sonnet's in this sample, within one question of 40.
- **Citations:** the difference is grounding. Sonnet at `high` cites sections that exist in the corpus far more often.
- **Shipped:** Sonnet 5 with effort pinned at `high`. The cap went from 4,000 to 16,000, because `high` produced up to 5,055 tokens; the old cap would have truncated the JSON into a 502.
- **COLREGs:** 0 of 10 citations resolved for every model. The quiz verifier matched `section_number` case-sensitively, and the corpus writes "COLREGS Rule 13" where quizzes cite "COLREGs Rule 13(b)". It now matches case-insensitively, with no collisions: 35,866 distinct section numbers either way. Guides share the verifier and get the fix too.
- **Found, not fixed:** exam-bank context retrieval matches the whole topic string, so multi-word topics get none (roadmap).

---

## Appendix — evidence

- Call-site inventory: `grep -rn -A9 -E 'messages[.](create|stream)[(]' apps/api/app packages/rag/rag packages/ingest/ingest scripts --include=*.py`
- Cross-cutting counts: `cache_control` 1 hit; `output_config` 0; `thinking=` 0; `_parse_json` 6 files / 18 hits; `json.loads` 27 files / 67 hits; `asyncio.gather` in `engine.py`: 0
- Static prompt size: `assemble_system_prompt()` → 39,110 chars / 8,944 cl100k tokens (default), 41,193 / 9,381 (precision)
- Token profile: `SELECT model_used, count(*), avg(tokens_used), percentile_cont(0.5) … FROM messages WHERE role='assistant' GROUP BY 1;` and `SELECT avg(input_tokens), avg(output_tokens) FROM retrieval_misses;`
- Calls per question: `journalctl -u regknots-api --since '30 days ago' | grep -c 'api.anthropic.com/v1/messages'` ÷ `grep -c 'Routed query'`
- Sonnet 5 block order (thinking omitted): live call 2026-09-22 → `['text']`, 1.35 s; Opus 5.5 at `low`/`medium` → `['thinking', 'text']`, 3.1–3.3 s
- SDK surface: `anthropic/types/output_config_param.py`, `json_output_format_param.py`, `web_search_tool_20260209_param.py`, `cache_control_ephemeral_param.py` (ttl) all present in 0.86.0; PyPI `anthropic` latest 1.8.0
