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

Sprint D6.16b — IMDG 3.2 Dangerous Goods List sections take a tabular
fast-path that emits one chunk per UN-numbered row. Diluting an
embedding across 9-50 unrelated UN entries (the previous chunker
default) was the root cause of the UN-2734 hallucination, even after
the keyword bypass was fixed. Per-row chunking gives vector retrieval
a fair shot at surfacing single rows.
"""

import hashlib
import re
from datetime import date

import tiktoken

from ingest.models import Chunk, Section

_ENCODER = tiktoken.get_encoding("cl100k_base")

MAX_TOKENS = 512
OVERLAP_TOKENS = 50

# Sprint D6.16b — IMDG DGL row pattern. Captures lines that look like:
#   "  2734    Amines, liquid, corrosive, flammable, n.o.s."
# i.e. optional leading whitespace, exactly four digits, two-or-more
# spaces, then the proper shipping name running to end of line. The
# 2-space gap is what distinguishes a UN row from prose that happens
# to start with a 4-digit year ("2024 amendments to the IMDG Code...").
_IMDG_DGL_ROW_RE = re.compile(r"^\s*(\d{4})\s{2,}(.+?)\s*$", re.MULTILINE)


# ── Public API ───────────────────────────────────────────────────────────────

def chunk_section(section: Section) -> list[Chunk]:
    """Split a Section into ≤MAX_TOKENS chunks with OVERLAP_TOKENS overlap."""
    # Strip NUL bytes — Postgres rejects them in TEXT/VARCHAR columns
    # ("invalid byte sequence for encoding UTF8: 0x00"). PDF extractors
    # occasionally emit them when a PDF has malformed content streams
    # (seen on NMA Norwegian rundskriv PDFs in D6.46).
    text = section.full_text.replace("\x00", "").strip()
    if not text:
        return []

    # Sprint D6.16b — IMDG DGL fast-path: one chunk per UN row. Only
    # fires for IMDG 3.2 sections; everything else uses the standard
    # paragraph-/sentence-aware chunker below.
    if _is_imdg_dgl(section):
        rows = _chunk_imdg_dgl(section)
        if rows:
            return rows
        # No UN rows extracted (header-only section, frontmatter, etc.) —
        # fall through to the default chunker so we still emit something.

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


# ── IMDG DGL per-row chunking (Sprint D6.16b) ───────────────────────────────

def _is_imdg_dgl(section: Section) -> bool:
    """Detect IMDG 3.2 Dangerous Goods List sections.

    The DGL is split across many Sections at ingest time (one per page
    range), but every one of them carries section_number="IMDG 3.2" and
    source="imdg". That's enough to route deterministically.
    """
    return section.source == "imdg" and section.section_number == "IMDG 3.2"


def _chunk_imdg_dgl(section: Section) -> list[Chunk]:
    """Emit one chunk per UN row in an IMDG 3.2 section.

    Non-row lines (chapter headers, search-term annotations, page
    markers) are dropped — they don't belong with any single UN entry
    and aren't worth their own chunk for vector retrieval.

    Each row chunk's text takes the form:
      "[IMDG 3.2] UN <number> — <proper shipping name>"

    so every embedding is anchored to exactly one UN identity. Returns
    [] if no rows match (caller falls back to default chunking).
    """
    text = section.full_text or ""
    chunks: list[Chunk] = []
    seen_un: set[str] = set()
    for m in _IMDG_DGL_ROW_RE.finditer(text):
        un_number = m.group(1)
        shipping_name = m.group(2).strip()
        # Skip pathological short matches (OCR noise) and duplicates
        # within the same section (rare but defensive).
        if not shipping_name or un_number in seen_un:
            continue
        seen_un.add(un_number)
        # Embed-friendly format: identifier first, then the descriptive
        # name. The UN prefix is added so vector queries that say
        # "UN 2734" share a token with the chunk; bare-number queries
        # also still match via the line-anchored "<number>" form below.
        chunk_text = f"[IMDG 3.2] UN {un_number} — {shipping_name}\n{un_number}    {shipping_name}"
        chunks.append(Chunk(
            source                = section.source,
            title_number          = section.title_number,
            section_number        = section.section_number,
            section_title         = section.section_title,
            chunk_index           = len(chunks),
            chunk_text            = chunk_text,
            content_hash          = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            token_count           = _count(chunk_text),
            up_to_date_as_of      = section.up_to_date_as_of,
            parent_section_number = section.parent_section_number,
            published_date        = section.published_date,
            expires_date          = section.expires_date,
            superseded_by         = section.superseded_by,
            language              = getattr(section, "language", "en"),
        ))
    return chunks


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
        published_date=section.published_date,
        expires_date=section.expires_date,
        superseded_by=section.superseded_by,
        language=getattr(section, "language", "en"),
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
