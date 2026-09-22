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
| U10 | Quiz generation → Sonnet 5 (F11) | 1 h | Exam-key accuracy | Karynn's call |
| U11 | Captain model floor at Opus 5.5 `low` (F12) | 1 h | Best model for the paying tier at ~$0.10/question | Blake's call |

**Sequencing that respects the standing rules:** U1–U3 are each a spec-then-go and each gets a before/after on `scripts/eval_retrieval.py` (retrieval is untouched, so the check is that the score *doesn't move*) plus a five-question answer-quality spot check. U4 first, then U5. U8 before the next ingest sprint.

**Not recommended:** moving the Haiku sidecars up a tier (they are classification/ranking tasks and Haiku 4.5 is the current Haiku); the embedding model (twice audited as not the bottleneck); re-enabling hybrid retrieval (measured, 2026-07-19). Fast mode on Opus 5.5 ($8/$40) — TTFT here is dominated by the sequential sidecars (U1), not by output speed.

---

## Appendix — evidence

- Call-site inventory: `grep -rn -A9 -E 'messages[.](create|stream)[(]' apps/api/app packages/rag/rag packages/ingest/ingest scripts --include=*.py`
- Cross-cutting counts: `cache_control` 1 hit; `output_config` 0; `thinking=` 0; `_parse_json` 6 files / 18 hits; `json.loads` 27 files / 67 hits; `asyncio.gather` in `engine.py`: 0
- Static prompt size: `assemble_system_prompt()` → 39,110 chars / 8,944 cl100k tokens (default), 41,193 / 9,381 (precision)
- Token profile: `SELECT model_used, count(*), avg(tokens_used), percentile_cont(0.5) … FROM messages WHERE role='assistant' GROUP BY 1;` and `SELECT avg(input_tokens), avg(output_tokens) FROM retrieval_misses;`
- Calls per question: `journalctl -u regknots-api --since '30 days ago' | grep -c 'api.anthropic.com/v1/messages'` ÷ `grep -c 'Routed query'`
- Sonnet 5 block order (thinking omitted): live call 2026-09-22 → `['text']`, 1.35 s; Opus 5.5 at `low`/`medium` → `['thinking', 'text']`, 3.1–3.3 s
- SDK surface: `anthropic/types/output_config_param.py`, `json_output_format_param.py`, `web_search_tool_20260209_param.py`, `cache_control_ephemeral_param.py` (ttl) all present in 0.86.0; PyPI `anthropic` latest 1.8.0
