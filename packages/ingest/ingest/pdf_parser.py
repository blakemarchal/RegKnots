"""
General-purpose maritime PDF parser.

Currently supports the USCG Navigation Rules handbook (COLREGs / 72 COLREGS +
Inland Rules).  Designed to be extended for SOLAS, MARPOL, STCW by adding
new source-specific `PageConfig` and calling `parse_pdf()` with a different
config.

PDF structure (Navigation Rules handbook):
  - Pages 1–10:   Front matter — skip.
  - Pages 11–119: Rules 1–38.  Pages strictly alternate INTERNATIONAL / INLAND.
                  Each page opens with '—INTERNATIONAL—' or '—INLAND—'.
  - Pages 120:    Blank transition page — skip.
  - Pages 121–~149: Annexes I–IV (International + Inland alternating).
  - Pages ~150+:  Back matter (penalty provisions, demarcation lines) — stop.

Per-page boilerplate that is stripped before accumulating rule text:
  - The variant header line ('—INTERNATIONAL—' / '—INLAND—').
  - One-line section labels ('General', 'Steering and Sailing Rules', etc.).
  - Inland CFR cross-references ('33 CFR 83', '§ 83.XX').
  - Standalone page numbers (digits only, optionally followed by ‡).
  - Part/subpart header lines used only for structure tracking.
  - '[BLANK]' sentinel used for empty pages.

Rule / Annex boundary lines (stripped from text, used as markers only):
  - 'Rule N'             → start of a new rule.
  - 'Rule N—CONTINUED'  → continuation of the current rule on a new page.
  - 'Annex I'           → start of an annex (Roman numeral).
  - 'Annex I—CONTINUED' → continuation of the current annex.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

_RULE_START     = re.compile(r"^Rule\s+(\d+)$", re.IGNORECASE)
_RULE_CONT      = re.compile(r"^Rule\s+\d+\s*[—\-]+\s*CONTINUED$", re.IGNORECASE)
_ANNEX_START    = re.compile(r"^Annex\s+([IVX]+)$", re.IGNORECASE)
_ANNEX_CONT     = re.compile(r"^Annex\s+[IVX]+\s*[—\-]+\s*CONTINUED$", re.IGNORECASE)
_PART_HEADER    = re.compile(r"^(?:PART|SUBPART)\s+([A-E])\s*[—\-]", re.IGNORECASE)
_SECTION_HEADER = re.compile(r"^Section\s+[IVX]+\s*[—\-]", re.IGNORECASE)
_CFR_REF        = re.compile(r"^33\s+CFR\s+\d", re.IGNORECASE)
_INLAND_SEC_REF = re.compile(r"^§\s*\d+\.\d+")
_PAGE_NUMBER    = re.compile(r"^\d+\s*[‡]?\s*$")

# Section names that appear as boilerplate at the top of each content page
_SECTION_LABELS = {
    "General",
    "Steering and Sailing Rules",
    "Conduct of Vessels in Any Condition of Visibility",
    "Conduct of Vessels in Sight of One Another",
    "Conduct of Vessels in Restricted Visibility",
    "Lights and Shapes",
    "Sound and Light Signals",
    "Exemptions",
    "Distress Signals",
    "72 COLREGS",
    "Annex",          # bare "Annex" used as section label on some pages
    "Legal Citations",
    "Penalty Provisions",
}

# Lines that unambiguously mark we've entered back matter
_BACK_MATTER_SENTINELS = {
    "PENALTY PROVISIONS",
    "33 U.S.C. 2072",
    "COLREGS DEMARCATION LINES",
    "VESSEL TRAFFIC SERVICES",
    "NOTES",
}

# Mapping rule number → parent Part letter
_RULE_PART: dict[int, str] = {
    **{r: "A" for r in range(1,  4)},    # Rules 1–3
    **{r: "B" for r in range(4,  20)},   # Rules 4–19
    **{r: "C" for r in range(20, 32)},   # Rules 20–31
    **{r: "D" for r in range(32, 38)},   # Rules 32–37
    **{r: "E" for r in range(38, 39)},   # Rule 38
}

# Full part names for display
_PART_NAMES: dict[str, str] = {
    "A": "General",
    "B": "Steering and Sailing Rules",
    "C": "Lights and Shapes",
    "D": "Sound and Light Signals",
    "E": "Exemptions",
}


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class ParsedRule:
    """A single rule or annex extracted from the PDF."""
    rule_type: str          # "rule" | "annex"
    number: str             # "1"–"38" for rules; "I"–"IV" for annexes
    title: str              # e.g. "Application", "Responsibility"
    part: str               # "A"–"E" for rules; "Annex" for annexes
    international_text: str
    inland_text: str        # empty string if identical to international or not present
    parse_warnings: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_colregs_pdf(pdf_path: Path) -> list[ParsedRule]:
    """Parse the USCG Navigation Rules handbook and return a list of ParsedRule.

    Processes pages sequentially, accumulating International and Inland text
    separately for each rule/annex, then combines them into ParsedRule objects.

    Args:
        pdf_path: Path to the Navigation Rules Handbook PDF.

    Returns:
        List of ParsedRule objects, one per rule (1–38) and annex (I–IV).
    """
    # Accumulators: keyed by canonical section id ("Rule 1", "Annex I", ...)
    intl_text:    dict[str, list[str]] = {}
    inland_text:  dict[str, list[str]] = {}
    titles:       dict[str, str]       = {}
    rule_types:   dict[str, str]       = {}  # "rule" | "annex"
    rule_numbers: dict[str, str]       = {}  # canonical number ("1", "I", ...)
    parts:        dict[str, str]       = {}  # "A"–"E" or "Annex"
    section_order: list[str]           = []  # ordered unique section ids
    warnings:     dict[str, list[str]] = {}

    # Mutable parsing state
    current_id: str | None        = None   # e.g. "Rule 1", "Annex II"
    current_variant: str | None   = None   # "international" | "inland"
    expect_title: bool            = False  # True immediately after Rule N start
    in_back_matter: bool          = False

    with pdfplumber.open(pdf_path) as pdf:
        for pdf_page in pdf.pages:
            if in_back_matter:
                break

            raw = pdf_page.extract_text() or ""
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

            if not lines:
                continue

            # ── Detect back matter ────────────────────────────────────────────
            # Check for explicit back-matter sentinels early
            for ln in lines[:4]:
                if ln.upper() in _BACK_MATTER_SENTINELS:
                    in_back_matter = True
                    break
            if in_back_matter:
                break

            # ── Classify page variant ─────────────────────────────────────────
            if lines[0] == "—INTERNATIONAL—":
                current_variant = "international"
                lines = lines[1:]
            elif lines[0] == "—INLAND—":
                current_variant = "inland"
                lines = lines[1:]
            else:
                # Front matter, divider page, or back matter
                current_variant = None
                continue

            # ── Process lines on this content page ───────────────────────────
            for ln in lines:
                # ── Hard stop on back-matter sentinels mid-page ───────────────
                if ln.upper() in _BACK_MATTER_SENTINELS:
                    in_back_matter = True
                    break

                # ── Rule boundary detection ───────────────────────────────────
                m_rule = _RULE_START.match(ln)
                m_rule_cont = _RULE_CONT.match(ln)
                m_annex = _ANNEX_START.match(ln)
                m_annex_cont = _ANNEX_CONT.match(ln)

                if m_rule:
                    num = m_rule.group(1)
                    new_id = f"Rule {num}"
                    current_id = new_id
                    expect_title = True
                    if new_id not in section_order:
                        section_order.append(new_id)
                        rule_types[new_id] = "rule"
                        rule_numbers[new_id] = num
                        parts[new_id] = _RULE_PART.get(int(num), "?")
                        warnings[new_id] = []
                    continue

                if m_rule_cont:
                    # Stay on same current_id, no title update
                    expect_title = False
                    continue

                if m_annex:
                    roman = m_annex.group(1).upper()
                    new_id = f"Annex {roman}"
                    current_id = new_id
                    expect_title = True
                    if new_id not in section_order:
                        section_order.append(new_id)
                        rule_types[new_id] = "annex"
                        rule_numbers[new_id] = roman
                        parts[new_id] = "Annex"
                        warnings[new_id] = []
                    continue

                if m_annex_cont:
                    expect_title = False
                    continue

                # ── Skip boilerplate ──────────────────────────────────────────
                if _is_boilerplate(ln):
                    continue

                # ── No active section yet (front matter lines leaking through) ─
                if current_id is None:
                    continue

                # ── Title capture ─────────────────────────────────────────────
                # Prefer International pages for the authoritative title.
                # If the line starts with "(" it's a paragraph, not a title —
                # skip title capture and accumulate as content.
                if expect_title:
                    is_paragraph = ln.startswith("(")
                    if current_variant == "international":
                        if not is_paragraph:
                            if current_id not in titles:
                                titles[current_id] = ln
                            expect_title = False
                            continue          # title line is not content
                        else:
                            # Paragraph directly after rule number — no title
                            expect_title = False
                            # fall through to accumulate as content
                    else:
                        # Inland page: use as fallback title only if no intl title yet
                        if not is_paragraph and current_id not in titles:
                            titles[current_id] = ln
                        expect_title = False
                        # fall through to accumulate as content

                # ── Accumulate text ───────────────────────────────────────────
                bucket = intl_text if current_variant == "international" else inland_text
                if current_id not in bucket:
                    bucket[current_id] = []
                bucket[current_id].append(ln)

    # ── Assemble ParsedRule objects ───────────────────────────────────────────
    results: list[ParsedRule] = []
    for sec_id in section_order:
        intl_lines   = intl_text.get(sec_id, [])
        inl_lines    = inland_text.get(sec_id, [])
        title        = titles.get(sec_id, "")
        rtype        = rule_types[sec_id]
        num          = rule_numbers[sec_id]
        part         = parts[sec_id]
        w            = warnings.get(sec_id, [])

        intl_str = "\n".join(intl_lines).strip()
        inl_str  = "\n".join(inl_lines).strip()

        if not intl_str and not inl_str:
            w.append(f"{sec_id}: no text extracted — skipped")
            logger.warning("%s: no text extracted — skipped", sec_id)
            continue

        results.append(ParsedRule(
            rule_type=rtype,
            number=num,
            title=title,
            part=part,
            international_text=intl_str,
            inland_text=inl_str,
            parse_warnings=w,
        ))
        if w:
            for msg in w:
                logger.warning(msg)

    logger.info("Parsed %d sections from %s", len(results), pdf_path.name)
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_boilerplate(line: str) -> bool:
    """Return True if this line should be stripped from content."""
    if line in _SECTION_LABELS:
        return True
    if _CFR_REF.match(line):
        return True
    if _INLAND_SEC_REF.match(line):
        return True
    if _PAGE_NUMBER.match(line):
        return True
    if _PART_HEADER.match(line):
        return True
    if _SECTION_HEADER.match(line):
        return True
    if line == "[BLANK]":
        return True
    # e.g. "Distress Signals" mid-page label
    if line.upper() in {s.upper() for s in _SECTION_LABELS}:
        return True
    return False


def _try_update_part(line: str, current_id: str | None, parts: dict) -> None:
    """Update the part assignment when a PART/SUBPART header is encountered."""
    if current_id is None:
        return
    m = _PART_HEADER.match(line)
    if m:
        parts[current_id] = m.group(1).upper()
