# Corpus Status

_Last updated: 2026-05-27 (Sprint D6.97 — shore-side compliance pivot: COSWP 2025, IMO graphical symbols, per-Reg IMO codes, jurisdiction backfill)_

This document is the engineering counterpart to the user-facing
[/coverage](https://regknots.com/coverage) page. It tracks what's
ingested, what's curated to a subset, what's wired but blocked, and
what's roadmap.

The user-facing page is for trust ("we're specific about scope, not
vague about it"). This document is for engineering planning.

---

## What's live (full-text or near-full)

| Source | Code | Tier | Coverage | Last refresh |
|---|---|---|---|---|
| 33 CFR | `cfr_33` | 1 | Full | Continuous (eCFR API) |
| 46 CFR | `cfr_46` | 1 | Full | Continuous |
| 49 CFR | `cfr_49` | 1 | Full + per-row hazmat table chunking (D6.16b) | Continuous |
| 46 USC Subtitle II | `usc_46` | 1 | Full | Continuous |
| NVIC | `nvic` | 2 | Full set | Manual; weekly cadence target |
| NMC Policy | `nmc_policy` | 2 | Full | Manual |
| NMC Checklist | `nmc_checklist` | 2 | Full | Manual |
| USCG MSM | `uscg_msm` | 2 | All current chapters | Manual |
| USCG Bulletins | `uscg_bulletin` | 3 | 2023-04 to 2026-04 window | Discovery scheduled |
| SOLAS | `solas` | 1 | Full + Jan 2026 supplement | Manual |
| MARPOL | `marpol` | 1 | Full + supplements | Manual |
| COLREGs | `colregs` | 1 | Full | Static |
| STCW | `stcw` | 1 | Full + Jan 2025 supplement | Manual |
| ISM Code | `ism` | 1 | Full + supplements | Manual |
| IMDG Code | `imdg` | 1 | Vol 1 + Vol 2 (2024 Edition / Amdt 42-24) + per-row DGL chunking | Manual |
| ERG | `erg` | 4 | Full guide set (2020 edition) | Static |
| WHO IHR | `who_ihr` | 1 | Full (2005 + 2014/2022/2024 amendments) | Manual |
| ABS Marine Vessel Rules | `abs_mvr` | 1 | Pt.3, 4, 5C-1, 5C-2, 5D, 6 + Notices + Notations Table (2025 ed., 217 MB; Pt.1/2/5A/5B/7 deferred — different filename pattern). 354 sections / 5,851 chunks. | Manual |
| Lloyd's Register Code for Lifting Appliances | `lr_lifting_code` | 1 | Full LR-CO-001 July 2025 — 15 .docx, 81 sections / 448 chunks | Manual (Regs4ships) |
| Lloyd's Register Rules for Classification of Ships | `lr_rules` | 1 | LR-RU-001 July 2025 — Pt.1, 2, 3, 4, 5, 6, 8 + Notice 1 (Pt.7 pending Blake's pull). 615 sections / 2,982 chunks. | Manual (Regs4ships) |
| Bureau Veritas NR467 | `bv` | 1 | Rules for the Classification of Steel Ships — Parts A/B/C/D/E. 7,213 chunks. (D6.97) | Manual |
| IACS Common Structural Rules | `iacs_csr` | 1 | CSR for Bulk Carriers and Oil Tankers (harmonized structural design, all IACS members). 1,000 chunks. (D6.97) | Manual |
| COSWP 2025 | `coswp` | 1 | UK MCA Code of Safe Working Practices for Merchant Seafarers, 2025 Edition. 357 sections per-§ granularity across 34 chapters. Crown Copyright OGL v3. (D6.97 #54) | Manual |
| IMO LSA Code | `imo_lsa` | 1 | MSC.48(66) adoption + MSC.485(103) 2021 amendments. Per-Chapter. (D6.97) | Manual |
| IMO FSS Code | `imo_fss` | 1 | MSC.98(73) — fire safety systems. Per-Chapter. (D6.97) | Manual |
| IMO Graphical Symbols | `imo_symbols` | 1 | A.952(23) FCP symbols + A.760(18) + A.1116(30) LSA/escape signs. 5 sections / 25 chunks. (D6.97 #48) | Manual |
| Cyprus DMS | `cy_dms` | 2 | Cyprus Shipping Deputy Ministry Circulars. 1,484 chunks. (D6.97) | Manual |
| Panama MMC | `pa_mmc` | 2 | Panama Maritime Authority Merchant Marine Circulars + Notices. 1,376 chunks. (D6.97) | Manual |
| Australia Statutes | `au_statutes` | 1 | Navigation Act 2012 + Marine Safety (DCV) National Law Act 2012. 338 chunks. (D6.97 AU sprint) | Manual |
| Australia NSCV | `nscv` | 1 | National Standard for Commercial Vessels — DCV operational standard. 1,207 chunks. (D6.97 AU sprint) | Manual |
| USCG NMC Exam Bank | `nmc_exam_bank` | 4 | National Maritime Center merchant-mariner exam questions. Powers Study Tools (D6.83). 2,938 chunks. | Manual |

**~52,000 chunks pre-D6.93. Class-society corpus added 9,281 (D6.93). D6.97 corpus pivot added another ~19,400 chunks (BV 7,213 + IACS CSR 1,000 + COSWP ~700 + Cyprus 1,484 + Panama 1,376 + AU statutes 338 + NSCV 1,207 + NMC exam bank 2,938 + IMO Symbols 25 + per-Reg/Tier-2-enrichment net deltas across SOLAS + 10 IMO codes). Current total ~80k chunks across 64 registered sources.**

## Per-section granularity improvements (Sprint D6.97 #45, #47)

The B-sprint and #47 sprints re-parsed SOLAS and the 10 IMO codes to
move from per-Chapter to per-Regulation/per-Section granularity so
citation lookups for "SOLAS Ch.III Reg.6" or "IBC Ch.17" structured-
match against real section_numbers instead of falling through to
keyword search:

- **SOLAS** — 81 Parts → +379 per-Regulation Sections (Karynn's
  IMO-sticker case + many compliance-officer citation lookups)
- **imo_ibc** — 1 → 7 chapters (paragraph splitter handles the
  `N.N.N` numbered-paragraph IBC amendment doc structure)
- **imo_css** — 1 → 7 chapters
- **imo_bwm** — 9 → 50 (per-MEPC-resolution sub-chapters)
- **imo_igf** — 2 → 7
- **imo_polar** — 4 → 6
- Plus chapter-level (no change) re-ingest for imo_fss, imo_lsa, imo_igc, imo_hsc, imo_loadlines with Tier 2 alias enrichment applied (Sonnet generates 8-12 maritime-shorthand search terms per chunk, prepended as `[Search terms: ...]` block before embedding)

## Jurisdiction tagging fixes (D6.97 #51)

Five sources shipped with `jurisdictions=['intl']` instead of their
actual flag tags. Identified during Maersk-pivot retrieval audit
(Karynn's US-flag query was surfacing Cyprus DMS at rank 7). Backfill
ran 2026-05-25, re-tagging 7,343 chunks:

  cy_dms     → ['cy']  (was 'intl')
  pa_mmc     → ['pa']  (was 'intl')
  au_statutes→ ['au']  (was 'intl')
  nscv       → ['au']  (was 'intl')
  nmc_exam_bank → ['us']  (was 'intl')

Added `'cy'` alias to `_FLAG_ALIASES` (was missing entirely). Added
`COSWP` and `Code of Safe Working Practices` to the UK query-signal
pattern so non-UK users can invoke COSWP explicitly.

## Curated subset (operational essentials only)

| Source | Code | Tier | Curated set | Total available |
|---|---|---|---|---|
| UK MCA — Marine Guidance Notes | `mca_mgn` | 2 | 7 of ~335 currently in force | All MGNs |
| UK MCA — Merchant Shipping Notices | `mca_msn` | 1 | 8 of ~130 currently in force | All MSNs |
| AMSA Marine Orders | `amsa_mo` | 1 | 22 of 25 verified (3 series-ID resolution failures) | ~30 in force |
| Singapore MPA | `mpa_sc` | 1 | 11 verified circulars | Master active-list (PC 01/2026) |
| Hong Kong Marine Department | `mardep_msin` | 1 | 12 current MSINs | ~110 numbered |
| Liberia LISCR | `liscr_mn` | 2 | 13 of 17 priority Marine Notices | ~50 in force |
| Marshall Islands IRI | `iri_mn` | 2 | 14 of 24 priority Marine Notices | ~110 in force |
| Bahamas BMA | `bma_mn` | 2 | 5 of 16 verified (filename-pattern misses) | ~103 in force |
| Norway NMA | `nma_rsv` | 1 | 18 verified English circulars (RSR/RSV/SM) | More in Norwegian |
| IACS Unified Requirements | `iacs_ur` | 4 | 8 of 28 attempted (ClassNK rate-limited 20) | ~250 URs total |
| IMO HSC Code | `imo_hsc` | 1 | MSC.97(73) adoption resolution | + ~6 amendments not yet ingested |
| IMO IGC Code | `imo_igc` | 1 | MSC.370(93) consolidated 2014 revision | + 2 amendments |
| IMO IBC Code | `imo_ibc` | 1 | MEPC.318(74) major 2019 amendment | + restructuring resolution |
| IMO CSS Code | `imo_css` | 1 | A.714(17) base resolution | + Circ.1352/Rev.2 + 1623 |
| IMO Load Lines | `imo_loadlines` | 1 | Partial (MSC.375(93) + treaty HTML; note: 4 chunks only) | 1966 base + protocol amendments |

## Wired but blocked

| Source | Code | Block reason | Workaround | ETA |
|---|---|---|---|---|
| Transport Canada SSBs | `tc_ssb` | gov.ca network unreachable from DigitalOcean IP range (timeout, not 403) | Local-ingest from a different network, push to VPS DB | Next sprint |
| Maritime NZ Marine Notices | n/a | Cloudflare WAF (403 on direct fetch) | Playwright / browser-automation crawl | Next sprint |
| Transport Malta MS Notices | n/a | Same Cloudflare WAF | Same | Next sprint |
| IAMSAR Vol III | `imo_iamsar` | USCG mirror geo-blocks our DO IP range | USCG NSFCC alternate / direct from IMO/ICAO Vol III shipboard distribution | Next sprint |
| MOU PSC reports | `mou_psc` | parismou.org returned 403/404 on tested URLs | Manual download + scp into raw_dir | Next sprint |
| 20 IACS URs (ClassNK mirror) | `iacs_ur` | ClassNK rate-limits non-JP IPs to 8 successive requests | Member-society mirror rotation (ABS, DNV, LR, BV) | Next sprint |
| 11 BMA Marine Notices | `bma_mn` | Filename-pattern guesses didn't match WP upload paths | Visit listing page, extract actual filenames | Next sprint |
| LR-RU-001 Pt.7 (Other Ship Types and Systems) | `lr_rules` | Folder exists empty — Blake will pull tonight | `run_ingest.sh --source lr_rules --update --no-notify` after files land — hashes skip the seven Parts already ingested | This sprint (Blake) |
| DNV Rules | n/a yet | `rules.dnv.com` is a React SPA — returns JS shim to non-browser agents; PDFs gated behind authenticated browser sessions | Playwright headless Chromium scrape; see `docs/sprint-audits/class-society-corpus-d693.md` | Next sprint (~1 day) |
| ABS Pt.1/2/5A/5B/7 | `abs_mvr` | `1-mvr-part-N-jul25.pdf` 404'd for those parts — different prefix or date variant | Visit ABS publications page in browser, copy actual URLs, re-run `--update` | Blake to confirm filenames |

## Translation-deferred (pipeline pending)

These have public regulatory content available but require a
translation pipeline first. Schema (original_text + original_lang
columns), translation function (Claude Sonnet 4.6 with regulated
prompt), and quality validation are designed but not yet built.

| Flag | Regulator | Native lang | Effort estimate |
|---|---|---|---|
| France | DGAMPA / Division 221 | French | ~6h (first translation case — pipeline build) |
| Germany | BG Verkehr | German + EN summaries | ~3h after pipeline |
| Greece | HCG | Greek | ~5h |
| Japan | JMSA / MLIT | Japanese | ~5h |
| China | MSA | Chinese | ~6h |
| Korea | KMOF | Korean | ~5h |

## Permanently out of scope (no value/cost ratio)

- ~~Class society proprietary rules~~ — Sprint D6.93 overturned this assumption. ABS rules are free and publicly hosted on `ww2.eagle.org`; Lloyd's rules are accessible via the Regs4ships portal (commercial subscription Blake holds). DNV is wired-but-blocked; BV / ClassNK / RINA / CCS / KR / IRS remain gated behind member portals or paywalls and are still out of scope barring partner-shared credentials.
- OCIMF SIRE / SIRE 2.0 inspection questionnaires — paywalled.
- INTERTANKO contract templates — proprietary.
- Small open registries below ~30M GT (Cook Islands, Vanuatu, Belize, Antigua & Barbuda, etc.) — diminishing marginal value.
- Port-of-call PSC inspection regimes outside Tokyo / Paris MOU — too volatile.

## Quality / chunking notes

- **49 CFR 172.101** uses per-row chunking (D6.16b) — each UN row is its own chunk.
- **IMDG 3.2 DGL** uses per-row chunking (D6.16b) — 477 chunks averaging 2 UNs each.
- **Other tabular sources** (49 CFR 173.62 explosives, 49 CFR 173.225 organic peroxides) still use default paragraph chunking — flagged for future per-row work if user demand surfaces.

## Severance architecture (D6.19 — D3)

All chunks carry `jurisdictions text[]` tags. Retrieval applies a
per-query allow-set (`base ∪ flag-derived ∪ query-explicit`)
intersected with chunk tags via PostgreSQL `&&` array overlap. This
gives hard severance:

- US-flag user mathematically cannot retrieve UK / AU / SG / etc. content unless they explicitly invoke that jurisdiction in their query.
- Cross-jurisdictional queries (UK-flag user asks about CFR) are unlocked by the user, not by us.
- 9-flag severance regression: 9/9 architectural pass.

## Discovery & freshness

Currently manual `--fresh` ingest for each source. NMC and NVIC have
scheduled discovery (Celery beat), other sources do not. Automating
discovery for new sources is parked — wave 1 corpora need 1-2 manual
re-ingests first to learn failure modes.
