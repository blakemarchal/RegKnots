"""Sprint D6.88 Phase 3.5 — split MARPOL chapter-level rows into regulation-level rows.

The MARPOL corpus has 80 sections at chapter / appendix granularity
(e.g., 'MARPOL Annex VI Ch.3', 'MARPOL Annex I App.III'). The model
cites regulations directly ('MARPOL Annex VI Regulation 14.1') —
chip clicks miss because the regulation isn't a distinct row.

This script:
  1. Reads every chapter-level MARPOL chunk grouped by parent
  2. Reconstructs full_text per parent
  3. Splits on 'Regulation N\\n*Title*' markers
  4. Embeds each child via OpenAI text-embedding-3-small with
     tiktoken-precise token truncation
  5. Inserts as new rows with parent_section_id linking to the
     parent chapter chunk

Parents NOT modified or deleted — broad annex/chapter queries
still get the full chapter context; specific regulation queries
now find the right regulation. Same hierarchical retrieval pattern
as SOLAS Phase 2.

Skipped sections (no useful regulation-level structure):
  Anything matching 'MARPOL Annex .* App.*' (appendices)
  Anything matching 'MARPOL Annex .* UI.*'  (unified interpretations)
  'MARPOL Amendments .*'                    (already resolution-level)
  'MARPOL Additional Information .*'

Usage:
    uv run --with asyncpg --with openai --with python-dotenv --with tiktoken \\
      python scripts/split_marpol_to_regulations.py --dry-run
    uv run --with ... python scripts/split_marpol_to_regulations.py --apply
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
log = logging.getLogger("split_marpol")


SOURCE = "marpol"
EMBED_MODEL = "text-embedding-3-small"
EMBED_TOKEN_LIMIT = 8000
BATCH_SIZE = 32
EMBED_INPUT_CHAR_CAP = 24_000
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


# MARPOL regulation markers observed in production chunks:
#   "Regulation 12\n*Ozone-depleting substances*\n\n1   This regulation..."
#   "Regulation 14\nTanks for all residues (sludge)\n\n1   Unless..."
# Captures the regulation number + title on the next line. Title may
# be italicized with surrounding asterisks (markdown emphasis) which
# we strip.
_REG_HEADER_RE = re.compile(
    r"^Regulation\s+(\d+(?:-\d+)?)\s*\n\*?([^\n]+?)\*?\s*$",
    re.MULTILINE,
)

# Parents NOT to split. Anything that isn't a chapter-level annex
# regulation set — appendices have a different internal structure,
# UI documents are interpretive notes, amendments are resolution-
# level already. Conservative — better to skip than misparse.
_SKIP_RE = re.compile(
    r"(App|UI|UI App|Amendments|Additional Information|Articles)",
    re.IGNORECASE,
)

# Skip the marpol_amend and marpol_supplement sources entirely —
# they're already at resolution level (MEPC.XXX(YY) rows).
_SKIP_SOURCES = {"marpol_amend", "marpol_supplement"}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate_to_tokens(text: str, max_tokens: int = EMBED_TOKEN_LIMIT) -> tuple[str, bool]:
    tokens = _TOKENIZER.encode(text)
    if len(tokens) <= max_tokens:
        return text, False
    return _TOKENIZER.decode(tokens[:max_tokens]), True


def _child_section_number(parent: str, reg_number: str) -> str:
    """'MARPOL Annex VI Ch.3' + reg 12 -> 'MARPOL Annex VI Reg.12'.
    Strips the chapter suffix from the parent. Falls through to
    appending if the parent doesn't have a Ch. component."""
    if " Ch." in parent:
        annex = parent.rsplit(" Ch.", 1)[0]
        return f"{annex} Reg.{reg_number}"
    return f"{parent} Reg.{reg_number}"


def split_parent(
    parent_section_number: str,
    parent_full_text: str,
) -> list[tuple[str, str, str]]:
    matches = list(_REG_HEADER_RE.finditer(parent_full_text))
    if not matches:
        return []

    children: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        reg_number = m.group(1)
        reg_title = m.group(2).strip().strip("*").strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(parent_full_text)
        body = parent_full_text[body_start:body_end].strip()
        if not body:
            continue
        child_sn = _child_section_number(parent_section_number, reg_number)
        child_text = f"[{child_sn}] {reg_title}\n\n{body}"
        children.append((child_sn, reg_title[:200], child_text))
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
    parser.add_argument("--parent", type=str, default=None)
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("must pass --dry-run or --apply")

    conn = await _get_db()
    try:
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
        log.info(f"loaded {len(rows)} marpol rows across {len({r['section_number'] for r in rows})} sections")

        by_parent: dict[str, list[asyncpg.Record]] = {}
        for r in rows:
            by_parent.setdefault(r["section_number"], []).append(r)

        all_children: list[dict] = []
        skipped: list[str] = []
        for parent_sn, parent_rows in by_parent.items():
            if _SKIP_RE.search(parent_sn):
                skipped.append(parent_sn)
                continue
            full = "\n\n".join(r["full_text"] for r in parent_rows if r["full_text"])
            children = split_parent(parent_sn, full)
            if not children:
                log.debug(f"  {parent_sn}: 0 children (no regulation markers)")
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
        if skipped:
            log.info(f"skipped sections (no regulation structure): {len(skipped)}")
            for s in skipped[:8]:
                log.info(f"  - {s}")

        # Internal dedup: same regulation can appear under different
        # parent chapters if MARPOL cross-references it. Merge texts.
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

        # Skip rows already in DB
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
            log.info(f"  ({truncated_count} truncated to {EMBED_TOKEN_LIMIT} tokens for embed)")

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
        log.info(f"inserted {len(fresh)} child regulations.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
