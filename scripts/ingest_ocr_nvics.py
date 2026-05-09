"""Ingest OCR'd NVIC text files into the regulations table.

After scripts/ocr_scanned_nvics.py writes data/ocr/nvic/{nid}.txt for
each scanned NVIC PDF, this script:

  1. Reads each .txt file.
  2. Parses sections using the same regex the canonical NVIC adapter
     uses (top-level numbered sections "1. HEADING", "2. ACTION", etc.)
  3. Assembles Section objects with section_number "NVIC {nid} §{n}".
  4. Embeds + upserts via the same store layer the regular pipeline uses.

Why a separate script: the canonical packages/ingest/ingest/sources/nvic.py
adapter calls pdfplumber directly. Modifying it to fall through to a
sidecar .txt file would couple the OCR path to the PDF path. Cleaner
to keep them as two distinct ingest sources of truth for now.

Run on the VPS, after the OCR pass has finished:
  /root/.local/bin/uv run --project /opt/RegKnots/packages/ingest \\
      python /opt/RegKnots/scripts/ingest_ocr_nvics.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import date
from pathlib import Path

import asyncpg

REPO = Path("/opt/RegKnots")
OCR_DIR = REPO / "data" / "ocr" / "nvic"

logger = logging.getLogger("ingest_ocr_nvic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Same section-start pattern as packages/ingest/ingest/sources/nvic.py:
# "1. HEADING" — 1-2 digit number, period, space(s), then non-digit char.
# Negative lookahead prevents matching "1.1 Sub-section".
_SECTION_START = re.compile(r"^(\d{1,2})\.\s+(?!\d+\.)(\S.{1,})", re.MULTILINE)


def _split_into_sections(text: str, nid: str) -> list[tuple[str, str, str]]:
    """Split OCR'd NVIC text into (section_number, section_title, body).

    Mirrors the section detection in packages/ingest/ingest/sources/nvic.py
    so OCR'd NVICs match the structure of pdfplumber-parsed ones.
    """
    matches = list(_SECTION_START.finditer(text))
    if not matches:
        # No numbered sections found. Some short NVICs are single-section.
        return [(f"NVIC {nid}", f"NVIC {nid}", text.strip())]
    sections: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        n = m.group(1)
        title = m.group(2).strip().rstrip(".")[:200]
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < 50:
            continue
        sections.append((f"NVIC {nid} §{n}", title, body))
    return sections


async def _read_db_url() -> str:
    """Read DATABASE_URL from /opt/RegKnots/.env."""
    with (REPO / ".env").open() as f:
        for line in f:
            if line.startswith("REGKNOTS_DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
                # asyncpg wants postgresql:// not postgresql+asyncpg://
                return url.replace("postgresql+asyncpg://", "postgresql://")
    raise RuntimeError("REGKNOTS_DATABASE_URL not in /opt/RegKnots/.env")


async def _read_openai_key() -> str:
    with (REPO / ".env").open() as f:
        for line in f:
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENAI_API_KEY not in /opt/RegKnots/.env")


async def main(args: argparse.Namespace) -> int:
    if not OCR_DIR.exists():
        logger.error("No OCR directory at %s — run ocr_scanned_nvics.py first", OCR_DIR)
        return 2

    txt_files = sorted(OCR_DIR.glob("*.txt"))
    logger.info("found %d OCR'd .txt files", len(txt_files))

    # Group: which NVIC IDs do we have OCR text for?
    nids = [p.stem for p in txt_files]
    logger.info("OCR'd NVIC IDs: %s", ", ".join(nids[:10]) + ("…" if len(nids) > 10 else ""))

    # Skip if already in DB.
    db_url = await _read_db_url()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    rows = await pool.fetch(
        "SELECT DISTINCT section_number FROM regulations WHERE source = 'nvic'"
    )
    existing_section_numbers = {r["section_number"] for r in rows}
    existing_nids: set[str] = set()
    for sn in existing_section_numbers:
        m = re.match(r"^NVIC (\d+-\d+)", sn)
        if m:
            existing_nids.add(m.group(1))

    todo = [p for p in txt_files if p.stem not in existing_nids]
    logger.info("after dedup against DB: %d NVICs to ingest", len(todo))

    if args.dry_run or not todo:
        for p in todo[:10]:
            text = p.read_text(encoding="utf-8")
            sections = _split_into_sections(text, p.stem)
            logger.info("%s: %d sections, %d chars", p.stem, len(sections), len(text))
        await pool.close()
        return 0

    # Embedder: import lazily so module load doesn't require openai installed.
    sys.path.insert(0, str(REPO / "packages" / "ingest"))
    from ingest.embedder import EmbedderClient
    from ingest.chunker import chunk_section
    from ingest.models import Section
    from ingest import store

    openai_key = await _read_openai_key()
    embedder = EmbedderClient(api_key=openai_key)

    sections_total = 0
    chunks_total = 0
    embedded_total = 0
    today = date.today()

    for p in todo:
        nid = p.stem
        text = p.read_text(encoding="utf-8")
        parsed = _split_into_sections(text, nid)
        sections_total += len(parsed)

        section_objs: list[Section] = []
        for section_number, section_title, body in parsed:
            section_objs.append(Section(
                source="nvic", title_number=0,
                section_number=section_number,
                section_title=section_title,
                full_text=body,
                up_to_date_as_of=today,
                parent_section_number=f"NVIC {nid}",
                published_date=today,
            ))

        # Chunk + embed + store using the existing pipeline functions.
        all_chunks = []
        for s in section_objs:
            all_chunks.extend(chunk_section(s))
        chunks_total += len(all_chunks)

        if not all_chunks:
            logger.warning("%s: chunking produced 0 chunks, skipping", nid)
            continue

        # Embed batch
        try:
            embedded_chunks = await embedder.embed_chunks(all_chunks)
        except Exception as exc:
            logger.warning("%s: embedding failed — %s", nid, exc)
            continue

        # Store via upsert
        try:
            await store.upsert_chunks(pool, embedded_chunks)
            embedded_total += len(embedded_chunks)
            logger.info("%s: %d sections, %d chunks ingested", nid, len(parsed), len(embedded_chunks))
        except Exception as exc:
            logger.warning("%s: store failed — %s", nid, exc)
            continue

    logger.info(
        "DONE: %d NVICs processed, %d sections, %d chunks ingested",
        len(todo), sections_total, embedded_total,
    )

    # Rebuild HNSW index so the new chunks become searchable. Uses the
    # same REINDEX statement cli.py uses after a successful ingest.
    if embedded_total > 0:
        logger.info("rebuilding HNSW index (REINDEX INDEX idx_regulations_embedding) ...")
        async with pool.acquire() as conn:
            await conn.execute("REINDEX INDEX idx_regulations_embedding")
        logger.info("HNSW rebuilt.")

    await pool.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="preview only")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
