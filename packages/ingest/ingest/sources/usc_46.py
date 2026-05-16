"""46 USC source adapter (Sprint D5.1, expanded D6.95).

Parses United States Code Title 46 USLM (United States Legislative Markup)
XML and emits Section objects for the shared chunker→embedder→store pipeline.

Scope: ALL EIGHT SUBTITLES. The D5.1 launch covered only Subtitle II
(Vessels and Seamen). D6.95 expands to the full title because:

  Subtitle I   — General (incl. § 501 navigation/inspection waiver auth)
  Subtitle II  — Vessels and Seamen (the original scope)
  Subtitle III — Maritime Liability (Limitation of Liability Act, DOHSA,
                 salvage, Suits in Admiralty)
  Subtitle IV  — Regulation of Ocean Shipping (Shipping Act 1984, FMC)
  Subtitle V   — Merchant Marine (THE JONES ACT — § 55102, coastwise
                 trade, Subtitle V Ch.551 + waivers in § 55109-55121)
  Subtitle VI  — Clearance, Tonnage Taxes, and Duties
  Subtitle VII — Security and Drug Enforcement (port + facility security)
  Subtitle VIII— Miscellaneous

Trigger was Nicholas Brauckmann's 2026-05-16 Jones Act waiver question:
the chat fell to web fallback and Claude hallucinated 46 USC § 55113
(an OSRV-specific provision) as the answer's anchor because § 55102 +
§ 501 weren't in our corpus. With full-title coverage every mariner-
asked 46 USC question now retrieves the right statute.

Source: https://uscode.house.gov/download/releasepoints/us/pl/119/84/xml_usc46@119-84.zip
The zip contains a single usc46.xml file following the USLM 1.0 schema.
Download, unzip, and pass the XML path to parse_source().

Section identifiers in USLM follow `/us/usc/t46/st<II>/pt<E>/ch<71>/s<7101>`
pattern. We extract the trailing `/s<num>` to produce `46 USC 7101`
section_number values matching our existing citation regex. Chapter
numbers do not collide across subtitles (Subtitle II uses Ch.21-89,
Subtitle V uses Ch.501-587, etc.) so the section_number stays unique
without a subtitle prefix.

Skipped by design:
- Sections with status="repealed" (USLM marks these explicitly)
- Sourcing notes (<sourceCredit>), historical revision notes,
  editorial notes, amendments — these are commentary about the statute,
  not the statute itself. Citing them to a user would confuse "the law
  says X" with "the law was amended in 1996 to say X".
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE = "usc_46"
TITLE_NUMBER = 0  # non-CFR

# USLM 1.0 default namespace
_NS = {"u": "http://xml.house.gov/schemas/uslm/1.0"}

# Release point 119-84 published date from the XML meta (dcterms:created).
# Re-check this when re-ingesting from a newer release point.
SOURCE_DATE = date(2026, 3, 26)

# Tags whose body text we want to include in the full_text. Everything
# else (sourceCredit, notes) is commentary.
_BODY_TAGS = {"subsection", "paragraph", "subparagraph", "clause", "content", "chapeau"}


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _plain_text(elem: ET.Element) -> str:
    """Recursive text extraction, preserving order of text + tail."""
    if elem is None:
        return ""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_plain_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _render_section_body(section_elem: ET.Element) -> str:
    """Turn a <section> element's regulatory body into clean text.

    Skips <num>, <heading>, <sourceCredit>, <notes>. For subsections,
    renders the `(a)` label followed by the content. Recursively handles
    nested subsection / paragraph / subparagraph indentation with
    preservation of (a), (1), (i), (A) labels.
    """

    def walk(e: ET.Element, depth: int) -> list[str]:
        tag = _strip_ns(e.tag)
        if tag in ("num", "heading", "sourceCredit", "notes"):
            return []
        if tag in ("subsection", "paragraph", "subparagraph", "clause"):
            num_elem = e.find("u:num", _NS)
            label = (num_elem.text or "").strip() if num_elem is not None else ""
            chapeau = e.find("u:chapeau", _NS)
            chapeau_text = _plain_text(chapeau).strip() if chapeau is not None else ""
            content_elem = e.find("u:content", _NS)
            content_text = _plain_text(content_elem).strip() if content_elem is not None else ""

            lines: list[str] = []
            indent = "  " * depth
            if label and chapeau_text:
                lines.append(f"{indent}{label} {chapeau_text}")
            elif label and content_text:
                lines.append(f"{indent}{label} {content_text}")
            elif content_text:
                lines.append(f"{indent}{content_text}")

            # Recurse into nested levels (skip chapeau/content already handled)
            for child in e:
                ctag = _strip_ns(child.tag)
                if ctag in ("num", "chapeau", "content"):
                    continue
                lines.extend(walk(child, depth + 1))
            return lines

        # Top-level content (section has a simple <content> without subsections)
        if tag == "content":
            text = _plain_text(e).strip()
            return [text] if text else []

        return []

    lines: list[str] = []
    for child in section_elem:
        lines.extend(walk(child, 0))

    # Collapse whitespace in each line + drop empties
    clean = []
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            clean.append(ln)
    return "\n".join(clean)


def _is_repealed(section_elem: ET.Element) -> bool:
    if section_elem.get("status") == "repealed":
        return True
    # Repealed sections sometimes have "[REPEALED]" bracketed in heading
    heading = section_elem.find("u:heading", _NS)
    if heading is not None:
        text = _plain_text(heading).strip().upper()
        if text.startswith("[REPEALED") or text.endswith("REPEALED]"):
            return True
    return False


def _find_title(root: ET.Element) -> ET.Element:
    """Return the top-level <title> element holding all eight subtitles."""
    main = root.find("u:main", _NS)
    if main is None:
        raise ValueError("USLM XML missing <main> element")
    title = main.find("u:title", _NS)
    if title is None:
        raise ValueError("USLM XML missing <title> element")
    return title


def _walk_for_sections(elem: ET.Element, sections_out: list[Section], chapter_label: str | None = None):
    """Recursively walk the tree collecting <section> elements.

    Tracks the most-recent chapter heading so every section can be tagged
    with its parent_section_number (e.g. "46 USC Chapter 71").
    """
    tag = _strip_ns(elem.tag)

    if tag == "chapter":
        num_elem = elem.find("u:num", _NS)
        heading_elem = elem.find("u:heading", _NS)
        raw_num = (num_elem.get("value") or "") if num_elem is not None else ""
        raw_heading = _plain_text(heading_elem).strip() if heading_elem is not None else ""
        new_label = f"46 USC Chapter {raw_num}".strip()
        if raw_heading:
            new_label = f"{new_label} — {raw_heading}"
        # Descend using this chapter's label
        for child in elem:
            _walk_for_sections(child, sections_out, chapter_label=new_label)
        return

    if tag == "section":
        sec = _section_to_ingest(elem, chapter_label)
        if sec is not None:
            sections_out.append(sec)
        return

    # Subtitle, part, or other container: descend
    for child in elem:
        _walk_for_sections(child, sections_out, chapter_label=chapter_label)


def _section_to_ingest(section_elem: ET.Element, chapter_label: str | None) -> Section | None:
    if _is_repealed(section_elem):
        return None
    identifier = section_elem.get("identifier", "")
    if "/s" not in identifier:
        return None

    # Trailing "/s<num>" — the section number. Some repealed segments end
    # in "/s7101a" (lowercase letter suffix for added sections) — preserve.
    raw_num = identifier.rsplit("/s", 1)[-1]
    if not raw_num:
        return None

    heading_elem = section_elem.find("u:heading", _NS)
    heading = _plain_text(heading_elem).strip() if heading_elem is not None else ""
    heading = re.sub(r"\s+", " ", heading)

    body = _render_section_body(section_elem)
    if not body.strip():
        return None

    section_number = f"46 USC {raw_num}"
    section_title = heading or f"Section {raw_num}"

    return Section(
        source=SOURCE,
        title_number=TITLE_NUMBER,
        section_number=section_number,
        section_title=section_title,
        full_text=body,
        up_to_date_as_of=SOURCE_DATE,
        parent_section_number=chapter_label,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(xml_path: Path) -> list[Section]:
    """Parse 46 USC USLM XML, return list of Section objects for the
    entire Title 46 (all eight subtitles).

    Args:
        xml_path: Path to `usc46.xml` extracted from the House release-point zip.

    Returns:
        List of Section objects (one per non-repealed section across all
        subtitles), ordered by appearance in the XML (which matches
        statutory order: Subtitle I → II → … → VIII).
    """
    if not xml_path.exists():
        raise FileNotFoundError(f"USC 46 XML not found: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    title = _find_title(root)

    sections: list[Section] = []
    _walk_for_sections(title, sections, chapter_label=None)

    logger.info(
        "Parsed %d non-repealed sections from 46 USC (all subtitles, source_date=%s)",
        len(sections),
        SOURCE_DATE,
    )
    return sections
