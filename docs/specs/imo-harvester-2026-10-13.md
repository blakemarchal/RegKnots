# IMO resolution harvester: new amendments into the library on their own (spec, 2026-10-13)

**Status:** built 2026-10-13. Blake, 2026-10-13: "Greenlight all 4, auto-fetch parents, full
backlog." Evidence and numbers: §6 (filled in after the backlog run).

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
| Read | pdfplumber text (IMO running heads stripped); a scan goes through tesseract and is cached in `data/ocr/imo_harvest/`. Adoption and entry-into-force dates from the text (operative wording only: "shall enter into force on", not a recital's "entered into force"); a report annex with no adoption line takes its session's date. |
| Status | Every section title of the document ends `[MSC.583(111): adopted 22 May 2026; entry into force 1 January 2028]` (plus "certified text pending" while the IMO says so). `published_date` = entry into force, else adoption. |
| Parent | For an amendment to a code or guideline: the resolution its title names ("(RESOLUTION MSC.81(70))") or its preamble says adopted the instrument. If the corpus lacks it, fetch it too, one level (this is how the IMSBC, ESP, SPS, MODU, IS and IP Codes come in). Never a resolution the text revokes; never for a convention amendment. |
| Revoked | A newer edition revokes the older ("REVOKES resolution A.1185(33)"): PSC Procedures 2021 / 2023 / 2025, HSSC survey guidelines, the III Code obligations lists. Only the current one is ingested; a harvested one a later resolution revokes is removed; a curated row it revokes is listed for review. |
| Ingest | Each document is recorded in `<raw_dir>/harvest.json` of its source; `sources/imo_codes.py` reads that file, so a curated run of the source (`ingest.cli --source imo_lsa`) still produces every harvested row and `--prune` keeps them. Only the new documents go through `run_pdf_pipeline`, fresh mode, with a prune scoped to them. |
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

## Measured

See §6.

## Not done

- MSC.1/Circ. / MEPC.1/Circ. circulars (IMODOCS account needed; Blake would create it).
- IMO meeting summaries (what the committees *approved* for adoption at the next session, the
  earliest signal of a coming rule) and a "what comes into force next year" calendar.
- Amendments are deltas, not a consolidated text: "Regulation 7 is replaced by the following"
  sits next to the base text it replaces. The status line and the dates rule carry the order.
- A code's amendments before 2005 (and a code's parent when the IMO's PDF is a scan the VPS
  can't OCR) are not fetched.

## §6 Results

(filled in after the backlog run)
