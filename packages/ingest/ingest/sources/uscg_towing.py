"""Towing Vessel National Center of Expertise (TVNCOE): the Coast Guard's own
Subchapter M answers and guides (2026-09-30).

Why: "Subchapter M TSMS", "which subchapter applies", "what does the TPO audit"
and SCBA/CO2-by-subchapter questions hedged. TVNCOE publishes FAQ answers for
each Sub M part, the Uninspected Towing Vessel Guidebook and the applicability
flowchart; CG-CVC publishes the inspected towing vessel (ITV) inspector job aid
and CG-5R the small-entity compliance guide for the towing vessel rule. See
docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

The Sub M final rule preamble (81 FR 40003, 2016) is not included: several
hundred pages of comment responses would crowd the regulation text in
retrieval; the "Preamble" FAQ covers the points USCG chose to answer.

section_number: "Sub M FAQ Part 138", "Sub M FAQ Parts 1, 2 and 15",
"Sub M FAQ General", "Sub M FAQ Preamble", "TVNCOE UTV Guidebook",
"TVNCOE Subchapter Applicability Flowchart", "USCG ITV Inspector Job Aid",
"USCG Towing Vessel Rule Small Entity Guide".
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "uscg_towing"
TITLE_NUMBER = 0

_TVNCOE = "https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Traveling-Inspector-Staff-CG-5P-TI/Towing-Vessel-National-Center-of-Expertise/"
FAQ_URL = _TVNCOE + "SubMFAQs/"

# Documents not on the FAQ page: (doc_id, title, url, published).
_FIXED: list[tuple[str, str, str, str | None]] = [
    ("USCG ITV Inspector Job Aid", "Inspected Towing Vessel Inspector Job Aid (CG-CVC, November 2018)",
     "https://www.dco.uscg.mil/Portals/9/DCO%20Documents/5p/CG-5PC/CG-CVC/CVC1/tool/inspbk/ITV_Job_Aid_Nov_18.pdf",
     "2018-11-01"),
    ("USCG Towing Vessel Rule Small Entity Guide",
     "Small Entity Compliance Guide: Inspection of Towing Vessels (46 CFR Subchapter M)",
     "https://www.dco.uscg.mil/Portals/9/CG-5R/Small%20Entity%20Compliance%20Guides/Small%20Entities%20Guide-%20Towing%20Vessel%20Rule.pdf",
     "2018-06-04"),
]

_UPDATED = re.compile(r"\(\s*Last Updated\s*([^)]*)\)", re.I)


def _faq_id(text: str) -> str:
    """"Part 138 - Towing Safety Management System (TSMS)" -> "Sub M FAQ Part 138";
    "Parts - 1, 2 and 15" -> "Sub M FAQ Parts 1, 2 and 15"; "General" -> "Sub M FAQ General"."""
    text = _UPDATED.sub("", text).strip()
    m = re.match(r"^(Parts?)\s*-?\s*([\d ,and]+?)(?:\s+-\s+.*)?$", text, re.I)
    if m:
        return f"Sub M FAQ {m.group(1).title()} {re.sub(r'\s+', ' ', m.group(2)).strip()}"
    return f"Sub M FAQ {text.split(' - ')[0].strip()}"


def discover(html_faqs: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for href, text in u.links(html_faqs, FAQ_URL):
        # TVNCOE documents, plus per-part FAQs filed elsewhere (Part 143 is under
        # /CG-CVC/CVC1/towing/). The page chrome links unrelated PDFs (MSM Vol III,
        # a TSAC report) that match neither.
        if not u.is_pdf_href(href) or not text or "dco.uscg.mil" not in href:
            continue
        if "/TVNCOE/" not in href and not re.match(r"^Parts?\b", text):
            continue
        name = _UPDATED.sub("", text).strip()
        updated = _UPDATED.search(text)
        published = u.parse_date(updated.group(1)) if updated else None
        if "flowchart" in name.lower():
            doc_id, title = "TVNCOE Subchapter Applicability Flowchart", "Towing vessel subchapter applicability flowchart (C, M, I, D, L, T, H, K)"
        elif "guidebook" in name.lower():
            doc_id, title = "TVNCOE UTV Guidebook", "Requirements for Uninspected Towing Vessels (Subchapter C) — TVNCOE guidebook"
        else:
            doc_id = _faq_id(text)
            topic = name.split(" - ", 1)[1] if " - " in name else name
            title = f"Coast Guard answers to Subchapter M questions — {topic}"
        docs.setdefault(doc_id, u.Doc(doc_id=doc_id, title=title, url=href,
                                      filename=u.safe_filename(doc_id), published=published))
    for doc_id, title, url, published in _FIXED:
        docs.setdefault(doc_id, u.Doc(doc_id=doc_id, title=title, url=url,
                                      filename=u.safe_filename(doc_id), published=published))
    return list(docs.values())


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = discover(u.fetch_html(FAQ_URL))
    if len(docs) <= len(_FIXED):
        logger.warning("uscg_towing: the FAQ page listed no documents; the layout may have changed")
    u.write_index(raw_dir, docs)
    return u.fetch_docs(docs, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return u.listing_source_date(raw_dir)


def parse_source(raw_dir: Path) -> list[Section]:
    return u.doc_sections(SOURCE, u.read_index(raw_dir), raw_dir)
