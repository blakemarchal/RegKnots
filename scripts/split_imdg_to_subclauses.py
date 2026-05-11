"""Sprint D6.88 Phase 3 — split IMDG chapter-level rows into sub-clause children.

IMDG today has 87 chapter-level sections (e.g., 'IMDG 7.4') with up
to 477 chunks per section. Citing 'IMDG 7.4.3.2' (segregation table
for containerships with closed cargo holds) and clicking the chip
pulls the entire chapter — a 100K+ char wall.

This script:
  1. For every IMDG chapter-level row (section_number like 'IMDG N.N')
  2. Reconstructs the chapter's full_text by concatenating chunks
  3. Splits on N.N.N or N.N.N.N sub-clause markers
  4. Embeds each child via OpenAI text-embedding-3-small
  5. Inserts as new rows with parent_section_id linking to the parent

Sub-clauses below level 3 stay in their parent row (i.e., text inside
a 7.4.3 sub-clause is kept whole; we don't split 7.4.3.1, 7.4.3.2 as
separate rows by default because the granularity goal is the
addressed level the model cites). To split deeper (level 4), pass
--max-depth 4.

Sections that have no sub-clause markers (e.g., 'IMDG Foreword',
'IMDG Index', 'IMDG 3.2' which is a UN-number list) are SKIPPED —
they don't have a hierarchical structure to split on.

Usage:
    ssh root@VPS — DATABASE_URL + OPENAI_API_KEY from /opt/RegKnots/.env
    uv run --with asyncpg --with openai --with python-dotenv \\
      python scripts/split_imdg_to_subclauses.py --dry-run
    uv run --with asyncpg --with openai --with python-dotenv \\
      python scripts/split_imdg_to_subclauses.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "ingest"))

import asyncpg
import tiktoken
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("split_imdg")


SOURCE = "imdg"
EMBED_MODEL = "text-embedding-3-small"
EMBED_TOKEN_LIMIT = 8000  # text-embedding-3-small caps at 8192; leave margin
BATCH_SIZE = 32
# Char-based cap as a coarse pre-filter before we run the precise
# token-count via tiktoken. Anything under this is almost certainly
# fine; anything over gets tokenized + truncated by token count.
EMBED_INPUT_CHAR_CAP = 24_000

# Reused tokenizer for text-embedding-3-small (cl100k_base).
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


def _truncate_to_tokens(text: str, max_tokens: int = EMBED_TOKEN_LIMIT) -> tuple[str, bool]:
    """Return (text-or-truncated, did_truncate). Uses tiktoken for
    precise count — IMDG segregation tables tokenize at ~2 chars/token
    so the char-based cap consistently underestimated."""
    tokens = _TOKENIZER.encode(text)
    if len(tokens) <= max_tokens:
        return text, False
    truncated_tokens = tokens[:max_tokens]
    return _TOKENIZER.decode(truncated_tokens), True

# Sub-clause markers: 7.4.3.2, 6.2.1.1, 4.1.4.4, etc.
# Captured at the start of a line, requiring at least 3 numeric parts
# (so we don't match the chapter-level 7.4 itself). Optional 4th level.
# The marker is followed by a description / title — we capture up to
# 80 chars to use as the section_title.
_SUBCLAUSE_RE = re.compile(
    r"^(\d+\.\d+\.\d+(?:\.\d+)?)\s+([A-Z][^\n]{0,150}?)\s*$",
    re.MULTILINE,
)

# Sections that have no useful sub-structure to split. UN-list sections,
# alphabetical indexes, etc.
_SKIP_SECTIONS = {
    "IMDG Foreword",
    "IMDG Index",
    "IMDG 3.2",         # Dangerous Goods List — each UN already its own chunk
    "IMDG App.A",       # Generic name list
    "IMDG App.B",       # Special provisions list
}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _child_section_number(parent: str, marker: str, max_depth: int) -> str:
    """Build the child section_number. parent='IMDG 7.4', marker='7.4.3.2'
    -> child 'IMDG 7.4.3.2'. If max_depth=3, '7.4.3.2' truncates to '7.4.3'.
    """
    parts = marker.split(".")
    truncated = ".".join(parts[:max_depth])
    return f"IMDG {truncated}"


def split_parent(
    parent_section_number: str,
    parent_full_text: str,
    max_depth: int,
) -> list[tuple[str, str, str]]:
    """Split a chapter-level IMDG text into sub-clause children.

    Returns: list of (child_section_number, child_section_title,
    child_full_text). Duplicates by child_section_number are merged
    by the caller.
    """
    matches = list(_SUBCLAUSE_RE.finditer(parent_full_text))
    if not matches:
        return []

    children: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        marker = m.group(1)
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(parent_full_text)
        body = parent_full_text[body_start:body_end].strip()
        if not body:
            continue
        child_sn = _child_section_number(parent_section_number, marker, max_depth)
        # Header convention matches the parents'
        child_text = f"[{child_sn}] {title}\n\n{body}"
        children.append((child_sn, title[:200], child_text))

    return children


async def _get_db() -> asyncpg.Connection:
    url = os.environ.get("DATABASE_URL") or os.environ.get("REGKNOTS_DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL or REGKNOTS_DATABASE_URL must be set.")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


async def _embed_batch(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-depth", type=int, default=4,
                        help="Max sub-clause depth (3 or 4). Default 4 (7.4.3.2-level).")
    parser.add_argument("--parent", type=str, default=None,
                        help="Limit to a single parent section_number.")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("must pass --dry-run or --apply")
    if args.max_depth not in (3, 4):
        parser.error("--max-depth must be 3 or 4")

    conn = await _get_db()
    try:
        # Load all IMDG rows.
        if args.parent:
            rows = await conn.fetch(
                """SELECT id, section_number, section_title, chunk_index, full_text,
                          effective_date, up_to_date_as_of, source_version, title
                   FROM regulations
                   WHERE source = $1 AND section_number = $2
                   ORDER BY chunk_index""",
                SOURCE, args.parent,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, section_number, section_title, chunk_index, full_text,
                          effective_date, up_to_date_as_of, source_version, title
                   FROM regulations WHERE source = $1
                   ORDER BY section_number, chunk_index""",
                SOURCE,
            )
        log.info(f"loaded {len(rows)} imdg rows across {len({r['section_number'] for r in rows})} sections")

        by_parent: dict[str, list[asyncpg.Record]] = {}
        for r in rows:
            by_parent.setdefault(r["section_number"], []).append(r)

        all_children: list[dict] = []
        skipped: list[str] = []
        for parent_sn, parent_rows in by_parent.items():
            if parent_sn in _SKIP_SECTIONS:
                skipped.append(parent_sn)
                continue
            full = "\n\n".join(r["full_text"] for r in parent_rows if r["full_text"])
            children = split_parent(parent_sn, full, args.max_depth)
            if not children:
                log.debug(f"  {parent_sn}: 0 children (no sub-clause markers)")
                continue
            log.info(f"  {parent_sn}: {len(children)} children")
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
        log.info(f"skipped sections (no useful sub-structure): {len(skipped)} ({skipped})")

        # Internal dedup by section_number — same child can appear across
        # parent boundaries (e.g., a 7.4.3 marker in a cross-reference).
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

        # Skip sections already present in DB (idempotency).
        existing_sns = {
            r["section_number"]
            for r in await conn.fetch(
                "SELECT DISTINCT section_number FROM regulations "
                "WHERE source = $1 AND section_number = ANY($2::text[])",
                SOURCE, [c["section_number"] for c in all_children],
            )
        }
        fresh = [c for c in all_children if c["section_number"] not in existing_sns]
        log.info(f"already-present in DB: {len(all_children) - len(fresh)}; new to ingest: {len(fresh)}")

        # Sample preview
        for c in fresh[:5]:
            preview = c["full_text"][:200].replace("\n", " ")
            log.info(f"  [{c['section_number']}] {c['section_title'][:60]}  -- {preview}...")

        if args.dry_run:
            log.info("dry-run complete; no embedding, no writes.")
            return 0

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
            inputs = []
            for b in batch:
                txt = b["full_text"]
                # Char-cap pre-filter, then precise token-count truncation
                # for anything that survived. Two-pass avoids tokenizing
                # every short input.
                if len(txt) > EMBED_INPUT_CHAR_CAP:
                    txt = txt[:EMBED_INPUT_CHAR_CAP]
                txt, did_trunc = _truncate_to_tokens(txt)
                if did_trunc:
                    truncated_count += 1
                inputs.append(txt)
            vecs = await _embed_batch(client, inputs)
            embeddings.extend(vecs)
            log.info(f"  batch {i // BATCH_SIZE + 1}/{(len(fresh) + BATCH_SIZE - 1) // BATCH_SIZE} done")
        await client.close()
        if truncated_count:
            log.info(f"  ({truncated_count} children truncated to {EMBED_TOKEN_LIMIT} tokens for embed; full_text intact in DB)")

        assert len(embeddings) == len(fresh)
        log.info("opening transaction + inserting...")
        async with conn.transaction():
            for c, emb in zip(fresh, embeddings):
                vec_literal = "[" + ",".join(f"{x:.7f}" for x in emb) + "]"
                await conn.execute(
                    """INSERT INTO regulations (
                        source, source_version, title, section_number, section_title,
                        full_text, chunk_index, parent_section_id,
                        effective_date, up_to_date_as_of, embedding, content_hash,
                        jurisdictions, language
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::vector,$12,$13,$14)""",
                    SOURCE, c["source_version"], c["title"],
                    c["section_number"], c["section_title"][:500],
                    c["full_text"], 0, c["parent_id"],
                    c["effective_date"], c["up_to_date_as_of"],
                    vec_literal, c["content_hash"],
                    ["intl"], "en",
                )
        log.info(f"inserted {len(fresh)} child sub-clauses.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
