"""Lloyd's Register Rules and Regulations for the Classification of Ships (LR-RU-001).

Sprint D6.93 — the BIG one. LR-RU-001 covers hull construction,
machinery, electrical engineering, surveys, periodic inspection, and
all ship-type-specific requirements. This is the document mariners
reach for on questions like:

  * Emergency power redundancy + reporting class on failures
    (Karynn's 2026-05-15 transformer-failure question — the motivating
    use case for this adapter)
  * Survey schedules and class-society audit triggers
  * Electrical engineering standards beyond the lifting-appliance
    subset that LR-CO-001 covers
  * Ship-type-specific construction rules (covered in LR-RU-008
    for gas carriers, LR-RU-009 for chemical tankers, etc. —
    those are siblings we may ingest later)

Shares the .docx parsing logic with ``lr_lifting_code`` via
``lloyds_docx.py``; only the source name, doc prefix, and edition
date differ.

Raw files: ``data/raw/lloyds_rules/`` (one .docx per chapter from
Regs4ships).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources.lloyds_docx import parse_lloyds_docx_dir, dry_run_dir

SOURCE = "lr_rules"
TITLE_NUMBER = 0
# Latest published edition per the Regs4ships portal index (LR-RU-001
# is on the July 2025 cycle alongside LR-CO-001).
SOURCE_DATE = date(2025, 7, 1)
DOC_PREFIX = "LR-RU-001"


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
        f"  [cyan]lr_rules:[/cyan] {count} Lloyd's .docx files "
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
