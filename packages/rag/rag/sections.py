"""Whole-section reading (2026-10-08, answer pipeline phase 1).

Retrieval ranks chunks, so the answer model used to read regulations in pieces:
on 2026-10-09 the Captain asked about "SOLAS ch v reg 23", the regulation's 4
chunks came back as 3, and the answer told her paragraphs 4-6 "did not surface"
(they were in chunk 3, in the database). Retrieval still decides WHICH sections
matter; this module decides what the model READS: every chunk of each selected
section, in document order, within a token budget.

  - Sections keep their retrieval rank (best section first); chunks within a
    section are in chunk_index order.
  - A section the user named (an identifier in the question) is read in full
    up to NAMED_SECTION_TOKENS and goes first, even if retrieval missed it.
  - Any other section is read in full when it fits SECTION_TOKENS; a longer one
    keeps its retrieved chunks plus their immediate neighbours.
  - Every retrieved chunk is reserved first, so siblings never push a retrieved
    chunk out; siblings fill the rest of the budget in section order.
  - Fail-open: any error returns the retrieved chunks unchanged.

Siblings carry their section's best similarity (downstream reads chunks[0]
similarity as the top cosine) and `_expanded: True`.
"""
from __future__ import annotations

import logging

import tiktoken

logger = logging.getLogger(__name__)

_ENCODER = tiktoken.get_encoding("cl100k_base")

CONTEXT_TOKENS = 20_000        # regulation text the answer model reads (was 6,000 of loose chunks)
SECTION_TOKENS = 4_000         # read a section whole when it fits this
NAMED_SECTION_TOKENS = 10_000  # a section the user named
_MAX_SECTION_CHUNKS = 60       # don't fetch a giant section whole (one has 1,554 chunks)


_HEADER_TOKENS = 40            # build_context's "[SOURCE: … — …] [tier]" line per chunk


def _tokens(text: str) -> int:
    return len(_ENCODER.encode(text or "")) + _HEADER_TOKENS


def named_sections(query: str) -> list[str]:
    """Section numbers the user's question names (the retriever's identifier parse)."""
    from rag.retriever import _extract_identifiers
    seen: list[str] = []
    for ident in _extract_identifiers(query or ""):
        sec = ident.get("section_number")
        if sec and sec not in seen:
            seen.append(sec)
    return seen


async def expand_sections(pool, chunks: list[dict], query: str,
                          budget: int = CONTEXT_TOKENS) -> list[dict]:
    try:
        return await _expand(pool, chunks, query, budget)
    except Exception as exc:  # noqa: BLE001 — never fail the answer over this
        logger.warning("whole-section reading skipped: %s: %s", type(exc).__name__, str(exc)[:200])
        return chunks


async def _expand(pool, chunks: list[dict], query: str, budget: int) -> list[dict]:
    named = named_sections(query)
    # Section order: named sections first, then retrieval rank.
    order: list[tuple[str, str]] = []
    best_sim: dict[tuple[str, str], float] = {}
    retrieved_ids: set = set()
    for c in chunks:
        key = (c.get("source") or "", c.get("section_number") or "")
        if not key[1]:
            continue
        retrieved_ids.add(c.get("id"))
        if key not in best_sim:
            order.append(key)
            best_sim[key] = float(c.get("similarity") or 0.0)
        else:
            best_sim[key] = max(best_sim[key], float(c.get("similarity") or 0.0))

    named_keys: list[tuple[str, str]] = []
    if named:
        rows = await pool.fetch(
            "SELECT DISTINCT source, section_number FROM regulations WHERE section_number = ANY($1::text[])",
            named,
        )
        named_keys = [(r["source"], r["section_number"]) for r in rows]
        for k in named_keys:
            best_sim.setdefault(k, max(best_sim.values(), default=0.0))
        order = named_keys + [k for k in order if k not in named_keys]
    if not order:
        return chunks

    sizes = await pool.fetch(
        """
        SELECT source, section_number, count(*) AS n
        FROM regulations
        WHERE (source, section_number) IN (SELECT * FROM unnest($1::text[], $2::text[]))
        GROUP BY 1, 2
        """,
        [k[0] for k in order], [k[1] for k in order],
    )
    n_chunks = {(r["source"], r["section_number"]): r["n"] for r in sizes}
    fetch_whole = [k for k in order if n_chunks.get(k, 0) <= _MAX_SECTION_CHUNKS]
    rows = await pool.fetch(
        """
        SELECT id, source, section_number, section_title, full_text, chunk_index
        FROM regulations
        WHERE (source, section_number) IN (SELECT * FROM unnest($1::text[], $2::text[]))
        ORDER BY source, section_number, chunk_index
        """,
        [k[0] for k in fetch_whole], [k[1] for k in fetch_whole],
    )
    by_section: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_section.setdefault((r["source"], r["section_number"]), []).append(dict(r))

    # Retrieved chunks of a giant section stay as retrieved.
    retrieved_by_section: dict[tuple[str, str], list[dict]] = {}
    for c in chunks:
        retrieved_by_section.setdefault((c.get("source") or "", c.get("section_number") or ""), []).append(c)

    # Which chunks of each section to read.
    plan: dict[tuple[str, str], list[dict]] = {}
    for key in order:
        all_rows = by_section.get(key)
        mine = retrieved_by_section.get(key, [])
        if not all_rows:
            plan[key] = mine
            continue
        cap = NAMED_SECTION_TOKENS if key in named_keys else SECTION_TOKENS
        if sum(_tokens(r["full_text"]) for r in all_rows) <= cap:
            plan[key] = all_rows
            continue
        # Too long to read whole: retrieved chunks plus their neighbours (a named
        # section that retrieval missed: its opening chunks).
        idx = {r["id"]: i for i, r in enumerate(all_rows)}
        keep = {j for c in mine if c.get("id") in idx for j in (idx[c["id"]] - 1, idx[c["id"]], idx[c["id"]] + 1)}
        if not keep:
            keep = set(range(min(3, len(all_rows))))
        plan[key] = [all_rows[i] for i in sorted(k for k in keep if 0 <= k < len(all_rows))]

    # Reserve every retrieved chunk first, then add siblings in section order.
    used = sum(_tokens(c.get("full_text") or "") for c in chunks)
    chosen: dict[tuple[str, str], set] = {k: {c.get("id") for c in retrieved_by_section.get(k, [])} for k in order}
    for key in order:
        for r in plan[key]:
            if r["id"] in chosen[key]:
                continue
            t = _tokens(r["full_text"])
            if used + t > budget:
                continue
            chosen[key].add(r["id"])
            used += t

    out: list[dict] = []
    added = 0
    for key in order:
        rows_for_key = by_section.get(key) or retrieved_by_section.get(key, [])
        mine = {c.get("id"): c for c in retrieved_by_section.get(key, [])}
        for r in rows_for_key:
            if r["id"] not in chosen[key]:
                continue
            if r["id"] in mine:
                out.append(mine[r["id"]])
            else:
                out.append({**r, "similarity": best_sim.get(key, 0.0), "_expanded": True})
                added += 1
    # Retrieved chunks without a section number keep their place at the end.
    out += [c for c in chunks if not c.get("section_number")]
    logger.info("whole-section reading: %d sections, %d chunks retrieved, %d added (%d named)",
                len(order), len(chunks), added, len(named_keys))
    return out
