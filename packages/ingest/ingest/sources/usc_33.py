"""33 USC, the maritime chapters (2026-09-30).

Why: the statutes behind COFRs, oil spill liability, marine sanitation devices,
bridge-to-bridge radio and wreck removal were not in the corpus (46 USC is).
Kept (by section number):

  §§ 401–467    Rivers and Harbors Act and related provisions (chapter 9):
                obstructions, the Refuse Act (§ 407), sunken vessels and
                wreck marking and removal (§§ 409, 414, 415)
  §§ 1201–1208  Vessel Bridge-to-Bridge Radiotelephone Act (chapter 24)
  §§ 1321–1322  Clean Water Act § 311 (oil and hazardous substance liability,
                discharge reporting) and § 312 (marine sanitation devices)
  §§ 1901–1915  Act to Prevent Pollution from Ships (MARPOL implementation)
  §§ 2701–2762  Oil Pollution Act of 1990 (chapter 40: responsible parties,
                limits of liability, financial responsibility / COFR)

The Ports and Waterways Safety Act moved to 46 USC chapter 700 in 2018 and is
in usc_46. See docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4.

Source: the House Office of the Law Revision Counsel release point
(xml_usc33@<release>.zip from https://uscode.house.gov/download/download.shtml),
found fresh on each run. Parsed with the usc_46 walker; section_number
"33 USC 1321", parent "33 USC Chapter 26 — …".
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from ingest.models import Section
from ingest.sources import usc_46
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "usc_33"
TITLE_NUMBER = 0
DOWNLOAD_PAGE = "https://uscode.house.gov/download/download.shtml"
XML_NAME = "usc33.xml"

_KEEP: list[tuple[int, int]] = [(401, 467), (1201, 1208), (1321, 1322), (1901, 1915), (2701, 2762)]


def in_scope(section_number: str) -> bool:
    m = re.match(r"33 USC (\d+)", section_number or "")
    return bool(m) and any(lo <= int(m.group(1)) <= hi for lo, hi in _KEEP)


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with u.client() as http:
        page = u.fetch_html(DOWNLOAD_PAGE, http)
        m = re.search(r'href="([^"]*xml_usc33@([0-9-]+)\.zip)"', page)
        if not m:
            logger.warning("usc_33: no xml_usc33 link on %s", DOWNLOAD_PAGE)
            return (1, 0) if (raw_dir / XML_NAME).exists() else (0, 1)
        url, release = u.absolute(m.group(1), DOWNLOAD_PAGE), m.group(2)
        index = raw_dir / "index.json"
        current = json.loads(index.read_text(encoding="utf-8")).get("release") if index.exists() else None
        if current == release and (raw_dir / XML_NAME).exists():
            return (1, 0)
        try:
            resp = http.get(url)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
                (raw_dir / XML_NAME).write_bytes(zf.read(name))
        except Exception as exc:
            logger.warning("usc_33: download of %s failed — %s", url, exc)
            return (1, 1) if (raw_dir / XML_NAME).exists() else (0, 1)
    index.write_text(json.dumps({"release": release, "url": url}), encoding="utf-8")
    if console:
        console.print(f"  [cyan]usc_33:[/cyan] release point {release}")
    return (1, 0)


def _created(root: ET.Element) -> date:
    """The release point's creation date from the XML meta (dcterms:created)."""
    for el in root.iter():
        if el.tag.endswith("}created") and el.text:
            try:
                return date.fromisoformat(el.text.strip()[:10])
            except ValueError:
                break
    return date.today()


def get_source_date(raw_dir: Path) -> date:
    path = raw_dir / XML_NAME
    return _created(ET.parse(path).getroot()) if path.exists() else date.today()


def parse_source(raw_dir: Path) -> list[Section]:
    path = raw_dir / XML_NAME
    if not path.exists():
        raise FileNotFoundError(f"33 USC XML not found: {path}")
    root = ET.parse(path).getroot()
    as_of = _created(root)
    sections: list[Section] = []
    usc_46._walk_for_sections(usc_46._find_title(root), sections, None, title=33, source=SOURCE, as_of=as_of)
    kept = [s for s in sections if in_scope(s.section_number)]
    logger.info("usc_33: kept %d of %d non-repealed sections (as of %s)", len(kept), len(sections), as_of)
    return kept
