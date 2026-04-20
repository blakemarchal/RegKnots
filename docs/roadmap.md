# RegKnot Roadmap

**Last updated:** 2026-04-20 (post-notification-system sprint)

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
- Source-affinity boost: queries mentioning `MSIB`, `MMC`, `medical certificate`, etc. tilt scoring toward the relevant group.
- Vessel-profile boost: query scoring adjusts for the active vessel's type, route, cargo.
- Tailored starter prompts on empty chat, driven by the active vessel's profile.

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

### 1c. Pilot-user feedback loop on bulletin smoke tests

Sprint B2's smoke tests showed 4/4 queries surfacing uscg_bulletin content. Real-world queries from Karynn + early pilot captains will reveal what the synthetic tests miss. Need:

- Light-touch logging of which bulletin chunks get cited in chat responses.
- Weekly review pass on the bulletins that are NEVER cited (likely candidates for stricter filtering next iteration).
- Weekly review pass on queries that returned 0 bulletin hits (candidates for missing operational terminology in our enrichment).

**Estimated effort:** 0.5 session to add the logging + a standing weekly review checklist.

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

- Migration 0042 downgrade path omits `ism_supplement` (legacy bug, fixed forward in 0044 but downgrade-of-0042 still regresses).
- `regulations` table has no `updated_at` column — cannot tell when a chunk was last modified vs. first inserted. Low priority; `content_hash` + version table cover most audit cases.
- Local Windows DNS is unreliable (private note — forces curl `--resolve` workaround on local test fetches).
- CRA `_send_trial_reminders_async` and similar tasks read `RESEND_API_KEY` from env; not currently hit by notify.py's immediate-alert path because env isn't set in the ingest container.

## Deprecated / removed

- `nmc_memo` source. Shipped in migration 0042 but had no working adapter (dispatch called methods that didn't exist). Dropped in migration 0044.
- Blanket Pass 1 ALCOAST accept rule in uscg_bulletin filter (Sprint B). Replaced with LLM-classifier decision in Sprint B2.
