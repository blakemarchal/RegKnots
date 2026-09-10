# RegKnots Full-System Audit — 2026-09-10

**Context.** First look at the system since 2026-08-10. Trigger: the first organic Captain-tier purchase (2026-09-09, cassclark.425@gmail.com) — a working Master is now paying $39/mo and asking real vessel questions, and Karynn wants to push again. Every number below was queried live today (journald, Postgres, Stripe webhook logs, `.env`, git). Nothing is from memory. Evidence commands are in the appendix.

**Headline.** Infrastructure is green and the purchase flow worked end to end. The product the Captain actually *experienced* is degraded by two things that are each a one-line fix:

1. Prod is running `HYBRID_RETRIEVAL_ENABLED=true` — the retrieval mode the 2026-07-19 eval measured as **losing 16 of 62 gold pairs** (strong-recall@8 0.548 vs 0.790 dense). The code default was flipped to OFF in July; the prod `.env` override from May was never removed.
2. Her vessel (MAERSK Kinloss, IMO 9333022) has `flag_state = Unknown`, so jurisdiction severance never engages and foreign-flag notices leak into a US-flag Master's answers.

Together they put **19 of 38 citations** in the session's five answers on off-topic or foreign-flag material — Bahamas safety alerts, Marshall Islands LRIT, Liberian ISM circulars, VTS Houston/Galveston, under-deck tonnage — and she spent her last two messages ("ABS USA", "confirming flag state") trying to fix her own profile through the chat box, which cannot write profile fields.

Nothing here is a crash. It is a paying user getting a visibly worse product than the eval harness says we can deliver, for reasons already known and already measured.

---

## TL;DR — before Karynn pushes

All items await a "go" per the standing rule. Ranked by impact per minute.

| # | Item | Sev | Effort | Owner |
|---|---|---|---|---|
| 1 | Remove `HYBRID_RETRIEVAL_ENABLED=true` from prod `.env`, restart `regknots-api`, re-run her four questions | P1 | 5 min | Claude, on go |
| 2 | Set `vessels.flag_state = 'United States'` for MAERSK Kinloss; ship the product fix so this cannot recur (§2.4) | P1 | 1 min + 2 h | Claude, on go |
| 3 | Stripe dashboard: confirm which price_id `sub_1UDop0B6F2sQMkiGQwjVd969` uses. `amount_paid = 3900` matches no configured price ($39.99 / $29.99 promo). If it is not in `plans.py`, renewals and cancellations will not map | P1 | 5 min | Blake |
| 4 | Celery Beat is still running weekly ingest unwrapped inside the worker cgroup, and a monthly **non-concurrent** `REINDEX` (271 s ACCESS EXCLUSIVE on 09-01). Wrap the former in `run_ingest.sh`; delete the latter (systemd `db-maintenance` already does it CONCURRENTLY) | P2 | 30 min | Claude, on go |
| 5 | Karynn eyeball (5 min): the MOB-alarm answer asserts a specific alarm pattern citing NVIC 07-98 (the SMCP NVIC); the BMP-MS answer says it was "developed by the IMO" (it is industry guidance) and cites protective-coatings and ballast-water chunks | P2 | 5 min | Karynn |
| 6 | Commit a regenerated `packages/ingest/uv.lock` (committed lock predates `playwright`; prod re-resolves on every run); gitignore `apps/api/celerybeat-schedule` | P3 | 10 min | Claude, on go |
| 7 | Confirm the Anthropic console monthly spend cap is set on the new key (unverifiable from the box) | P3 | 2 min | Blake |

---

## Section 1 — Captain tier: did the purchase work?

**Yes.** The flow was: free account created 2026-04-04 → `/billing/checkout` 2026-09-09 16:56 → Stripe → `invoice.paid` + `checkout.session.completed` webhooks 16:58 → first question 17:10. Twelve minutes from card to chat.

| Field | Value | Verdict |
|---|---|---|
| `subscription_tier` / `status` | `captain` / `active` | correct |
| `current_period_end` | 2026-10-09 | correct |
| `stripe_subscription_id` | present | correct |
| `billing_events` row | 2026-09-09, `captain`, 3900 USD, paid | written |
| `monthly_message_cap` | None (unlimited) via `plans.py` | correct |
| `persona` / `jurisdiction_focus` | `mariner_shipboard` / `us` | set at signup |
| `billing_interval` | **NULL** | defect §1.1 |
| `onboarding_completed_at` | **NULL** (5-month-old account) | defect §2.4 |
| vessel `profile_enriched_at` | **never** (IMO number present) | defect §2.4 |

Tier distribution today: 68 free · 1 cadet (n.leachman82, $9.99/mo, renewing monthly since June) · **1 captain** · 2 legacy `pro` (Karynn comp'd to 2027; `kdmarchal+test` is a zombie — period ended 2026-05-08, `cancel_at_period_end=true`, still `active`). 72 users total, 0 created in the last 31 days: the Captain is a conversion, not an acquisition.

### 1.1 Webhook ordering race → `billing_interval` never recorded

From the API log at 16:58:09, in order:

```
Stripe webhook received: type=invoice.paid
Invoice paid: customer_id=cus_VEHL… subscription_id=sub_1UDop…
Stripe webhook received: type=checkout.session.completed
Checkout completed: customer_id=cus_VEHL… subscription_id=sub_1UDop…
Invoice paid UPDATE by subscription_id: UPDATE 0
```

`invoice.paid` ran its `UPDATE users … WHERE stripe_subscription_id = $1` before `checkout.session.completed` had written the subscription id onto the user. **0 rows matched.** The interval extraction in `stripe_service.py` (~L533–546) therefore never landed. The Cadet user shows `month` because renewals arrive after the id exists. Consequence today is cosmetic (attribution/admin). Consequence tomorrow: any logic that keys on interval for the first cycle is wrong for every new subscriber. Fix: fall back to `stripe_customer_id` in the `invoice.paid` UPDATE, or re-extract interval in the checkout-completed handler. A recorded-fixture test for exactly this sequence is the first API test worth writing (there are currently zero API tests).

### 1.2 Price mismatch

`amount_paid_cents = 3900`. Configured Captain prices per `email.py` / `plans.py`: $39.99 monthly, $29.99 promo, annual. $39.00 matches none. Either a price exists in Stripe that `plans.py` does not know about (then `plan_info_from_price_id` returned None and the tier was set by a legacy path), or a coupon/proration applied. Only the dashboard can say. This is the one item that could silently break at renewal.

---

## Section 2 — What the Captain experienced (2026-09-09 17:10–17:33 UTC)

Four questions, all routed to `claude-haiku-4-5-20251001` (router score 1), all judged `precision_callout` (confident, no fallback). Reranker top-8 scores Q1 `[5,4,3,3,2,2,2,2]`, Q2 `[5,5,3,2,2,1,1,1]` — it rescued the top of the list and the tail still got cited.

| # | Question | Cites | Off-topic / foreign-flag | What was shown |
|---|---|---|---|---|
| 1 | "man overboard signal" | 7 | 1 | SOLAS V/8, V/29, V/35, LSA Ch.III, COSWP 4.7, NVIC 07-98 §18 — and a Bahamas safety alert on fall-arrest equipment |
| 2 | "what is the man overboard alarm" | 7 | 4 | COSWP 4.7, ISM 8, NVIC 07-98 — and BMA SA25 again, 33 CFR 164.46 (AIS), 33 CFR 161.35 (VTS Houston), 46 CFR 69.163 (under-deck tonnage) |
| 3 | "ABS USA" | 8 | 4 | ABS MVR 5D/7/5 (rescue equipment), 46 CFR 113.25-25 (general alarm), ISM 8, ISM 1.4 — and BMA SA25, HSC Code Ch.11, RMI BNWAS notice, LISCR manning notice |
| 4 | "confirming flag state" | 8 | 5 | Bahamas MN091, RMI LRIT notice, LISCR ISM circular, MGN 635 (ro-ro inspections), MARPOL I/2, MLC A5.1.1, SOLAS XI/5, XI-1 |

Karynn, 2026-09-10, "What is the BMP-MS": 8 cites, 5 off-topic (COLREGS Rule 7, MSC.215(82) protective coatings, NVIC 01-18 ballast water, STCW Res 2, 46 USC 50307). BMP is not in the corpus; the answer attributes it to the IMO. **19 of 38 citations across the session were noise.**

### 2.1 Root cause A — hybrid retrieval is live in prod against the measured verdict

`apps/api/app/config.py:212` carries the July note verbatim: *"⛔ MEASURED 2026-07-19 — DO NOT FLIP AS BUILT … Failure mode: RRF's rank-based fusion gives lexically-matching but topically-wrong chunks from small sources (COLREGS, WHO IHR, flag notices) equal footing with dense's correct hits."* Default is `False`. Prod `.env` still says `true` (set 2026-05-09 when the flag was first flipped on; never reverted when the July eval reversed the decision). The 09-09 logs show `rag.retriever:Hybrid selected:` on every query, and the selections are the documented failure mode almost word for word: `bma_mn/BMA SA25 (d=3, l=None, sim=0.0659)`, `who_ihr/WHO IHR Annex 4`, `erg/ERG Hazard ID Numbers` for a man-overboard question.

### 2.2 Root cause B — `flag_state = Unknown` disables jurisdiction severance

The D6.17/D6.23 severance architecture scopes retrieval by vessel flag. With flag Unknown, nothing scopes, so 1,274 Bahamas chunks, 332 RMI chunks and 319 LISCR chunks compete on equal terms with 46 CFR for a US-flag vessel. The user's `jurisdiction_focus` is already `us` — the signal exists on the user row and is not consulted when the vessel row is blank.

### 2.3 Contributing — everything routes to Haiku

Router is complexity-based, not tier-aware (`router.py`; `subscription_tier` reaches `engine.py` but is not used for model selection). Simple questions from a $39/mo user get the cheapest model. Not a bug; a product decision worth making explicitly — a Sonnet floor for Captain costs on the order of a cent per question.

### 2.4 The profile never got completed, and chat cannot fix it

Account created April, upgraded September, `onboarding_completed_at` NULL, `profile_enriched_at` NULL despite an IMO number that could resolve flag/class/tonnage. When the model said "your profile currently shows Unknown" the user did the natural thing and typed the answer into chat. Product fixes, in effort order: (a) when vessel flag is Unknown and the user's `jurisdiction_focus` is set, derive the flag for retrieval scoping; (b) surface a one-click "confirm flag" prompt in the chat UI when the profile is incomplete; (c) enrich from IMO number on vessel save; (d) a chat intent that writes profile fields with confirmation.

### 2.5 Two answers for Karynn to read (5 minutes)

- **MOB alarm.** Answer 2 asserts "continuous ringing of the ship's general alarm bell" as *the* man-overboard alarm and cites NVIC 07-98 §18. NVIC 07-98 is the IMO Standard Marine Communication Phrases circular — a phrase list, not an alarm-pattern authority. MOB alarm patterns are muster-list / SMS-defined; the answer states one as universal.
- **BMP-MS.** Answer says "developed by the International Maritime Organization." BMP Maritime Security (2024) is industry-authored (ICS, BIMCO, INTERTANKO, OCIMF et al.) and circulated by IMO. It is a free PDF and is not in the corpus — the eight citations are adjacent material.

---

## Section 3 — RAG / retrieval state

- **Eval baseline** (unchanged since July): dense strong-recall@8 0.790 / MRR 0.627 on the 62-pair gold set; answer quality 97.4% A-or-A− on 149 questions (2026-05-09). No eval has run since 2026-07-19. Re-run after the hybrid flip is the first verification step; add the Captain's four real questions to the gold set.
- **Tier router** (D6.84) was killed 2026-05-19 (`docs/sprint-audits/tier-router-shadow-kill-2026-05-19.md`). `CONFIDENCE_TIERS_MODE=shadow` in prod `.env` is dead config — `tier_router_shadow_log` has 0 rows in 31 days. Remove for clarity.
- **Ops tables, 31 days:** `retrieval_misses` 0, `web_fallback_responses` 0, `hedge_audits` 0, `off_topic_queries` 0, `citation_errors` 0, `support_tickets` empty. Consistent with five confident answers and no traffic otherwise — the feedback loops are idle, not broken.
- **Glossary** at 63 entries (52 in May). Phase-2 multi-model build not evidently done.
- **OSHA no-cite clause** appears shipped (3 references in `prompts.py`).
- **NULL `model_used` regression:** 0 assistant rows in 31 days. Migration 0115 holds.

---

## Section 4 — Infrastructure + ops

**Green:** all three services `active`, 0 restarts and 0 failed units in 31 days; alembic `0115 (head)` on prod and local; backup `regknots-20260910-030023.sql.gz` (763 MB) this morning; disk 39 %; memory 2.2 GiB available; smoke passes with content assertions on all five routes; Caddy has HSTS / X-Frame-Options / Referrer-Policy (CSP still absent); `.env` mode 600, no CR bytes.

**Findings:**

1. **A second scheduler was missed on 2026-08-10.** I disabled the four systemd corpus-refresh timers and reported the automated jobs off. Celery Beat (`apps/api/celery_beat.py`) has its own schedule and kept running `update_regulations` every Sunday 02:00 UTC for `cfr_33`, `cfr_46`, `cfr_49`, `nvic` (runs 08-16, 08-23, 08-30, 09-06; ~15 min each). Cost is negligible — deltas were 67 / 14 / 41 / 2 / 161 chunks per week plus 41 NVIC chunks, fractions of a cent in embeddings — and it makes **no Anthropic call** (`pipeline.py:181` only instantiates the enricher when `--enrich` is passed; the task does not pass it). It is not what burned the August credits. But it runs as a bare `uv run` subprocess inside the worker's 1 GB `MemoryMax` cgroup, bypassing `run_ingest.sh`, and its output is captured rather than journaled — which is the blind spot in my August "zero Anthropic calls from the VPS" check. Recommendation: keep the weekly refresh (a US-flag Master benefits from a current CFR) but route it through `run_ingest.sh --no-notify`, and log the CLI summary table instead of `stdout[-300:]`.
2. **Monthly non-concurrent REINDEX.** `reindex-vector-embeddings-monthly` runs `REINDEX INDEX idx_regulations_embedding` (no CONCURRENTLY) on the 1st at 03:00 UTC. It held ACCESS EXCLUSIVE for 271 s on 2026-09-01. The July session removed exactly this lock from the ingest path and moved to weekly `REINDEX CONCURRENTLY` in `regknots-db-maintenance.timer`. Delete the Celery task.
3. **eCFR 503s** on 08-23 and 08-30 (`versioner/v1/full/…/title-33.xml`). The task's 1-hour retry handled them; 09-06 was clean. No action, but the retry storm on 08-30 (three attempts, 02:00 → 04:46) is worth a backoff cap.
4. **`uv.lock` drift.** The committed lock is dated 2026-05-15; `playwright` was added to `pyproject.toml` on 05-22 and the lock never regenerated. Every `uv run` on prod re-resolves and dirties the file (`greenlet`, `playwright`, `pyee`). `deploy.sh`'s `reset --hard` reverts it; the next Sunday re-dirties it. Regenerate and commit.
5. **Untracked on prod:** `apps/api/celerybeat-schedule` (runtime state — gitignore it), `packages/rag/test_colregs.py` and `test_retrieval_diversity.py` (April diagnostic probes, dated 2026-04-07). `reset --hard` does not remove untracked files, so nothing is at risk; they are noise.
6. **Worker cgroup.** `MemoryHigh=512M / MemoryMax=1G` with a `cfr_49` ingest (16k chunks) running inside it. It has survived four runs; it is the class of failure the May audit attributed 12 of 13 OOM events to. Item 1 fixes it.
7. **Offsite backup** still not configured — no `offsite` timer registered; `scripts/backup_offsite.sh` header still says it needs Blake's DO Spaces bucket + keys. Local backups continue to share a disk with the database.
8. **Still open from May:** `next@15.5.14` (DoS CVE GHSA-q4gf-8mx6-v5v3, fix is 15.5.15 — four months); Sentry `environment` tag absent from both instrumentation files; no CI (`.github/` does not exist); `llm_helpers.py` not extracted; tests exist for `packages/rag` (7 files) and `packages/ingest` (2) but **zero for `apps/api`**; SpiritFlow co-tenancy unchanged (`merch-*`, `bree-*` still on the box).

---

## Section 5 — Anthropic spend (closing the August loop)

- New key (`…C6Z7xQAA`) valid and loaded by all seven service processes. 27 successful Anthropic calls on 09-09/09-10, 0 errors. Credits present.
- The Celery ingest path cannot spend Anthropic credits without `--enrich`. The August burn was therefore not this either; the off-box conclusion stands, and the legacy key is dead.
- Whether the console spend cap was set is unverifiable from here. Worth a two-minute confirmation.

---

## Section 6 — Corpus

**106,041 chunks across 66 sources** (docs say 77,111 / 50 and ~80k / 64 — both stale). `cfr_*` current to eCFR 2026-09-03; `nvic` refreshed 2026-09-06 (1,638 sections / 4,202 chunks).

Stale bases: `stcw` 2017-07, `ism` 2018-07, `uscg_msm` 2021-09, `marpol` 2022-11. The amendment sources (`stcw_amend`, `marpol_amend` 618 chunks) carry the deltas, so the risk is answer *shape*, not missing rules.

IMO instruments a US-flag container Master needs and the corpus does not have, or has only as an adopting resolution: ISPS Code (absent), LSA Code (58 chunks — resolution text, not the Code), FSS Code (29), 2008 IS Code (absent), Load Lines (3 chunks), IAMSAR Vol III (geo-blocked), BMP MS (absent, free). The acquisition plan — free route vs purchase, per instrument — is in `docs/roadmap.md`.

---

## Section 7 — Documentation drift

| Doc | Last updated | Wrong today |
|---|---|---|
| `docs/PROJECT_STATE.md` | 2026-05-07 | alembic `0092` (is 0115); 77,111 chunks / 50 sources; local path; lists JWT / `.env` perms / backups as open (all fixed) |
| `docs/roadmap.md` | 2026-05-09 | entire "Now / Next" set is four months old; several items shipped, several still open |
| `docs/corpus-status.md` | 2026-05-27 | ~80k / 64; Load Lines "4 chunks" (is 3); NVIC "manual" (is weekly via Celery) |
| `CLAUDE.md` | 2026-07-19 | "refresh timers all active" (four disabled 2026-08-10); no mention of migration 0115, key rotation, or the second scheduler |

Patched today: the factual headers above. Rewritten today: `docs/roadmap.md` (previous archived to `docs/archive/roadmap-2026-05.md`).

---

## Proposed fix spec — awaiting "go"

Nothing below has been executed. Ordered so each step is independently verifiable.

**Step 1 — Retrieval flip (prod, 5 min).**
```
ssh regknots-prod
sed -i 's/^HYBRID_RETRIEVAL_ENABLED=true$/HYBRID_RETRIEVAL_ENABLED=false/' /opt/RegKnots/.env
sed -i '/^CONFIDENCE_TIERS_MODE=/d' /opt/RegKnots/.env
systemctl restart regknots-api
journalctl -u regknots-api -n 5 --no-pager
```
Verify: re-ask "what is the man overboard alarm" against the MAERSK Kinloss profile; expect no `Hybrid selected:` line and no Bahamas / VTS / tonnage chips. Then run `scripts/eval_retrieval.py` and confirm 0.790 / 0.627.

**Step 2 — Captain's vessel (prod DB, 1 min).**
```
UPDATE vessels SET flag_state = 'United States', updated_at = now()
 WHERE imo_mmsi = '9333022' AND flag_state = 'Unknown';
```
Confirm the value string matches whatever `_FLAG_ALIASES` expects before running — read `packages/rag/rag/retriever.py` first.

**Step 3 — Product fix for §2.4** (code, ~2 h): derive retrieval flag from `users.jurisdiction_focus` when `vessels.flag_state` is Unknown; chat-UI "confirm your flag" prompt when the active vessel profile is incomplete. Spec before code.

**Step 4 — Celery hygiene** (code + prod, 30 min): `update_regulations` → `subprocess.run(["scripts/run_ingest.sh", "--source", source, "--update", "--no-notify"])`; delete `reindex-vector-embeddings-monthly` from `celery_beat.py` and the task from `tasks.py`; add exponential backoff cap to the retry; gitignore `celerybeat-schedule`; `uv lock` in `packages/ingest` and commit. Deploy via `scripts/deploy.sh`.

**Step 5 — Stripe** (Blake, dashboard): identify price_id on `sub_1UDop0B6F2sQMkiGQwjVd969`; if absent from `plans.py`, add env var + map entry. Then fix the `invoice.paid` fallback (§1.1) with a fixture test.

---

## Appendix — evidence commands

All read-only. Run from the laptop; `regknots-prod` is the SSH alias.

- Services / timers: `systemctl is-active regknots-{api,web,worker}`; `systemctl list-timers --all | grep regknots`
- Anthropic by day: `journalctl -u regknots-api --since '31 days ago' -o short-iso | grep api.anthropic.com | cut -dT -f1 | uniq -c`
- Hybrid live: `journalctl -u regknots-api --since 2026-09-09 | grep 'Hybrid selected'`
- Celery runs: `journalctl -u regknots-worker --since '31 days ago' | grep -E 'update-regulations-weekly|Ingest (failed|complete)|reindex'`
- Captain row: `SELECT subscription_tier, subscription_status, billing_interval, current_period_end FROM users WHERE email LIKE 'cassclark%';`
- What she was shown: `SELECT m.created_at, r.source, r.section_number FROM messages m CROSS JOIN LATERAL unnest(m.cited_regulation_ids) cid JOIN regulations r ON r.id = cid WHERE m.role = 'assistant' AND m.created_at > now() - interval '31 days' ORDER BY 1;`
- Vessel: `SELECT name, flag_state, classification_society, imo_mmsi, profile_enriched_at FROM vessels WHERE imo_mmsi = '9333022';`
- Corpus: `SELECT source, count(*), max(up_to_date_as_of) FROM regulations GROUP BY 1 ORDER BY 1;`
- Weekly deltas: `SELECT source, detected_at::date, changed_sections FROM regulation_versions WHERE detected_at > '2026-08-01' ORDER BY 2;`
- Prod drift: `cd /opt/RegKnots && git status --short`
- Stripe trace: `journalctl -u regknots-api --since 2026-09-09 --until 2026-09-10 | grep -iE 'webhook|checkout|Invoice paid'`
