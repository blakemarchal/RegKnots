# IMO resolution harvester: new amendments into the library on their own (spec, 2026-10-13)

**Status:** live 2026-10-13 (`b2477f3` … `6a77bac`); backlog harvested. Blake, 2026-10-13: "Greenlight
all 4, auto-fetch parents, full backlog." Evidence and numbers: §6.

## Why

- **The corpus stopped at the resolutions someone picked by hand.** Of the resolutions the IMO
  has posted since late 2021, the corpus held 11 of 109 MSC, 11 of 59 MEPC and 0 of 70
  Assembly (administrative ones included). MSC 111 (13–22 May 2026) adopted 18 resolutions,
  among them SOLAS IV / V (VDES as an alternative to AIS), the MASS Code, LSA, IMDG, ESP and HSC
  amendments, all in force 1 January 2028; none was in the library.
- **The weekly "IMO amendment check" had been blind.** It fetched three pages and grepped for
  `MSC.n(m)`. The Marshall Islands page failed its TLS check every run, the two IMO pages now
  answer 301, and it compared only against `solas_supplement` / `stcw_supplement`. It logged
  "no new references found" every Monday, MSC 111 included. It also only emailed; a person
  had to download and ingest.
- **Phase 2 web research** (2026-10-09) can ingest an IMO PDF it finds while answering, but only
  reactively, one question at a time. `corpus_gaps` was still empty on 2026-10-13.
- **The answer model never knew today's date**, so even a retrieved amendment could not be
  placed as "in force" or "from 1 January 2028".

## What the IMO publishes (checked 2026-10-13)

- **Index of IMO Resolutions** (imo.org Knowledge Centre): one top page per body (MSC, MEPC,
  Assembly) linking pages per period (`msc-2026-27.aspx`, `mepc-2024-25.aspx`, `a-2025-27.aspx`,
  back to the 1980s). Each holds a plain HTML table: resolution number, title, a PDF on
  `wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/{MSCResolutions,
  MEPCDocuments,AssemblyDocuments}/<code>.pdf`, and "AWAITING CERTIFICATION" while the certified
  copy is pending (the PDF is already there). Older pages add notes: "Amends MSC.98(73)",
  "Revoked by A.1054(27)". 1,710 resolutions in all; no login, no JavaScript.
- Amendment PDFs state their adoption date ("(adopted on 22 May 2026)") and, in the operative
  paragraphs, when they enter into force. Their preamble names the resolution that adopted the
  instrument they amend ("resolution MSC.268(85), by which it adopted the IMSBC Code").
- Not here: MSC.1/Circ. and MEPC.1/Circ. circulars (unified interpretations, guidelines) are on
  IMODOCS behind a free account; conference resolutions (ISPS Code) are not in this index.

## Design (`packages/ingest/ingest/imo_harvest.py`)

| Step | What happens |
|---|---|
| Discover | Read the index: the two newest period pages per body weekly, every page with `--backlog` (cached in `data/raw/imo_harvest/index-full.json`). A page that parses to 0 rows is an error, not silence. |
| Select | Harvest a resolution when it is (a) **window**: adopted at MSC 104 / MEPC 77 / A 32 (late 2021) or later, or (b) **chain**: an amendment to an IMO code, from MSC 80 / MEPC 52 / A 24 (2005). Skip it when it is administrative (budget, arrears, rules of procedure, appreciation, …), already in the corpus (its number in any `section_number`), revoked per the index notes, or already merged into one of our consolidated editions (SOLAS 2024 to MSC 105, IMDG 42-24 to MSC 108, MARPOL 2022 to MEPC 76, STCW 2017 to MSC 97, ISM 2018 to MSC 98). |
| Route | By title to the source of its instrument: LSA → `imo_lsa`, FSS → `imo_fss`, IGC / IBC / IGF / HSC / Polar / Load Lines / CSS → their sources, BWM and biofouling → `imo_bwm`, STCW → `stcw_amend`, MARPOL and NOx Technical Code amendments → `marpol_amend`, anything else MSC / Assembly → `imo_msc`, MEPC → `imo_mepc`. **No new source, no migration.** |
| Read | pdfplumber text (IMO running heads stripped; a page whose text shows doubled glyphs, "RREESSOOLLUUTTIIOONN" in older fake-bold PDFs, is re-read with `dedupe_chars(extra_attrs=())`); a scan goes through tesseract. The text is cached in `data/ocr/imo_harvest/<stem>.txt` and the pipeline reads it, so a document is extracted once. Adoption and entry-into-force dates from the text (operative wording only: "shall enter into force on", not a recital's "entered into force"); a report annex with no adoption line takes its session's date. |
| Status | Every section title of the document ends `[MSC.583(111): adopted 22 May 2026; entry into force 1 January 2028]` (plus "certified text pending" while the IMO says so). `published_date` = entry into force, else adoption. |
| Parent | For an amendment to a code or guideline: the resolution its title names ("(RESOLUTION MSC.81(70))"), the index note ("Amends MSC.98(73)"), or the preamble recital that says it adopted the instrument, scored against the title's words (a preamble recalls the 1998 FTP Code before the 2010 one; "2010" and "FTP" pick MSC.307(88)). If the corpus lacks it, fetch it too, one level (this is how the IMSBC, ESP, SPS, MODU, IS and IP Codes come in). Never a resolution the text revokes, one skipped on purpose, one before MSC 60 / MEPC 40 / A 18 (the 1983 IBC / IGC originals), or for a convention amendment. |
| Revoked | A newer edition revokes the older ("REVOKES resolution A.1185(33)"): PSC Procedures 2021 / 2023 / 2025, HSSC survey guidelines, the III Code obligations lists. Only the current one is ingested; a harvested one a later resolution revokes is removed; a curated row it revokes is listed for review. |
| Ingest | Only the new documents go through `run_pdf_pipeline`, fresh mode, 20 at a time, with a prune scoped to them. A document is recorded in `<raw_dir>/harvest.json` of its source once its sections are written (one that parsed to nothing is reported and tried again next run); `sources/imo_codes.py` reads that file, so a curated run of the source (`ingest.cli --source imo_lsa`) still produces every harvested row and `--prune` keeps them. |
| Re-check | A document harvested while "AWAITING CERTIFICATION" is downloaded again when the flag clears, re-ingested if the PDF changed. |
| Report | `data/raw/imo_harvest/report-latest.json`; `app.tasks.harvest_imo_resolutions` (Mondays 10:00 UTC, replacing `check_solas_supplements`) emails a digest to hello@ when anything was added, failed or revoked. Admin › Jobs › "IMO resolution harvest" queues it. No Anthropic calls; OpenAI embeddings only. |

Run by hand: `scripts/run_ingest.sh --module ingest.imo_harvest [--backlog] [--plan] [--limit N] [--no-parents] [--no-notify]`.
The backlog run never notifies users; the weekly run creates the usual regulation-update
notification for a source that changed.

## Answer side

- **Today's date** in the user turn of every answer and regeneration (`engine.today_line`), not
  the cached system prompt.
- **DATES AND AMENDMENTS** block (all modes, Precision included): say whether an amendment is in
  force today or from what date and what applies until then; never present a future amendment
  as current law, never drop an adopted one the question concerns.
- **Source description** for the harvested resolutions in the system prompt's library list.
- **Retrieval groups:** `imo_igf`, `imo_polar`, `imo_symbols` join `imo_codes`; `marpol_amend`
  and `imo_bwm` join `marpol`; `stcw_amend` joins `stcw`. Until now those six sources (1,064
  chunks, incl. CII / EEXI in MEPC.328(76)) were in **no group**, so the diversified fetch
  never searched them: they surfaced only when a question named a resolution or a rare word.
- **Authority tiers:** MARPOL, IMDG, MLC, the LSA / FSS / IGF / Polar Codes, BWM and the
  amendment sources had no tier, so the answer model read them as "Tier 2 — federal
  interpretive guidance". They are Tier 1 now. `imo_msc` / `imo_mepc` stay Tier 2 (they mix
  amendments, each titled with its dates, and guidelines).
- **Citations:** the verifier checks MEPC and Assembly numbers as well as MSC, across every IMO
  source; bare `MEPC.400(83)` and `A.1206(34)` get chips; a bare resolution number opens the
  resolution's own opening section (`regulations._resolution_rows`).
- **What's coming** (`rag/live_context.py`): "what changed this month" no longer counts rows
  dated before its window (the backlog's 2006 amendments are not news); questions like "what
  comes into force next year" / "upcoming amendments" get a list of the IMO amendments in the
  library that enter into force in the next 18 months, soonest first.

## Measured

See §6.

## Not done

- **Licensing (checked 2026-10-13, Blake's IMODOCS public account works):** IMODOCS says each regulatory text is in the public domain but "the online IMODOCS collection is proprietary and cannot be reproduced, translated, distributed, sold or otherwise used without a prior written permission"; the imo.org website terms (which cover wwwcdn.imo.org, where the harvester and the curated IMO adapter download from) say "Reuse of the Materials for commercial purposes is expressly prohibited." No circular scraper without IMO's written permission (imo.org/en/publications/Pages/PermissionRequests.aspx); the resolution harvester's standing with IMO is Blake's call.

- MSC.1/Circ. / MEPC.1/Circ. circulars (IMODOCS account needed; Blake would create it).
- IMO meeting summaries (what the committees *approved* for adoption at the next session, the
  earliest signal of a coming rule, six months before a resolution exists).
- Amendments are deltas, not a consolidated text: "Regulation 7 is replaced by the following"
  sits next to the base text it replaces. The status line and the dates rule carry the order.
- A code's amendments before 2005 (and a code's parent when the IMO's PDF is a scan the VPS
  can't OCR) are not fetched.

## §6 Results (2026-10-13)

**Backlog run on prod** (`scripts/run_ingest.sh --module ingest.imo_harvest --backlog`, 20 min):

| | |
|---|---|
| Index rows read | 1,710 (MSC 596, MEPC 408, Assembly 706) |
| Selected | 276 (188 window, 88 chain) |
| Skipped | 40 administrative, 30 already in the corpus, 15 in a consolidated edition, 1 revoked per the index |
| Not yet published | 11 "AWAITING CERTIFICATION" placeholder PDFs: MSC.583–591(111) (SOLAS IV/V and VDES, ESP, HSC, IMDG 43-26, IP Code, LSA, MSC.402 amendments, Load Lines), MEPC.407–408(84) (Annex VI). Re-tried weekly. |
| Superseded by a newer harvested edition | 17 not ingested (PSC procedures 2021 / 2023, HSSC 2021 / 2023, III lists, SEEMP 2022, EEDI survey, G4, plastic litter, LH2 carriage …) |
| Harvested | **248 resolutions + 19 parent codes**: IMSBC MSC.268(85), ESP A.1049(27), IS MSC.267(85), 2008 SPS MSC.266(84), 2009 MODU A.1023(26), 2010 FTP MSC.307(88), Casualty Investigation MSC.255(84), 1994 HSC MSC.36(63), LSA testing MSC.81(70), CII reduction factors MEPC.338(76), shaft power limitation MEPC.335(76), VDR / S-VDR / BAM / radio performance standards, … |
| Parents skipped | 8 too old (1983 IBC / IGC, 1983 / 1989 SPS / MODU, the 1991 Grain Code MSC.23(59)), 2 consolidated instruments (MEPC.176(58) Revised Annex VI 2008, MSC.416(97) STCW), 1 not on the CDN (MSC.88(66)) |
| Written | **+8,910 chunks** (imo_msc 5,633, imo_ibc 1,190, imo_mepc 999, stcw_amend 225, marpol_amend 223, imo_lsa 211, imo_hsc 157, imo_bwm 127, …); corpus 102,890 → **111,800** |
| Curated rows now revoked (Blake's call) | A.1050(27) enclosed spaces (by MSC.581(110)), A.1118(30) ISM implementation guidelines (A.1188(33)), MEPC.207(62) biofouling (MEPC.378(80)), MEPC.259(68) EGCS 2015 (MEPC.340(77)) |

**Memory.** The first attempt held 1.0 GB + 0.9 GB swap after 170 PDFs and filled the box's 2 GB
swap; the second hit 1.07 GB + 0.77 GB on one 600-page PDF. Both were stopped before writing.
pdfplumber keeps every page's objects until the file closes: `page.close()` per page took
MSC.461(101) from 1,922 MB to 71 MB peak. The third run stayed under 600 MB with no swap.

**Retrieval** (dense harness, 80 pairs; deployed = 10-09 baseline 0.9500 / 0.9750 / 0.7874):

| step | strong / weak / MRR | pairs |
|---|---|---|
| IMO sources grouped (pre-backlog corpus) | 0.9500 / 0.9750 / 0.7957 | none moved in or out |
| backlog ingested, `imo_msc` in the solas group | 0.9125 / 0.9625 / 0.7793 | F1/V1, F1/V2, N-S1/V1 lost |
| + `imo_res` group | 0.9250 / 0.9625 / 0.7741 | F1 ×2 lost (keyword lane) |
| + keyword caps scale with corpus size (`6a77bac`) | **0.9500 / 0.9750 / 0.7874** | none lost; N-M2/V1 1 → 3 |

Causes: the VDR performance standards took the solas group's six slots (N-S1, a VDR question,
lost SOLAS V/20); "scba" went from 199 to 201 matching chunks and "breathing apparatus" from
599 to 839, over the keyword lane's fixed 200 / 800 caps. With five new pairs on harvested
resolutions (A28-*), the 85-pair baseline is **0.9529 / 0.9765 / 0.7839**; the new pairs hit at
ranks 2, 1, 7 (weak 1), 1, 1.

**Answers** (`compare_synthesis_models.py --dates-ab --session-judge`): **ON since 2026-10-13** after `compare_synthesis_models.py --dates-ab --session-judge` (16 questions: 10 on IMO amendments for the Captain's vessel, 4 gold, her 2; ~$5 API, grading on the subscription): session judge overall 7.81 → 7.94, accuracy 7.88 → 8.38, errors flagged 26 → 21, judged best 9 vs 7 (today ahead); GPT-4o overall 9.31 → 9.62, accuracy 9.81 → 9.94, errors 2 → 0, best 6 → 10. Date wins: IMO9 caught MEPC.413(84) reversing the 2025 SEEMP distance rule (6 → 9), IMO7 placed IMDG 43-26 against today, IMO3 got the 2025 enclosed-space changes without inventing any. Variance seen: the coverage check sent one capture to the web and not the other (IMO6). `IMO_DATES_PROMPT_ENABLED=false` reverts.
