# RegKnot Roadmap

**Last updated:** 2026-04-20 (post-Sprint-C3)

> **One-page snapshot:** `docs/PROJECT_STATE.md` is the canonical quick-reference for fresh sessions. This file is the strategic roadmap.
>
> **Agent split:** Claude Code owns the repo (`/opt/RegKnots`, local worktree). Claude Cowork owns everything else — Gmail, `data/raw/` folder hygiene, pilot-ops reports, business paperwork. See §5 below.

## Recent sprints (reverse chronological)

### Sprint D5.1 — 46 USC Subtitle II ingest (2026-04-23)
Ingested US Code Title 46 Subtitle II (Vessels and Seamen) — 399 non-repealed sections, 511 chunks — to directly address Karynn's 2026-04-22 labor-cluster hedges (foreign articles, slop chest, crew sign-on, wages). Adapter parses USLM XML from the House release-point zip (current through Pub. L. 119-84). Added `usc_46` to authority.py as Tier 1 (binding statute) and to retriever.py as its own SOURCE_GROUP (prevents crowding by the much larger CFR corpus in per-group diversification).

Results: eval 150 runs, A-or-A− **95.3% → 98.7%**, F count **7 → 2**. Sailor-speak subset hit **100% A-or-A−** for the first time. Sailor-speak `labor` domain hedge rate **66.7% → 33.3%** (target achieved). Other major improvements: security 66.7% → 0%, port 55.6% → 22.2%, hazmat 44.4% → 22.2%, nav 33.3% → 11.1%. Minor regression on credentialing (26.7% → 40.0%) — USC Chapter 71 now competes for retrieval attention with 46 CFR Parts 10-12; worth one session of retrieval tuning when time allows. All three new USC canary questions (U-1 slop chest, U-2 articles, U-3 discharge) grade A.

**D5.2 (BMP5) and D5.3 (USCG Marine Safety Manual) blocked on source acquisition** — BMP5 PDFs 404/403 across all known URLs (likely retired in favor of the 2025 Global Counter Piracy Guidance, which we haven't located publicly yet); USCG MSM is behind Akamai anti-bot on dco.uscg.mil. Both need manual download + scp path. Documented in `docs/MORNING_REVIEW_2026-04-23.md` for operator decision.

### Sprint D3 — authority-tier synthesis with ERG protection (2026-04-22)
New `packages/rag/rag/authority.py` maps every source to a 4-tier authority scheme (binding statute/treaty → federal interpretive guidance → operational notice → domain reference standard). The context builder prefixes every retrieved chunk with its tier label, and the system prompt gained three rules: conflict resolution (prefer higher tier when sources truly conflict), applicability (identify which Tier-1 applies when SOLAS vs CFR or different Subchapters could both apply), and explicit **Tier-4 protection** — ERG must not be deprioritized by Tier 1 for hazmat questions because it's the authoritative source within its own subject matter (first-response actions, isolation distances, PPE). Ships with two new regression questions: N-AUTH1 (UN1219 on international voyage — must cite both ERG Guide 129 and 49 CFR HM rules) and N-AUTH2 (fire safety applicability test for international containership). Post-D3 eval: 57/57 A-or-A−, zero ERG regression, both AUTH questions graded A with correct dual-citation and applicability reasoning.

### Sprint D2.1 + D2.1b + D2-LOG — naturalistic eval, hedge demotion, retrieval-miss logging (2026-04-22)
Measurement-first pass on the "more bad answers than good lately" pushback. Three coordinated deliverables shipped together:

- **D2.1** — `scripts/eval_rag_baseline.py` gained 20 naturalistic-phrasing questions (verbatim from real hedged user queries: Karynn's G&H Towing, chlorine/ammonia/UN1219, VDR beacon, HRA transit) alongside the existing 28 regulatory-register questions. Added V0 "no vessel profile" so we can measure Karynn's exact failure mode directly.
- **D2.1b** — new `packages/rag/rag/hedge.py` module with `HEDGE_PATTERNS` shared between the engine and the eval grader. Eval now demotes A→A− and A−→B when the answer contains a hedge phrase, closing the "partial retrieval + honest hedge still graded A because a peripheral citation matched regex" loophole that masked the real bad-answer signal.
- **D2-LOG** — migration 0047 adds `retrieval_misses` table. Every chat response whose final answer contains a hedge phrase gets logged with the query, vessel_profile_set boolean, full vessel_profile JSONB, top-8 retrieved chunks with similarity scores, what the model actually cited, the matched hedge phrase, model/tokens, and a 2KB answer preview. Fire-and-forget; DB errors never fail chat responses.

Key finding from D2.1 baseline: the blanket "paraphrase retrieval is broken" hypothesis was wrong. ERG, credentialing (with vessel), and most naturalistic scenarios pass. The real failures are concentrated: (a) no-vessel profile → partial retrieval → hedge (Karynn's exact bug), (b) specific-interval queries (VDR, fire pump), and (c) geographic/ops scenario queries that don't trigger bulletin retrieval (N-P1 Mississippi). D2.2 / D2.3 broad alias-enrichment was cancelled; D2-LOG + Karynn's real-user test session will drive the targeted fixes. Pre-D2-LOG we could only find these by hand-grepping `messages.content`; now they accumulate as structured data.

### Sprint D1 — NMC monitor admin-only weekly digest (2026-04-22)
Retired the `nmc_memo` user-facing notification pathway that had been producing cold-start bursts of ~220 banners every time the `notifications` table was purged. New state: migration 0046 adds `nmc_monitor_seen_urls` as a dedicated tracking table; `check_nmc_updates` now reads/writes that table, dedupes new findings against the already-ingested `nmc_policy`/`nmc_checklist` corpus, and sends a single admin-only digest to `blakemarchal@gmail.com`. Zero rows are ever inserted into `notifications`. `scripts/seed_nmc_monitor.py` pre-populated the table with the current 221-URL NMC catalog on deploy so the first scheduled run will produce near-zero findings. Preferences list lost `nmc_memo` and picked up the actual shipped `nmc_policy`, `nmc_checklist`, `uscg_bulletin` entries.

### Sprint C3 — per-vessel grader + project state doc (2026-04-20)
Tightened the autonomous regression grader to use per-vessel `expected` regex dicts (V1 expects `46 CFR 96.35-10`, V2 expects `35.30-20`, V5 expects `142.226`) so cross-vessel regex leakage no longer masks applicability bugs. Added `29 CFR 1910` to `wrong_sub` to catch OSHA hallucinations. Still 28/28 A. Created `docs/PROJECT_STATE.md` as the operational one-pager. VPS + origin + local reconciled to `92d2d89`.

### Sprint C2 — vessel-type × CFR-Subchapter applicability filter (2026-04-20)
Retrieval now drops CFR chunks from Parts that don't apply to the user's vessel type (mapping at `packages/rag/rag/retriever.py:_VESSEL_TYPE_CFR_APPLICABILITY`). 10 vessel types mapped to applicable/forbidden CFR Part prefixes; non-CFR sources (SOLAS/NVIC/NMC/bulletin/ERG) pass through. Eval went from C1's 89.3% A-or-A- → 100% A.

### Sprint C1 — prompt refresh (2026-04-20)
Added NMC policy letters, NMC checklists, USCG bulletins to the KNOWLEDGE BASE SOURCES block with cite formats. Added an explicit anti-OSHA clause ("DO NOT cite 29 CFR") with a tanker-SCBA-specific redirect to 46 CFR 35.30-20 + SOLAS Ch.II-2 + NVIC 06-93. Softened the COVERAGE clause. Baseline 92.9% → C1 89.3% (mixed — prompt alone wasn't enough, set up C2).

### Sprint B3 — CFR content-hash gate + rollback tooling (earlier April)
Threshold-gated content-hash sensitivity so weekly eCFR republishes don't fire "3,482 new sections" notifications on trivial whitespace changes. Wrote `scripts/rollback_source.sh` for transactional corpus + notification rollback after the Sprint B → B2 transition left a stale banner.

### Sprint B2 — USCG bulletin filter rewrite (earlier April)
Replaced the blanket "accept all ALCOASTs" Pass 1 with a subject-only deterministic filter + Claude Haiku LLM Pass 2 with prompt caching. Dropped from 7,414 raw → 1,658 operational bulletins (2,232 chunks).

### Sprint B — USCG GovDelivery backfill (earlier April)
3 years of Wayback-CDX-sourced MSIBs, ALCOASTs, NMC announcements. New `uscg_bulletin` source + migration 0045 freshness columns (`published_date`, `expires_date`, `superseded_by`).

---

## 0. Current state — what we have today

### Corpus (15 sources)

| Source | Type | Notes |
|---|---|---|
| cfr_33 | CFR Title 33 | 7,190 chunks. Navigation, towing, drawbridges. |
| cfr_46 | CFR Title 46 | 10,523 chunks. Shipping, inspection, credentialing. |
| cfr_49 | CFR Title 49 | 15,827 chunks. Hazmat, transportation. |
| colregs | International / Inland Nav Rules | 102 chunks. |
| erg | Emergency Response Guidebook 2024 | 762 chunks. Material-name alias enrichment. |
| ism | ISM Code | 63 chunks. |
| ism_supplement | MSC resolution amendments to ISM | 23 chunks. |
| solas | SOLAS 2024 Consolidated | 1,034 chunks. |
| solas_supplement | MSC resolution amendments to SOLAS | 12 chunks. |
| stcw | STCW Convention + Code | 532 chunks. |
| stcw_supplement | MSC resolution amendments to STCW | 4 chunks. |
| nvic | Navigation & Vessel Inspection Circulars | ~3,450 chunks. NVIC 04-08 Ch-2 (medical) manually ingested. |
| **nmc_policy** | NMC policy letters + crediting | 127 chunks. 13 docs, 4 OCR'd via Claude Vision. |
| **nmc_checklist** | MMC application / renewal checklists | 33 chunks. 6 docs. |
| **uscg_bulletin** | USCG GovDelivery — MSIBs, ALCOASTs, NMC announcements | 2,232 chunks. 1,658 bulletins filtered from 7,414 fetched. |

Total corpus: ~42,000 chunks across 15 sources. Three new sources (bold) added in the last two weeks.

### Retrieval & RAG features

- Hybrid search: vector (text-embedding-3-small, pgvector HNSW) + ILIKE trigram + structured-identifier regex (UN1219, NVIC 04-08, Rule 14, etc.).
- Source-diversified fetch: per-group top-N so small sources aren't swamped by CFR.
- **Vessel-type × CFR-Subchapter applicability filter (Sprint C2)** — drops CFR chunks from Parts that don't apply to the user's vessel type; non-CFR sources pass through. Map at `packages/rag/rag/retriever.py:_VESSEL_TYPE_CFR_APPLICABILITY`.
- Source-affinity boost: queries mentioning `MSIB`, `MMC`, `medical certificate`, etc. tilt scoring toward the relevant group.
- Vessel-profile boost: query scoring adjusts for the active vessel's type, route, cargo.
- Citation verification: regex extracts cites, verifies each in DB; regenerates on unverified with feedback; strips any still-unverified.
- Tailored starter prompts on empty chat, driven by the active vessel's profile.

### Eval & QA infrastructure

- `scripts/eval_rag_baseline.py` — autonomous regression harness (28 queries × 5 vessel profiles) with per-vessel expected regex + `wrong_sub` Subchapter-leakage detection. Current score: 28/28 A.
- `scripts/debug_retrieval.py` — replay any query against live retriever with vessel context.
- `scripts/verify_filter.py` — standalone unit test for `_filter_by_vessel_applicability`.

### Ingest features

- Shared chunker (512-token, 50-overlap) + shared embedder (OpenAI text-embedding-3-small) + shared pgvector upsert.
- LLM-based classifier pipeline (Claude Haiku with prompt caching) for noisy firehose sources (GovDelivery). Fail-closed on any API error.
- ERG-style alias enrichment per source: credential vocabulary on NMC docs, material names on ERG, operational vocabulary on bulletins.
- Freshness metadata (`published_date`, `expires_date`, `superseded_by`) captured at ingest. Retrieval-side filtering not yet implemented.

### Notifications & UX

- Collapse-per-source: one active banner per source, not a running history.
- Bulk-republish gate: eCFR weekly republishes no longer fire thousands-of-sections notifications when content didn't substantively change.
- Coming Up widget now shows only user-specific items (credentials, COI, PSC checklist, log gap) — no longer duplicates regulation banners.
- Rollback helper script keeps corpus state and notifications in sync.

---

## 1. Priority 1 — weeks ahead (pre-marketing-push)

### 1a. GovDelivery forward channel

We have 3 years of USCG bulletin history via the Wayback CDX backfill, but no ongoing ingestion. New bulletins appear daily.

**V1 — Cowork-driven (recommended, zero code):** subscribe Blake's Gmail to GovDelivery, let a scheduled Cowork task triage the inbox weekly, classify MSIB/ALCOAST/NMC, drop PDFs + metadata into `data/raw/uscg_bulletins/`, and fire the existing ingest pipeline. See §5 below.

**V2 — webhook-driven (upgrade, if/when near-real-time becomes a marketing claim):**
- Subscribe `alerts@regknots.com` to the USDHSCG GovDelivery feed.
- Inbound email parser (Resend webhook or Postmark inbound) extracts bulletin URL + subject + body from each email.
- Apply the same Pass-1-deterministic / pre-deny / Pass-2-LLM filter pipeline we use for the backfill.
- Upsert via the existing `uscg_bulletin` source — no schema changes.

**Estimated effort:** V1 ~30 min of Cowork setup. V2 ~1 session including Resend webhook wiring. Zero cost beyond the Haiku classifier (~$0.01/day) either way.

**Why priority 1:** the backfill data goes stale fast. "Latest MSIB" queries need freshness to justify the marketing claim; V1 gets us to weekly-fresh now, V2 goes real-time later.

### 1b. Retrieval-side freshness filtering

Three columns added in migration 0045 are captured but unused in retrieval. Need:

- Add `WHERE expires_date IS NULL OR expires_date > NOW()` clause to the bulletin retrieval path.
- Weight recent bulletins (past 30 days) higher than 3-year-old ones via a published_date-based score bump.
- Honor `superseded_by` by excluding documents that have been explicitly replaced.

**Estimated effort:** ~1 session. Pure retriever change, no schema or ingest changes. Matches the sprint prompt's original "retrieval-side expiration filtering (future sprint)" flag.

### 1c. Karynn exhaustive test pass (in progress)

Current blocker before re-engaging lapsed pilots. Karynn runs the 10-vessel × ~60-question test bank (`docs/testing/retrieval-regression-test-plan.md`) over 2-3 days. Any findings get a hardening sprint before pilots see the upgraded system. Then: personal "we heard you, we upgraded" note from Karynn to lapsed pilots.

**Status:** awaiting Karynn's availability; harness + test bank + PROJECT_STATE doc all ready.

### 1d. V5/F5 retrieval gap — Subchapter M CO2 promotion

Identified but deferred during Sprint C2: towing-vessel CO2 system question (`46 CFR 144.240`) isn't being surfaced by vector search. The filter can drop wrong content but can't promote missing content. Answer degrades to honest-limit rather than wrong, so it's not eval-failing — but a real Subchapter-M captain would expect the citation. Needs a retrieval-side promotion pass once Karynn's test data reveals whether this is an isolated miss or a pattern.

**Estimated effort:** 1 session, pending pilot data to scope.

### 1e. Pilot-user feedback loop on bulletin smoke tests

Sprint B2's smoke tests showed 4/4 queries surfacing uscg_bulletin content. Real-world queries from Karynn + early pilot captains will reveal what the synthetic tests miss. Need:

- Light-touch logging of which bulletin chunks get cited in chat responses.
- Weekly review pass on the bulletins that are NEVER cited (likely candidates for stricter filtering next iteration).
- Weekly review pass on queries that returned 0 bulletin hits (candidates for missing operational terminology in our enrichment).

**Estimated effort:** 0.5 session to add the logging + a standing weekly review checklist.

### 1f. Deploy script — end ssh-and-edit drift

Sprint C1/C2 was deployed by ssh-into-VPS-and-edit-in-place, leaving the VPS git HEAD 3 commits behind its running code until C3 reset cleaned it up. A `scripts/deploy.sh` that does `ssh … "cd /opt/RegKnots && git fetch && git reset --hard origin/main && systemctl restart regknots-api regknots-web regknots-worker"` would make future deploys boring and auditable.

**Estimated effort:** 0.25 session.

## 2. Priority 2 — next month

### 2a. content_hash normalization (Issue A proper fix)

The threshold-based gate we just shipped suppresses ~90% of the noise, but a "proper" fix normalizes chunk_text before hashing (strip whitespace variance, metadata timestamps) so weekly eCFR republishes don't register as changes at all. Migration-adjacent: computing new canonical hashes without triggering a mass "update" event on the transition.

**Estimated effort:** ~1 session, needs careful rollout plan.

### 2b. NVIC adapter section-numbering fix

The NVIC adapter's regex matches numbered list items inside enclosures as top-level sections, producing 1,277 unique section_numbers for ~160 actual NVICs. Collapsing to one section per document + chunk_index for sub-sections would (a) reduce citation noise and (b) align with the simpler NMC adapter pattern.

**Estimated effort:** ~1 session including re-ingest.

### 2c. "Compliance Activity" pilot user check-in surface

Today the Coming Up widget is a read-only signal. Capture user acknowledgment: when a user dismisses an expiring-credential item, log it. Daily email digest fires only when there's net new activity. Credential-expiry reminders + MSIB alerts for relevant vessel types become a weekly newsletter.

**Estimated effort:** ~2 sessions (backend + email template + digest cadence config).

### 2d. 2FA (user-requested, previously deferred)

TOTP enrollment + backup codes + login step-up + account recovery. Scoped ~4-8 hours pre-launch. Revisit now that marketing push is imminent and user accounts will matter more.

**Estimated effort:** 1 full session.

## 3. Priority 3 — quarter ahead

### 3a. Forms product v1 — downloadable CG-719 series

The 7 CG-719 PDFs at `data/raw/nmc/` (excluded from RAG corpus) could be served as a direct-download utility: `/forms` page listing the MMC applications, medical certificate forms, etc. with metadata about each form's purpose and which endorsements it's used for. Requires AcroForm verification first (the placeholder URL files from the prior audit need to become real PDFs).

**Estimated effort:** 1 session for v1 (download only). Adds ~$0 in infra — serve static.

### 3b. Forms product v2 — in-app fill + save

v2 turns the forms into first-class in-app objects: render the PDF fields as a form, save drafts, produce filled PDFs for download. Requires pypdf or similar, plus a new `form_drafts` table. Depends on v1.

**Estimated effort:** 4-6 sessions (AcroForms), +50% if any are scanned.

### 3c. USCG Maritime Commons blog ingest

`mariners.coastguard.blog` is a mariner-facing blog that aggregates important USCG posts. Adds another discovery channel for bulletin-adjacent operational content. Non-Akamai, RSS-feedable.

**Estimated effort:** 1 session.

### 3d. CFR Title 50 (NOAA fisheries) — if we pivot toward commercial fishing

Current corpus covers 33/46/49. Fishing captains would want 50 too. Sizeable — ~20K chunks. Low priority unless fishing becomes a target segment.

### 3e. MARPOL dedicated source

Environmental-compliance queries currently hit CFR 33 subchapter N, which is the US implementation. The International MARPOL convention text is a separate document and would strengthen the international-voyage user segment.

**Estimated effort:** 1 session to obtain + ingest + enrich.

## 4. Non-code priorities (for Karynn to drive)

- **Pilot user recruitment** — 10-20 captains across vessel types (small passenger, tug, tanker, offshore). See the operator update in `docs/announcements/operator-update-april-2026.md`.
- **Marketing content** — operator-voice case studies; "ask RegKnot about MSIB Vol XXV Issue 046" demo video.
- **Regulatory partnership** — maritime associations (AMO, CAWA, Passenger Vessel Association, OMSA) — one-page flyer introducing RegKnot as a free-tier tool for members.

---

## 5. Claude Cowork integration

**Agent split:** Claude Code owns `/opt/RegKnots` and the local repo (worktrees, deploys, CI-adjacent work, all file edits inside the repo). Claude Cowork owns everything else — Gmail, `data/raw/` folder hygiene, pilot-ops reports, business paperwork, Karynn deliverables.

Do **not** connect Cowork to the repo path. Mixing both agents on the same repo will create exactly the kind of "which agent committed what to which branch" mess that the Sprint C3 VPS reset just cleaned up.

**Classifier boundary (critical):** the authoritative USCG-bulletin classifier is the Pass-1-deterministic + Pass-2-Haiku pipeline in `packages/ingest/sources/uscg_bulletin.py`. Cowork never classifies for ingest. When Cowork reads email subject lines to describe them in a weekly summary, that's a summary-only label — it must never be used as canonical metadata for a chunk. Two classifiers → guaranteed drift.

### 5.0. One-time setup

- Install the **Founders / Productivity** plugin (whichever is available) in Cowork.
- Connectors, priority-ranked:
  - 🟢 **Gmail** — GovDelivery inbox processing, Karynn comms, pilot outreach
  - 🟢 **Local filesystem** scoped to `C:\Users\Blake Marchal\Documents\RegKnots\data\raw\` — regulation PDF staging, corpus hygiene
  - 🟡 **Google Sheets / Excel** — pilot metrics tracking, weekly one-pager source
  - 🟡 **Google Calendar** — sprint cadence, Karynn sync scheduling
  - ⚪ **GitHub (read-only)** — "what shipped this week" summaries for Karynn (never write). Note: read-only includes issues and PR bodies; don't paste prompts, API keys, or proprietary content into either.
  - ⚪ **Stripe** — billing-state reports once we turn on paid tiers

Copy/paste bring-up prompts live at `docs/chat-bring-up-prompt.md`.

### 5.1. GovDelivery inbox → ingest pipeline staging (scheduled Mon 0700) — supersedes 1a V1

Cowork task reads GovDelivery emails from the past 7 days, downloads attached PDFs + captures source URLs, stages them into `data/raw/uscg_bulletins/incoming/<YYYY-MM-DD>/`, writes a per-folder `manifest.json` with subject, sender, URL, file path, and Cowork's **descriptive label** (not a classification — see boundary rule above). The authoritative MSIB/ALCOAST/NMC classification happens when Blake runs the existing `packages/ingest` pipeline against the staged folder.

**Why Cowork-first:** the backfill ingest pipeline already works; the missing piece is delivery. Wiring a Resend webhook (V2) costs a session. A Cowork task costs 30 min.

**When V2 becomes necessary:** Cowork's weekly cadence means a bulletin published on Tuesday sits in Gmail for ~6 days before becoming queryable. Fine for current pilot users — nobody is asking "latest MSIB" with sub-24h expectations. But when marketing claims "real-time regulatory freshness" as a differentiator, or when a single real-world incident surfaces a "this bulletin came out 3 days ago and you didn't have it" user complaint, build V2. V2's Resend webhook lands into the same `incoming/` staging folder — the migration is drop-in.

### 5.2. Weekly RegKnot ops one-pager for Karynn (scheduled Mon 0800)

Pull: (a) new USCG GovDelivery email subjects received in Gmail past 7 days with Cowork's descriptive label (not a canonical classification), (b) files added to `data/raw/` past 7 days, (c) recent commit subjects on the RegKnots repo via GitHub connector, (d) user-facing metrics (DAU, messages/user, checklist edit rate) from the ops dashboard export. Compose into a Google Doc titled "RegKnot weekly — {date}". Share read link with Karynn.

**Independent value:** this artifact earns its keep even if §5.1 never ships. Partnership rhythm is the actual product here — Karynn gets consistent context without Blake writing status updates, which is exactly the kind of thing that quietly falls apart in a 50/50 partnership when one side is heads-down in code.

Replaces §2c "Compliance Activity digest" for the *internal* use-case; the pilot-facing digest still ships as code when we get there.

### 5.3. Regulation source folder hygiene (scheduled Sun 1800)

Scan `data/raw/solas/`, `data/raw/solas_supplements/`, `data/raw/nmc/`, `data/raw/erg/`, and flag: inconsistent filenames (non-ISO date prefixes, mixed case), duplicates via filesize+mtime, zero-byte or corrupted PDFs, unexpected files (non-PDF, non-metadata). Propose renames + moves; require Blake's approval before executing. Write a weekly hygiene report to `docs/ops-log/folder-hygiene-<date>.md`.

### 5.4. Business paperwork assembly (ad-hoc)

LLC filings, trademark renewals, Stripe tax-form assembly, vendor agreements. Document-assembly tasks: hand Cowork the folder + template + prior year's version, get back drafts for Blake to review.

### 5.5. Pilot outreach personalization (ad-hoc, after Karynn's test pass)

Once Karynn's test bank yields results, Cowork drafts per-pilot outreach emails (from Karynn's voice, citing specific upgrades that addressed that pilot's original complaint) for her to review and send.

---

## Known drift / tech debt

- **CRLF/LF on VPS**: ssh-edited files on `/opt/RegKnots` were LF; local repo is CRLF. Benign (git auto-normalizes), but every file on the VPS will show as "modified" until `git reset --hard origin/main` is run. Hardened by the Sprint C3 reset; the deploy script (1f) will keep it fixed.
- **DB check constraint drift**: `ism_supplement` was added to the prod `sources` check constraint live on the VPS, but the change isn't captured in a migration file. Next time migration 0042 downgrades run, this regresses. Low-probability issue.
- Migration 0042 downgrade path omits `ism_supplement` (legacy bug, fixed forward in 0044 but downgrade-of-0042 still regresses).
- `regulations` table has no `updated_at` column — cannot tell when a chunk was last modified vs. first inserted. Low priority; `content_hash` + version table cover most audit cases.
- Local Windows DNS is unreliable (private note — forces curl `--resolve` + `--ssl-no-revoke` workaround on local test fetches).
- CRA `_send_trial_reminders_async` and similar tasks read `RESEND_API_KEY` from env; not currently hit by notify.py's immediate-alert path because env isn't set in the ingest container.
- Live GovDelivery feed not wired — bulletin corpus freshness stops at ~2026-04. Priority 1a.

## Deprecated / removed

- `nmc_memo` source. Shipped in migration 0042 but had no working adapter (dispatch called methods that didn't exist). Dropped in migration 0044.
- Blanket Pass 1 ALCOAST accept rule in uscg_bulletin filter (Sprint B). Replaced with LLM-classifier decision in Sprint B2.
