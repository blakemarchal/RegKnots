"""
COLREGs source adapter.

Converts parsed PDF rules into ingest.models.Section objects ready for
the shared chunker → embedder → store pipeline.

Merging strategy (per spec):
  - Short adjacent rules within the same Part are merged until the combined
    text reaches ~TARGET_TOKENS, producing one Section per group.
  - Rules are never merged across Part boundaries.
  - Rules with text > TARGET_TOKENS get their own Section and are split
    further by chunk_section() downstream.

International / Inland text:
  - When both variants exist and differ, the full text is:
      [INTERNATIONAL]\n{intl}\n\n[INLAND]\n{inl}
  - When both variants are effectively the same, only the INTERNATIONAL
    text is stored (saves embedding space and avoids confusion).
  - Inland-only content (e.g., Annex V) is stored as-is.
"""

import logging
from datetime import date
from pathlib import Path

import tiktoken

from ingest.models import Section
from ingest.pdf_parser import ParsedRule, _PART_NAMES, parse_colregs_pdf

logger = logging.getLogger(__name__)

# Date from the PDF filename / cover page correction notice
SOURCE_DATE = date(2024, 8, 12)

# Title overrides for rules whose International page had no standalone title line
_TITLE_OVERRIDES: dict[str, str] = {
    "19": "Conduct of Vessels in Restricted Visibility",
    "37": "Distress Signals",
}

# Source tag for all COLREGs content
SOURCE = "colregs"

# title_number=0 → TITLE_NAMES[0] in store._to_row
TITLE_NUMBER = 0

# Target token budget for merged chunks (never merge across this boundary)
TARGET_TOKENS = 450

_ENCODER = tiktoken.get_encoding("cl100k_base")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the COLREGs PDF and return a list of Section objects.

    Args:
        pdf_path: Path to 'colregs_2024.pdf'.

    Returns:
        List of Section objects, with short adjacent rules within the same
        Part merged into combined sections.
    """
    parsed_rules = parse_colregs_pdf(pdf_path)
    if not parsed_rules:
        raise ValueError(f"No rules parsed from {pdf_path}")

    # Separate rules and annexes
    rules   = [r for r in parsed_rules if r.rule_type == "rule"]
    annexes = [r for r in parsed_rules if r.rule_type == "annex"]

    sections: list[Section] = []

    # Apply title overrides for rules with known parsing gaps
    for rule in parsed_rules:
        if rule.rule_type == "rule" and rule.number in _TITLE_OVERRIDES:
            if not rule.title or rule.title.startswith("("):
                rule.title = _TITLE_OVERRIDES[rule.number]

    # ── Rules: group by Part, merge short ones ────────────────────────────────
    parts_seen: list[str] = []
    rules_by_part: dict[str, list[ParsedRule]] = {}
    for rule in rules:
        p = rule.part
        if p not in rules_by_part:
            rules_by_part[p] = []
            parts_seen.append(p)
        rules_by_part[p].append(rule)

    for part in parts_seen:
        part_rules = rules_by_part[part]
        merged = _merge_rules(part_rules, part)
        sections.extend(merged)

    # ── Annexes: each gets its own Section ───────────────────────────────────
    for annex in annexes:
        full_text = _build_text(annex)
        sec_number = f"COLREGS Annex {annex.number}"
        parent = "COLREGS Annexes"
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=sec_number,
            section_title=annex.title,
            full_text=full_text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=parent,
        ))

    logger.info(
        "COLREGs: %d rules → %d sections + %d annexes",
        len(rules),
        len([s for s in sections if "Annex" not in s.section_number]),
        len(annexes),
    )
    return sections


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_text(rule: ParsedRule) -> str:
    """Build the full_text for a rule, merging International and Inland variants.

    If both exist and are meaningfully different, both are included with
    [INTERNATIONAL] / [INLAND] separators.  If they are identical (or one is
    empty), only the available text is used.
    """
    intl = rule.international_text.strip()
    inl  = rule.inland_text.strip()

    if not inl:
        return intl
    if not intl:
        return inl

    # Check similarity: if the texts are very close, use only International
    if _texts_similar(intl, inl):
        return intl

    return f"[INTERNATIONAL]\n{intl}\n\n[INLAND]\n{inl}"


def _texts_similar(a: str, b: str, threshold: float = 0.92) -> bool:
    """Return True if two texts are similar enough to be considered the same.

    Uses a simple character-level Jaccard similarity on 3-grams.
    """
    def trigrams(s: str) -> set[str]:
        s = s.lower()
        return {s[i:i+3] for i in range(len(s) - 2)} if len(s) >= 3 else set()

    ta, tb = trigrams(a), trigrams(b)
    if not ta and not tb:
        return True
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def _count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _rule_section_number(rules: list[ParsedRule]) -> str:
    """Build a canonical section_number for a group of rules."""
    nums = [r.number for r in rules]
    if len(nums) == 1:
        return f"COLREGS Rule {nums[0]}"
    return f"COLREGS Rules {nums[0]}-{nums[-1]}"


def _rule_section_title(rules: list[ParsedRule]) -> str:
    """Build a combined title for a group of rules."""
    parts = []
    for r in rules:
        if r.title:
            parts.append(f"Rule {r.number}: {r.title}")
    return "; ".join(parts) if parts else f"Rules {rules[0].number}–{rules[-1].number}"


def _merge_rules(part_rules: list[ParsedRule], part: str) -> list[Section]:
    """Merge adjacent short rules within a Part into combined Sections.

    Rules whose combined text would exceed TARGET_TOKENS are kept separate
    (or broken into individual rules when one rule alone exceeds the target).
    """
    # Pre-compute token counts for each rule
    rule_texts   = [_build_text(r) for r in part_rules]
    rule_tokens  = [_count_tokens(t) for t in rule_texts]

    parent = f"COLREGS Part {part}"
    sections: list[Section] = []

    bucket_rules: list[ParsedRule] = []
    bucket_texts: list[str]        = []
    bucket_tokens: int             = 0

    def flush_bucket() -> None:
        if not bucket_rules:
            return
        combined_text  = "\n\n---\n\n".join(bucket_texts)
        sec_number     = _rule_section_number(bucket_rules)
        sec_title      = _rule_section_title(bucket_rules)
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=sec_number,
            section_title=sec_title,
            full_text=combined_text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=parent,
        ))

    for rule, text, tokens in zip(part_rules, rule_texts, rule_tokens):
        if not text.strip():
            logger.warning("COLREGs Rule %s: empty text, skipping", rule.number)
            continue

        if bucket_tokens + tokens > TARGET_TOKENS and bucket_rules:
            # Adding this rule would exceed budget — flush current bucket first
            flush_bucket()
            bucket_rules  = []
            bucket_texts  = []
            bucket_tokens = 0

        bucket_rules.append(rule)
        bucket_texts.append(text)
        bucket_tokens += tokens

    flush_bucket()
    return sections
