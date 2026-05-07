"""NMC exam-question-bank ingest — Sprint D6.83 (Study Tools Phase A1).

The 248 q### PDFs published by NMC are official USCG exam study
materials. Filename pattern is `qNNN_<subject>.pdf` where:

  - NNN is the question-pool identifier (q100s for Master Inland,
    q300s for Western Rivers, q500-700s for engine, q800s for ratings,
    etc. — exact mapping isn't authoritative anywhere we can verify,
    so we don't try to encode endorsement level here).
  - <subject> is the topic suffix: deck_general, deck_safety,
    nav_general-near_coastal, motor_plants, etc.

This adapter classifies each file by topic (the user-facing primary
axis for the Study Tools quiz/guide generator) and ingests as
`source = 'nmc_exam_bank'`. Critically: this source is NOT in
SOURCE_GROUPS (packages/rag/rag/retriever.py), so chat retrieval
ignores it automatically. Only the Study Tools retrieval path queries
it explicitly via `WHERE source = 'nmc_exam_bank'`.

Why curated over wholesale: subjects are the primary user-facing axis
("I want a quiz on deck safety"). A wholesale ingest with no metadata
would force the quiz generator to free-text-search across all 248
files, which would mix engine questions into deck-safety queries
because of the embedding similarity floor. Topic metadata in the
section_title gives us a clean SQL filter.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


# Source name used in regulations.source. Must be added to the table's
# CHECK constraint before running this ingest.
SOURCE_NAME = "nmc_exam_bank"
TITLE_NUMBER = 0  # not a real CFR title

# CLI compatibility — the cli.py PDF pipeline expects these symbols even
# for adapters that don't actively download. The exam-bank PDFs are
# placed manually by the existing refresh_nmc_corpus cron, so the
# discover_and_download function just confirms the files are present
# (no network round-trip).
SOURCE_DATE = date.today()


# ── Topic classification ────────────────────────────────────────────────────
#
# Keys are filename-suffix prefixes (after stripping `qNNN_` and `.pdf`).
# Order matters — first match wins, so longer / more specific prefixes
# must come before shorter / more general ones (e.g. nav_problems before
# nav_general).

_TOPIC_RULES: list[tuple[str, str]] = [
    # Rules of the Road — order before nav_general so we don't mistakenly
    # categorize "ror_inland-international" as nav.
    ("ror_inland", "rules_of_road"),
    ("rules_of_the_road", "rules_of_road"),

    # Engine — specific plant types first.
    ("motor_plants", "engine_motor"),
    ("motor_plant_i", "engine_motor"),
    ("motor_plant_ii", "engine_motor"),
    ("steam_plants", "engine_steam"),
    ("steam_plant_i", "engine_steam"),
    ("steam_plant_ii", "engine_steam"),
    ("gas_turbine_plants", "engine_gas_turbine"),
    ("electrical_electronic_control_engineering", "engine_electrical"),
    ("electrical_electronics_and_control_engineering", "engine_electrical"),
    ("electrical_electronics_control_engineering", "engine_electrical"),
    ("engineering_safety_environmental_protection", "engine_safety_env"),
    ("engineering_safety_ep", "engine_safety_env"),
    ("engineering_safety_and_environmental_protection", "engine_safety_env"),
    ("eng_safety_environmental_protection", "engine_safety_env"),
    ("general_subjects", "engine_general"),

    # Deck — order specific suffixes (safety, problems) before general.
    ("nav_problems", "nav_problems"),
    ("nav_general", "nav_general"),
    ("nav_dk_general_dk_safety", "nav_deck_general"),
    ("nav_deck_general_safety", "nav_deck_general"),
    ("nav_and_deck_general-safety", "nav_deck_general"),
    ("nav_and_deck_general", "nav_deck_general"),
    ("nav_general_near_coastal", "nav_general"),
    ("nav_general_oceans_nc", "nav_general"),
    ("nav_general_western_rivers", "nav_general"),
    ("nav_gen_western_rivers", "nav_general"),
    ("navigation_general", "nav_general"),

    # Misc nav-style files
    ("chart_plot_mississippi_river", "nav_problems"),
    ("great_lakes_topics", "great_lakes"),

    # Deck — order specific (safety) before general.
    ("deck_safety-stability", "deck_stability"),
    ("deck_safety", "deck_safety"),
    ("deck_general_safety", "deck_general"),
    ("deck_general-safety", "deck_general"),
    ("deck_general", "deck_general"),

    # Specialty endorsements
    ("tankship_dangerous_liquids", "tankship_dangerous"),
    ("tankship_liquefied_gases", "tankship_gases"),
    ("lifeboatman_limited", "lifeboatman"),
    ("lifeboatman", "lifeboatman"),
    ("auxiliary_sail", "auxiliary_sail"),
    ("assistance_towing", "assistance_towing"),

    # OIM / Barge supervisor / BCO
    ("oim", "oim"),
    ("barge_supervisor", "barge_supervisor"),
    ("bco", "bco"),
]

# Friendly labels for topics (used in section_title and surfaced in UI).
_TOPIC_LABELS: dict[str, str] = {
    "rules_of_road": "Rules of the Road (COLREGs)",
    "deck_general": "Deck General Knowledge",
    "deck_safety": "Deck Safety",
    "deck_stability": "Deck Safety — Stability",
    "nav_general": "Navigation — General",
    "nav_problems": "Navigation — Practical Problems",
    "nav_deck_general": "Navigation + Deck General",
    "great_lakes": "Great Lakes Topics",
    "engine_motor": "Engine — Motor Plants",
    "engine_steam": "Engine — Steam Plants",
    "engine_gas_turbine": "Engine — Gas Turbine Plants",
    "engine_electrical": "Engine — Electrical / Electronic / Control",
    "engine_safety_env": "Engineering Safety + Environmental Protection",
    "engine_general": "Engine — General Subjects",
    "tankship_dangerous": "Tankship — Dangerous Liquids",
    "tankship_gases": "Tankship — Liquefied Gases",
    "lifeboatman": "Lifeboatman / Survival Craft",
    "auxiliary_sail": "Auxiliary Sail",
    "assistance_towing": "Assistance Towing",
    "oim": "Offshore Installation Manager (OIM)",
    "barge_supervisor": "Barge Supervisor",
    "bco": "Barge Cargo Operations",
    "uncategorized": "USCG Exam Bank — Uncategorized",
}


# Some q### filenames have ambiguous suffixes that historically landed
# under one topic by convention — listed here for future auditing.
_QFILE_RE = re.compile(r"^q(\d+)_(.+)\.pdf$", re.IGNORECASE)


def _classify(filename: str) -> tuple[Optional[int], str, str]:
    """Parse `q###_<suffix>.pdf` → (q_number, topic_key, topic_label).

    Returns (None, 'uncategorized', label) on any pattern mismatch.
    """
    m = _QFILE_RE.match(filename)
    if not m:
        return None, "uncategorized", _TOPIC_LABELS["uncategorized"]
    q_num = int(m.group(1))
    suffix = m.group(2).lower()

    # Try the rules in order — first prefix match wins.
    for prefix, topic_key in _TOPIC_RULES:
        if suffix.startswith(prefix):
            return q_num, topic_key, _TOPIC_LABELS.get(topic_key, topic_key)

    # No match — log so future runs can refine the rule list.
    logger.info(
        "nmc_exam_bank: %s suffix %r did not match any topic rule — using uncategorized",
        filename, suffix,
    )
    return q_num, "uncategorized", _TOPIC_LABELS["uncategorized"]


# ── Text extraction ────────────────────────────────────────────────────────


def _extract_pdf_text(pdf_path: Path) -> str:
    """Same approach as nmc.py: page-by-page extract, blank-line separator."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            stripped = raw.strip()
            if stripped:
                parts.append(stripped)
    return "\n\n".join(parts)


# Same image / dash cleanup as the NMC adapter — these PDFs share the
# same NMC publishing pipeline and have the same artifacts.
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)
_DASH_LINE = re.compile(r"^[\-–—]{4,}\s*$", re.MULTILINE)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── CLI integration helpers ────────────────────────────────────────────────


def discover_and_download(
    raw_dir: Path,
    failed_dir: Path,
    console=None,
) -> tuple[int, int]:
    """No-op: PDFs are placed by refresh_nmc_corpus.py, not by this adapter.

    Returns (count_present, 0). The CLI checks (success > 0 OR failures > 0)
    to decide whether to proceed; we report the count of q-files on disk
    so an empty data dir still produces a "no docs found" exit.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return 0, 0
    count = sum(1 for p in raw_dir.iterdir() if _QFILE_RE.match(p.name))
    return count, 0


def get_source_date(raw_dir: Path) -> date:
    """Always today — exam pool files are versioned by NMC publication
    cycle but we don't parse that out of the filenames; the q### number
    is the stable identifier the user reads."""
    return date.today()


# ── Public API ──────────────────────────────────────────────────────────────


def parse_source(raw_dir: Path, source: str = SOURCE_NAME) -> list[Section]:
    """Parse all q###_*.pdf files in raw_dir.

    Returns one Section per PDF. Files that aren't q### exam pool PDFs
    are skipped silently (the adapter is filename-pattern scoped).
    """
    if source != SOURCE_NAME:
        raise ValueError(f"nmc_exam_bank adapter called with unknown source={source!r}")

    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        logger.error("nmc_exam_bank raw_dir does not exist: %s", raw_dir)
        return []

    sections: list[Section] = []
    today = date.today()

    files = sorted(p for p in raw_dir.iterdir() if _QFILE_RE.match(p.name))
    logger.info("nmc_exam_bank: found %d q###_*.pdf files in %s", len(files), raw_dir)

    topic_counts: dict[str, int] = {}

    for pdf_path in files:
        try:
            full_text = _extract_pdf_text(pdf_path)
        except Exception as exc:
            logger.warning(
                "nmc_exam_bank: failed to extract %s: %s", pdf_path.name, exc,
            )
            continue

        cleaned = _clean_text(full_text)
        if not cleaned:
            logger.warning(
                "nmc_exam_bank: %s produced no text — skipping", pdf_path.name,
            )
            continue

        q_num, topic_key, topic_label = _classify(pdf_path.name)
        topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1

        # section_number is the canonical q-pool identifier so citations
        # surface as "NMC Q103" — recognizable to mariners studying the
        # exam pools. section_title leads with the topic label so
        # embedding search picks up topical terms.
        section_number = f"NMC Q{q_num}" if q_num is not None else f"NMC {pdf_path.stem}"
        section_title = (
            f"{topic_label} — USCG exam-pool questions (Q{q_num})"
            if q_num is not None
            else f"{topic_label} — USCG exam-pool questions"
        )

        section = Section(
            source=SOURCE_NAME,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=section_title[:500],
            full_text=cleaned,
            up_to_date_as_of=today,
            parent_section_number=None,
        )
        sections.append(section)

    logger.info("nmc_exam_bank: parsed %d sections", len(sections))
    logger.info("nmc_exam_bank: topic distribution:")
    for topic, count in sorted(topic_counts.items(), key=lambda kv: -kv[1]):
        logger.info("  %-30s %d", topic, count)

    return sections
