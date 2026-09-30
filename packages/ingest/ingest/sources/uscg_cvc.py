"""USCG Office of Commercial Vessel Compliance (CG-CVC): policy letters, Mission
Management System work instructions and forms (2026-09-30).

Why: the corpus had the regulations and NVICs but not the office's own guidance
on applying them: Subchapter M special consideration and TSMS certificate
inspections (CVC-WI-010, -013), Sub M third-party organization guidance
(CVC-WI-038), ATB manning (CVC-WI-037), doublers on towing vessels (PL 21-03),
UTV equipment beyond Subchapter C (PL 10-06), the K-boat and T-boat inspection
checklists (CVC-FM-840K/T), and more. See
docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

Listings (all decades are in the letters page's HTML; the tabs are client-side):
  letters  …/Commercial-Vessel-Compliance/CG-CVC-Policy-Letters/letters/
           tables of Number | Program | Subject; the Subject cell links the PDF
  MMS      …/Commercial-Vessel-Compliance/CVCmms/
           tables of Serial Number | Title | Category | Issue Date | Revision Date

A letter whose row says it was canceled, superseded by something else, not
issued or incorporated into another document is skipped. "(Supersedes Policy
Letter 23-05)" marks the current letter and is kept as a note.

section_number: "CG-CVC PL 21-03", "CG-543 PL 11-07", "CG-CVC PL 23-05 CH-1",
"CG-CVC PL 17-08 Encl.1"; "CVC-WI-013" (the revision goes in the title);
"CVC-FM-840K".
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "uscg_cvc"
TITLE_NUMBER = 0

_BASE = "https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Inspections-Compliance-CG-5PC-/Commercial-Vessel-Compliance/"
LETTERS_URL = _BASE + "CG-CVC-Policy-Letters/letters/"
MMS_URL = _BASE + "CVCmms/"

_SKIP = re.compile(r"\bcancel+ed\b|superseded by|\bnot issued\b|incorporated into", re.I)
_SUPERSEDES = re.compile(r"^\(\s*(Supersedes[^)]*)\)\s*>?\s*", re.I)
_NUMBER = re.compile(r"(\d{2}-\d{2,3})\s*(?:\(\s*(CH|E)\s*-?\s*(\d+)\s*\))?", re.I)
_SERIAL = re.compile(r"^((?:CVC|5P)-(?:WI|FM)-\d{3}[A-Z]?)\s*\((\d+)\)?", re.I)

# Stored in nmc_policy with the NMC crediting guidance. The chat's citation
# lookup matches cited rows on section_number alone, so it is not duplicated.
_ALREADY_STORED = {"CG-CVC PL 15-03"}


def _letter_id(number: str, program: str) -> str | None:
    m = _NUMBER.search(number)
    if not m:
        return None
    kind, k = (m.group(2) or "").upper(), m.group(3)
    suffix = f" CH-{k}" if kind == "CH" else f" Encl.{k}" if kind == "E" else ""
    return f"{program.strip() or 'CG-CVC'} PL {m.group(1)}{suffix}"


def _letter_year(doc_id: str) -> date:
    yy = int(re.search(r"PL (\d{2})-", doc_id).group(1))
    return date(1900 + yy if yy >= 90 else 2000 + yy, 1, 1)


def discover(html_letters: str, html_mms: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for cells, links in u.rows(html_letters, LETTERS_URL):
        pdfs = [h for h, _ in links if u.is_pdf_href(h)]
        if len(cells) < 3 or not pdfs:
            continue
        number, program, subject = cells[0], cells[1], " ".join(cells[2:])
        if _SKIP.search(subject):
            continue
        doc_id = _letter_id(number, program)
        if not doc_id or doc_id in _ALREADY_STORED or doc_id in docs:
            continue
        note = ""
        m = _SUPERSEDES.match(subject)
        if m:
            note, subject = m.group(1), subject[m.end():]
        docs[doc_id] = u.Doc(doc_id=doc_id, title=subject.strip(), url=pdfs[0],
                             filename=u.safe_filename(doc_id), published=_letter_year(doc_id).isoformat(), note=note)
    for cells, links in u.rows(html_mms, MMS_URL):
        pdfs = [h for h, _ in links if u.is_pdf_href(h)]
        if len(cells) < 3 or not pdfs:
            continue
        m = _SERIAL.match(cells[0])
        if not m:
            continue
        doc_id = m.group(1).upper()
        revision = m.group(2)
        title, category = cells[1], cells[2]
        issued = cells[3] if len(cells) > 3 else ""
        revised = cells[4] if len(cells) > 4 else ""
        published = u.parse_date(revised) or u.parse_date(issued)
        docs[doc_id] = u.Doc(doc_id=doc_id, title=f"{title} ({category})", url=pdfs[0],
                             filename=u.safe_filename(doc_id), published=published,
                             note=f"revision {revision}" if revision else "")
    return list(docs.values())


# ── Adapter interface (cli.py multi-PDF path) ────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    with u.client() as http:
        docs = discover(u.fetch_html(LETTERS_URL, http), u.fetch_html(MMS_URL, http))
    if not docs:
        logger.warning("uscg_cvc: no documents listed; the page layout may have changed")
        return (0, 1)
    u.write_index(raw_dir, docs)
    return u.fetch_docs(docs, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return u.listing_source_date(raw_dir)


def parse_source(raw_dir: Path) -> list[Section]:
    return u.doc_sections(SOURCE, u.read_index(raw_dir), raw_dir)
