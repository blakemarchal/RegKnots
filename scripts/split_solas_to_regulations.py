"""Sprint D6.88 Phase 2 — split SOLAS parent chunks into regulation-level rows.

The SOLAS corpus is ingested at the Chapter > Part level (e.g.,
'SOLAS Ch.II-2 Part A'). Each parent row contains 5-10 distinct
regulations marked inline with 'Regulation N Title\\nGo to section...'
headers. The model cites regulations directly ('SOLAS Ch.II-2 Reg.19')
and chip clicks fail because the granular regulation isn't a row.

This script:
  1. Reads every SOLAS chunk grouped by section_number
  2. Reconstructs full_text per parent by concatenating chunks
  3. Splits each parent on 'Regulation N Title' headers
  4. Embeds each child via OpenAI text-embedding-3-small
  5. Inserts children as new rows with parent_section_id linking
     to one of the parent's chunks (so hierarchical retrieval can
     surface broader context when needed)

Parent rows are NOT modified or deleted — they remain available for
broad-scope queries. The model's reranker can decide which to favor.

Idempotency: child content_hash is sha256 of the rendered child text.
Re-running produces identical hashes; we skip rows that already exist.

Usage:
    uv run --with asyncpg --with openai python scripts/split_solas_to_regulations.py --dry-run
    uv run --with asyncpg --with openai python scripts/split_solas_to_regulations.py --apply
    uv run --with asyncpg --with openai python scripts/split_solas_to_regulations.py --apply --parent "SOLAS Ch.II-2 Part A"  (single parent)

Connection:
    DATABASE_URL env var. Defaults to REGKNOTS_DATABASE_URL if set, then to
    postgres://... assembled from individual REGKNOTS_* vars, then local.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sys
import uuid
from collections.abc import Iterable
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "ingest"))

import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("split_solas")


SOURCE = "solas"
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 32
# text-embedding-3-small caps at 8192 tokens. Some SOLAS regulations
# (Ch.V Reg.19, Ch.II-2 Reg.10, etc.) exceed that when fully assembled.
# We cap the embedding INPUT to a conservative ~6000 tokens (≈ 24K
# chars) so every regulation embeds in a single call. The full_text
# stored in DB stays intact; truncation affects retrieval relevance
# only, and the top of a regulation (where 'Application' + the first
# requirements live) is what the embedding most needs.
EMBED_INPUT_CHAR_CAP = 24_000

# Regulation header pattern observed in production chunks:
#   "Regulation 11 Application\nGo to section...\n"
#   "Regulation 4 General\nGo to section...\n"
# Captures the regulation number + title. The 'Go to section...' line
# is a paste-from-PDF artifact that consistently follows each header.
_REG_HEADER_RE = re.compile(
    r"^Regulation\s+(\d+(?:-\d+)?)\s+(.+?)\s*\nGo to section\.\.\.\s*\n",
    re.MULTILINE,
)


def _child_section_number(parent: str, reg_number: str) -> str:
    """Build the child section_number from parent + regulation N.

    'SOLAS Ch.II-2 Part A'  + reg 11  ->  'SOLAS Ch.II-2 Reg.11'
    'SOLAS Ch.II-1 Part B-1' + reg 5  ->  'SOLAS Ch.II-1 Reg.5'
    'SOLAS Ch.III' (no Part) + reg 1  ->  'SOLAS Ch.III Reg.1'
    'SOLAS Annex 1'         + reg 1  ->  'SOLAS Annex 1 Reg.1'
    """
    if " Part " in parent:
        chapter = parent.rsplit(" Part ", 1)[0]
        return f"{chapter} Reg.{reg_number}"
    return f"{parent} Reg.{reg_number}"


def split_parent(
    parent_section_number: str,
    parent_full_text: str,
) -> list[tuple[str, str, str]]:
    """Split a concatenated parent text into regulation-level children.

    Returns: list of (child_section_number, child_section_title, child_full_text).
    """
    matches = list(_REG_HEADER_RE.finditer(parent_full_text))
    if not matches:
        return []

    children: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        reg_number = m.group(1)
        reg_title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(parent_full_text)
        body = parent_full_text[body_start:body_end].strip()
        if not body:
            continue

        child_sn = _child_section_number(parent_section_number, reg_number)
        # Render the child with the same header convention parents use,
        # so downstream retrieval and citation extraction see a
        # consistent shape.
        child_text = f"[{child_sn}] {reg_title}\n\n{body}"
        children.append((child_sn, reg_title, child_text))

    return children


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _get_db() -> asyncpg.Connection:
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("REGKNOTS_DATABASE_URL")
    )
    if not url:
        raise SystemExit(
            "DATABASE_URL or REGKNOTS_DATABASE_URL must be set. Run via:\n"
            "  ssh root@68.183.130.3 \"cd /opt/RegKnots && "
            "DATABASE_URL=$(grep DATABASE_URL .env | head -1 | cut -d= -f2) "
            "uv run ... \""
        )
    # asyncpg doesn't accept the +driver suffix from SQLAlchemy URLs
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


async def _embed_batch(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a batch with simple retry on rate limit."""
    for attempt in range(5):
        try:
            resp = await client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as exc:
            if attempt == 4:
                raise
            wait = 3 * (2 ** attempt)
            log.warning(f"embed retry {attempt + 1}/5 ({type(exc).__name__}): waiting {wait}s")
            await asyncio.sleep(wait)
    raise RuntimeError("unreachable")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Plan + count, no DB writes, no OpenAI calls.")
    parser.add_argument("--apply", action="store_true", help="Write children to DB after embedding.")
    parser.add_argument("--parent", type=str, default=None, help="Limit to a single parent section_number.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("must pass either --dry-run or --apply")
    if args.verbose:
        log.setLevel(logging.DEBUG)

    log.info("connecting to DB...")
    conn = await _get_db()
    try:
        # Pull existing SOLAS rows ordered for clean concatenation.
        if args.parent:
            rows = await conn.fetch(
                """
                SELECT id, section_number, section_title, chunk_index, full_text,
                       effective_date, up_to_date_as_of, source_version, title
                FROM regulations
                WHERE source = $1 AND section_number = $2
                ORDER BY chunk_index
                """,
                SOURCE, args.parent,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, section_number, section_title, chunk_index, full_text,
                       effective_date, up_to_date_as_of, source_version, title
                FROM regulations
                WHERE source = $1
                ORDER BY section_number, chunk_index
                """,
                SOURCE,
            )
        log.info(f"loaded {len(rows)} solas rows across {len({r['section_number'] for r in rows})} sections")

        # Group by parent section_number, reconstruct full text in chunk order.
        by_parent: dict[str, list[asyncpg.Record]] = {}
        for r in rows:
            by_parent.setdefault(r["section_number"], []).append(r)

        # Build children per parent.
        all_children: list[dict] = []
        for parent_sn, parent_rows in by_parent.items():
            full = "\n\n".join(r["full_text"] for r in parent_rows if r["full_text"])
            children = split_parent(parent_sn, full)
            if not children:
                log.debug(f"  {parent_sn}: 0 children (no Regulation N headers)")
                continue
            log.info(f"  {parent_sn}: {len(children)} children")
            # Use the first chunk of the parent as the parent_section_id anchor.
            parent_anchor_id = parent_rows[0]["id"]
            for child_sn, child_title, child_text in children:
                all_children.append({
                    "parent_id": parent_anchor_id,
                    "parent_section_number": parent_sn,
                    "section_number": child_sn,
                    "section_title": child_title,
                    "full_text": child_text,
                    "content_hash": _content_hash(child_text),
                    "title": parent_rows[0]["title"],
                    "source_version": parent_rows[0]["source_version"],
                    "effective_date": parent_rows[0]["effective_date"],
                    "up_to_date_as_of": parent_rows[0]["up_to_date_as_of"],
                })

        log.info(f"total children candidates: {len(all_children)}")

        # Internal dedup: different parent Parts can produce children
        # with the same section_number (e.g., 'SOLAS Ch.II-1 Part A'
        # → 'SOLAS Ch.II-1 Reg.1' and 'SOLAS Ch.II-1 Part A-1' →
        # 'SOLAS Ch.II-1 Reg.1' if both Parts have a Reg.1). Merge by
        # concatenating texts so we preserve all content under the
        # canonical child section_number. Recompute the content_hash
        # after merging.
        merged: dict[str, dict] = {}
        merged_count = 0
        for c in all_children:
            sn = c["section_number"]
            if sn in merged:
                merged_count += 1
                merged[sn]["full_text"] += "\n\n" + c["full_text"]
                merged[sn]["content_hash"] = _content_hash(merged[sn]["full_text"])
            else:
                merged[sn] = c
        if merged_count:
            log.info(f"merged {merged_count} duplicate-section_number candidates")
        all_children = list(merged.values())
        log.info(f"after internal dedup: {len(all_children)} unique children")

        if not all_children:
            log.info("nothing to insert.")
            return 0

        # Skip rows that already exist by content_hash.
        existing_hashes = {
            r["content_hash"]
            for r in await conn.fetch(
                "SELECT content_hash FROM regulations WHERE source = $1 AND content_hash = ANY($2::text[])",
                SOURCE, [c["content_hash"] for c in all_children],
            )
        }
        fresh = [c for c in all_children if c["content_hash"] not in existing_hashes]
        log.info(f"already-ingested by hash: {len(all_children) - len(fresh)}; new to ingest: {len(fresh)}")

        # Skip rows that already exist by (source, section_number) — defensive,
        # in case a previous run produced the same section_number with slightly
        # different text. Prefer to not double-insert.
        if fresh:
            existing_sns = {
                r["section_number"]
                for r in await conn.fetch(
                    "SELECT DISTINCT section_number FROM regulations "
                    "WHERE source = $1 AND section_number = ANY($2::text[])",
                    SOURCE, [c["section_number"] for c in fresh],
                )
            }
            fresh_no_dupes = [c for c in fresh if c["section_number"] not in existing_sns]
            log.info(
                f"already-present by section_number (would have collided): "
                f"{len(fresh) - len(fresh_no_dupes)}; final to ingest: {len(fresh_no_dupes)}"
            )
            fresh = fresh_no_dupes

        # Sample preview
        for c in fresh[:3]:
            preview = c["full_text"][:200].replace("\n", " ")
            log.info(f"  [{c['section_number']}] {c['section_title'][:60]}  -- {preview}...")

        if args.dry_run:
            log.info("dry-run complete; no embedding, no writes.")
            return 0

        # Embed in batches.
        oa_key = os.environ.get("OPENAI_API_KEY", "")
        if not oa_key:
            log.error("OPENAI_API_KEY not set; cannot embed.")
            return 2
        client = AsyncOpenAI(api_key=oa_key)
        log.info(f"embedding {len(fresh)} children in batches of {BATCH_SIZE}...")
        embeddings: list[list[float]] = []
        truncated_count = 0
        for i in range(0, len(fresh), BATCH_SIZE):
            batch = fresh[i : i + BATCH_SIZE]
            # Cap each input to keep under text-embedding-3-small's 8192-token limit.
            inputs = []
            for b in batch:
                txt = b["full_text"]
                if len(txt) > EMBED_INPUT_CHAR_CAP:
                    truncated_count += 1
                    txt = txt[:EMBED_INPUT_CHAR_CAP]
                inputs.append(txt)
            vecs = await _embed_batch(client, inputs)
            embeddings.extend(vecs)
            log.info(f"  batch {i // BATCH_SIZE + 1}/{(len(fresh) + BATCH_SIZE - 1) // BATCH_SIZE} done")
        if truncated_count:
            log.info(f"  ({truncated_count} children had their embedding-input truncated to {EMBED_INPUT_CHAR_CAP} chars; full_text intact in DB)")
        await client.close()

        assert len(embeddings) == len(fresh), "embed count mismatch"

        # Insert in a single transaction so a mid-run failure doesn't
        # leave the corpus half-updated. pgvector accepts the embedding
        # as a literal string '[1.234, ...]' through the asyncpg driver
        # without explicit type registration.
        log.info("opening transaction + inserting...")
        async with conn.transaction():
            for c, emb in zip(fresh, embeddings):
                vec_literal = "[" + ",".join(f"{x:.7f}" for x in emb) + "]"
                await conn.execute(
                    """
                    INSERT INTO regulations (
                        source, source_version, title, section_number, section_title,
                        full_text, chunk_index, parent_section_id,
                        effective_date, up_to_date_as_of, embedding, content_hash,
                        jurisdictions, language
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector, $12, $13, $14)
                    """,
                    SOURCE,
                    c["source_version"],
                    c["title"],
                    c["section_number"],
                    c["section_title"][:500],
                    c["full_text"],
                    0,  # chunk_index — children are single-chunk for now
                    c["parent_id"],
                    c["effective_date"],
                    c["up_to_date_as_of"],
                    vec_literal,
                    c["content_hash"],
                    ["intl"],  # SOLAS is the international convention
                    "en",
                )
        log.info(f"inserted {len(fresh)} child regulations.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
