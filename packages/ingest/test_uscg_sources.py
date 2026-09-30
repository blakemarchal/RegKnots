"""2026-09-30 — the inland / Coast Guard sources: listing-page discovery,
download bookkeeping, text cleanup and document splitting (no network)."""
import json
from pathlib import Path

import pytest

from ingest import cfr_scope, models
from ingest.sources import (epa_vgp, nmc, usc_33, uscg_cvc, uscg_docs as u, uscg_msm,
                            uscg_safety_alert, uscg_towing, uscg_waterways)


# ── uscg_docs ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,iso", [
    ("9/23/2026", "2026-09-23"), ("2026-09-23", "2026-09-23"), ("01Jun26", "2026-06-01"),
    ("22APR24", "2024-04-22"), ("14 July 2026", "2026-07-14"), ("July 14, 2026", "2026-07-14"),
    ("(Last Updated 04/30/2024)", "2024-04-30"), ("N/A", None), ("", None),
])
def test_parse_date(text, iso):
    assert u.parse_date(text) == iso


def test_pdf_links_with_versions_and_spaces():
    assert u.is_pdf_href("/x/NVIC 03-16.pdf?ver=a%3d") and u.is_pdf_href("a.PDF#page=2")
    assert not u.is_pdf_href("/NVIC/Year/2010/")
    assert u.absolute("/Portals/9/A B.pdf?ver=1", "https://www.dco.uscg.mil/x/") == \
        "https://www.dco.uscg.mil/Portals/9/A%20B.pdf?ver=1"


def test_clean_text_drops_page_furniture_and_untriples_bold():
    pages = [f"COMDTINST M16721.48\nChapter text {i}\nPage {i} of 5\nContents ........ 3" for i in range(5)]
    pages[0] += "\nTTTOOOWWWIIINNNGGG OOOFFFFFFIIICCCEEERRR\nsweeping"
    out = u.clean_text("\f".join(pages))
    assert "COMDTINST M16721.48" not in out          # running header on every page
    assert "Page 1 of 5" not in out and "........" not in out
    assert "TOWING OFFICER" in out and "sweeping" in out and "Chapter text 3" in out


def test_fetch_docs_redownloads_only_when_the_listed_url_changes(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, path, http=None):
        calls.append(url)
        path.write_bytes(b"%PDF-1.4")
        return True

    monkeypatch.setattr(u, "download_file", fake_download)
    monkeypatch.setattr(u, "REQUEST_DELAY", 0)
    doc = u.Doc(doc_id="A", title="t", url="https://x/a.pdf?ver=1", filename="a.pdf")
    assert u.fetch_docs([doc], tmp_path, tmp_path / "failed", "s") == (1, 0)
    assert u.fetch_docs([doc], tmp_path, tmp_path / "failed", "s") == (1, 0)
    doc.url = "https://x/a.pdf?ver=2"
    u.fetch_docs([doc], tmp_path, tmp_path / "failed", "s")
    assert calls == ["https://x/a.pdf?ver=1", "https://x/a.pdf?ver=2"]


def test_a_listing_that_shrinks_by_half_keeps_the_saved_index(tmp_path):
    docs = [u.Doc(doc_id=f"D{i}", title="t", url=f"https://x/{i}.pdf", filename=f"{i}.pdf") for i in range(10)]
    u.write_index(tmp_path, docs)
    u.write_index(tmp_path, docs[:4])          # a broken page, not six withdrawals
    assert len(u.read_index(tmp_path)) == 10
    u.write_index(tmp_path, docs[:8])          # two withdrawn
    assert [d.doc_id for d in u.read_index(tmp_path)] == [f"D{i}" for i in range(8)]


def test_listing_sources_always_parse_on_update(tmp_path):
    # store.get_previous_as_of reads one arbitrary row; a document date could
    # skip a new letter dated only by year. Hash dedup finds the changes.
    from datetime import date
    for adapter in (uscg_cvc, uscg_towing, uscg_safety_alert, uscg_waterways):
        assert adapter.get_source_date(tmp_path) == date.today()


def test_a_failed_download_keeps_parsing_the_old_copy(tmp_path, monkeypatch):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-old")
    (tmp_path / "downloaded.json").write_text(json.dumps({"a.pdf": "https://x/a.pdf?ver=1"}))
    monkeypatch.setattr(u, "download_file", lambda url, path, http=None: False)
    doc = u.Doc(doc_id="A", title="t", url="https://x/a.pdf?ver=2", filename="a.pdf")
    assert u.fetch_docs([doc], tmp_path, tmp_path / "failed", "s") == (1, 1)
    assert (tmp_path / "failed" / "s_A.json").exists()


# ── uscg_cvc ─────────────────────────────────────────────────────────────────

LETTERS = """<table><tr><th>Number</th><th>Program</th><th>Subject</th></tr>
<tr><td>21-03</td><td>CG-CVC</td><td><a href="/p/2021/CG-CVC 21-03.pdf">Use of Doublers on Towing Vessels</a></td></tr>
<tr><td>23-05(CH1)</td><td>CG-CVC</td><td><a href="/p/23-05.pdf?ver=x">(Supersedes Policy Letter 23-05)>Guidance on Surveillance</a></td></tr>
<tr><td>20-02</td><td>CG-CVC</td><td><a href="/p/20-02.pdf">High Risk SPVs (Canceled)</a></td></tr>
<tr><td>18-01 (CH 2)</td><td>CG-CVC</td><td><a href="/p/18-01.pdf">(Cancelled: Incorporated into CG CVC-WI-013(7)</a></td></tr>
<tr><td>17-08 (E1)</td><td>CG-CVC</td><td><a href="/p/17-08E1.pdf">Enclosure 1 For 2017-08</a></td></tr>
<tr><td>15-03</td><td>CG-CVC</td><td><a href="/p/15-03.pdf">Crediting Recent Service</a></td></tr>
<tr><td>99-03</td><td>CG-MOC</td><td><a href="/p/99-03.pdf">Emergency Control Systems for Tank Barges</a></td></tr>
</table>"""
MMS = """<table><tr><th>Serial Number</th><th>Title</th><th>Category</th><th>Issue Date</th><th>Revision Date</th></tr>
<tr><td><a href="/m/CVC-WI-013(8).pdf">CVC-WI-013(8)</a></td><td>Initial Towing Vessel COI Inspection under TSMS Option</td><td>Domestic Inspection Program</td><td>18SEP18</td><td>06NOV23</td></tr>
<tr><td><a href="/m/CVC-FM-840K(3).pdf">CVC-FM-840K(3)</a></td><td>K-Boat Checklist (Long)</td><td>Domestic Vessel Inspection</td><td>04 February 21</td><td>February 2026</td></tr>
</table>"""


def test_cvc_discovery_keeps_current_letters_and_work_instructions():
    docs = {d.doc_id: d for d in uscg_cvc.discover(LETTERS, MMS)}
    assert set(docs) == {"CG-CVC PL 21-03", "CG-CVC PL 23-05 CH-1", "CG-CVC PL 17-08 Encl.1",
                         "CG-MOC PL 99-03", "CVC-WI-013", "CVC-FM-840K"}
    assert docs["CG-CVC PL 23-05 CH-1"].note == "Supersedes Policy Letter 23-05"
    assert docs["CG-CVC PL 23-05 CH-1"].title == "Guidance on Surveillance"
    assert docs["CG-MOC PL 99-03"].published == "1999-01-01"
    assert docs["CVC-WI-013"].published == "2023-11-06" and docs["CVC-WI-013"].note == "revision 8"
    assert docs["CVC-FM-840K"].published == "2021-02-04"   # "February 2026" has no day
    assert docs["CG-CVC PL 21-03"].url.endswith("/p/2021/CG-CVC%2021-03.pdf")


# ── uscg_safety_alert ────────────────────────────────────────────────────────

def test_safety_alert_discovery():
    html = """<table><tr><td>Number</td><td>Safety Alert</td><td>Title</td><td>Date</td></tr>
    <tr><td>15-26</td><td><a href="/a/USCGSA_1526.pdf">USCGSA_1526.pdf</a></td><td>Retractable Pilot Houses on Towing Vessels</td><td>9/23/2026</td></tr>
    <tr><td>20-25 CH1</td><td><a href="/a/USCGSA_2025CH1.pdf">x</a></td><td>EGR Cooler Weld</td><td>6/2/2026</td></tr>
    <tr><td>SA-101</td><td><a href="/a/SA-101.aspx">SA-101.aspx</a></td><td>NTSB alert</td><td>9/10/2025</td></tr></table>"""
    docs = {d.doc_id: d for d in uscg_safety_alert.discover(html)}
    assert set(docs) == {"USCG SA 15-26", "USCG SA 20-25 CH-1"}
    assert docs["USCG SA 15-26"].title.endswith("Retractable Pilot Houses on Towing Vessels (2026-09-23)")
    assert docs["USCG SA 15-26"].published == "2026-09-23"


def test_findings_of_concern_discovery():
    html = """<table>
    <tr><td><a href="/Portals/9/DCO Documents/5p/CG-5PC/INV/foc/USCGFOC_008-26.pdf">USCGFOC_008-26.pdf</a></td>
        <td>Risks Associated With Unmanned (Autonomous) Vessel Operations</td><td>9/29/2026</td></tr>
    <tr><td><a href="/Portals/9/DCO Documents/5p/CG-5PC/INV/foc/USCGFOC_006-26.pdf">USCGFOC_006-26.pdf</a></td>
        <td>Improper Electrical Heating Practices Create Lifeboat Fire Risk</td><td>9/15/2026</td></tr>
    <tr><td><a href="/Portals/9/x/Some_Other.pdf">x</a></td><td>not a finding</td><td>1/1/2020</td></tr></table>"""
    docs = uscg_safety_alert.discover_findings(html)
    assert [d.doc_id for d in docs] == ["USCG FOC 008-26", "USCG FOC 006-26"]
    assert docs[1].title == "Coast Guard Finding of Concern: Improper Electrical Heating Practices Create Lifeboat Fire Risk (2026-09-15)"
    assert docs[0].url.endswith("/INV/foc/USCGFOC_008-26.pdf") and " " not in docs[0].url


# ── uscg_towing ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,doc_id", [
    ("Part 138 - Towing Safety Management System (TSMS) (Last Updated 10/09/2020)", "Sub M FAQ Part 138"),
    ("Parts - 1, 2 and 15 (Last Updated 10/09/2020)", "Sub M FAQ Parts 1, 2 and 15"),
    ("Parts 141 and 199 (Last Updated 7/11/2023)", "Sub M FAQ Parts 141 and 199"),
    ("General (Last Updated 10/09/2020)", "Sub M FAQ General"),
])
def test_faq_ids(text, doc_id):
    assert uscg_towing._faq_id(text) == doc_id


def test_towing_discovery_takes_faqs_filed_elsewhere_but_not_page_chrome():
    html = """<a href="/Portals/9/TVNCOE/Documents/SubMFAQs/Part%20136.pdf">Part 136 - Certification (Last Updated 10/09/2020)</a>
    <a href="/Portals/9/DCO%20Documents/5p/CG-5PC/CG-CVC/CVC1/towing/Part%20143.pdf">Part 143 - Machinery (Last Updated 04/30/2024)</a>
    <a href="https://media.defense.gov/x/CCN_16000.PDF">Marine Safety Manual Volume III</a>
    <a href="/Portals/9/TVNCOE/Documents/ToolBag/UTVGUIDEBOOK.pdf">Uninspected Towing Vessel Guidebook</a>"""
    ids = [d.doc_id for d in uscg_towing.discover(html)]
    assert ids[:3] == ["Sub M FAQ Part 136", "Sub M FAQ Part 143", "TVNCOE UTV Guidebook"]
    assert len(ids) == 3 + len(uscg_towing._FIXED)


# ── uscg_waterways ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,year", [
    ("VTS LMR User Manual 2026 Final.pdf", "2026"), ("VTS_LALB_UserManual_210331.pdf", "2021"),
    ("VTS_PortArthur_User Manual_May23.pdf", "2023"), ("VTS_SMR_UserManual (2020).pdf", "2020"),
])
def test_edition_year(name, year):
    assert uscg_waterways._edition_year(name) == year


def test_waterways_discovery_takes_one_manual_per_area():
    base = "/sites/default/files/pdf/VTS User Guides/"
    html = (f'<a href="{base}2026 VTS PWS User\'s Manual (15th Edition).pdf">User Manual</a>'
            f'<a href="{base}VTS_PWS_UserManual (2024_14thEd).pdf"></a>'
            f'<a href="{base}VTS_PS_UsersManual_(2024).pdf">User Manual</a>'
            f'<a href="{base}VTS_HG_UserManual_2025.pdf">User Manual</a>')
    docs = {d.doc_id: d for d in uscg_waterways.discover(html)}
    assert {"VTS Prince William Sound User Manual", "VTS Puget Sound User Manual",
            "VTS Houston-Galveston User Manual"} <= set(docs)
    assert "2026" in docs["VTS Prince William Sound User Manual"].url
    assert len(docs) == 3 + len(uscg_waterways._WAPS)


# ── epa_vgp ──────────────────────────────────────────────────────────────────

def test_vgp_split_uses_body_headings_and_state_level_part_6():
    text = "\n".join([
        "2.2.3 Ballast Water", "2.2.5 Aqueous Film Forming Foam (AFFF)",    # table of contents
        "2.2.3 Ballast Water", "All discharges of ballast water must comply with the requirements below.",
        "2.2.5 Aqueous Film Forming Foam (AFFF)", "Discharges of AFFF are not authorized except in an emergency.",
        "6.25 Wisconsin", "6.25.1 The permittee shall allow WDNR reasonable entry onto the premises.",
        "Appendix A — Definitions", "Annual report means the report required in Part 4.4 of this permit.",
    ])
    doc = u.Doc(doc_id=epa_vgp.DOC_ID, title="", url="", filename="")
    parts = {num: body for num, _, body in epa_vgp.split_sections(doc, text)}
    assert list(parts) == ["EPA 2013 VGP 2.2.3", "EPA 2013 VGP 2.2.5", "EPA 2013 VGP 6.25", "EPA 2013 VGP App.A"]
    assert parts["EPA 2013 VGP 2.2.3"].startswith("All discharges of ballast water")
    assert "6.25.1 The permittee" in parts["EPA 2013 VGP 6.25"]


# ── usc_33, CFR scope, titles ────────────────────────────────────────────────

def test_usc_33_scope():
    assert usc_33.in_scope("33 USC 1321") and usc_33.in_scope("33 USC 2716a")
    assert usc_33.in_scope("33 USC 409") and usc_33.in_scope("33 USC 1203")
    assert not usc_33.in_scope("33 USC 1251") and not usc_33.in_scope("33 USC 901")


def test_scoped_titles():
    assert cfr_scope.in_scope("cfr_40", "40 CFR 139.21") and not cfr_scope.in_scope("cfr_40", "40 CFR 112.7")
    assert cfr_scope.in_scope("cfr_29", "29 CFR 1918.2") and not cfr_scope.in_scope("cfr_29", "29 CFR 1910.134")
    assert cfr_scope.PART_FETCH <= set(cfr_scope.CFR_PART_SCOPE) and "cfr_49" not in cfr_scope.PART_FETCH
    assert models.SOURCE_TO_TITLE["cfr_47"] == 47 and models.title_name("cfr_47", 47) == "Title 47—Telecommunication"
    assert models.title_name("nvic", 0) == "nvic"


# ── NMC checklists, Medical Manual ───────────────────────────────────────────

def test_checklist_discovery_lists_every_checklist_and_the_toars(tmp_path, monkeypatch):
    page = ('<a href="/Portals/9/NMC/pdfs/checklists/mcp_fm_nmc5_28_web.pdf?ver=a">National Mate Pilot of Towing</a>'
            '<a href="/Portals/9/NMC/pdfs/checklists/mcp_fm_nmc5_56_web.pdf">National Entry Level Ratings</a>'
            '<a href="/nmc/forms/">Forms</a>')
    monkeypatch.setattr(u, "fetch_html", lambda url, http=None: page)
    fetched = []
    monkeypatch.setattr(u, "fetch_docs", lambda docs, *a, **k: fetched.extend(docs) or (len(docs), 0))
    nmc.discover_and_download_checklists(tmp_path, tmp_path / "failed")
    index = nmc._checklist_index(tmp_path)
    assert index["mcp_fm_nmc5_28_web.pdf"] == {"doc_id": "MCP-FM-NMC5-28", "title": "National Mate Pilot of Towing"}
    assert index["WesternRivers_toar.pdf"]["doc_id"] == "TOAR Western Rivers"
    assert len(fetched) == 2 + len(nmc._TOARS)
    assert {"mcp_fm_nmc5_56_web.pdf", "WesternRivers_toar.pdf", "mcp_fm_nmc5_01_web.pdf"} <= nmc._files_for("nmc_checklist", tmp_path)


def test_medical_manual_splits_at_upper_case_chapter_headings_only():
    opts = uscg_msm._DOC_OPTIONS["CIM_16721_48.pdf"]
    text = ("Chapter 12: Cardiovascular Conditions ........ 111\n"          # table of contents
            "CHAPTER 12. CARDIOVASCULAR CONDITIONS\nSee Chapter 7 of this Manual for medications.\n"
            "CHAPTER 13. EAR, NOSE, AND THROAT CONDITIONS\nHearing loss guidance.")
    parts = uscg_msm._split_into_chapters(text, "M16721.48", "Merchant Mariner Medical Manual",
                                          prefix=opts["prefix"], chapter_re=opts["chapter_re"])
    assert [p[0] for p in parts] == ["COMDTINST M16721.48 Ch.12", "COMDTINST M16721.48 Ch.13"]
    assert "Chapter 7 of this Manual" in parts[0][2]
    assert parts[1][1] == "Merchant Mariner Medical Manual — Ch.13 EAR, NOSE, AND THROAT CONDITIONS"
