"""
Token-aware chunker for CFR regulation sections.

Strategy:
  1. If section fits in MAX_TOKENS → single chunk.
  2. Otherwise split by paragraphs (\\n\\n), then by sentences within
     long paragraphs.  A 50-token overlap window is prepended to each
     continuation chunk to preserve cross-boundary context.
  3. Last resort: token-level hard split for paragraphs > MAX_TOKENS
     with no sentence boundaries.

Each chunk_text is prefixed with "[{section_number}] {section_title}"
so every embedding is self-contained even when split across chunks.
"""

import hashlib
import re
from datetime import date

import tiktoken

from ingest.models import Chunk, Section

_ENCODER = tiktoken.get_encoding("cl100k_base")

MAX_TOKENS = 512
OVERLAP_TOKENS = 50


# ── Public API ───────────────────────────────────────────────────────────────

def chunk_section(section: Section) -> list[Chunk]:
    """Split a Section into ≤MAX_TOKENS chunks with OVERLAP_TOKENS overlap."""
    text = section.full_text.strip()
    if not text:
        return []

    header = _make_header(section)
    header_tokens = _count(header)

    # Available tokens for content after the header
    content_budget = MAX_TOKENS - header_tokens - 2  # 2 for "\n\n" separator

    if content_budget <= 0:
        # Header alone exceeds budget — emit a single chunk anyway
        return [_make_chunk(section, 0, header, text)]

    total_tokens = _count(text)
    if total_tokens <= content_budget:
        return [_make_chunk(section, 0, header, text)]

    units = _split_into_units(text, content_budget)
    return _pack_chunks(section, header, units, content_budget)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _make_header(section: Section) -> str:
    if section.section_title:
        return f"[{section.section_number}] {section.section_title}"
    return f"[{section.section_number}]"


def _make_chunk(section: Section, idx: int, header: str, content: str) -> Chunk:
    chunk_text = f"{header}\n\n{content}".strip()
    return Chunk(
        source=section.source,
        title_number=section.title_number,
        section_number=section.section_number,
        section_title=section.section_title,
        chunk_index=idx,
        chunk_text=chunk_text,
        content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        token_count=_count(chunk_text),
        up_to_date_as_of=section.up_to_date_as_of,
        parent_section_number=section.parent_section_number,
    )


def _count(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_into_units(text: str, budget: int) -> list[str]:
    """Split text into units that each fit within budget tokens."""
    paragraphs = [p.strip() for p in re.split(r"\n\n+|\n(?=\s*\()", text) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if _count(para) <= budget:
            units.append(para)
        else:
            units.extend(_split_sentences(para, budget))
    return units


def _split_sentences(text: str, budget: int) -> list[str]:
    """Split a long paragraph into sentence-boundary units."""
    # Split after sentence-ending punctuation followed by whitespace + capital
    # Avoids splitting "No. 1", "Sec. 1", "U.S.", "e.g.", "i.e."
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\(\"])", text)
    sentences = [s.strip() for s in raw if s.strip()]

    result: list[str] = []
    for sent in sentences:
        if _count(sent) <= budget:
            result.append(sent)
        else:
            # Hard split by tokens as last resort
            result.extend(_hard_split(sent, budget))
    return result


def _hard_split(text: str, budget: int) -> list[str]:
    """Token-level split when no sentence boundary is available."""
    token_ids = _ENCODER.encode(text)
    parts: list[str] = []
    for i in range(0, len(token_ids), budget):
        parts.append(_ENCODER.decode(token_ids[i : i + budget]))
    return [p for p in parts if p.strip()]


def _pack_chunks(
    section: Section, header: str, units: list[str], budget: int
) -> list[Chunk]:
    """Pack units into chunks respecting budget, with OVERLAP_TOKENS overlap."""
    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0
    chunk_idx = 0

    for unit in units:
        unit_tokens = _count(unit)

        if current_tokens + unit_tokens > budget and current:
            # Emit current chunk
            chunks.append(_make_chunk(section, chunk_idx, header, "\n\n".join(current)))
            chunk_idx += 1

            # Build overlap window from the tail of current
            overlap, overlap_tokens = _build_overlap(current)
            current = overlap
            current_tokens = overlap_tokens

        current.append(unit)
        current_tokens += unit_tokens

    if current:
        chunks.append(_make_chunk(section, chunk_idx, header, "\n\n".join(current)))

    return chunks


def _build_overlap(units: list[str]) -> tuple[list[str], int]:
    """Return the trailing units that together fit within OVERLAP_TOKENS."""
    overlap: list[str] = []
    total = 0
    for unit in reversed(units):
        t = _count(unit)
        if total + t <= OVERLAP_TOKENS:
            overlap.insert(0, unit)
            total += t
        else:
            break
    return overlap, total
