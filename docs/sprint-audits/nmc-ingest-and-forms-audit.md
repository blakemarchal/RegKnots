# NMC Ingest & Forms Product Audit

**Date:** 2026-04-17
**Auditor:** Claude Opus 4.7 (audit sprint — findings only, no production changes)
**Scope:** NVIC pipeline health, ingest/RAG parity for an NMC source, forms product feasibility.

---

## Critical finding up front: the NMC "PDFs" are URL placeholders, not actual PDFs

Before anything else, the ingest sprint cannot proceed until this is fixed.

The 25 files at `C:/Users/Blake Marchal/Documents/RegKnots/data/raw/nmc/` are **60–220 byte plain-text files containing URLs, not PDF content**. Each file's entire contents is the URL of the NMC document it was meant to be. Example:

```
$ cat data/raw/nmc/cg_719b.pdf
https://www.dco.uscg.mil/Portals/9/NMC/pdfs/forms/cg_719b.pdf
```

`pdfplumber` fails on every one with "No /Root object! - Is this really a PDF?". The directory appears to have been populated by saving browser-address-bar text (or similar) rather than the actual binary PDFs. **All 25 files need to be re-downloaded as real PDFs** before any of the ingest or forms work below can actually run. See "Area 2 — Re-download plan" for the file list and source paths extracted from the URL placeholders.

This also means the AcroForm / fillable-vs-scanned question in **Area 3** is **unanswered by this audit** — I have no real binaries to inspect. The audit still provides the structural plan for the forms product, but the AcroForm determination is blocked until real PDFs exist.

---

## Area 1 — NVIC pipeline health check

### 1.1 NVIC ingest handler

**Path:** [`packages/ingest/ingest/sources/nvic.py`](packages/ingest/ingest/sources/nvic.py)
**Last modified (local worktree):** file is unchanged from the committed version on main. Git blame shows the module shipped intact when NVIC was added; no recent modifications.
**Handler shape:** three phases — `discover_nvics()` → `_download_nvics()` → `parse_source()`. Dispatched via `_run_pdf_source()` in [`packages/ingest/ingest/cli.py:322`](packages/ingest/ingest/cli.py:322) through the `raw_dir` (multi-PDF) adapter pattern.

Key implementation details relevant to the pipeline-health question:

- **URL:** `https://www.dco.uscg.mil/Our-Organization/NVIC/` plus per-decade subpages ([`nvic.py:49`](packages/ingest/ingest/sources/nvic.py:49)).
- **WAF avoidance:** sends a full browser `User-Agent` + `Sec-Fetch-*` headers ([`nvic.py:51-69`](packages/ingest/ingest/sources/nvic.py:51)) specifically to bypass Akamai's bot filter on `dco.uscg.mil`.
- **Rate limiting:** 1.0s between PDF downloads, 0.5s between decade pages, 45s timeout.
- **Idempotent:** existing PDFs on disk are skipped; failures are written to `data/failed/nvic_{number}.json` rather than raised.
- **Section chunking:** splits PDFs on `^\d{1,2}\.\s+` numbered section boundaries ([`nvic.py:80`](packages/ingest/ingest/sources/nvic.py:80)); falls back to one-section-per-document when no boundaries detected.

### 1.2 Celery beat schedule

**File:** [`apps/api/celery_beat.py`](apps/api/celery_beat.py)

The NVIC scrape is **not a standalone weekly task**. It runs as part of the unified weekly regulation update:

```python
# celery_beat.py:12-16
"update-regulations-weekly": {
    "task": "app.tasks.update_regulations",
    "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),  # Sunday 02:00 UTC
},
```

Looking at [`apps/api/app/tasks.py:27-32`](apps/api/app/tasks.py:27), NVIC is in the automatable-sources list alongside the CFR titles:

```python
_AUTOMATABLE_SOURCES = ["cfr_33", "cfr_46", "cfr_49", "nvic"]
```

Each runs in its own CLI subprocess (`uv run python -m ingest.cli --source nvic --update`) with a 1-hour timeout. On any failure the whole task retries once after 3600s.

**Target URL:** the hardcoded `_INDEX_URL` in the NVIC adapter: `https://www.dco.uscg.mil/Our-Organization/NVIC/` (plus decade subpages discovered at runtime).

There is a **separate weekly NMC monitor** at [`tasks.py:727`](apps/api/app/tasks.py:727) (`check_nmc_updates`, Wednesdays 12:00 UTC) which scrapes NMC *announcement pages* looking for new PDF hrefs — this is a human-alert monitor that inserts rows into `notifications` and emails `hello@regknots.com`. It does **not** ingest anything into the `regulations` table.

### 1.3 VPS chunks-table query — commands for the user to run

The table is `regulations` (not `chunks` — worth noting; the audit prompt's terminology doesn't match the schema). Confirmed via [`apps/api/alembic/versions/0001_initial_schema.py:94`](apps/api/alembic/versions/0001_initial_schema.py:94).

**I could not execute these queries myself** (no VPS access from this session). Run these on the VPS via `psql $DATABASE_URL`:

```sql
-- Most recent NVIC ingest
SELECT MAX(created_at) AS last_ingested_at,
       COUNT(*) AS total_chunks
FROM regulations
WHERE source = 'nvic';

-- Note: the schema does NOT have an ingested_at column. Use created_at
-- (chunk row insert time) or up_to_date_as_of (the NVIC's effective date).
-- The prompt's "ingested_at" doesn't exist.

-- All distinct NVIC section_numbers represented
SELECT DISTINCT parent_section_number
FROM regulations
WHERE source = 'nvic'
ORDER BY parent_section_number;

-- Specifically: is NVIC 04-08 (Medical and Physical Evaluation Guidelines) present?
SELECT section_number, section_title, up_to_date_as_of, created_at
FROM regulations
WHERE source = 'nvic'
  AND (section_number ILIKE 'NVIC 04-08%' OR parent_section_number ILIKE 'NVIC 04-08%')
ORDER BY section_number;
```

### 1.4 Scraper dry-run — cannot execute from this session

The NVIC scraper **cannot be dry-run from this worktree** — the current working directory is a Windows worktree with no ingest venv and no network test harness. The only way to verify whether Akamai is blocking NVIC downloads from the VPS specifically is to run the scrape on the VPS.

**Reproducible command to run on the VPS** (from `/opt/RegKnots/packages/ingest`):

```bash
# Test discovery only — writes data/raw/nvic/index.json but no DB writes
uv run python -c "
from pathlib import Path
from ingest.sources.nvic import discover_nvics
metas = discover_nvics(Path('data/raw/nvic'))
print(f'Discovered {len(metas)} NVICs')
for m in metas[:5]:
    print(f'  {m.number} — {m.title[:60]} — {m.pdf_url}')
"
```

Then check for specific blockage on a single NVIC PDF:

```bash
curl -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" \
     -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" \
     -H "Accept-Language: en-US,en;q=0.9" \
     -H "Sec-Fetch-Dest: document" \
     -H "Sec-Fetch-Mode: navigate" \
     -I -L "https://www.dco.uscg.mil/Portals/9/NVIC/2008/NVIC%2004-08%20Change%204.pdf"
```

**Expected patterns:**
- `200 OK` + `Content-Type: application/pdf` → pipeline works from VPS.
- `403 Forbidden` + `Server: AkamaiGHost` or a JS challenge page → same Akamai WAF block as NMC (memory entry).
- `ConnectTimeout` / DNS fail → network issue, not WAF.

The NVIC adapter's `User-Agent`/`Sec-Fetch-*` headers were clearly added as a first-pass WAF mitigation ([`nvic.py:56-69`](packages/ingest/ingest/sources/nvic.py:56) has a literal comment "to avoid WAF 403 on dco.uscg.mil"). **Whether that workaround still works is the exact thing the VPS test above will tell us.** Given that NVICs live on the same host as the blocked NMC pages (`dco.uscg.mil`), it's plausible but not confirmed that Akamai is treating them the same way.

### 1.5 NVIC 04-08 presence — likely gap

Per the audit prompt, NVIC 04-08 Change 4 (Medical and Physical Evaluation Guidelines) is the most likely gap for medical-certificate queries. Confirmation requires the VPS query in 1.3. If absent, three plausible causes in order of likelihood:

1. **Discovery gap:** the decade-page + main-index scrape only finds what's linked on `/Our-Organization/NVIC/Year/...`. NVICs that are only linked from a Medical-subject page may be missed. Worth spot-checking `discover_nvics()` output against the manually-known NVIC number.
2. **Akamai WAF block** (see 1.4): if the page fetch is being rejected or returning a challenge HTML instead of a NVIC table, discovery finds nothing and no download is attempted.
3. **Parsing drop:** if the PDF is unusually structured (scanned image, non-standard section numbering) `_parse_nvic_pdf()` may produce 0 sections and log-and-skip — the document is "downloaded" but not "ingested".

A failed download leaves a file at `data/failed/nvic_04-08.json` — querying that file on the VPS would distinguish (1)/(2) from (3).

### 1.6 Summary — Area 1

| Question | Answer |
|---|---|
| NVIC handler path | [`packages/ingest/ingest/sources/nvic.py`](packages/ingest/ingest/sources/nvic.py) |
| Celery beat schedule | `update-regulations-weekly`, Sunday 02:00 UTC, part of batched `update_regulations` task |
| Target URL | `https://www.dco.uscg.mil/Our-Organization/NVIC/` + per-decade subpages |
| Chunks table | Actually named `regulations`, not `chunks` |
| Most recent ingest timestamp | **Requires VPS query** (see 1.3) |
| NVIC sections present | **Requires VPS query** (see 1.3) |
| Dry-run result | **Requires VPS execution** (see 1.4) |
| WAF-blocked on VPS? | Plausible but unverified — same host as NMC, same Akamai, with a workaround already embedded in the scraper that may or may not still work |
| NVIC 04-08 Change 4 presence | **Requires VPS query**; if absent, most likely cause is WAF block or discovery-page gap |

---

## Area 2 — Enrichment parity audit

### 2.1 Per-source ingest pipelines

The pipeline shares a common spine: **adapter `parse_source()` → `chunker.chunk_section()` → optional `enricher.AliasEnricher.enrich_chunks()` → `embedder` → `store.upsert()` → notification hook**. What varies is (a) how sections are constructed before chunking, and (b) whether enrichment runs.

#### cfr_33 (and cfr_46, cfr_49 by analogy)

- **Entry:** [`packages/ingest/ingest/pipeline.py:38`](packages/ingest/ingest/pipeline.py:38) `run_pipeline()`.
- **Fetch:** `ECFRClient` pulls the title XML via the eCFR API.
- **Parse:** [`packages/ingest/ingest/parser.py`](packages/ingest/ingest/parser.py) `parse_title_xml()` walks the XML tree and emits one `Section` per CFR section (`§ 46.10-5` etc.).
- **Chunking:** shared `chunker.chunk_section()`. 512-token chunks, 50-token overlap, paragraph-first splits fall back to sentence-level then hard-token splits ([`chunker.py:26-27`](packages/ingest/ingest/chunker.py:26)).
- **Header format:** `[{section_number}] {section_title}` prepended to every chunk ([`chunker.py:58-61`](packages/ingest/ingest/chunker.py:58)) so embeddings remain self-contained across chunk boundaries.
- **Enrichment:** eligible — `enricher.py` excludes only `erg` from the skip-list ([`enricher.py:48`](packages/ingest/ingest/enricher.py:48)). Runs when `--enrich` passed to the CLI. Default is **OFF** (see [`cli.py:156`](packages/ingest/ingest/cli.py:156) — `default=False`).

#### colregs

- **Entry:** single-PDF path in `_run_pdf_source()` ([`cli.py:383`](packages/ingest/ingest/cli.py:383)).
- **Parse:** [`packages/ingest/ingest/sources/colregs.py:56`](packages/ingest/ingest/sources/colregs.py:56) calls `parse_colregs_pdf()` then merges short adjacent rules within the same Part up to `TARGET_TOKENS=450` ([`colregs.py:49`](packages/ingest/ingest/sources/colregs.py:49)) — one Section per merged group, never across Part boundaries.
- **International vs Inland:** both variants concatenated with `[INTERNATIONAL]` / `[INLAND]` markers when they differ, INTL-only when identical.
- **Enrichment:** eligible; same default-off rule as CFR.

#### solas

- **Entry:** text-dir path ([`cli.py:405`](packages/ingest/ingest/cli.py:405)).
- **Parse:** [`packages/ingest/ingest/sources/solas.py:70`](packages/ingest/ingest/sources/solas.py:70) reads a `headers.txt` index plus `<start>-<end>.txt` page-range files. One Section per header entry. `section_number` canonicalized to forms like `SOLAS Ch.II-1 Part B-1`, `SOLAS Annex I`, `SOLAS Articles`.
- **Enrichment:** eligible; same default-off.

#### nvic

- Covered in Area 1.1. Sections are top-level numbered subdivisions of each NVIC PDF with `section_number = "NVIC {number} §{n}"` and `parent_section_number = "NVIC {number}"`.

#### nmc_memo (existing source, the closest precedent for the new NMC work)

- **Entry:** `raw_dir` path, but the adapter at [`packages/ingest/ingest/sources/nmc_memo.py`](packages/ingest/ingest/sources/nmc_memo.py) does NOT implement `discover_and_download()` or `get_source_date()` — the `raw_dir` dispatch path in [`cli.py:352`](packages/ingest/ingest/cli.py:352) would fail on NMC memo because it calls those functions.

  **Possible bug:** `cli.py:61-63` registers `nmc_memo` under the `raw_dir` pattern but the adapter only exposes `parse_source()`. Either (a) the pipeline currently short-circuits because the adapter is manually-placed PDFs only and the missing functions raise AttributeError at runtime, or (b) the dispatch code hasn't been exercised since `nmc_memo` was added. Worth verifying on the VPS — memory mentions the NMC memo source shipped (commit `3d5b047 feat(ingest): NMC memo ingest pipeline + RAG source group`), so either the bug is latent or there's a code path I missed.

  **Update after re-reading `cli.py:352-381`:** the dispatch at line 357 calls `adapter.discover_and_download(...)` directly. If `nmc_memo` is invoked via `--source nmc_memo`, this will raise `AttributeError` — the function simply doesn't exist in [`nmc_memo.py`](packages/ingest/ingest/sources/nmc_memo.py). This is a real gap; the new NMC source must either implement these functions or extend the dispatch to treat PDF-directory-only sources differently.

- **Chunking:** after `parse_source()`, delegates to the same shared `chunker.chunk_section()`.
- **Date strategy:** extracts year from filename patterns like `policy_letter_01-24` ([`nmc_memo.py:62-87`](packages/ingest/ingest/sources/nmc_memo.py:62)); falls back to today's date.

### 2.2 Enrichment & RAG per-source behavior

**Alias enrichment** ([`enricher.py`](packages/ingest/ingest/enricher.py)):

- One opt-in LLM pass via Claude Sonnet, 8–12 colloquial search terms per chunk, prepended as `[Search terms: ...]` inside the chunk's header block ([`enricher.py:165`](packages/ingest/ingest/enricher.py:165)).
- **Default OFF** per [`cli.py:156`](packages/ingest/ingest/cli.py:156) (`default=False`). Must be explicitly enabled with `--enrich`.
- Skip-list: only `erg` ([`enricher.py:48`](packages/ingest/ingest/enricher.py:48)) — the ERG adapter has its own native alias mechanism (see below). Every other source including `nvic`, `solas`, `colregs`, and `nmc_memo` is eligible when the flag is on.
- Results cached by `content_hash` at `~/.regknot/alias_cache/{source}.json`; re-ingests only call the API for genuinely new/modified chunks.

**ERG's native alias mechanism** (the "chemical-name appending" memory entry):

- [`packages/ingest/ingest/sources/erg.py:425-454`](packages/ingest/ingest/sources/erg.py:425) appends the top associated material common-names to the Orange Guide section_title: `f"{title} ({', '.join(names)})"`.
- Names are stripped of storage-form qualifiers (`, compressed`, `, liquefied` etc.) — matches how mariners actually phrase searches.
- Because the chunker prepends `[section_number] section_title` to every chunk, these material names end up in **every chunk of the guide**, giving them strong embedding weight and making trigram ILIKE search on chemical names succeed.
- This is the only structural alias mechanism in the codebase besides the opt-in LLM enricher. It's custom to ERG and lives in the source adapter, not in `enricher.py`.

**RAG retrieval — per-source weighting** ([`packages/rag/rag/retriever.py`](packages/rag/rag/retriever.py)):

- **Diversified fetch** ([`retriever.py:43-59`](packages/rag/rag/retriever.py:43)): one vector-search query per SOURCE_GROUP concurrently, each group gets its own top-N pool, preventing a large source (CFR: ~33K chunks) from swamping small ones (COLREGs: ~102, SOLAS: 742). CFR gets 12 candidates, other groups get 6 ([`retriever.py:56-59`](packages/rag/rag/retriever.py:56)).
- **SOURCE_GROUPS structure** ([`retriever.py:43`](packages/rag/rag/retriever.py:43)):

  ```python
  SOURCE_GROUPS = {
      "cfr":     ("cfr_33", "cfr_46", "cfr_49"),
      "colregs": ("colregs",),
      "solas":   ("solas", "solas_supplement"),
      "nvic":    ("nvic",),
      "stcw":    ("stcw", "stcw_supplement"),
      "ism":     ("ism", "ism_supplement"),
      "erg":     ("erg",),
      "nmc":     ("nmc_memo",),   # ← existing group; takes the new NMC source too
  }
  ```

- **Source affinity boosts** ([`retriever.py:184-228`](packages/rag/rag/retriever.py:184)): soft +0.20 score bump when query contains group keywords. NMC group already wired up at [`retriever.py:168-181`](packages/rag/rag/retriever.py:168) — terms include `nmc`, `mmc renewal`, `medical certificate`, `cg-719`, `endorsement`, `sea service`, `twic`, `raise of grade`, etc. Credentialing queries additionally get a +0.10 nudge on CFR (Parts 10–16 territory).
- **Vessel-awareness boost** ([`retriever.py:757-786`](packages/rag/rag/retriever.py:757)): +0.05 per term hit when the chunk text mentions the vessel's type / route / cargo. Soft nudge, not filtering.
- **Hybrid keyword tier** ([`retriever.py:612-721`](packages/rag/rag/retriever.py:612)): structured identifiers (UN1219, NVIC numbers, CFR sections, `SOLAS II-2`, etc.) get +0.05, broad keywords get +0.02. Existing NVIC identifier regex is [`retriever.py:244`](packages/rag/rag/retriever.py:244) — a new source would add an entry here if it has distinctive identifier patterns.

### 2.3 NMC content classification — what we have

Despite the PDFs being URL placeholders, the URLs themselves are enough to classify what the sprint is meant to handle. Grouping the 25 file-name URLs by path prefix:

**Forms** (7): `/NMC/pdfs/forms/`
- `cg_719b.pdf` — Application for Merchant Mariner Credential
- `cg_719c.pdf` — Application for Dangerous Substances Endorsement
- `cg_719k.pdf` — Medical Certificate Application (for mariners not taking the physical)
- `cg_719ke.pdf` — Medical Certificate Application (short form / extension?)
- `cg_719p.pdf` — Periodic Drug Test Form
- `cg_719s.pdf` — Small Vessel Sea Service Form
- `cg719b_application_guide.pdf` — CG-719B Application Guide
- `application_acceptance_checklist.pdf`

**Checklists** (4): `/NMC/pdfs/checklists/`
- `mcp_fm_nmc5_01_web.pdf`
- `mcp_fm_nmc5_27_web.pdf`
- `mcp_fm_nmc5_209_web.pdf`
- `mcp_fm_nmc5_224_web.pdf`

**Policy letters / credentialing guidance** (13): `/NMC/pdfs/regulations_policies/` (8) + `/DCO Documents/...` (3) + `/professional_qualifications/` (1) + one orphan-numbered (1)
- `01-00.pdf`, `01-16.pdf`, `04-03.pdf`, `07-01.pdf`, `11-12.pdf`, `11-15.pdf` — numbered NMC policy letters
- `CG-CVC_pol15-03.pdf` — CVC policy letter
- `cg-mmc_policy_letter_01-17_final_3_9_17-date.pdf`
- `PolicyLetter01_16.pdf`
- `CG-MMC 01-18 Harmonization.pdf` — MMC policy
- `CG OES Policy Letter 01-15 signature with Enclosures.pdf` — OES policy
- `Liftboat Policy Letter_Signed 20150406.pdf`
- `crediting_military_ss.pdf` — military sea-service crediting guidance

**Re-download plan** (once PDFs are replaced with real content):

```bash
# On the local machine — the URL is the placeholder content itself:
cd /c/Users/Blake\ Marchal/Documents/RegKnots/data/raw/nmc
for f in *.pdf; do
    url=$(cat "$f")
    curl -A "Mozilla/5.0 (compatible)" -L -o "${f}.download" "$url" \
        && mv "${f}.download" "$f" \
        || echo "FAILED: $f ($url)"
done
```

If Akamai blocks the automated download, these need to be fetched manually via a browser and copied in — same situation the memory entry describes for NMC policy pages.

### 2.4 Recommended source split

**Recommendation: split into three regulation sources by document type, plus a separate non-regulation bucket for forms.**

```
nmc_policy   — policy letters + credentialing guidance (13 docs)
nmc_checklist — application acceptance checklists (4 docs)
nmc_memo     — already exists (migration 0042); keep as catch-all for memos
nmc_form     — NOT a regulation source; lives outside the RAG corpus (see Area 3)
```

Rationale:

- **Policy letters** carry binding interpretation of CFR — treat them the way NVICs are treated. High retrieval priority for credentialing queries.
- **Checklists** are prescriptive "what to submit with an application X" content. They embed well but need a different `section_title` convention so retrieval doesn't confuse "checklist item" with "regulatory requirement" in citations.
- **Forms** are not prose and shouldn't be RAG-indexed at all. They are a separate product surface (Area 3). Feeding a CG-719B AcroForm PDF to `pdfplumber` produces garbled half-text that will generate noisy, misleading chunks.

**Structural analogue:** the closest existing adapter is [`sources/nmc_memo.py`](packages/ingest/ingest/sources/nmc_memo.py) — same input pattern (a directory of drop-in PDFs, no scraping), same numbered-section parsing. SOLAS is a poorer fit because it requires a `headers.txt` index and pre-extracted per-range text files; the NMC documents don't map to that structure. A new adapter would be `nmc_memo.py` with three modifications:

1. Rename `SOURCE = "nmc_policy"` (or similar).
2. Parameterize `parent_section_number` to prefix with the document type label (`Policy`, `Checklist`).
3. If the split above is adopted, three thin wrapper modules (`nmc_policy.py`, `nmc_checklist.py`, `nmc_memo.py`) can share a single `_parse_pdf()` helper in a `_common.py`.

**Schema impact — migration required.** The `regulations_source_check` CHECK constraint (migration 0042) currently allows: `cfr_33, cfr_46, cfr_49, colregs, erg, ism, ism_supplement, nmc_memo, nvic, solas, solas_supplement, stcw, stcw_supplement`. Adding `nmc_policy` and `nmc_checklist` requires a migration 0044 (and touches the `regulations_source_check` constraint the same way 0042 did).

**Latent migration issue flagged by memory entry (verified here):** migration 0042's *downgrade* path at [`0042_add_nmc_memo_source.py:33-37`](apps/api/alembic/versions/0042_add_nmc_memo_source.py:33) reverts to a constraint that **omits `ism_supplement`** — matching the memory note that `ism_supplement` was added live in production without a migration and is not actually in any version-controlled migration. The upgrade path includes it but the downgrade path would drop it. This means `alembic downgrade -1` from 0042 silently breaks `ism_supplement` ingests. The new NMC migration should (a) include `ism_supplement` in both its downgrade and upgrade paths, and (b) optionally add a standalone repair migration that formalises `ism_supplement` so future downgrades don't keep re-introducing the gap.

### 2.5 Enrichment recommendations for the new NMC source

**To match existing source quality:**

1. **Native title-enrichment** for forms-referencing content (pattern borrowed from ERG): append form-number aliases to `section_title` when a policy letter references specific forms. E.g., a policy letter mentioning CG-719B and CG-719K should end up with `(CG-719B, CG-719K)` at the end of its section_title so every chunk header carries those identifiers. This is cheap (regex over full_text during parsing) and dramatically improves recall for "what form do I need for..." queries.

2. **Add identifier regex** at [`retriever.py:238-246`](packages/rag/rag/retriever.py:238) for `CG-719[A-Z]?` pattern. Example:

   ```python
   ("cg_form", re.compile(r"\bCG-?\s*719([A-Z]?)\b", re.IGNORECASE)),
   ```

3. **Extend `_NMC_TERMS`** at [`retriever.py:168-181`](packages/rag/rag/retriever.py:168) with any new vocabulary the additional documents reveal — `raise of grade`, `medical evaluation`, `psychological evaluation`, `drug screen`, `oath of allegiance`, `merchant mariner credential`, `restricted local area license`, `lower level`, etc.

4. **SOURCE_GROUPS wiring**: if the three-way split is adopted, collapse all NMC sub-sources into a single `"nmc"` group:

   ```python
   "nmc": ("nmc_memo", "nmc_policy", "nmc_checklist"),
   ```

   The group-level candidate pool (6) then covers all three sub-sources together — mirrors how `cfr` covers three CFR titles.

5. **LLM alias enrichment**: worth turning ON for the NMC corpus specifically (add a whitelist flag to `cli.py`, or just run with `--enrich` on initial ingest). The policy-letter vocabulary is formal — things like "substantial compliance with 46 CFR 11.201" — and mariners phrase their questions in informal language ("can I get my license renewed if I skipped a physical"). Alias enrichment closes that gap.

---

## Area 3 — Forms product capability audit

### 3.1 Does the app currently serve PDFs to users?

**Yes, two generated-PDF endpoints exist.** Both produce PDFs from templates using `fpdf2` — neither serves a pre-existing PDF from disk or storage.

**Endpoint 1:** [`apps/api/app/routers/sea_service.py`](apps/api/app/routers/sea_service.py)
- `POST /credentials/sea-service-letter` → generates the USCG Sea Service Letter PDF on the fly, returns as `StreamingResponse` ([`sea_service.py:228-232`](apps/api/app/routers/sea_service.py:228)).
- No DB persistence — "letters are point-in-time documents. The signed paper is the version that matters" ([`sea_service.py:12`](apps/api/app/routers/sea_service.py:12)).

**Endpoint 2:** [`apps/api/app/routers/export.py`](apps/api/app/routers/export.py)
- `GET /export/vessel/{vessel_id}/pdf` → compliance summary PDF ([`export.py:85-88`](apps/api/app/routers/export.py:85)).
- `POST /export/vessel/{vessel_id}/share` + `GET /export/shared/{share_token}` → shareable public profile page (not a PDF — an HTML page at `/shared/{token}`).

**Static-asset PDF serving: no.** No `StaticFiles`/`FileResponse` mount exists for user-facing PDFs. The only static-served binary paths are the user-uploaded vessel documents (see 3.3), served back to the user who owns them via the documents router.

**Signed URLs: no.** No pre-signed S3 / GCS pattern. Everything is local disk or DB streaming.

### 3.2 Existing form-building / state-persistence code

**Form generation is present but not form-building.** The `fpdf2` library (`>=2.8.0` in [`apps/api/pyproject.toml:33`](apps/api/pyproject.toml:33)) is used exclusively for *writing* PDFs — the sea-service letter and compliance-summary PDFs are built from scratch by drawing on a blank page. Neither reads an existing AcroForm PDF, fills it, and re-serves it.

**No `pypdf` / `PyPDF2` / `pdfrw` in the API venv** — confirmed via `ls apps/api/.venv/Lib/site-packages/`. Filling an AcroForm PDF requires adding one of these (or switching to `pdfplumber`+`fpdf2` round-trip which is error-prone). `pdfplumber` *is* in the ingest venv but the ingest package doesn't produce PDFs — it reads them.

**Form-state persistence: no.** Neither the sea-service letter nor the compliance summary saves a draft. Both are single-request generate-and-stream patterns. There is no `form_drafts` table, no `partially_completed_forms` column, no "resume a draft" UI anywhere.

### 3.3 AcroForm vs. scanned PDFs — UNABLE TO VERIFY

**The CG-719-series files at `data/raw/nmc/` are URL placeholders, not PDFs.** This audit cannot determine AcroForm presence on any of them.

Based on public USCG practice (unverified in this audit):
- The CG-719-series PDFs published on `dco.uscg.mil/NMC/pdfs/forms/` are known to be **fillable AcroForm PDFs** — this has been consistently true for the last ~10 years of CG-719 revisions.
- The `mcp_fm_nmc5_*` checklist PDFs are typically **flat reference documents**, not fillable — but this should be verified.

**To confirm once real PDFs are in place**, re-run (in an environment with `pypdf` installed):

```python
from pypdf import PdfReader
from pathlib import Path
for p in sorted(Path("data/raw/nmc").glob("*.pdf")):
    r = PdfReader(p)
    acro = bool(r.trailer["/Root"].get("/AcroForm"))
    fields = r.get_fields() or {}
    print(f"{p.name}: acroform={acro}, fields={len(fields)}")
```

**If AcroForm**: fill via `pypdf.PdfWriter.update_page_form_field_values()` — clean, reliable, field names stable across revisions. One-session-shop per form.

**If not AcroForm (scanned/flat)**: overlay strategy — measure field positions via a tool like `pdfjs-dist` in the browser or `pdfplumber.Page.chars` in Python, render a transparent text layer at known coordinates, merge via `pypdf`. Fragile; every form revision can shift coordinates. 2–3× more effort per form. Not recommended if ANY of the CG-719-series turn out to be scans.

### 3.4 Database schema support for form drafts

**No existing table fits cleanly.** Surveyed:

- **`vessel_documents`** ([`0019_create_vessel_documents.py`](apps/api/alembic/versions/0019_create_vessel_documents.py)) — stores uploaded COIs and safety certs, keyed on `vessel_id`. Has `extracted_data JSONB` which *could* be misused for form-state, but the `document_type` CHECK constraint limits values to `'coi', 'safety_equipment', 'safety_construction', 'safety_radio', 'isps', 'ism', 'other'` and is vessel-scoped (forms are user-scoped, not vessel-scoped, since they represent the mariner's application). Wrong shape.

- **`user_credentials`** ([`0035_create_user_credentials.py`](apps/api/alembic/versions/0035_create_user_credentials.py)) — stores mariner credentials with expiry dates and reminder flags. Again wrong shape; credentials are *the thing being applied for*, not the application itself.

- **`compliance_logs`** ([`0036_create_compliance_logs.py`](apps/api/alembic/versions/0036_create_compliance_logs.py)) — audit-log style, not suitable for editable drafts.

**A new `form_drafts` table will be required.** Minimum shape:

```sql
CREATE TABLE form_drafts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    form_type   TEXT NOT NULL CHECK (form_type IN (
                    'cg_719b', 'cg_719c', 'cg_719k', 'cg_719ke',
                    'cg_719p', 'cg_719s', 'checklist_*'
                )),
    field_data  JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'submitted_offline', 'archived')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_form_drafts_user ON form_drafts(user_id);
```

Optionally index `(user_id, form_type)` and add a soft-delete column. Standard migration — no tricky joins.

### 3.5 Scope estimates

**v1 — "download the form":** ~1 session.
- Real PDFs re-downloaded and stored at `apps/api/static/forms/` (or served via nginx directly).
- New router `apps/api/app/routers/forms.py` with `GET /forms/{form_code}` returning `FileResponse`.
- Frontend: add a "Forms" page at `/forms` listing the 7-ish forms with download buttons, each triggering the new endpoint.
- No DB changes. No form filling. No draft persistence.

**v2 — "fill in-app, save draft, export filled PDF":** ~4–6 sessions (assuming AcroForms; add 2–3 if scans).
- `form_drafts` migration + CRUD endpoints (1 session).
- Field-schema JSON per form — mapping AcroForm field names to human-friendly labels, types, validation rules (1 session per ~2 forms; the CG-719B alone has ~40 fields).
- Filling backend: add `pypdf` dependency, `POST /forms/{form_code}/render` endpoint that takes the draft's `field_data`, calls `update_page_form_field_values()`, streams the filled PDF (1 session).
- Frontend form UI: one page per form, auto-save draft every N seconds, pre-fill from user profile + active vessel's `vessels` row + most recent COI extraction (1–2 sessions for the framework; 0.5 per additional form once the framework is stable).
- Validation for NMC submittal requirements (what fields are required, what formats match NMC expectations) — domain-heavy, probably a Karynn interview to enumerate (0.5 session).

Both estimates assume the real PDFs exist and AcroForm turns out to be the case. Scanned-overlay adds ~50% to v2.

---

## Summary — what needs to happen before a build sprint

1. **Re-download the real NMC PDFs.** The 25 current files are URL placeholders (~60–220 bytes each, containing only the URL to the actual PDF). The script in §2.3 is a starting point; Akamai WAF may require manual browser downloads for some.
2. **Run the VPS queries in §1.3** to confirm current NVIC ingest state and whether NVIC 04-08 is present.
3. **Run the VPS discovery + curl tests in §1.4** to determine whether NVICs are Akamai-blocked from the VPS or working.
4. **Fix the latent `nmc_memo` dispatch bug** in [`cli.py:352-381`](packages/ingest/ingest/cli.py:352) (missing `discover_and_download` / `get_source_date` functions in [`nmc_memo.py`](packages/ingest/ingest/sources/nmc_memo.py)) — either add those functions or register a new PDF-directory-only dispatch pattern in `cli.py`.
5. **Future migration 0044** to add `nmc_policy` + `nmc_checklist` to `regulations_source_check` AND to fix the `ism_supplement` gap in migration 0042's downgrade path.
6. **Verify AcroForm status** on the real CG-719 PDFs using the pypdf script in §3.3 before committing to v2 of the forms product.
