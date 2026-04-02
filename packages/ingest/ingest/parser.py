"""
Parse eCFR full-title XML into a flat list of Section objects.

The eCFR XML uses a DIVn / TYPE hierarchy (GPO SGML-derived format):

  ECFR (root)
    DIV1  TYPE="TITLE"   N="33"
      DIV3  TYPE="CHAPTER"   N="I"
        DIV4  TYPE="SUBCHAP"  N="A"
          DIV5  TYPE="PART"    N="1"
            DIV6  TYPE="SUBPART" N="1.01"
              DIV7  TYPE="SUBJGRP"
                DIV8  TYPE="SECTION" N="1.01-1"  ← atomic unit
                  HEAD  "§ 1.01-1   District Commander."
                  P / FP / ...  paragraph text
                  CITA  (citation — skipped)
            DIV8  TYPE="SECTION"   (sections directly under PART, no subpart)
          DIV9  TYPE="APPENDIX"    (skipped — not section-numbered)

Section number comes from the N attribute on the DIV8 element.
Section title comes from the HEAD child, with the leading "§ N  " prefix stripped.
"""

import logging
import re
from datetime import date
from typing import Optional

from lxml import etree

from ingest.models import Section, TITLE_TO_SOURCE

logger = logging.getLogger(__name__)

# Tags whose full text contributes to section content
_TEXT_TAGS = {"P", "FP", "FP-1", "FP-2", "NOTE", "EXTRACT", "Q", "GPOTABLE",
              "TABLE", "THEAD", "TBODY", "TR", "TH", "TD"}

# Tags to skip entirely when extracting text
_SKIP_TAGS = {"CITA", "FTNT", "EDNOTE", "SECAUTH", "AUTH", "SOURCE"}


def parse_title_xml(
    xml_bytes: bytes, title_number: int, up_to_date_as_of: date
) -> list[Section]:
    """Parse a full-title CFR XML response into a flat list of Section objects."""
    source = TITLE_TO_SOURCE[title_number]

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        logger.error(f"XML parse error for title {title_number}: {exc}")
        return []

    # Build a parent map so we can walk ancestors from any section element
    parent_map: dict = {child: parent for parent in root.iter() for child in parent}

    sections: list[Section] = []
    skipped = 0

    for section_el in root.iter():
        if section_el.get("TYPE") != "SECTION":
            continue
        try:
            sec = _extract_section(
                section_el, parent_map, title_number, source, up_to_date_as_of
            )
            if sec is not None:
                sections.append(sec)
            else:
                skipped += 1
        except Exception as exc:
            skipped += 1
            logger.debug(f"Skipped section element N={section_el.get('N')!r}: {exc}")

    logger.info(
        f"Title {title_number}: {len(sections)} sections parsed, {skipped} skipped"
    )
    if not sections:
        tag = root.tag
        children = [(c.tag, c.get("TYPE", "")) for c in root][:10]
        logger.warning(
            f"Title {title_number}: 0 sections found. "
            f"Root tag={tag!r}, top-level children={children}"
        )

    return sections


# ── Section extraction ───────────────────────────────────────────────────────

def _extract_section(
    el: etree._Element,
    parent_map: dict,
    title_number: int,
    source: str,
    as_of: date,
) -> Optional[Section]:
    # Section number is the N attribute: e.g. "1.01-1"
    raw_n = el.get("N", "").strip()
    if not raw_n:
        return None

    section_number = f"{title_number} CFR {raw_n}"
    section_title = _get_head_title(el, raw_n)
    full_text = _extract_text(el)

    if not full_text.strip():
        return None

    parent_section_number = _get_parent_section_number(el, parent_map, title_number)

    return Section(
        source=source,
        title_number=title_number,
        section_number=section_number,
        section_title=section_title,
        full_text=full_text,
        up_to_date_as_of=as_of,
        parent_section_number=parent_section_number,
    )


def _get_head_title(section_el: etree._Element, raw_n: str) -> str:
    """Extract section title from HEAD child, stripping the leading '§ N' prefix."""
    head_el = section_el.find("HEAD")
    if head_el is None:
        return ""
    head_text = "".join(head_el.itertext()).strip()
    # Strip leading "§ 1.01-1" or "§1.01-1" prefix (with optional whitespace)
    cleaned = re.sub(r"^[§\s]*" + re.escape(raw_n) + r"\s*", "", head_text).strip()
    return cleaned.rstrip(".")


def _extract_text(section_el: etree._Element) -> str:
    """Build readable text from a section element's content children."""
    parts: list[str] = []

    for child in section_el:
        if child.tag == "HEAD":
            continue
        if child.tag in _SKIP_TAGS:
            continue

        text = _element_text(child)
        if text:
            parts.append(text)

    return "\n\n".join(parts)


def _element_text(el: etree._Element) -> str:
    """Recursively extract all text from an element, collapsing whitespace."""
    if el.tag in _SKIP_TAGS:
        return ""
    raw = "".join(el.itertext())
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    return "\n".join(line for line in lines if line).strip()


# ── Hierarchy context ────────────────────────────────────────────────────────

def _get_parent_section_number(
    section_el: etree._Element,
    parent_map: dict,
    title_number: int,
) -> Optional[str]:
    """Walk ancestors to build a human-readable parent identifier.

    Ancestor TYPE mapping:
      DIV6 TYPE="SUBPART"  → subpart
      DIV5 TYPE="PART"     → part
    """
    part_n: Optional[str] = None
    subpart_hd: Optional[str] = None

    current = section_el
    while current in parent_map:
        ancestor = parent_map[current]
        a_type = ancestor.get("TYPE", "")

        if a_type == "SUBPART" and subpart_hd is None:
            hd = ancestor.findtext("HEAD", "").strip()
            if hd:
                subpart_hd = hd

        if a_type == "PART" and part_n is None:
            part_n = ancestor.get("N", "").strip()

        if part_n and subpart_hd:
            break

        current = ancestor

    if part_n and subpart_hd:
        label = subpart_hd[:80].rstrip("—").strip()
        return f"{title_number} CFR Part {part_n}, {label}"
    if part_n:
        return f"{title_number} CFR Part {part_n}"
    return None
