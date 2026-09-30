"""EPA 2013 Vessel General Permit (VGP) (2026-09-30).

Why: the 2013 VGP still binds non-recreational vessels 79 feet and over (most
line-haul towboats among them) until the Coast Guard's regulations under the
Vessel Incidental Discharge Act take effect (due by October 2026); EPA's VIDA
standards themselves (40 CFR 139) come in through cfr_40. Nothing in the corpus
covered VGP inspections, recordkeeping, annual reports or its discharge
limits. See docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

The permit is split at its numbered sections ("2.2.3 Ballast Water",
"4.1.1 Routine Visual Inspections") and its appendices ("Appendix A — Definitions",
"Appendix H — Annual Report"). Its table of contents repeats every heading
first, so the last occurrence of a number or letter marks the section; text
before the first body heading (cover, contents) is dropped. Part 6 (state
certification conditions) splits by state only (6.25 Wisconsin): its
third-level numbers are numbered conditions, not headings.

section_number: "EPA 2013 VGP 2.2.3", "EPA 2013 VGP App.A"; parent "EPA 2013 VGP".
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "epa_vgp"
TITLE_NUMBER = 0

DOC_ID = "EPA 2013 VGP"
PERMIT_URL = "https://www.epa.gov/system/files/documents/2025-07/2013-vessel-general-permit.pdf"
PERMIT_DATE = "2013-12-19"  # effective date; EPA signed it 2013-03-28

_HEADING = re.compile(r"^(\d\.\d{1,2}(?:\.\d{1,2})?)\s+([A-Z][^\n]{2,140}?)\s*$", re.MULTILINE)


_APPENDIX = re.compile(r"^(?:Appendix|APPENDIX)\s+([A-K])\s*[—–-]\s*(\S[^\n]{2,140}?)\s*$", re.MULTILINE)


def split_sections(doc: u.Doc, text: str) -> list[tuple[str, str, str]]:
    last: dict[str, tuple[int, int, str]] = {}  # key -> (start, end of heading line, label)
    for m in _HEADING.finditer(text):
        num = m.group(1)
        if num.startswith("6.") and num.count(".") == 2:
            continue  # Part 6: numbered state conditions, not headings
        last[num] = (m.start(), m.end(), f"{num} {m.group(2).strip()}")
    for m in _APPENDIX.finditer(text):
        last[f"App.{m.group(1)}"] = (m.start(), m.end(), f"Appendix {m.group(1)} {m.group(2).strip()}")
    heads = sorted(last.items(), key=lambda kv: kv[1][0])
    out = []
    for i, (key, (start, head_end, label)) in enumerate(heads):
        end = heads[i + 1][1][0] if i + 1 < len(heads) else len(text)
        body = text[head_end:end].strip()
        if len(body) < 40:
            continue
        out.append((f"{DOC_ID} {key}", f"{DOC_ID} {label} — EPA Vessel General Permit (2013)", body))
    return out


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = [u.Doc(doc_id=DOC_ID, title="Vessel General Permit for Discharges Incidental to the Normal Operation of Vessels",
                  url=PERMIT_URL, filename="vgp_2013.pdf", published=PERMIT_DATE)]
    u.write_index(raw_dir, docs)
    return u.fetch_docs(docs, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return date.fromisoformat(PERMIT_DATE)


def parse_source(raw_dir: Path) -> list[Section]:
    return u.doc_sections(SOURCE, u.read_index(raw_dir), raw_dir, splitter=split_sections)
