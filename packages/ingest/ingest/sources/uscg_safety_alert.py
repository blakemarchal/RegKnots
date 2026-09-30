"""USCG Safety Alerts and Findings of Concern, Office of Investigations &
Casualty Analysis (CG-INV) (2026-09-30).

Why: recall and equipment-failure questions (dry-chemical extinguishers, SCBA,
fixed CO2) had nothing to cite; the corpus held one alert. CG-INV lists every
alert since 1996 (192 PDFs on 2026-09-30, 17 of them from 2026), e.g. SA 15-26
on retractable pilot houses on towing vessels, and 50 Findings of Concern
(lessons from casualty investigations, e.g. FOC 006-26 on lifeboat fires from
improper electrical heating). See
docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

Listings, both under …/Office-of-Investigations-Casualty-Analysis/:
  Safety-Alerts/        Number | Safety Alert (PDF link) | Title | Date. Rows
                        without a PDF (an NTSB alert linked as a web page) are
                        skipped.
  Findings-of-Concern/  Finding (PDF link, "USCGFOC_008-26.pdf") | Title | Date.

Both can be old: the date goes into the section title, and each Section's
up_to_date_as_of is its date, so an answer can say how old it is.

section_number: "USCG SA 15-26", "USCG SA 20-25 CH-1", "USCG FOC 008-26".
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "uscg_safety_alert"
TITLE_NUMBER = 0

_INV = ("https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/"
        "Inspections-Compliance-CG-5PC-/Office-of-Investigations-Casualty-Analysis/")
LIST_URL = _INV + "Safety-Alerts/"
FOC_URL = _INV + "Findings-of-Concern/"

_NUMBER = re.compile(r"^(\d{1,2}-\d{2})\s*(?:CH\s*-?\s*0?(\d+))?", re.I)
_FOC_FILE = re.compile(r"USCGFOC_(\d{3})-(\d{2})\.pdf", re.I)


def discover(html: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for cells, links in u.rows(html, LIST_URL):
        pdfs = [h for h, _ in links if u.is_pdf_href(h)]
        if len(cells) < 3 or not pdfs:
            continue
        m = _NUMBER.match(cells[0])
        if not m:
            continue
        doc_id = f"USCG SA {m.group(1)}" + (f" CH-{m.group(2)}" if m.group(2) else "")
        title = cells[2] if len(cells) >= 4 else cells[-1]
        published = u.parse_date(cells[-1])
        if published:
            title = f"{title} ({published})"
        docs.setdefault(doc_id, u.Doc(doc_id=doc_id, title=f"Coast Guard Safety Alert: {title}", url=pdfs[0],
                                      filename=u.safe_filename(doc_id), published=published))
    return list(docs.values())


def discover_findings(html: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for cells, links in u.rows(html, FOC_URL):
        pdfs = [h for h, _ in links if u.is_pdf_href(h)]
        m = _FOC_FILE.search(pdfs[0]) if pdfs else None
        if len(cells) < 3 or not m:
            continue
        doc_id = f"USCG FOC {m.group(1)}-{m.group(2)}"
        published = u.parse_date(cells[-1])
        title = cells[1] + (f" ({published})" if published else "")
        docs.setdefault(doc_id, u.Doc(doc_id=doc_id, title=f"Coast Guard Finding of Concern: {title}",
                                      url=pdfs[0], filename=u.safe_filename(doc_id), published=published))
    return list(docs.values())


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = discover(u.fetch_html(LIST_URL))
    if not docs:
        logger.warning("uscg_safety_alert: no alerts listed; the page layout may have changed")
        return (0, 1)
    try:
        findings = discover_findings(u.fetch_html(FOC_URL))
    except Exception as exc:  # the alerts still refresh without them
        logger.warning("uscg_safety_alert: Findings of Concern page failed: %s", exc)
        findings = []
    if not findings:
        logger.warning("uscg_safety_alert: no Findings of Concern listed")
    u.write_index(raw_dir, docs + findings)
    return u.fetch_docs(docs + findings, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return u.listing_source_date(raw_dir)


def parse_source(raw_dir: Path) -> list[Section]:
    return u.doc_sections(SOURCE, u.read_index(raw_dir), raw_dir)
