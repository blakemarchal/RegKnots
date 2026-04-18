# Federal Register Discovery — Gap Report

**Generated:** 2026-04-18T15:40:30+00:00

**Method.** Queried the Federal Register API (`https://www.federalregister.gov/api/v1/documents.json`) for USCG-agency documents containing each category's diagnostic terms (NVIC / Navigation and Vessel Inspection Circular; NMC, CG-MMC, CG-CVC, CG-OES, policy letter, Merchant Mariner Credential; MSIB / Marine Safety Information Bulletin). Title-pattern regex in `packages/ingest/ingest/sources/federal_register_discovery.py` extracts the canonical doc number from each FR title where parsable. Cross-referenced against the production `regulations` table. NVIC corpus rows normalized by stripping `§N` / `Ch-N` (NVIC adapter regex over-splits).

---

## 0. Headline finding — FR is the wrong channel for these categories

The Federal Register API does **not** carry NVIC, NMC policy letter, or MSIB publications as titled documents — it carries USCG rulemaking notices that *mention* these instruments in their abstracts. The full-text term search returns the rulemakings, not the source documents themselves. Specifically:

| Category | FR full-text matches | Term in title | Parseable doc # | Effective signal-to-noise |
|---|---|---|---|---|
| NVIC | 416 | 19 (5%) | 17 (14 unique) | 3.4% |
| NMC | 805 | 49 (6%) | 2 (2 unique) | 0.2% |
| MSIB | 660 | 0 (0%) | 0 (0 unique) | 0.0% |

**Translation:**

- NVIC: of 416 FR results, only 14 distinct NVICs are titled in FR. The vast majority are FR rulemakings that mention NVICs in passing.
- NMC: of 805 FR results, only 2 distinct CG-MMC/CG-CVC/CG-OES policy letters are titled. NMC publishes interpretive guidance, not rulemaking — so it doesn't go through FR.
- MSIB: of 660 FR results, **zero** have an MSIB number in the title. MSIBs are field advisories distributed via GovDelivery — they never appear in FR as published bulletins.

**Architectural implication.** The original sprint hypothesis was that FR could serve as the canonical discovery channel with GovDelivery as a fallback for MSIBs only. The data flips this: **GovDelivery (or another non-FR channel) is the primary requirement for all three categories.** FR remains useful for occasional NVIC notices-of-availability and for rulemaking that surrounds these documents, but it cannot enumerate them.

---

## 4.1 NVIC coverage

- **FR documents matching category terms (full-text):** 416
- **Of those, contain category term in TITLE:** 19 (5%)
- **Of those, parseable to a canonical doc number in title:** 17 (14 unique numbers)
- **Noise ratio (term-only-in-abstract or unparsed):** 96%
- **Unique documents in RegKnot corpus (this source):** 160
- **Matched (FR ∩ corpus, by canonical doc number):** 5
- **Missing (FR-discoverable \ corpus):** 7 unique doc numbers

**Matched docs (FR knows AND corpus has):**

  - NVIC 01-16
  - NVIC 02-16
  - NVIC 02-99
  - NVIC 04-08
  - NVIC 11-93

**Host distribution of missing-doc PDFs:**

| Host | Count | Direct-fetchable from VPS? |
|---|---|---|
| www.govinfo.gov | 8 | ✓ yes |

**Missing documents by decade (7 unique):**

### 2010s (6 unique)

  - **NVIC 2-10** — Notice of Public Availability of Navigation and Vessel Inspection Circular (NVIC) 2-10, “Guidance for Implementation and… · 2010-10-06 · [FR 2010-25071](https://www.federalregister.gov/documents/2010/10/06/2010-25071/notice-of-public-availability-of-navigation-and-vessel-inspection-circular-nvic-2-10-guidance-for) · [PDF](https://www.govinfo.gov/content/pkg/FR-2010-10-06/pdf/2010-25071.pdf)
  - **NVIC 05-17** — Navigation and Vessel Inspection Circular (NVIC) 05-17; Guidelines for Addressing Cyber Risks at Maritime Transportation… · 2017-07-12 · [FR 2017-14616](https://www.federalregister.gov/documents/2017/07/12/2017-14616/navigation-and-vessel-inspection-circular-nvic-05-17-guidelines-for-addressing-cyber-risks-at) · [PDF](https://www.govinfo.gov/content/pkg/FR-2017-07-12/pdf/2017-14616.pdf)
  - **NVIC 02-18** — Guidance: Change 2 to NVIC 02-18 Guidelines on Qualification for STCW Endorsements as Officer in Charge of a Navigationa… · 2021-09-02 · [FR 2021-18956](https://www.federalregister.gov/documents/2021/09/02/2021-18956/guidance-change-2-to-nvic-02-18-guidelines-on-qualification-for-stcw-endorsements-as-officer-in) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-09-02/pdf/2021-18956.pdf)
  - **NVIC 24-14** — Guidance: Change 3 to NVIC 24-14 Guidelines on Qualification for STCW Endorsements as Electro-Technical Rating on Vessel… · 2021-09-09 · [FR 2021-19411](https://www.federalregister.gov/documents/2021/09/09/2021-19411/guidance-change-3-to-nvic-24-14-guidelines-on-qualification-for-stcw-endorsements-as) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-09-09/pdf/2021-19411.pdf)
  - **NVIC 19-14** — Guidance: Change 3 to NVIC 19-14 Policy on Qualified Assessors · 2021-12-06 · [FR 2021-26390](https://www.federalregister.gov/documents/2021/12/06/2021-26390/guidance-change-3-to-nvic-19-14-policy-on-qualified-assessors) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-12-06/pdf/2021-26390.pdf)
  - **NVIC 21-14** — Guidance: Change 1 to NVIC 21-14 Guidelines for Qualification for STCW Endorsement for Vessel Security Officers · 2021-12-13 · [FR 2021-26878](https://www.federalregister.gov/documents/2021/12/13/2021-26878/guidance-change-1-to-nvic-21-14-guidelines-for-qualification-for-stcw-endorsement-for-vessel) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-12-13/pdf/2021-26878.pdf)

### 2020s (1 unique)

  - **NVIC 01-20** — Navigation and Vessel Inspection Circular (NVIC) 01-20; Guidelines for Addressing Cyber Risks at Maritime Transportation… · 2020-03-20 · [FR 2020-05823](https://www.federalregister.gov/documents/2020/03/20/2020-05823/navigation-and-vessel-inspection-circular-nvic-01-20-guidelines-for-addressing-cyber-risks-at) · [PDF](https://www.govinfo.gov/content/pkg/FR-2020-03-20/pdf/2020-05823.pdf)

---

## 4.2 NMC policy letter coverage

- **FR documents matching category terms (full-text):** 805
- **Of those, contain category term in TITLE:** 49 (6%)
- **Of those, parseable to a canonical doc number in title:** 2 (2 unique numbers)
- **Noise ratio (term-only-in-abstract or unparsed):** 100%
- **Unique documents in RegKnot corpus (this source):** 19
- **Matched (FR ∩ corpus, by canonical doc number):** 0
- **Missing (FR-discoverable \ corpus):** 2 unique doc numbers

**Host distribution of missing-doc PDFs:**

| Host | Count | Direct-fetchable from VPS? |
|---|---|---|
| www.govinfo.gov | 2 | ✓ yes |

**Missing documents by decade (2 unique):**

### 2010s (1 unique)

  - **CG-MMC PL 02-18** — Policy Letter: Change 1 to CG-MMC Policy Letter 02-18, Guidelines for Qualifications of Personnel for Issuing STCW Endor… · 2021-10-05 · [FR 2021-21633](https://www.federalregister.gov/documents/2021/10/05/2021-21633/policy-letter-change-1-to-cg-mmc-policy-letter-02-18-guidelines-for-qualifications-of-personnel-for) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-10-05/pdf/2021-21633.pdf)

### 2020s (1 unique)

  - **CG-MMC PL 01-21** — Policy Letter: Change 1 to CG-MMC Policy Letter 01-21, Guidelines for Qualifying for STCW Endorsements for Basic and Adv… · 2021-10-05 · [FR 2021-21635](https://www.federalregister.gov/documents/2021/10/05/2021-21635/policy-letter-change-1-to-cg-mmc-policy-letter-01-21-guidelines-for-qualifying-for-stcw-endorsements) · [PDF](https://www.govinfo.gov/content/pkg/FR-2021-10-05/pdf/2021-21635.pdf)

**Calibration: how much NMC policy gets announced in FR?**

Of the 13 NMC policy letters manually ingested, **0 appear in FR** with a parseable canonical doc number. This calibrates expected FR coverage at 0% — GovDelivery is mandatory for full NMC discovery; FR is at best supplementary.

---

## 4.3 MSIB coverage

- **FR documents matching category terms (full-text):** 660
- **Of those, contain category term in TITLE:** 0 (0%)
- **Of those, parseable to a canonical doc number in title:** 0 (0 unique numbers)
- **Noise ratio (term-only-in-abstract or unparsed):** 100%
- **Unique documents in RegKnot corpus (this source):** 0
- **Matched (FR ∩ corpus, by canonical doc number):** 0
- **Missing (FR-discoverable \ corpus):** 0 unique doc numbers

**MSIBs are not in FR. Period.** Of 660 FR results that surfaced from term searches, 0 had an MSIB number in the title and 0 had a parseable MSIB identifier. MSIBs distribute exclusively via:

- USCG GovDelivery email subscriptions (`uscoastguard@service.govdelivery.com`)
- Direct posting at `dco.uscg.mil` (Akamai WAF blocked from VPS)
- Industry republishing (USCG News, AMO, MarPro, AIS providers)

---

## 4.4 Host distribution for ALL FR-discoverable, corpus-missing documents

Aggregating across NVIC + NMC + MSIB missing-doc PDFs (10 FR rows):

| Host | Count | Fetchable from VPS? | Implication |
|---|---|---|---|
| www.govinfo.gov | 10 | ✓ yes | Direct backfill in Sprint C |

**Notable:** every FR-discoverable missing document has a govinfo.gov PDF URL. There are zero Akamai-blocked PDFs in the FR-discoverable gap set — the FR corpus is uniformly fetchable. The Akamai problem is exclusively about documents NOT discoverable via FR (i.e. the 80%+ of NMC and 100% of MSIB content).

---

## 4.5 Publication-rate calibration

Average FR publications/year over the past 5 calendar years (counting all term-matched FR results, including the noisy ones — these set an upper bound on the cadence of relevant USCG rulemaking surrounding each category):

| Category | FR docs (5y avg/yr) | Real-world cadence | Architecture implication |
|---|---|---|---|
| NVIC | 9.4 | USCG publishes 2-5 NVICs and 2-8 Change-Notes per year | Trickle — daily polling sufficient |
| NMC | 21.6 | USCG publishes 5-15 NMC PLs per year | Trickle — daily polling sufficient |
| MSIB | 57.2 | USCG broadcasts 50-100 MSIBs per year | Stream — automate aggressively |

(FR pubrate ≠ real cadence. The FR numbers are inflated by tangential USCG rulemaking. Real cadence comes from USCG/NMC publication schedules.)

---

## 4.6 Recommendations

### A. GovDelivery is the primary discovery channel — Sprint B priority

Build GovDelivery email-parsing first (the channel referenced by your subscription screenshot). Subscribe a forwarded inbox to `uscoastguard@service.govdelivery.com`, parse incoming bulletin emails for PDF links, fetch via the email's embedded URLs (which often point to non-WAF mirrors or include unwafable redirects).

**Order within Sprint B:** MSIB (FR yields 0 — no alternative) → NMC PLs (FR yields ~0.25%) → NVIC (FR catches ~3%, but NVIC scrape from prior sprint already covers most of the corpus).

### B. Sprint C — FR-discoverable backfill is small and easy

FR enumerates only **7 missing NVICs** and **2 missing NMC docs** — all on govinfo.gov, all directly fetchable from the VPS. This is a one-shot backfill, not an ongoing channel. Run the existing nvic/nmc adapters with these specific PDF URLs and you're done. Tactical effort, ~1 hour. Worth doing even before Sprint B lands because it's so cheap.

### C. Reuse this discovery utility for ongoing observability — Sprint D seed

`packages/ingest/ingest/sources/federal_register_discovery.py` is reusable. Wire it into Celery beat as a daily job that diffs today's FR results against the corpus inventory and emails `hello@regknots.com` when new FR-discoverable items appear. Even with 3-6% signal-to-noise, the absolute count of new daily FR-discoverable items is tiny (<1/day on average), so a human can spot-check the alerts. Don't auto-ingest — FR's noise level demands human review.

### D. Architecture nits flagged by the data

- **NVIC adapter section-numbering bug remains** — corpus has 1,277 unique section_numbers vs ~160 unique parent NVICs (per normalization). The adapter regex over-splits document subsections. Functional but noisy at retrieval; a future fix should make the section_number = parent NVIC and use chunk_index for sub-sections (matches the NMC adapter's pattern).
- **25-year FR query hits a 10,000-row ceiling** — for any future deep-history discovery, paginate via narrow date windows (1-year buckets).
- **Title-parser regex coverage:** NVIC ~90% of term-in-title rows (17/19), NMC ~4% (2/49), MSIB N/A (no titles to match). NMC is fundamentally untitled in FR; widening the regex won't help. GovDelivery is the answer.
