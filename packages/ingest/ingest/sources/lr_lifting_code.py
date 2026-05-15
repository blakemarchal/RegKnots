"""Lloyd's Register Code for Lifting Appliances in a Marine Environment (LR-CO-001).

Sprint D6.93 — first Lloyd's Register adapter. Source files are .docx
exports from the Regs4ships portal (one per chapter, plus General
Regulations and the Notice that summarizes amendments for the edition).

Covers cranes, derricks, shiplifts, ro-ro access equipment, lifts,
materials and fabrication, testing, marking and surveys. Used by every
vessel with lifting equipment — high-traffic class-society reference
even on US-flag vessels where 46 CFR is the primary regulator.

All chunking and parsing logic lives in ``lloyds_docx.py`` so the
sibling ``lr_rules`` adapter (the bigger Rules and Regulations for
the Classification of Ships, LR-RU-001) can share it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources.lloyds_docx import parse_lloyds_docx_dir, dry_run_dir

SOURCE = "lr_lifting_code"
TITLE_NUMBER = 0
# Per the Notice No.1 file in the corpus: "July 2025" edition.
SOURCE_DATE = date(2025, 7, 1)
DOC_PREFIX = "LR-CO-001"


def parse_source(raw_dir: Path) -> list[Section]:
    return parse_lloyds_docx_dir(
        raw_dir,
        source_name=SOURCE,
        doc_prefix=DOC_PREFIX,
        source_date=SOURCE_DATE,
    )


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op: .docx files are placed manually from Regs4ships exports.

    The CLI dispatcher (raw_dir-style sources) expects this function and
    aborts ingest if (0, 0) is returned. We return (file_count, 0) so the
    dispatcher proceeds to parse_source.
    """
    _ = failed_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    count = len(list(raw_dir.glob("*.docx")))
    console.print(
        f"  [cyan]lr_lifting_code:[/cyan] {count} Lloyd's .docx files "
        f"(manually placed, no download)"
    )
    return count, 0


def get_source_date(raw_dir: Path) -> date:
    _ = raw_dir
    return SOURCE_DATE


def dry_run(raw_dir: Path) -> None:
    dry_run_dir(
        raw_dir,
        source_name=SOURCE,
        doc_prefix=DOC_PREFIX,
        source_date=SOURCE_DATE,
    )
