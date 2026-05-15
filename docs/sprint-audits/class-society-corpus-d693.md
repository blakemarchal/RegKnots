# Class-society corpus — Sprint D6.93 status + DNV follow-up

**Author:** Claude (with Blake)
**Date:** 2026-05-15
**Motivating use case:** Karynn's 2026-05-13 ship-handover question — vessel had an emergency diesel generator failure plus a defective backup transformer. She needed to know if class-society reporting was required. The vessel referenced Lloyd's Register Rules sections 31.01-3(b), 71.15-5(b), 91.15-5(b) from the 1998 edition. Maersk's vessel manager couldn't answer; RegKnots should.

## What shipped this sprint

| Source | DB tag | Citation shape | Status |
|---|---|---|---|
| ABS Marine Vessel Rules (2025) | `abs_mvr` | `ABS MVR Pt.4 Ch.2 Sec.1` | **Live** — 354 sections / 5,851 chunks (Pt.3, 4, 5C-1, 5C-2, 5D, 6 + Notices + Notations Table; 217 MB) |
| Lloyd's Register — Code for Lifting Appliances (LR-CO-001, July 2025) | `lr_lifting_code` | `LR-CO-001 Ch.10 Sec.2` | **Live** — 81 sections / 448 chunks across 15 .docx files |
| Lloyd's Register — Rules for Classification of Ships (LR-RU-001, July 2025) | `lr_rules` | `LR-RU-001 Ch.X Sec.Y` | **Wired, awaiting files** — Blake pulling from Regs4ships portal |

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

**Action for the ship-handover question:** ask the chat directly with
phrasing like "ABS-classed transformer failure — when is it
reportable?" The retrieval pipeline will surface the Pt.4 Ch.8 +
Pt.6 chunks above. If a citation chip appears as
`ABS MVR Pt.4 Ch.8 Sec.4`, click-through resolves to the
"Shipboard Installation and Tests" body and confirms the chip
plumbing works end-to-end. If neither covers her exact scenario,
flag the gap and her transcript becomes a gold-set entry; that's
what the LR-RU-001 ingest (once Blake's files land) will close.

---

*See `packages/ingest/ingest/sources/abs_mvr.py`,
`lloyds_docx.py`, `lr_lifting_code.py`, `lr_rules.py` and migration
`0099_add_class_society_sources.py` for the implementation.*
