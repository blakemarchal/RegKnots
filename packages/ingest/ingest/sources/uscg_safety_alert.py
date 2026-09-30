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

# "10-10 (b)", "01-12(A)", "20-25 CH1"
_NUMBER = re.compile(r"^(\d{1,2}-\d{2})\s*(?:\(\s*([A-Za-z])\s*\))?\s*(?:CH\s*-?\s*0?(\d+))?", re.I)
# "USCGFOC_008-26.pdf", "USCGFOC_004_24.pdf", "USCGFOC_017_23_Corr01.pdf"
_FOC_FILE = re.compile(r"USCGFOC_(\d{3})[-_](\d{2})(?:_Corr0*(\d+))?\.pdf", re.I)
# the Findings table is paged: "?udt_40515_param_page=2"
_PAGER = re.compile(r"[?&]udt_\d+_param_page=\d+")


def _add(docs: dict[str, u.Doc], doc_id: str, title: str, url: str, published: str | None) -> None:
    """Keep every listed document. CG-INV reused numbers (01-17 is an advisory
    and a lessons-learned alert; 09-08 was issued in 1998, 2008 and 2009): a
    later one with the same number gets its date added to the id."""
    if doc_id in docs:
        if docs[doc_id].url == url:
            return
        doc_id = f"{doc_id} ({published or len(docs)})"
        if doc_id in docs:
            return
    docs[doc_id] = u.Doc(doc_id=doc_id, title=title, url=url, filename=u.safe_filename(doc_id),
                         published=published)


def discover(html: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for cells, links in u.rows(html, LIST_URL):
        pdfs = [h for h, _ in links if u.is_pdf_href(h)]
        if len(cells) < 3 or not pdfs:
            continue
        m = _NUMBER.match(cells[0])
        if not m:
            continue
        doc_id = (f"USCG SA {m.group(1)}" + (f"({m.group(2).lower()})" if m.group(2) else "")
                  + (f" CH-{m.group(3)}" if m.group(3) else ""))
        title = cells[2] if len(cells) >= 4 else cells[-1]
        published = u.parse_date(cells[-1])
        if published:
            title = f"{title} ({published})"
        _add(docs, doc_id, f"Coast Guard Safety Alert: {title}", pdfs[0], published)
    return list(docs.values())


def discover_findings(*pages: str) -> list[u.Doc]:
    """Findings of Concern from one or more pages of the (paged) table."""
    docs: dict[str, u.Doc] = {}
    for html in pages:
        for cells, links in u.rows(html, FOC_URL):
            pdfs = [h for h, _ in links if u.is_pdf_href(h)]
            m = _FOC_FILE.search(pdfs[0]) if pdfs else None
            if len(cells) < 3 or not m:
                continue
            doc_id = f"USCG FOC {m.group(1)}-{m.group(2)}"
            published = u.parse_date(cells[-1])
            title = cells[1] + (f" ({published})" if published else "")
            if m.group(3):
                title += f" (correction {m.group(3)})"
            _add(docs, doc_id, f"Coast Guard Finding of Concern: {title}", pdfs[0], published)
    return list(docs.values())


def finding_pages(html: str) -> list[str]:
    """URLs of the Findings table's other pages, from page 1's pager links."""
    pages = {absolute for absolute, _ in u.links(html, FOC_URL) if _PAGER.search(absolute)}
    return sorted(pages)


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = discover(u.fetch_html(LIST_URL))
    if not docs:
        logger.warning("uscg_safety_alert: no alerts listed; the page layout may have changed")
        return (0, 1)
    try:
        with u.client() as http:
            first = u.fetch_html(FOC_URL, http)
            findings = discover_findings(first, *[u.fetch_html(url, http) for url in finding_pages(first)])
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
