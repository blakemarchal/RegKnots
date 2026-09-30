"""2026-09-30 — NVIC discovery takes the versioned links USCG now serves, and a
prune removes the rows of a cancelled NVIC (nvic.RETIRED)."""
import asyncio
from types import SimpleNamespace

from bs4 import BeautifulSoup

from ingest import prune
from ingest.sources import nvic

DECADE_PAGE = """
<table>
  <tr><th>Number</th><th>Description</th></tr>
  <tr><td>03-16 (CH-7)</td><td><a href="/Portals/9/DCO Documents/5p/5ps/MMC/CG-MMC-2 Policies/NVIC 03-16 Towing (Incl CH-7) 20240909.pdf?ver=i23b">CH-7 Guidelines for Credentialing Officers of Towing Vessels, NVIC 03-16, COMDTPUB 16721</a></td></tr>
  <tr><td>01-14</td><td>Cancelled/Superseded by Merchant Mariner Medical Manual (COMDTINST M16721.48)</td></tr>
  <tr><td>07-14 (CH-8)</td><td><a href="/Portals/9/DCO%20Documents/5p/5ps/NVIC/2014/NVIC%2007-14.pdf?ver=abc&amp;timestamp=1">CH-7 to Guidelines for Qualification for STCW Endorsements as Rating Forming Part of a Navigational Watch</a></td></tr>
  <tr><td>02-19</td><td><a href="/Portals/9/DCO%20Documents/5p/5ps/NVIC/2019/NVIC_02-19.pdf">Guidelines on Towing Vessel Stability</a></td></tr>
</table>
"""


def _discover(html):
    metas, seen = [], set()
    nvic._extract_table_nvics(BeautifulSoup(html, "lxml"), metas, seen)
    return {m.number: m for m in metas}


def test_versioned_and_spaced_links_are_discovered():
    found = _discover(DECADE_PAGE)
    assert set(found) == {"03-16", "07-14", "02-19"}  # 01-14 is cancelled
    url = found["03-16"].pdf_url
    assert url.startswith("https://www.dco.uscg.mil/Portals/9/DCO%20Documents/")
    assert " " not in url and url.endswith("20240909.pdf?ver=i23b")
    assert found["03-16"].title.startswith("CH-7 Guidelines for Credentialing Officers of Towing Vessels")


def test_link_check_ignores_non_pdf_and_other_hosts():
    tag = BeautifulSoup('<p><a href="/NVIC/Year/2010/">page</a>'
                        '<a href="https://example.com/x.pdf">elsewhere</a></p>', "lxml")
    assert nvic._find_pdf_link_in_tag(tag) is None


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        return self.rows


def _row(sec, idx=0):
    return {"id": f"{sec}#{idx}", "section_number": sec, "chunk_index": idx, "created": "2026-04-18"}


def test_prune_retires_a_cancelled_nvic_but_keeps_other_absent_ones():
    stored = [_row("NVIC 04-08 Ch-2"), _row("NVIC 04-08 Ch-2 Encl.1", 3),  # cancelled: retire
              _row("NVIC 07-68 §4"),                                     # absent this run: keep
              _row("NVIC 02-19")]
    chunks = [SimpleNamespace(section_number="NVIC 02-19", chunk_index=0)]
    report = asyncio.run(prune.build_report(_Pool(stored), "nvic", chunks, nvic.prune_scope))
    assert sorted(r["section_number"] for r in report.stale) == ["NVIC 04-08 Ch-2", "NVIC 04-08 Ch-2 Encl.1"]
    assert report.kept_out_of_scope == {"NVIC 07-68": 1}
