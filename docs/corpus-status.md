# Corpus Status

_Last updated: 2026-04-28 (Sprint D6.23)_

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

**~52,000 chunks across these sources.**

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

- Class society proprietary rules (ABS, DNV, Lloyd's Register, Bureau Veritas, ClassNK, RINA, CCS) — paid; IACS URs cover the unified-requirement layer.
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
