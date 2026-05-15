# Class-society corpus — Sprint D6.93 status + DNV follow-up

**Author:** Claude (with Blake)
**Date:** 2026-05-15
**Motivating use case:** Karynn's 2026-05-13 ship-handover question — vessel had an emergency diesel generator failure plus a defective backup transformer. She needed to know if class-society reporting was required. The vessel referenced Lloyd's Register Rules sections 31.01-3(b), 71.15-5(b), 91.15-5(b) from the 1998 edition. Maersk's vessel manager couldn't answer; RegKnots should.

## What shipped this sprint

| Source | DB tag | Citation shape | Status |
|---|---|---|---|
| ABS Marine Vessel Rules (2025) | `abs_mvr` | `ABS MVR Pt.4 Ch.2 Sec.1` | **Live** — 354 sections / 5,851 chunks (Pt.3, 4, 5C-1, 5C-2, 5D, 6 + Notices + Notations Table; 217 MB) |
| Lloyd's Register — Code for Lifting Appliances (LR-CO-001, July 2025) | `lr_lifting_code` | `LR-CO-001 Ch.10 Sec.2` | **Live** — 81 sections / 448 chunks across 15 .docx files |
| Lloyd's Register — Rules for Classification of Ships (LR-RU-001, July 2025) | `lr_rules` | `LR-RU-001 Pt.6 Ch.2 Sec.3` | **Live** — 615 sections / 2,982 chunks across Pt.1, 2, 3, 4, 5, 6, 8 + Notice 1. Pt.7 (Other Ship Types and Systems) pending Blake's pull. |

## Classification model

All three new sources are tagged uniformly:

- **Jurisdictions:** `["intl"]` (universal). Class society scope is per-vessel, not per-flag. ABS classes Liberian/MH/Singapore-flag tankers; LR classes vessels under just as many flags. Tagging the society's HQ flag (`["us"]` for ABS, `["uk"]` for LR) would silently hide the rules from non-US/non-UK users whose vessels are classed by them. `intl` mirrors the IACS UR / SOLAS / IMO codes posture. Made explicit in `packages/ingest/ingest/store.py` _SOURCE_TO_JURISDICTIONS and `packages/rag/rag/jurisdiction.py` SOURCE_TO_JURISDICTIONS (previously fell through to the default — fragile, now documented).

- **Authority tier:** Tier 1 (binding regulation/treaty). By analogy to `mca_msn` (Tier 1 — "binding technical detail of UK Statutory Instruments"). SOLAS Ch.II-1 delegates construction approval to "recognized organizations" — the class society's rules ARE the binding technical detail behind that SOLAS delegation for the classed vessel. Not interpretive guidance (Tier 2), not domain-reference (Tier 4 — that's IACS URs, common-denominator across all members).

- **Retrieval group:** `class_society` in `packages/rag/rag/retriever.py` SOURCE_GROUPS. Independent candidate pool: up to 6 chunks per source per query, so a class-survey query doesn't crowd CFR/SOLAS candidates. When all three surface together, the synthesizer disambiguates by vessel profile (which society the user's vessel is actually classed by).

- **References authority order:** placed between Tier 3 (USCG bulletins) and flag-state circulars in `_REFERENCES_AUTHORITY_ORDER` (`apps/api/app/routers/regulations.py`). On citation 404 fallback, class society rules surface above flag-state circulars but below the primary IMO/CFR sources — they're binding for the classed vessel but ABS Pt.4 isn't more authoritative than SOLAS itself.

Migration `0099_add_class_society_sources.py` adds all three to the
`regulations.source` CHECK constraint. RAG side: `_SOURCE_TO_TIER`
ranks them Tier 1 (binding for classed vessels), `SOURCE_GROUPS` has
a new `class_society` group, `_REFERENCES_AUTHORITY_ORDER` places
them between Tier 3 and flag-state.

## What was deferred + why

### ABS Parts 1, 2, 5A, 5B, 7

Same publisher (`ww2.eagle.org` CDN — free, no auth) but a different
filename convention than Parts 3 / 4 / 5C-* / 5D / 6 / Notices /
Notations. The pattern `1-mvr-part-N-jul25.pdf` returned 404 for
N=1, 2, 5a, 5b, 7. Tried curl brute-force on plausible permutations
plus `WebFetch` on the directory listing plus `WebSearch site:ww2.eagle.org`
— no hits. ABS likely uses a different prefix (`2-mvr-part-…`?) or a
date variant (`jan25` instead of `jul25`) for those parts. **Cost to
resolve:** ~30 minutes manually inspecting the ABS publications page
in a browser, copying the actual URLs. The deferred parts cover:

- Pt.1 — Classification and Surveys (relevant for Karynn's reporting
  question — survey-trigger criteria live here)
- Pt.2 — Materials and Welding
- Pt.5A — Vessels Intended to Carry Oil
- Pt.5B — Vessels Intended to Carry Chemicals in Bulk
- Pt.7 — Surveys After Construction

**Recommendation:** Blake to pull these via browser at the next
opportunity (same flow as LR-RU-001), drop them into
`data/raw/abs/` on his laptop, `scp` to VPS, re-run
`scripts/run_ingest.sh --source abs_mvr --update`. The `--update`
mode hashes-skips unchanged content, so re-running is cheap.

### DNV (Det Norske Veritas) — fully blocked tonight

DNV publishes rules at `rules.dnv.com` but the site is a React SPA.
Non-browser agents (curl, WebFetch, Python httpx) receive a 739-byte
JavaScript shim that bootstraps the React app — no actual rule
content. The PDF download buttons are gated behind:

1. The SPA must boot (requires a JS engine)
2. Some endpoints require an authenticated session cookie
3. PDFs are served from a separate CDN with short-lived tokens
   embedded by the SPA on first render

Attempted workarounds:

- **3rd-party mirrors** — pame.is (Iceland Marine Inspection) and
  home.hvl.no (Norwegian university) mirror a handful of DNV rule
  sets but coverage is patchy (mostly older editions of a few
  technical guides; nothing systematic).
- **DNV's `dnv.com/maritime` published-products page** — links into
  the same SPA. Even direct PDF URLs from the page require the SPA
  to inject auth.

**The right approach is a Playwright-driven scrape:**

1. Headless Chromium launched against `rules.dnv.com`
2. Wait for SPA boot (DOMContentLoaded + 2s settle)
3. Programmatically click each rule category, follow each PDF
   download button, capture the resulting PDF
4. Run the same `ingest.sources.dnv_rules` adapter we'd write
   (modeled after `abs_mvr.py`)

**Scope estimate:** ~1 day. The discover phase is the bulk of it
because DNV's rule structure differs (numbered "Pt./Ch./Sec." plus
"Service Specifications", "Standards", "Recommended Practices",
"Class Programmes" — five distinct doc families). Adapter itself
mirrors the ABS pdfplumber pattern.

**Worth doing?** DNV classes a meaningful slice of European-flag
tankers and container ships, plus a growing offshore wind portfolio.
For US-flag operators (RegKnots' primary segment), ABS is far more
common; LR sits in second place. DNV is third-tier from a US-flag
hit-rate perspective. **Recommendation: queue for a separate sprint
after ABS + LR are validated against real questions for 2-4 weeks.**

### BV (Bureau Veritas) and ClassNK

Both gate their rule sets behind member portals (login required).
No public scrape path. Defer indefinitely unless RegKnots picks up
a user with a BV- or ClassNK-classed vessel and Blake can borrow
their member credentials to verify they're the right answer source
before investing in OCR'ing partner-shared PDFs.

## Sources we did not pursue (and why)

| Society | Status | Note |
|---|---|---|
| RINA (Italy) | Skipped | Public PDF access exists but small US-flag footprint. Tier 4 priority. |
| KR (Korean Register) | Skipped | Member-portal gated. Same as BV/ClassNK. |
| CCS (China Classification Society) | Skipped | Bilingual portal but auth-gated for full rules. |
| IRS (Indian Register of Shipping) | Skipped | Limited public rules, mostly Indian-flag exposure. |

ABS + LR + DNV is the operational coverage that matters for US-flag
plus EU operators using a major Western society. The remaining IACS
members (RINA, KR, CCS, IRS, PRS, BKI) are addressed implicitly via
the existing `iacs_ur` corpus (IACS Unified Requirements are the
common-denominator technical baseline every member adopts).

## Operational notes for the live corpus

1. **Citation regex** in `apps/web/src/components/ChatMessage.tsx`
   handles three forms:
   - `LR-CO-001 Ch.10 Sec.2` and `LR-RU-001 Ch.5 Sec.3` (toSection
     routes to `lr_lifting_code` vs `lr_rules` by the captured CO/RU)
   - `LR-CO-001 GenReg Sec.4` and `LR-CO-001 Notice1` (pseudo-chapter)
   - `ABS MVR Pt.4 Ch.2 Sec.1` — `\w+` Part matches digits AND the
     `5C1` / `5D` / `Notices` / `Notations` variants
2. **Karynn's 1998-edition references** (31.01-3(b), 71.15-5(b),
   91.15-5(b)) are in a deprecated numbering scheme. The 2025 edition
   uses Pt./Ch./Sec. The retrieval pipeline's vocab-mismatch handler
   (synonyms + query rewrite, shipped pre-D6.93) should bridge the
   gap on common terms, but the section-number lookup will miss.
   The synthesizer will recover via semantic retrieval on the
   underlying topic ("transformer failure reporting class society").
3. **Notices and Notations PDFs** are emitted as single bulk
   sections — they're tabular reference docs, not hierarchical rule
   text. The chunker tokenizes them into ~512-token chunks at the
   embed stage. They'll surface in retrieval but as "ABS MVR
   Pt.Notations" not as a hierarchy.

## Karynn's question — does it answer now?

Likely partial. Without LR-RU-001 (still pending Blake's pull) and
ABS Pt.7 (surveys, deferred — see above), the immediate "is this a
reportable failure" question won't have its primary source. But
the following IS in the corpus and should surface via retrieval:

- **ABS MVR Pt.4 Ch.8 Sec.4** — "Electrical Systems — Shipboard
  Installation and Tests" (104 KB body, ~30 chunks). Covers
  installation requirements + post-installation tests that should
  pick up on transformer-failure context.
- **ABS MVR Pt.6** — Survey Requirements, 37 sections / 541 chunks.
  Should cover the survey-trigger questions even though Pt.7
  (Surveys After Construction) is deferred.
- **LR-CO-001 Ch.12 Sec.3** — "Testing, Marking and Surveys —
  Survey requirements" (~74 KB body). Failure-reporting obligations
  for lifting-appliance class scope. Less relevant for the
  transformer specifically but provides anchor language for "what
  triggers a class society report" generally.
- **LR-CO-001 Ch.10 Sec.2** — "Electrotechnical Systems — Control,
  alarm and safety systems" — electrical control-system class scope
  on lifting appliances; same caveat.

**LR-RU-001 update (post-pull 2026-05-15):** LR-RU-001 is now LIVE.
The directly-relevant chapter is:

- **LR-RU-001 Pt.6 Ch.2 Electrical Engineering** (24 sections / 386 chunks):
  - Sec.2: Main source of electrical power
  - **Sec.3: Emergency source of electrical power** ← Karynn's emergency-power scenario
  - Sec.5: Supply and distribution
  - **Sec.6: System design – Protection** ← transformer protection coordination
  - Sec.7: Switchgear and controlgear assemblies
  - Sec.21: Testing and trials (post-failure re-validation)
  - + 18 more sections covering propulsion, batteries, lightning, safety systems.

LR-RU-001 also includes **Pt.1 Ch.3 Periodical Survey Regulations**
(the survey-trigger authority for the "when do I have to report
this" question) and **Pt.6 Ch.1 Control Engineering Systems**
(control/alarm/safety from a control-engineering lens).

**Action for the ship-handover question:** ask the chat directly with
phrasing like "ABS or Lloyd's classed vessel transformer failure —
when is it reportable to class?" Retrieval will surface chunks from
both ABS Pt.4 Ch.8 + Pt.6 and LR-RU-001 Pt.1 Ch.3 + Pt.6 Ch.2. The
synthesizer routes to the correct society once vessel profile is
known (or the chat asks). Citation chips like
`LR-RU-001 Pt.6 Ch.2 Sec.3` and `ABS MVR Pt.4 Ch.8 Sec.4` should
click through cleanly.

**Still pending:** LR-RU-001 Pt.7 (Other Ship Types and Systems).
Blake pulling tonight; re-run `--update` mode to fold it in.

---

*See `packages/ingest/ingest/sources/abs_mvr.py`,
`lloyds_docx.py`, `lr_lifting_code.py`, `lr_rules.py` and migration
`0099_add_class_society_sources.py` for the implementation.*
