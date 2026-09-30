"""Waterway guidance for inland and harbor traffic (2026-09-30): the Coast Guard's
Vessel Traffic Service user manuals and the Eighth District's Waterways Action
Plans for the Mississippi River system.

Why: Lower Mississippi high-water and bridge-clearance questions had nothing to
cite. The VTS user manuals carry each VTS area's reporting points, VTS measures
and high-water procedures; the Waterways Action Plans carry the high-water and
low-water action levels, horsepower-per-barge and tow-size limits, and closure
procedures for the Lower Mississippi, Upper Mississippi, Ohio Valley, Illinois
and Missouri rivers. See docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

Listings:
  VTS  https://www.navcen.uscg.gov/vessel-traffic-services-locations — each VTS
       area has a "User Manual" link (a second, unlabeled link is skipped; for
       Prince William Sound it points at the previous edition)
  WAP  fixed URLs on atlanticarea.uscg.mil (no index page lists them all)

section_number: "VTS Lower Mississippi River User Manual",
"D8 WAP Lower Mississippi River Annex". The edition year is in the title.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "uscg_waterways"
TITLE_NUMBER = 0

VTS_URL = "https://www.navcen.uscg.gov/vessel-traffic-services-locations"

# Filename keyword -> VTS area name.
_VTS_AREAS: list[tuple[str, str]] = [
    ("LMR", "Lower Mississippi River"), ("NY", "New York"), ("SF", "San Francisco"),
    ("LALB", "Los Angeles-Long Beach"), ("PWS", "Prince William Sound"), ("PS", "Puget Sound"),
    ("HG", "Houston-Galveston"), ("SMR", "St. Marys River"), ("BerwickBay", "Berwick Bay"),
    ("Louisville", "Louisville"), ("Tampa", "Tampa"), ("PortArthur", "Port Arthur"),
]

_WAP_BASE = "https://www.atlanticarea.uscg.mil/Portals/7/Eigth%20District/"
_WAPS: list[tuple[str, str, str, str]] = [
    ("D8 WAP Lower Mississippi River Annex", "Sector Lower Mississippi River annex (2020)",
     _WAP_BASE + "Sector%20Lower%20Mississippi%20River/pdf/2020%20WAP%20Annex%20SLMR%20Final.pdf", "2020-06-04"),
    ("D8 WAP Ohio Valley", "Sector Ohio Valley, Mississippi River, Ohio River and tributaries (2021)",
     _WAP_BASE + "Waterways/docs/2021%20Sector%20Ohio%20Valley%20WAP.pdf", "2021-01-01"),
    ("D8 WAP Upper Mississippi River", "Sector Upper Mississippi River (2017)",
     _WAP_BASE + "SectorUMR/UMR%20WAP%202017.pdf", "2017-01-01"),
    ("D8 WAP Illinois Waterway", "Illinois Waterway annex (2017)",
     _WAP_BASE + "WesternRivers/docs/ILR_WAP_2017_Final.pdf", "2017-01-01"),
    ("D8 WAP Missouri River", "Missouri River annex (2017)",
     _WAP_BASE + "WesternRivers/docs/MOR_WAP_2017_Final.pdf", "2017-01-01"),
]


def _edition_year(filename: str) -> str | None:
    """"VTS LMR User Manual 2026 Final.pdf" -> "2026"; "…_210331.pdf" -> "2021"; "…May23.pdf" -> "2023"."""
    m = re.search(r"(19|20)\d{2}", filename)
    if m:
        return m.group(0)
    m = re.search(r"_(\d{2})\d{4}\.pdf$", filename) or re.search(r"[A-Za-z]{3}(\d{2})\.pdf$", filename)
    return f"20{m.group(1)}" if m else None


def discover(html_vts: str) -> list[u.Doc]:
    docs: dict[str, u.Doc] = {}
    for href, text in u.links(html_vts, VTS_URL):
        if not u.is_pdf_href(href) or "user manual" not in text.lower():
            continue
        filename = href.rsplit("/", 1)[-1].replace("%20", " ")
        compact = filename.replace(" ", "").replace("_", "")
        area = next((name for key, name in _VTS_AREAS if key.lower() in compact.lower()), None)
        if not area:
            logger.warning("uscg_waterways: unrecognized VTS manual %s", filename)
            continue
        year = _edition_year(filename)
        doc_id = f"VTS {area} User Manual"
        docs.setdefault(doc_id, u.Doc(
            doc_id=doc_id, title=f"Vessel Traffic Service {area} user manual" + (f" ({year} edition)" if year else ""),
            url=href, filename=u.safe_filename(doc_id), published=f"{year}-01-01" if year else None))
    for doc_id, title, url, published in _WAPS:
        docs.setdefault(doc_id, u.Doc(doc_id=doc_id, title=f"Eighth District Waterways Action Plan — {title}",
                                      url=url, filename=u.safe_filename(doc_id), published=published))
    return list(docs.values())


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = discover(u.fetch_html(VTS_URL))
    if len(docs) <= len(_WAPS):
        logger.warning("uscg_waterways: NAVCEN listed no VTS manuals; the page layout may have changed")
    u.write_index(raw_dir, docs)
    return u.fetch_docs(docs, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return u.listing_source_date(raw_dir)


def parse_source(raw_dir: Path) -> list[Section]:
    return u.doc_sections(SOURCE, u.read_index(raw_dir), raw_dir)
