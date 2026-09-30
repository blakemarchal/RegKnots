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
