# RegKnot Roadmap

**Last updated:** 2026-04-20 (post-Sprint-C3)

> **One-page snapshot:** `docs/PROJECT_STATE.md` is the canonical quick-reference for fresh sessions. This file is the strategic roadmap.

## Recent sprints (reverse chronological)

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

We have 3 years of USCG bulletin history via the Wayback CDX backfill, but no ongoing ingestion. New bulletins appear daily. Need:

- Subscribe `alerts@regknots.com` (or similar) to the USDHSCG GovDelivery feed.
- Inbound email parser (Resend webhook or Postmark inbound) extracts bulletin URL + subject + body from each email.
- Apply the same Pass-1-deterministic / pre-deny / Pass-2-LLM filter pipeline we use for the backfill.
- Upsert via the existing `uscg_bulletin` source — no schema changes.

**Estimated effort:** ~1 session including Resend webhook wiring. Zero cost beyond the Haiku classifier (~$0.01/day).

**Why priority 1:** the backfill data goes stale fast. "Latest MSIB" queries need real-time freshness to justify the marketing claim.

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
