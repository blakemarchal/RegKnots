# Corpus gap audit: inland and Coast Guard focus (2026-09-29)

Question (Blake): what data don't we have that would be great to go get, for
U.S. inland and Coast Guard users (towing, inland passenger, barge, fishing,
credentialing)?

Method, no Anthropic spend: read-only SQL on prod (`regulations`, the hedge
audits, retrieval misses, web-fallback log, unverified citations, citation
lookups), a section-by-section diff of our CFR against the eCFR API, and the
public USCG / NMC / NAVCEN / EPA sites (read in a browser; dco.uscg.mil
returns 403 to plain fetches).

## Summary

- **The CFR, 46 USC and the Marine Safety Manual are complete.** 46 CFR: 8,319
  of 8,321 live sections; 33 CFR: 4,596 of 4,598 (details in §1).
- **The gaps are in the USCG guidance layer, and the two biggest are bugs in
  sources we already collect:**
  1. NVIC discovery silently skips **36 current NVICs**: every one whose PDF
     link ends in `?ver=…`. That is almost the whole modern credentialing
     series and **NVIC 03-16, towing-officer credentialing (the TOARs)**.
  2. We serve **NVIC 04-08, the medical guidelines cancelled in 2019** by the
     Merchant Mariner Medical Manual, which we don't have.
- **Best additions for inland users, all free USCG / EPA publications:**
  - NMC credential checklists: 111 of 115 missing.
  - CG-CVC policy letters, work instructions and inspection forms: about 80
    documents.
  - The Towing Vessel National Center of Expertise's Subchapter M FAQs and
    guides.
  - 196 USCG Safety Alerts (we have 1).
  - VTS user manuals and the Mississippi River waterway action plans.
  - EPA's vessel discharge rules (VGP and VIDA).
- **`uscg_bulletin` is about 90% expired operational traffic.** It has been
  stale since February, and retrieval never reads a publication or expiry date.
- **Cost of everything in Tier 1:** about 7–9k chunks of OpenAI embeddings,
  well under $1. No Claude calls needed.

## 1. What we have (U.S.-tagged sources)

| Source | Chunks | Docs / sections | Notes |
|---|---|---|---|
| `cfr_46` | 10,490 | 8,319 | complete vs eCFR 2026-09-25 |
| `cfr_33` | 7,214 | 4,596 | complete vs eCFR 2026-09-28 |
| `nvic` | 6,103 | 209 circulars | 36 current ones missing (§3.1) |
| `uscg_bulletin` | 3,392 | 2,629 | newest 2026-02-03; ~90% ephemeral (§3.3) |
| `cfr_49` | 3,145 | 1,203 | maritime parts only (by design) |
| `uscg_msm` | 3,048 | 72 chapters | Vol II A–G (16000.70–.76), Vol III (16000.8B), Vol V (16000.10A) |
| `nmc_exam_bank` | 2,938 | 244 | |
| `usc_46` | 1,283 | 1,004 | 8104, 8904, 55102, 55113, 10313, 70001 all present |
| `erg` | 762 | 227 | |
| `nmc_policy` | 209 | 54 | incl. 8 policy letters |
| `nmc_checklist` | 33 | 6 | 4 of NMC's 115 checklists |

The CFR diff found four missing sections, none substantive:
- 46 CFR 69.75 and 69.123: figures only.
- 33 CFR 83.28: reserved.
- 33 CFR 165.849: a Sector Mobile hurricane safety zone published this week; Sunday's refresh will pick it up.

## 2. What users asked that we couldn't answer

- **120 open hedge audits are classified `CORPUS_GAP`** (all users, all time).
  The inland / USCG themes:
  - TOAR sign-offs and the towing officer path (deckhand → steersman → master).
  - Getting hired at a towing company with no credential.
  - Sub M TSMS.
  - SCBA and fixed CO2 applicability by subchapter.
  - Marine casualty statements (46 CFR 4, CG-2692).
  - Fire extinguisher recalls.
  - The AFFF (PFAS foam) phase-out.
  - Lower Mississippi high water and bridge clearance.
  - OCMI contacts.
  - Shipping articles and discharge of seamen.
  - The eNOA arrival-time definition.
- **The web fallback's most-used outside domain is dco.uscg.mil** (13 answers
  surfaced, 24 appearances among candidate URLs). What it fetched:
  - NMC checklist MCP-FM-NMC5-56 (entry-level ratings).
  - The Western Rivers TOAR.
  - NMC's medical-certificate FAQ.
  - CG-INV casualty pages.
  - The CSNCOE fixed-CO2 exam guidance.
  - Separately, ecfr.gov was used 15 times, but for sections we hold. That is a ranking problem, not a data gap.
- **Unverified citations (88 distinct) are mostly section numbers the model
  remembers wrongly, not missing data:**
  - 46 CFR 10.215 (6 times): the medical standards now sit in 10.301–10.306.
  - 33 CFR 83.1 / 83.5 / 87.1: Inland Rules sections use two digits (83.01, 87.01).
  - Subpart-level cites: 46 CFR 92.07, 161.002.
  - The real gaps among them: 50 CFR 224.105 (right whale speed rule), 47 CFR 80.933 (FCC), 29 CFR 1910.x (OSHA).

## 3. Fix first: data we already collect

### 3.1 NVIC discovery drops 36 current circulars

`ingest/sources/nvic.py` `_find_pdf_link_in_tag` requires
`href.lower().endswith(".pdf")`. USCG now serves most 2014+ NVICs as
`….pdf?ver=…`, and the credentialing ones sit in an MMC folder with unencoded
spaces in the path. In the 2010s, 28 of 43 active NVICs are skipped; in the
2020s, 8 of 12. The main index page's unversioned link rescued only 01-25.

Missing:

| Area | NVICs |
|---|---|
| Credentialing | 03-16 (towing officers, with the TOARs as enclosures 2–5); 01-17, 02-17, 03-17, 04-17; 02-18, 03-18; the STCW endorsement series 05-14 to 18-14 and 21-14 to 24-14 (19-14 is qualified assessors); 01-24 (lifeboatman); 01-26 (Coast Guard-approved training) |
| Other | 01-20 (MTSA facility cyber); 01-22 (novel LSA); 03-19 (lifeboat maintenance, examination and testing); 01-23 (MARPOL electronic record books); 02-23 and 03-23 (offshore renewable energy); 05-17 (casualties where the U.S. is a substantially interested state); 09-00 CH-1 (CO2 system safety; also failing to download, `data/failed/nvic_09-00.json`) |

Fix: accept `.pdf` followed by a query string, and quote spaces. Then re-ingest
through `scripts/run_ingest.sh` (`--source nvic --update`).

Also to check:
- 03-75 and 10-02 are in the discovery cache but not in the database.
- 07-68 and 09-94 are in the database but no longer in USCG's active index. If they are cancelled, prune them.

### 3.2 We serve cancelled medical guidance

- NVIC 04-08 Ch-2 (120 chunks) was added by hand in `_EXTRA_DOCS` because
  "the index never listed it." It isn't listed because COMDTINST M16721.48, the
  Merchant Mariner Medical Manual, cancelled it on 2019-09-09 (along with NVIC
  01-14, which USCG's 2010s page marks as cancelled). We don't hold the Medical
  Manual; eight `nmc_policy` chunks only mention it.
- Medical is one of the most common user topics: CG-719K validity, waivers,
  diabetes, vision and hearing.
- Fix:
  - Remove 04-08 from `_EXTRA_DOCS`.
  - Prune its rows (`ingest/prune.py` keeps a backup).
  - Ingest the Medical Manual.
- More generally, no NVIC row carries `superseded_by` or `expires_date`.
  Discovery drops cancelled circulars, but anything added by hand bypasses that
  check.

### 3.3 `uscg_bulletin` is mostly expired operational traffic

2,629 documents (3,392 chunks). The newest is dated 2026-02-03, so discovery
has stopped. By title pattern:

| Kind | Documents | Older than 1 year |
|---|---|---|
| Daily or weekly outlooks, LNM notices | ~1,440 | ~1,440 |
| Broadcast notices and their updates | ~910 | ~900 |
| Closures, restrictions, river stages, storm and port conditions | ~55 | ~55 |
| Durable policy, safety and guidance | ~220 | ~220 |

- The problem:
  - All of it is tagged `us`, so it competes in every U.S. query.
  - Retrieval never reads `published_date` or `expires_date`.
  - So a question about current Lower Mississippi restrictions can retrieve a 2023 "5 Day Outlook".
- Recommended:
  - Prune the ephemeral kinds and keep the durable ones.
  - Filter the ephemeral kinds out at ingest, then resume discovery.
  - Add a recency rule so time-sensitive questions point to the live source (NAVCEN Local Notices to Mariners, sector MSIBs) rather than to an old copy.

### 3.4 Citation normalization (retrieval and verifier, no new data)

- Pad Inland Rules sections: 33 CFR parts 80–90 use two-digit section numbers, so "83.1" should mean 83.01.
- Map known redesignations, e.g. 46 CFR 10.215 → 10.301–10.306.
- Treat subpart citations (46 CFR 92.07) as subparts.
- This removes most of the unverified-citation noise and helps retrieval hit the right section.

### 3.5 Cosmetic: `regulations.title`

Every non-CFR row has the title "COLREGs — International/Inland Navigation
Rules", from `models.TITLE_NAMES[0]`. Nothing in retrieval or chat reads the
column. Fix the mapping and run one UPDATE when convenient.

## 4. Go get, ranked for inland / USCG users

All of Tier 1 and Tier 2 is U.S. government work (public domain), except ABS,
which is free and already in use.

### Tier 1

| # | Source | What it answers | Size | Evidence |
|---|---|---|---|---|
| 1 | **NMC credential checklists** (111 missing of 115) + **4 TOAR forms** + NMC FAQs | Requirements for every endorsement: sea time, exams, training. For towing: Mate (Pilot), Apprentice Mate (Steersman), Limited Apprentice Mate, Limited GL-I/WR, grandfathering. Also Master and Mate on Great Lakes and Inland at every tonnage, OUPV, tank vessel and barge PIC, entry-level ratings, QMED, DDE | ~111 short PDFs, same format as the 4 we hold (`nmc` adapter) | Web fallback pulled NMC5-56 and the Western Rivers TOAR; 6+ gap audits on credential paths |
| 2 | **CG-CVC policy letters, work instructions and forms** | ~48 letters not marked canceled on the 2010s and 2020s pages, 27 work instructions and 7 forms (older decades not yet counted). Towing: special consideration for Sub M vessels (WI-010), initial COI under the TSMS option (WI-013), Sub M TPO guidance (WI-038, May 2026), ATB manning under the FY2023 NDAA (WI-037), doublers (PL 21-03), UTV equipment beyond Sub C (PL 10-06), towing forms. Passenger vessels: long-form K-boat and T-boat checklists, machinery alarms, lithium-ion batteries. Also: laid-up vessels, drydock / UWILD, multiple subchapters (WI-032), VHF-DSC (PL 15-06) | ~80 PDFs, new `uscg_cvc` source | Sub M, SCBA and CO2 applicability audits |
| 3 | **TVNCOE Subchapter M package** | USCG's own FAQ answers for Parts 1/2/15 and 136–144, preamble FAQs, the UTV Guidebook, the applicability flowchart, the TugSafe decision aid, the ITV inspector job aid, the TPO list; plus the Sub M final rule preamble (81 FR 40004, 2016) | ~20 documents, new `uscg_towing` source | Sub M TSMS audits; M/V Bay Pioneer demo questions |
| 4 | **USCG Safety Alerts** (196; we have 1) + CG-INV Safety Advisories + Findings of Concern | Equipment failures and recalls: extinguishers, flares, heat detectors, lifejackets, SCBA. SA 15-26 (2026-09-23) covers retractable pilot houses on towing vessels | ~200 short PDFs; monthly refresh | Recall, SCBA and CO2 audits |
| 5 | **Merchant Mariner Medical Manual** (COMDTINST M16721.48) | Medical certificate standards, waivers, conditions | ~1 large PDF | §3.2; frequent medical questions |
| 6 | **Waterway guidance** | NAVCEN VTS user manuals (Lower Mississippi River 2026, Houston-Galveston 2025, ~10 more areas); District 8 Waterways Action Plans for the Mississippi River and tributaries (high-water horsepower and tow-size rules, closures) | ~15 PDFs | Lower Mississippi high-water and bridge questions |
| 7 | **EPA vessel discharge** | The 2013 VGP, which binds vessels 79 ft and over (most line-haul towboats among them) until USCG's VIDA rules take effect (due by October 2026). 40 CFR 139 VIDA standards (30 sections), 110 oil discharge / sheen (6), 140 MSD standards and no-discharge zones (5), 1042 / 1043 marine engines (99) | Extend `cfr_scope` to Title 40; VGP as a PDF | None yet; high compliance weight for towboats |

### Tier 2, as demand shows

- **47 CFR 80** (FCC maritime radio: VHF, DSC, EPIRB; 337 sections).
- **33 USC**, selected chapters:
  - OPA 90 (chapter 40) and CWA §311 (33 USC 1321);
  - APPS (1901–1915) and the Bridge-to-Bridge Radiotelephone Act (1201–1208);
  - Rivers and Harbors Act wreck marking and removal (33 USC 409);
  - the `usc_46` adapter extends to these.
- **50 CFR 224** (5 sections; the right whale speed rule our Whale Zones page cites).
- **29 CFR 1915 / 1917 / 1918 / 1919** (OSHA shipyard, marine terminal, longshoring and gear certification; 313 sections), for terminals and shore-side users.
- **USCG forms most asked about:** CG-2692 series with instructions, CG-705A (shipping articles), eNOA / NVMC instructions.
- **ABS Rules for Steel Vessels in River and Intracoastal Service**: free from eagle.org; availability to confirm.
- **NTSB marine investigations** for towing and inland casualties (lessons learned).
- **Other USCG policy offices:** CG-ENG and CG-OES policy letters (beyond credentialing), Marine Safety Center technical notes.

### Tier 3: live data (features, not corpus)

- A USACE river gage and lock status injector, like the whale-zone one. It would answer "what's the Carrollton gage?" and "is Lock 27 open?".
- USCG PSIX vessel lookup to prefill vessel profiles (flag, type, tonnage, subchapter). This fixes the flag-Unknown problem at the source (roadmap item 6).

### Not recommended

- AWO Responsible Carrier Program: members only.
- TPO / TVIB audit standards: proprietary.
- Harbor safety committee guides: not government works; ask before using.
- NOAA Coast Pilot and Light Lists: navigation data, and the regulation chapters duplicate 33 CFR.

## 5. Access and cost

- dco.uscg.mil sits behind Akamai.
  - The NVIC adapter's browser headers work from the VPS for most PDFs.
  - `ingest/headless.py` (Playwright) covers pages that need a browser.
  - A few PDFs have needed a laptop download plus scp (NVIC 04-08, April).
  - navcen.uscg.gov and epa.gov have not been tested from the VPS.
- Embeddings (text-embedding-3-small, $0.02 per million tokens): Tier 1 is
  roughly 7–9k chunks, about 4M tokens, under $0.10.
- Alias enrichment is optional and not needed for these sources.
- Each source ends with the dense harness run (OpenAI only), per the standing
  rule, and a `docs/corpus-status.md` update.

## 6. Proposed order

| Step | Work | Estimate |
|---|---|---|
| 1 | NVIC link fix and re-ingest; drop 04-08; add the Medical Manual | half day |
| 2 | Prune expired `uscg_bulletin` items, filter them at ingest, resume discovery | half day |
| 3 | NMC checklists and TOARs (extend the `nmc` adapter) | half day |
| 4 | `uscg_cvc` (policy letters, work instructions, forms) and `uscg_towing` (TVNCOE) | 1 day |
| 5 | Safety alerts: a small adapter plus a monthly Celery refresh | half day |
| 6 | Title 40 scope and the VGP; VTS manuals and waterway action plans | 1 day |
| 7 | Tier 2, as demand shows | — |

## 7. Shipped 2026-09-30

Blake: "Greenlight all". Commits `7a4b2b4` (ingest), `11de59c` (rag), `6f39772` (api, migration
**0119**), `5a1f239` (web), then `324fe65`, `fb4f048`, `9dd235e`, `a6db992`, `ff2998f`, `a3eeb73`,
`ae2cda2`, `5251e67`, `a81a610`, `178797c`. All deployed (last `178797c`);
the prod ingests ran through `scripts/run_ingest.sh` with `--no-notify`. No Anthropic spend: every
new source is parsed locally and embedded with OpenAI (well under $1 in all).

### Fixes to data we already had

- **NVIC discovery (§3.1).** `_find_pdf_link_in_tag` accepts `.pdf?ver=…` and encodes spaces.
  Discovery now lists 248 active NVICs. The update run embedded 3,663 new or changed chunks
  (+3,623 rows), so 03-16 (towing officers, TOARs), the STCW endorsement series, 01-20, 01-23, 01-24,
  01-26 and the rest of the §3.1 list are in.
  - 07-68 is active; the old link check had hidden it. 09-94 is marked Cancelled/Superseded on the
    1990s page and is retired (`nvic.RETIRED`).
  - 09-00 CH-1 (CO2 system safety): USCG's page links it twice; the URL column's link 404s. The
    adapter now takes the file under `/Portals/` from the number cell. It downloads now, but it
    is a scan too.
  - **Four NVICs are image-only:** 02-23 (offshore renewable energy, 70 pages), 10-02 CH-1
    (vessel security guidelines, 9 pages), 03-75 (bulk grain, 22 pages) and 09-00 CH-1 (18 pages).
    That is why 03-75 and 10-02 were in the discovery cache but not the database. They were read
    with tesseract (OCR, below) and ingested: 59 sections, 200 chunks.
  - Pruned: 172 rows (04-08 Ch-2 120, 09-94 16, and 36 leftover 07-68 §4 chunks from an April
    parse that the old link check had hidden). Backup `data/pruned/nvic-20260930-082907.csv.gz`.
    NVIC now: all 248 active circulars, 3,174 sections, 9,754 chunks.
- **Medical guidance (§3.2).** NVIC 04-08 Ch-2 is retired and pruned. The **Merchant Mariner
  Medical Manual** (COMDTINST M16721.48, 297 pages) is in `uscg_msm`: 25 chapters, 284 chunks,
  cited as "COMDTINST M16721.48 Ch.12".
- **`uscg_bulletin` (§3.3).**
  - Pruned by title, not by re-fetching (`--stale-report` / `--prune-stale` use
    `uscg_bulletin.stale_report`): 3,332 of 3,392 rows (2,602 documents) removed, backup
    `data/pruned/uscg_bulletin-20260930-082912.csv.gz`. Kinds removed: LNM notices and outlooks
    (1,569 rows), broadcast notices and their updates and cancellations (1,377), GPS / NANU / ice
    (160), closures, river stages, bridge deviations and VTS measures (100), CG-internal ALCOASTs and
    ACNs (85), port conditions (18), COVID measures (8), marine events (6), and 9 second copies of a
    bulletin stored under different LLM labels. Kept: 27 documents, e.g. the eVDSD and four-digit
    VHF channel ALCOASTs, the Kidde extinguisher recall ACN, MSIB XVIII-069 (ITV flammable storage
    cabinets), MSIB XXIII-012 (marine casualty notification), NMC credential announcements.
  - The same filter runs at ingest, before Pass 1 (a Sector VTS "MSIB … High Water" matches Pass 1).
    Regulatory keywords (STCW, merchant mariner, NVIC, policy letter, safety alert, final rule,
    Subchapter M …) accept without the LLM.
  - **Discovery resumed from GovDelivery's public feed**
    (`public.govdelivery.com/accounts/USDHSCG/feed.rss`, the latest 100 bulletins, about 30 hours).
    Daily Celery task `update_uscg_bulletins` (11:15 UTC) runs `--update`, which fetches only feed
    items no run has decided. On the 2026-09-30 feed, 98 of 100 items were dropped by subject, 1
    accepted (STCW basic training amendments) and 1 went to review. Ambiguous items go to
    `feed_review.tsv`; the LLM classifies them only with `USCG_BULLETIN_LLM=1`. (The weekly refresh
    that ran until 2026-08 re-fetched all 7,456 ids and sent about 6,000 subjects a week to Haiku.)
    The first run (08:29 UTC) found all 100 items new, as expected on a first run, and accepted one:
    the STCW basic training amendments. `uscg_bulletin` is now 28 documents / 62 chunks.
  - Accepted ids go to `feed_accepted.txt`, not `wayback_ids.txt`: the latter is tracked in git and
    `deploy.sh` resets the checkout.
- **Citation normalization (§3.4)**, `rag/citation_norm.py`, used by retrieval and the verifier:
  33 CFR Parts 83–88 two-digit sections ("83.5" also tries 83.05) and 46 CFR 10.215 → 10.302.
  Subpart citations (46 CFR 92.07) are not handled yet.
- **`regulations.title` (§3.5).** New and re-ingested rows get the source's own title
  (`models.title_name`). Existing rows keep "COLREGs — …" until re-ingested: nothing reads the
  column, and a one-off UPDATE would rewrite ~80k rows and their HNSW entries.
- Found on the way: the citation verifier looked for MSC resolutions in sources named `fss` and
  `lsa`, which do not exist, so every FSS / LSA Code citation was flagged unverified. It now checks
  `imo_fss`, `imo_lsa`, `imo_msc`, `imo_igf`, `imo_polar` and `imo_loadlines`.

### New sources

All U.S. government works. Listing-page sources re-read their page on every run (a document is
re-downloaded when its link's `?ver=` or revision changes) and embed only changed chunks.

| Source | What | Sections | Chunks |
|---|---|---|---|
| `uscg_cvc` | CG-CVC policy letters not marked cancelled (and the older CG-543 / CG-MOC / CG-PCV series), MMS work instructions (e.g. CVC-WI-013, initial ITV COI under TSMS; WI-038, Sub M TPOs), inspection forms (K- and T-boat checklists) | 99 | 1,378 |
| `uscg_towing` | TVNCOE: Sub M FAQs by part (1/2/15, 136–144, general, preamble), UTV Guidebook, applicability flowchart, ITV inspector job aid, small entity compliance guide | 16 | 283 |
| `uscg_safety_alert` | 181 CG-INV Safety Alerts since 1996 and 111 Findings of Concern (the "advisories" share the alerts page) | 292 | 646 |
| `uscg_waterways` | 12 NAVCEN VTS user manuals and 5 District 8 Waterways Action Plans (Lower / Upper Mississippi, Ohio, Illinois, Missouri) | 17 | 881 |
| `epa_vgp` | EPA 2013 VGP, one section per part / appendix (Part 6 at state level) | 135 | 352 |
| `usc_33` | 33 USC 401–467, 1201–1208, 1321–1322, 1901–1915, 2701–2762 (release point 2026-04-17) | 149 | 285 |
| `cfr_40` | 40 CFR 110, 139, 140, 1042, 1043 | 140 | 288 |
| `cfr_47` | 47 CFR 80 | 337 | 492 |
| `cfr_50` | 50 CFR 224 | 5 | 31 |
| `cfr_29` | 29 CFR 1915, 1917, 1918, 1919 | 312 | 710 |
| | **new sources, total** | **1,502** | **5,346** |

`nmc_checklist` went from 6 documents / 33 chunks to 122 / 476: the 112 checklists on NMC's checklist page
plus the four TOARs (NVIC 03-16 enclosures 2–5).

Two first runs failed and were re-run after a fix: eCFR returned a 502 on 29 CFR 1918
(`fetch_full_xml` now retries 5xx twice), and epa.gov answered in brotli, which httpx cannot
decode without the brotli package (`uscg_docs.get` asks again without `br`). CG-MOC PL 99-03's
file on dco.uscg.mil is a 28-byte stub; it is skipped. The first safety-alert run kept 174 alerts
and 45 findings: CG-INV lettered some alert numbers (10-10 (a) / (b)) and reused others (09-08 in
1998, 2008 and 2009), and the Findings table is paged. Both fixed (`178797c`); 6 renamed rows
pruned.

**Twelve CG-CVC letters are scans with no text layer**, read with tesseract (below): PL 18-02, 18-03
(UPV safety program), 16-01, 16-02 (non-metallic sea strainers on small passenger vessels), 16-03
(5-knot test after replacing on-load release gear), 15-06 CH-2 (VHF-DSC installation on inspected
passenger and fishing vessels, which §4 named), 15-02, 15-01, 14-03 (sea service on liftboats),
13-04 CH-1, 11-11 CH-1 and CG-PCV PL 06-08. They added 110 chunks; `uscg_docs.doc_sections` reads
`data/ocr/uscg_cvc/<file stem>.txt` for a PDF with no text layer.

### OCR (tesseract, Blake's pick: free)

- tesseract 5.3.4 installed on the VPS from Ubuntu's repositories (`apt-get install tesseract-ocr`).
- `python -m ingest.ocr --source nvic | uscg_cvc | …` (or `scripts/run_ingest.sh --ocr --source …`,
  the same capped unit as an ingest) finds PDFs with no text layer and no sidecar, renders pages at
  300 dpi (pdftoppm), reads them on one core and writes `data/ocr/nvic/<number>.txt` or
  `data/ocr/<source>/<file stem>.txt`.
- The 4 NVICs and 12 letters: 196 pages in about 17 minutes. 88–97% of tokens read as words; the
  slips are small ("Smal!" for "Small", a stray bracket), which retrieval tolerates.
- The monthly `update_uscg_guidance` ends with an OCR pass over nvic and the uscg_docs sources; the
  next scheduled run ingests anything it wrote.

### Retrieval, answers and chips

- Groups take the new sources without growing the fan-out: `cfr` + cfr_40/47/50/29 and epa_vgp;
  `usc` + usc_33; `nvic` + uscg_cvc and uscg_towing (so the Subchapter M boost reaches them);
  `uscg_bulletin` + uscg_safety_alert and uscg_waterways.
- Authority tiers: the scoped CFR titles, 33 USC and the VGP are Tier 1; CG-CVC, TVNCOE and the
  waterway guidance Tier 2; safety alerts Tier 3. All ten sources are tagged `us`.
- The prompt's knowledge-base list names every new source and its citation form. 29 CFR 1915–1919
  may be cited (1910 still may not). Bulletins no longer promise closures or river stages, and
  point to the VTS, the LNM and current MSIBs for today's status. The synthesis-model comparison
  was not re-run for this prompt change (about $3–4).
- Chips: CG-CVC / CG-543 / CG-MOC / CG-PCV policy letters and CVC work instructions and forms,
  USCG SA / FOC numbers, MCP-FM-NMC5 checklists, the TOARs, Sub M FAQ parts, COMDTINST M16721.48
  chapters, VGP parts. A chip whose guessed source lacks the section tries sibling sources before
  the fallbacks (CG-CVC PL 15-03 is stored with the NMC letters).
- "low water" matched "below waterline", which would have lifted the bulletin group on hull
  questions; vts / high water / low water now match as whole words.

### Schedules

- Weekly `update_regulations` (Sundays 02:00 UTC) adds cfr_40, cfr_47, cfr_50, cfr_29.
- Daily `update_uscg_bulletins`, 11:15 UTC, `--no-notify`.
- Monthly `update_uscg_guidance`, the 5th at 18:30 UTC: safety alerts and findings, CG-CVC,
  TVNCOE, VTS / waterways, NMC checklists. It stays outside Sunday's run: the worker runs two
  tasks at once, and two ingests at once would not fit the box's free memory.
- A listing that comes back under half its saved size keeps the saved index (a layout change, not
  withdrawals). Documents withdrawn from a listing stay stored until a prune.

### Dense harness (79 pairs)

| run | strong recall@8 | weak recall@8 | MRR |
|---|---|---|---|
| before (new code, old data) | 0.8608 | 0.9114 | 0.7189 |
| after the data, old gold set | 0.8101 | 0.8734 | 0.6314 |
| after the data, updated gold set | 0.8608 | 0.9114 | 0.6820 |
| + keyword floor (deployed, final data) | **0.9367** | **0.9494** | **0.7593** |
| + the OCR'd NVICs and letters | 0.9367 | 0.9494 | 0.7593 |

- **The gold set rewarded what the plan removed.** C3 (type 2 diabetes) expected NVIC 04-08, cancelled
  in 2019; the top results are now NMC's Top 10 Medical Conditions and COMDTINST M16721.48 Ch.14,
  Endocrine Conditions. F7 (recent safety alert on fire extinguishers) expected two ALCOAST/ACN
  bulletins; the top five are now the CG-INV extinguisher alerts. P1 expected expired LMR river-stage
  bulletins; the top result is the D8 Waterways Action Plan. Their patterns were added (`a81a610`),
  keeping the old ones; no earlier run could have matched the new patterns.
- **The rest was the broad keyword search.** Any query word matching no more than 200 chunks put up to
  five rows at first place (best similarity + 0.02), whatever they were, and ties followed physical
  row order, which every large ingest or prune reshuffles. "wanted" in N-C1 ("If I wanted to start a
  career…") surfaced MSM "Placing Merchant Mariners on the Wanted List" and BWM "unwanted
  organisms"; "Norfolk" in P3 put a Chantix safety alert above the Elizabeth River drawbridge rules.
  Keyword hits now take first place only within 0.10 of the best vector hit (`5251e67`,
  `retriever._KW_BOOST_MAX_GAP`): +6 pairs, none lost, 16 ranked higher, N-E3/V1 from rank 1 to 2.
- `dense-prod` (rewrite + reranker, ~$0.15) was not run.

### Not done

- Subpart citations (§3.4); the one-off `regulations.title` UPDATE (§3.5).
- Tier 2 items not taken: USCG forms (CG-2692 and others), ABS river and intracoastal rules, NTSB
  marine investigations, CG-ENG / CG-OES letters. Tier 3 (live gage / lock status, PSIX) remains.
- The prompt change has not been through `compare_synthesis_models` (Claude spend).
