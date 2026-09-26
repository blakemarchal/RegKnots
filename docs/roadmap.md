# RegKnots Roadmap

**Last updated:** 2026-09-26 (question-audit follow-up deployed, SOLAS / cfr_49 cleanup applied, `7080fce` awaiting verification, Anthropic credits exhausted; audit at `docs/sprint-audits/question-audit-2026-09-25.md`; Opus 5.5 low is the default answer model; LLM surface audit at `docs/sprint-audits/llm-surface-audit-2026-09-22.md`; system audit at `docs/sprint-audits/full-system-audit-2026-09-10.md`)

**Eval headline:** retrieval harness re-run 2026-09-10 after prod was flipped back to dense — strong-recall@8 **0.823 / MRR 0.658** on the 62-pair gold set, 0 errors (July baseline 0.790 / 0.627; evidence `data/eval/retrieval/20260910-144455-dense-ef0.json`). Answer-quality eval still 97.4% A-or-A− on 149 questions (2026-05-09). **New retrieval baseline to beat: 0.823 / 0.658.** Post-deploy 2026-09-23: dense 0.823 / 0.688 (unchanged recall; MRR drift from the weekly CFR refresh), and the first `dense-prod` baseline (rewrite + rerank) **0.919 / 0.737**.

**Where we are.** First organic Captain subscriber on 2026-09-09 (a working Master on a US-flag container ship). Infra is green. The audit found that her first session was degraded by two known, one-line problems (hybrid retrieval left on in prod against the July verdict; vessel flag Unknown so nothing scopes her to US regs) and that 19 of 38 citations she and Karynn were shown were noise. That is the whole of "Now / this week." The strategic question Blake asked — which IMO instruments to buy vs. source for free — is answered instrument by instrument in §IMO below.

This file is the strategic shipped / in-flight / upcoming view. `docs/PROJECT_STATE.md` is the operational one-pager; `docs/corpus-status.md` is the corpus inventory; `docs/scaling-roadmap.md` has capacity thresholds. Previous version: `docs/archive/roadmap-2026-05.md`.

---

## What changed since the May roadmap (headline only)

- **June audit sprint** — live-question quality pass: follow-up retrieval composition, CG-form identifier retrieval, never-assert-non-existence rule, MLC 2006 ingested, MEPC/MSC harvest phase 1, SIRE 2.0 library completed, whale-zones polish.
- **2026-07-18 model refresh** — Sonnet 5 / Opus 4.8 everywhere; `_MISSING_SOURCES` rot fixed.
- **2026-07-19 Wk1–4 wave** — retrieval eval harness (`scripts/eval_retrieval.py`) and the **hybrid verdict (dense wins, do not flip)**; per-ingest REINDEX removed in favour of weekly `REINDEX CONCURRENTLY`; backups restore-tested; citation trust pack; per-answer exports; persona nav; fleet audit readiness; live-context injectors; team audit log.
- **2026-08-09 incident** — Anthropic credits exhausted; the GPT-4o fallback engaged and could not persist (`messages_model_used_check` never allowed `fallback_gpt4o`) — 13 answers for one user generated, billed, discarded. **2026-08-10:** migration 0115 widens the constraint; key rotated (a carriage-return byte in `.env` blanked the key for every service — `file .env` is now part of the rotation procedure); four corpus-refresh systemd timers disabled per Blake's "questions only" cost posture.
- **2026-09-09** — first Captain purchase. **2026-09-10** — this audit + roadmap.
- **2026-09-22** — Opus traffic → **Opus 5.5** (`claude-opus-5-5`, $4/$20): `MODEL_MAP[3]`, `REGENERATION_MODEL`, alias map; regeneration path fixed to read by block type (Opus 5.5 always opens with a thinking block — the old `content[0].text` would have silently disabled regen); explicit effort (`medium` stream / `high` regen) + 16K cap; refusal → GPT-4o. Deployed `83ded7a`, smoke-verified on prod: synthesis TTFT **12.9 s at `medium`, 7.6 s at `low`**. **LLM surface audit** shipped alongside — see the new section below.
- **2026-09-22 (later)** — audit upgrades **U1–U9 shipped** on Blake's greenlight: SDK 1.8, shared `rag/llm.py`, structured outputs on 18 call sites, prompt caching (verified hits), router ∥ retrieval, native PDF input, Batch-API enrichment, Opus 5.5 `low` OCR; Opus stream effort → `low` (followup TTFT 5.9 s on prod). U6 measured and dropped. First `apps/api` tests.

Corpus today: **92,336 chunks across 66 sources** (2026-09-26, after the SOLAS re-parse and the cfr_49 scope; 106,041 on 2026-09-10; the May roadmap said ~77k / 50).

---

## Now / this week — her next session should not look like her first

All awaiting "go". Each is independently verifiable.

1. ~~**Flip prod to dense retrieval.**~~ **SHIPPED 2026-09-10.** `HYBRID_RETRIEVAL_ENABLED=false` and the dead `CONFIDENCE_TIERS_MODE` line removed from prod `.env`; `regknots-api` restarted; process environment verified. Her four questions re-run through dense retrieval with her real profile: **4/32 foreign-flag hits at flag Unknown → 0/32 at United States** (her live session under hybrid + Unknown: 14 of 30 off-topic). Harness: 0.823 / 0.658.
2. ~~**Set MAERSK Kinloss `flag_state`.**~~ **SHIPPED 2026-09-10** (`United States`, matching the 5 populated rows). **51 of 56 vessel profiles on prod have flag Unknown** — her case is the norm, which is why item 6 is now the top product item.
3. **Stripe: identify the $39.00 price** on `sub_1UDop0B6F2sQMkiGQwjVd969` and confirm it is in `plans.py`. **Answered 2026-09-26:** it is mapped (no unmapped-price warning at purchase), so renewals route. `STRIPE_PRICE_CAPTAIN_MONTHLY` is the legacy Pro price id at $39.00, while every page advertises $39.99 and the support FAQ still describes the old Pro plan. **Blake:** create a $39.99 price (new subscribers only) or change the copy to $39.
4. ~~**Celery hygiene.**~~ **SHIPPED 2026-09-10.** `update_regulations` now calls `scripts/run_ingest.sh` (which picks `--pipe` when there is no TTY, so the worker still captures output and the exit code); `reindex-vector-embeddings-monthly` and its task deleted; `celerybeat-schedule` gitignored; `packages/ingest/uv.lock` regenerated (greenlet, playwright, pyee) so prod stops re-resolving it every Sunday. The eCFR-503 retry was already bounded by `max_retries=2` — no change. Deployed via `scripts/deploy.sh`. First scheduled run under the wrapper: Sunday 2026-09-13 02:00 UTC — check `journalctl -u regknots-worker` and the transient `regknots-ingest-*` unit afterwards.
5. **Karynn reads two answers** (MOB alarm; BMP-MS) — 5 minutes, see audit §2.5. If either is wrong it becomes a hedge-audit entry and a gold-set pair.
6a. ~~**Sonnet synthesis thinking.**~~ **SHIPPED 2026-09-23, together with the Opus 5.5 default.** A six-way comparison on 16 questions put Opus 5.5 at effort `low` top with both blind judges: 8.62 vs 5.06 (Opus judge) and 9.25 vs 8.31 (GPT-4o) for what routing sent. It had 9 vs 53 flagged errors, the p90 first token fell from 16.4 s to 7.9 s after retrieval, and it costs ~$0.13 vs ~$0.04 per answer at a cold cache. It now answers every question (`SYNTHESIS_MODEL_FLOOR`, default `claude-opus-5-5`). Sonnet, when used, streams at effort `low`. Evidence: LLM surface audit §5, `data/eval/model_compare/20260923-175735/`.
6. **Vessel-profile completeness (product) — now the top product item.** 51 of 56 vessel profiles have flag Unknown, and the A/B above shows flag alone moves foreign-flag noise from 4/32 to 0/32. When `vessels.flag_state` is Unknown and `users.jurisdiction_focus` is set, use it for retrieval scoping; show a one-click "confirm your flag" prompt in chat when the active profile is incomplete; enrich from IMO number on save. **~2 h.** Spec first. **Scoping fallback built 2026-09-24** (committed `18fb15f`, awaiting deploy): on the Captain's profile with the flag set to Unknown, her questions went from 10/48 foreign-flag hits to 0/48. The confirm-your-flag prompt and IMO enrichment remain.

---

## Next 1–2 weeks

7. **Add her four real questions + Karynn's BMP question to the eval gold set** and re-baseline. The gold set was built from Karynn's and pilot users' questions; the first paying Master's questions belong in it.
8. ~~**Tier-aware model floor.**~~ **Superseded 2026-09-23:** Opus 5.5 `low` is the floor for every tier (item 6a). If cost ever matters, the same setting can become tier-aware in one line. Worst case at a cold cache is Cadet $3.25 of $9.99 and Mate $13 of $19.99 a month; Captain is uncapped, at about $39 a month for 10 questions a day.
9. ~~**Stripe webhook ordering fix.**~~ **Fixed 2026-09-26 (`4f19025`), with a different root cause.** The invoice.paid fallback worked. The real gap: the endpoint is not subscribed to `customer.subscription.created` or `.deleted`. Checkout and invoice.paid now record the interval. The daily `reconcile_subscriptions` task downgrades ended subscriptions; its first run fixed the item-14 zombie. Tests are in `apps/api/tests/test_stripe_webhooks.py`. **Blake:** add the two events to the endpoint in the Stripe dashboard.
10. **BMP Maritime Security (2024) ingest.** Free industry PDF (ICS / BIMCO / INTERTANKO / OCIMF et al.). Karynn asked for it on 09-10 and got a mis-attributed answer from adjacent chunks. **~2 h**, `pdf_pipeline` pattern.
11. **`next` 15.5.14 → 15.5.15+** (DoS CVE, open since May). `pnpm up next` + deploy. **10 min.** **Committed 2026-09-24** (`6976759`, 15.5.26); awaiting push and deploy.
12. ~~**Sentry `environment` tag**~~ **Done 2026-09-26** (`6ab370d`). CI added the same day (`.github/workflows/tests.yml`).
13. **Offsite backups** — Blake's 5-minute DO Spaces bucket + keys step (`scripts/backup_offsite.sh` header). Local backups still share a disk with the database.
14. ~~**Zombie test account**~~ **Fixed 2026-09-26** by the first `reconcile_subscriptions` run: now free / canceled, matching Stripe.

---

## From the 2026-09-25 question audit

Findings and evidence: `docs/sprint-audits/question-audit-2026-09-25.md`.

**Deployed 2026-09-26** (`78a7485`):
- SOLAS and CFR citation resolution.
- Vessel filter limited to Title 46.
- Reformulations overlap the primary retrieval. (Dropping their identifier search was reverted on 2026-09-26: −4 of 71 pairs on the full pipeline.)
- Reranker pairs.

**Status of the six proposals** (audit doc §6):
- **A1. Done 2026-09-26.** Pipeline prune (`1e41a87`) and the SOLAS parser fix (`825c62e`). SOLAS went from 1,739 to 848 chunks. Next: a stale report for the IMO codes re-split in Sprint #47.
- **A2. Done 2026-09-26.** cfr_49 is scoped to its maritime parts: 15,967 → 3,145 chunks.
- **A3. Deployed 2026-09-26** (`51231cc`, verified on prod): the gate counts citations in the answer text, and the corpus oracle runs on `partial_miss`. In testing it surfaced a verified 46 CFR 95.50-10 quote.
- **A4. Done 2026-09-26** (`2469c73`). Dense arm on the expanded set: 0.8451 / 0.7178 before the cleanup, 0.8592 / 0.6924 after.
- **A5. Deployed 2026-09-26:** analytics run after `done`. Last token → `done` went 3.7 → 0.0 s on normal answers and 9.3 → 4.4 s on hedged ones.
- **A6. Deployed 2026-09-26:** credential reminders appear only for credential questions (verified by A/B).
- **Full pipeline, clean corpus, 71 pairs:** pre-audit 0.8732 / 0.6722 → shipped **1.0000 / 0.7301**. These are the new baselines, with dense at 0.8592 / 0.6924.
- **Credit outage** (2026-09-26, 00:15 to ~02:10 UTC): resolved, with no user traffic in the window.

---

## IMO corpus acquisition plan

**The question:** many IMO instruments are missing or present only as the adopting resolution. Buy, or find free routes?

**Two routes exist for almost every instrument.**

- **Free route.** Every IMO code is adopted as the *annex* of an MSC / MEPC / Assembly resolution, and every amendment is another resolution. The resolutions are public on the IMO resolution index (imo.org Knowledge Centre) and docs.imo.org (free account). Ingesting the adopting resolution's annex gives the full base text; ingesting the amending resolutions as separate sections gives the deltas. **This is exactly the pattern `stcw_amend` and `marpol_amend` already use.** The cost is that the text is not consolidated — a user gets "base text, as amended by MSC.xxx" as two citations rather than one merged paragraph. That is how STCW and MARPOL work in the corpus today and nobody has complained.
- **Paid route.** IMO Publishing sells consolidated e-book editions with all amendments merged. Most single-code titles are in the tens of pounds; consolidated SOLAS and the IMSBC Code are the expensive outliers (>£100). Prices move; verify at checkout. PDF handling of purchased e-books is the same `pdf_pipeline` path as COLREGs and COSWP.

**Recommendation:** free route first for the whole of Tier A — it costs engineering hours and under $5 of embeddings, not licence fees. Buy consolidated editions only where (a) the free text turns out to be unobtainable or badly OCR'd, or (b) a paying segment needs merged text (bulk carriers → IMSBC). Ranked for the user we actually have — a US-flag container Master — first.

### Tier A — do first (free route covers all of it)

| Instrument | In corpus today | Why a Master needs it | Free route | Paid route | Effort |
|---|---|---|---|---|---|
| **ISPS Code** (Parts A + B) | absent | Every port call: DoS, SSP, security levels, PSC | SOLAS 2002 Conference resolution 2 annex; SOLAS XI-2 already in `solas` | ISPS Code consolidated | 4 h |
| **LSA Code** full text | 58 chunks — resolution text only | Lifejackets, liferafts, immersion suits, EPIRB/SART — every SOLAS III question bottoms out here | MSC.48(66) annex (the Code) + amending resolutions MSC.207(81) through MSC.485(103) | LSA Code consolidated | 6 h |
| **FSS Code** full text | 29 chunks — resolution only | Fire-fighting systems — every SOLAS II-2 equipment question | MSC.98(73) annex + the ~10 amending MSC resolutions on the IMO FSS page | FSS Code consolidated | 6 h |
| **2008 IS Code** (Intact Stability) | absent | Stability criteria, weather criterion, container-ship stability booklets; the Captain asked about stability in April | MSC.267(85) annex Parts A + B + amendments (MSC.319(89) onward) | IS Code consolidated | 5 h |
| **Load Lines 1966 / 1988 Protocol** | 3 chunks | Freeboard, zones and seasonal areas, LL certificate | Convention text (the treaty HTML the adapter skipped — needs an HTML-aware adapter) + MSC.143(77) consolidated Annex B | Load Lines consolidated | 4 h |
| **IAMSAR Vol III** | wired, geo-blocked | SAR on board, MOB search patterns, on-scene coordination | USCG mirror — download from the laptop, `scp` to `raw_dir` (already the documented workaround) | IMO / ICAO | 2 h |
| **BMP Maritime Security 2024** | absent | Piracy / HRA transits; Karynn's 09-10 question | Free industry PDF (ICS / BIMCO et al.) | n/a | 2 h |

Tier A total: ~29 engineering hours, $0 in licences, under $5 in embeddings.

### Tier B — next, still free

| Instrument | In corpus today | Why | Free route | Effort |
|---|---|---|---|---|
| **CSS Code** full + Annex 13 | 53 chunks | Cargo securing — container lashing, CSM approval | A.714(17) annex + MSC.1/Circ.1352/Rev.2 + MSC.1/Circ.1623 | 3 h |
| **CSC 1972** (Safe Containers) | absent | Container-ship specific: CSC plates, ACEP, examination intervals | Convention text + MSC.310(88), MSC.355(92) amendments | 3 h |
| **STCW base refresh** | `stcw` 2017-07 base; `stcw_amend` 28 chunks | 2010 Manila consolidated + 2022/2024 amendments as one coherent base | Existing `stcw_amend` pattern; MSC.486(103) onward | 4 h |
| **MARPOL base refresh** | `marpol` 2022-11 base; `marpol_amend` 618 chunks | Annex VI CII / EEXI / fuel sulphur enforcement moved | `marpol_amend` already carries MEPC.328(76) onward; refresh the base | 6 h |
| **HSC / IGC / IBC pending amendments** | bases present | ~6 HSC, 2 IGC, 1 IBC amendment resolutions not ingested | Resolution index | 3 h |

### Tier C — buy only on demand

| Instrument | Why deferred | If bought |
|---|---|---|
| **IMSBC Code** | Bulk carriers only; no bulk customers today. Free route via MSC.268(85) + amendments is large and fiddly | IMSBC consolidated (>£100) when a bulk operator signs |
| **Grain Code**, **BLU Code**, **Timber Deck Cargoes** | Bulk / specialist | Free resolutions; do with IMSBC |
| **FTP Code 2010**, **III Code**, **Casualty Investigation Code**, **MODU Code**, **SPS Code** | Yard / flag / investigator audiences, not a Master's daily questions | Free resolutions (MSC.307(88), A.1070(28), MSC.255(84), A.1023(26), MSC.266(84)); ~2 h each |
| **STCW-F**, **Tonnage 1969**, **AFS**, **HKC**, **Nairobi WRC**, **CLC / Bunkers** | Fishing / liability / niche | Out of scope this quarter |

### Sequencing

1. ISPS + BMP MS (both free, both quick, both port-call-relevant) — 1 day.
2. LSA + FSS full text — the two highest-impact gaps since May; 1.5 days.
3. IS Code + Load Lines — stability pair; 1 day (Load Lines needs the HTML adapter).
4. IAMSAR from the laptop — half a day.
5. Tier B as a corpus sprint when traffic justifies; run the eval before and after every step.

Every ingest above goes through `scripts/run_ingest.sh`, never bare `uv run`.

---

## LLM surface upgrades (audit 2026-09-22)

`docs/sprint-audits/llm-surface-audit-2026-09-22.md` — 35 Anthropic call sites inventoried. The models were current; the call shapes were not. **U1–U9 greenlit and shipped the same day** (`f64bbfc`, `cb7cf27`, `25eabf5`); measured outcomes in the audit's §4.

| # | Upgrade | Status |
|---|---|---|
| U1 | Sidecar parallelism | **Shipped, rescoped** — judge → oracle is dependent and retrieval was already concurrent inside; router ∥ retrieval saves ~0.6 s, not 2–4 s. The remaining pre-synthesis time is DB fan-out: see "DB headroom" below. |
| U2 | Shared `text_of` + refusal guard | **Shipped** (`packages/rag/rag/llm.py`) |
| U3 | Prompt caching on the static system block | **Shipped** — prefix is 14.5K tokens; cache hits verified on prod (stream → regen share it) |
| U4 | SDK 0.86 → 1.8 + shared helpers (May #9) | **Shipped** |
| U5 | Structured outputs | **Shipped** — 18 schemas, all validated live; six `_parse_json` copies deleted |
| U6 | `web_search_20260209` + `allowed_domains` | **Dropped** — measured 40 s / non-answer on a real fallback query; `allowed_domains` can't express the suffix whitelist |
| U7 | Native PDF `document` blocks | **Shipped** — credentials + documents; COI smoke correct |
| U8 | Batch API for enrichment | **Shipped** — first live run will be the next ingest (≥50 chunks); `REGKNOTS_ENRICH_MODE=online` reverts |
| U9 | Opus 5.5 `low` vision for OCR | **Shipped** — first live run will be the next OCR job |
| U10 | Quiz generation → Sonnet 5 | **Shipped 2026-09-23** (Blake's go). Answer keys were already equal (95% vs 95–97%); citations that resolve to the corpus rose from 50% to 97%. COLREGs citations had shown 0% verified for every model — a case-sensitive verifier, now fixed. See audit §6. |
| U11 | Captain model floor at Opus 5.5 `low` | **Superseded** — Opus 5.5 `low` answers every tier since 2026-09-23 (audit §5) |

**DB headroom — `shared_buffers` 512 MB SHIPPED 2026-09-24** (`e066078`; spec + results `docs/postgres-shared-buffers-spec-2026-09-23.md` §0). API downtime was 14 s, and `pg_prewarm` autoprewarm is running. The dense harness came back identical (0.8226 / 0.6881, 0 pairs changed). Warm group queries now read 0 MB from outside the pool. The DB phase of the first question after a deploy fell from ~13 s to 8.3 s, about the same as warm (7.6 s).

**Correction:** the warm pre-synthesis wait did not improve. The retrieval step is still 8–11 s, because the fan-out is CPU- and connection-bound rather than I/O-bound: 4 reformulations × 31 groups = 124 queries per question, through a 10-connection pool on 2 cores. The spec's projection of 0.4–1 s timed one isolated `retrieve()`.

**Next latency candidate (spec needed):** batch the 21 small exact-scan groups into one window-function query per reformulation (124 → ~44 queries per question). It keeps top-k per group exactly, so the harness can prove identical results. Then the Haiku rerank (3.2 s) and rewrite (1.3 s).

**Quiz exam-bank context (found 2026-09-23):** `_retrieve_for_topic` matches the whole topic string as a substring of the exam pool, so multi-word topics ("COLREGs Rule 13 overtaking") get 0 exam-bank chunks — true for 3 of the 6 real quiz topics. Fix: a vector search restricted to `nmc_exam_bank`. It changes quiz inputs, so quick-check it with the quiz audit probe first.

**Corpus gap found 2026-09-23:** Subchapter M (46 CFR 144) fire-protection text does not reach a towboat's fixed-CO2 question. The judge returned `partial_miss`, and the web fallback found it on eCFR. Gold pair F5/V5 is the test case.

---

## Within 30 days

15. **API test coverage** — billing webhook (fixture for the ordering race), message-cap gate, auth flow. `apps/api/tests/` does not exist. 2 days.
16. **CI** — `.github/workflows/ci.yml`: `pnpm lint`, `tsc --noEmit`, `pytest`. 2 h. Four months open.
17. **Extract `app/llm_helpers.py`** — Sonnet boilerplate ×6 in `me.py`, `_parse_json` ×6. 3 h.
18. **SpiritFlow off the box** (or RegKnots onto its own). `merch-*` and `bree-*` still share the 4 GB droplet. 6 h + $24/mo.
19. **Caddy CSP** header (HSTS / X-Frame / Referrer shipped; CSP still absent). 30 min.
20. **Documentation completion** — `docs/architecture.md`, `docs/runbook.md`, per-package READMEs. 6 h.

---

## Deferred / re-check next quarter

- `text-embedding-3-large` — still not the bottleneck.
- Hot-replica Postgres — revisit at scaling-roadmap Tier 4.
- USCG MSM refresh (2021-09) and ISM (2018-07) — stale bases, low query volume.
- Marketing landings → RSC + client islands.
- 2FA / TOTP — revisit when paid users cross a threshold.
- Glossary Phase 2 multi-model build (63 entries today).
- Translation pipeline (FR / DE / GR / JP / CN / KR regulators) — designed, not built.
- Hybrid retrieval as a *weighted supplement* to dense (not equal-partner RRF) — only after the harness shows it beats 0.790.

---

## Done — closed since 2026-05-09

Verified against code, prod and git today, not lifted from the previous roadmap.

- ~~Layer C UX inversion~~ — shipped 2026-05-09.
- ~~IMO HSC/IGC granularity~~; ~~NVIC OCR backfill~~ (+49 NVICs) — shipped 2026-05-09.
- ~~Corpus-completeness audit~~ — `docs/corpus-gap-report-2026-05-09.md`.
- ~~OSHA no-cite clause~~ — present in `prompts.py`.
- ~~Caddy security headers~~ — HSTS, X-Frame-Options, Referrer-Policy live (CSP remains, item 19).
- ~~Hybrid flip + re-eval~~ — evaluated 2026-07-19; **verdict: dense wins**. Reverting prod is item 1.
- ~~Backups restore-tested~~ — 2026-07-19 (offsite copy remains, item 13).
- ~~Retrieval eval gate~~ — `scripts/eval_retrieval.py`, 2026-07-19.
- ~~Per-ingest REINDEX lock~~ — removed 2026-07-19 (the Celery monthly duplicate remains, item 4).
- ~~JWT secret, `.env` 600, daily backups, cgroup caps, swap, `run_ingest.sh`~~ — May.
- ~~GPT-4o fallback could not persist~~ — migration 0115, 2026-08-10.
- ~~Anthropic key exposure~~ — rotated 2026-08-10; legacy key purged from disk.

**Still open from May, carried above:** `next` CVE (11), Sentry env tag (12), CI (16), API tests (15), `llm_helpers` (17), SpiritFlow (18), offsite backup (13), STCW / MARPOL refresh (Tier B), Load Lines / FSS / LSA (Tier A), IAMSAR (Tier A), UptimeRobot click-through (unverifiable from the box — confirm), 5 oversized + 2 unresolved scanned NVICs (low).
