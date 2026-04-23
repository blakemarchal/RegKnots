"""WHO International Health Regulations (2005) adapter — Sprint D5.4.

Ingests the IHR consolidated text (2005 + 2014/2022/2024 amendments) for
RegKnot's maritime port-health use case. Karynn's 2026-04-22 session
surfaced a Ship Sanitation Certificate ("derat") question that hedged
because WHO IHR content wasn't in corpus. This adapter closes that gap.

Source:
  https://apps.who.int/gb/bd/pdf_files/IHR_2014-2022-2024-en.pdf
  (The consolidated text distributed by the WHO governing-bodies secretariat.
   Free public PDF, 100 pages.)

Structure parsed:
  Articles 1-66  →  one Section each (body paragraphs)
  Annexes 1-10   →  one Section per Annex (including Annex 3 which is
                    the SSCC / Ship Sanitation Control Certificate model)

Skipped:
  - The front-matter explanatory note and appendixes (historical record
    of State Party notifications; not regulatory text users would cite)
  - Decision instruments and flowcharts (visual/tabular content that
    pdftotext extracts poorly and that users wouldn't benefit from
    reading as flat text)

Section number format:
  "WHO IHR Article 5"     for articles
  "WHO IHR Annex 3"       for annexes
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "who_ihr"
TITLE_NUMBER = 0

# Current text is IHR 2005 as amended through WHA77.17 (2024).
# Amendments adopted 2024 entered into force 19 September 2025 for most
# States Parties. WHO published this consolidated edition dated
# 19 September 2025.
SOURCE_DATE = date(2025, 9, 19)

# ── Header recognizers ───────────────────────────────────────────────────

# "Article 5 Surveillance" — number followed by title text on the same line.
# We require at least one non-digit, non-punctuation character right after
# the number to reject mid-paragraph references like "Article 6, in particular".
_ARTICLE_HDR = re.compile(
    r"^Article\s+(\d+)\s+([A-Z][^\n,]{2,})",
    re.MULTILINE,
)

# "ANNEX 3 MODEL SHIP SANITATION ..." — uppercase after number
_ANNEX_HDR = re.compile(
    r"^ANNEX\s+(\d+)\s+([A-Z][^\n]{2,})",
    re.MULTILINE,
)

# Strip running headers / page numbers
_PAGE_FOOTER = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
_RUNNING_HEADER = re.compile(
    r"^\s*International Health Regulations \(2005\)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_text(pdf_path: Path) -> str:
    """Run pdftotext to convert the PDF. Requires poppler installed."""
    out = subprocess.check_output(
        ["pdftotext", str(pdf_path), "-"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    # Clean up noise
    out = _PAGE_FOOTER.sub("", out)
    out = _RUNNING_HEADER.sub("", out)
    return out


def _collapse_whitespace(text: str) -> str:
    """Normalize line breaks within paragraphs; keep paragraph breaks."""
    # Collapse runs of 3+ newlines to 2 (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Within a paragraph, collapse soft-wrap line breaks to spaces
    lines = text.split("\n")
    out: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                out.append(" ".join(buf))
                buf = []
            out.append("")
        else:
            buf.append(stripped)
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out).strip()


def _section_from_slice(
    kind: str, num: str, title: str, body: str
) -> Section | None:
    """Build a Section from an Article / Annex slice."""
    body = body.strip()
    if not body:
        return None
    body = _collapse_whitespace(body)
    if kind == "article":
        section_number = f"WHO IHR Article {num}"
        parent = "WHO IHR (2005)"
    else:
        section_number = f"WHO IHR Annex {num}"
        parent = "WHO IHR Annexes"
    return Section(
        source=SOURCE,
        title_number=TITLE_NUMBER,
        section_number=section_number,
        section_title=title.strip().rstrip(".").title(),
        full_text=body,
        up_to_date_as_of=SOURCE_DATE,
        parent_section_number=parent,
    )


def _split_into_sections(text: str) -> list[Section]:
    """Find every Article + Annex header and slice the text between them.

    Because pdftotext output contains mid-paragraph references to
    "Article N" that we don't want to treat as section starts, we only
    accept a header if the line starts with `Article N` or `ANNEX N`
    AND what follows looks like a real title (starts with a capital letter,
    no comma/period/lowercase-word immediately after the number).
    """
    # Collect all candidate header positions
    matches: list[tuple[int, str, str, str]] = []  # (pos, kind, num, title)
    for m in _ARTICLE_HDR.finditer(text):
        matches.append((m.start(), "article", m.group(1), m.group(2).strip()))
    for m in _ANNEX_HDR.finditer(text):
        matches.append((m.start(), "annex", m.group(1), m.group(2).strip()))

    # De-dupe by (kind, num) — keep the FIRST occurrence. Subsequent matches
    # for the same Article/Annex are usually TOC entries or mid-text
    # references (e.g., the Table of Contents lists articles before the
    # body).
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[int, str, str, str]] = []
    # Sort by position
    matches.sort(key=lambda m: m[0])
    # Heuristic: the FIRST occurrence of each (kind, num) is almost always
    # the TOC entry, not the body. We want the SECOND occurrence if it
    # exists. So: group by (kind, num), pick the second if multiple, else
    # the first.
    grouped: dict[tuple[str, str], list[tuple[int, str, str, str]]] = {}
    for m in matches:
        k = (m[1], m[2])
        grouped.setdefault(k, []).append(m)
    chosen: list[tuple[int, str, str, str]] = []
    for k, group in grouped.items():
        # If we have 2+ hits for this (kind, num), take the second
        # (TOC mention is first, body is second). If only 1, use it.
        chosen.append(group[1] if len(group) >= 2 else group[0])
    chosen.sort(key=lambda m: m[0])

    sections: list[Section] = []
    for i, (pos, kind, num, title) in enumerate(chosen):
        end = chosen[i + 1][0] if i + 1 < len(chosen) else len(text)
        # Slice out the body. Skip the header line itself.
        slice_start = text.find("\n", pos) + 1
        if slice_start <= 0 or slice_start > end:
            continue
        body = text[slice_start:end]
        sec = _section_from_slice(kind, num, title, body)
        if sec is not None:
            sections.append(sec)
    return sections


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the IHR consolidated PDF and return Sections.

    Args:
        pdf_path: Path to the WHO IHR 2014-2022-2024 consolidated PDF.

    Returns:
        List of Section objects — one per Article, one per Annex.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"WHO IHR PDF not found: {pdf_path}")
    text = _extract_text(pdf_path)
    sections = _split_into_sections(text)
    logger.info(
        "Parsed %d sections from WHO IHR 2005 consolidated (source_date=%s)",
        len(sections),
        SOURCE_DATE,
    )
    return sections
