"""IMO resolution harvester (2026-10-13): index parsing, selection, routing,
dates, parents and revocations. No network, no database."""
from datetime import date

from ingest import imo_harvest as h
from ingest.sources import imo_codes

_PAGE = """
<html><body>
<!-- <table><tr><td><a href="x.pdf">MSC.1(1)</a></td><td>OLD COMMENTED ROW</td></tr></table> -->
<h3>MSC 111, 2026</h3>
<table><tbody>
<tr><td style="width:20%;"><strong>
  <a href="https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.599(111).pdf">MSC.599(111)</a>
</strong></td><td>AMENDMENTS TO THE WORLDWIDE RADIONAVIGATION SYSTEM (RESOLUTION A.1046(27))</td></tr>
<tr><td><strong><a href="https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.589(111).pdf">MSC.589(111)</a></strong></td>
  <td>AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE | AWAITING CERTIFICATION</td></tr>
<tr><td><strong>MSC.582(111)</strong></td><td>ACTIONS TO ENSURE THE SAFETY AND SECURITY OF NAVIGATION</td></tr>
<tr><td><a href="https://wwwcdn.imo.org/x/A.1019(26).pdf">A.1019(26)</a></td>
  <td>AMENDMENTS TO THE CODE FOR THE IMPLEMENTATION OF MANDATORY IMO INSTRUMENTS, 2007 | Revoked by A.1054(27)</td></tr>
</tbody></table>
</body></html>
"""


def test_index_page_rows_flags_and_notes():
    rows = {r.code: r for r in h.parse_index_page(_PAGE)}
    assert set(rows) == {"MSC.599(111)", "MSC.589(111)", "MSC.582(111)", "A.1019(26)"}  # comment ignored
    assert rows["MSC.599(111)"].pdf_url.endswith("MSC.599(111).pdf")
    assert rows["MSC.599(111)"].session == 111 and rows["MSC.599(111)"].number == 599
    assert rows["MSC.589(111)"].awaiting is True
    assert rows["MSC.589(111)"].title == "AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE"
    assert rows["MSC.582(111)"].pdf_url == ""
    assert rows["A.1019(26)"].notes == "Revoked by A.1054(27)"


def test_biennium_pages_oldest_first():
    top = ('<a href="/en/knowledgecentre/indexofimoresolutions/pages/msc-2026-27.aspx">x</a>'
           '<a href="/en/knowledgecentre/indexofimoresolutions/pages/msc-2024-25.aspx">x</a>'
           '<a href="/en/knowledgecentre/indexofimoresolutions/pages/MEPC.aspx">x</a>'
           '<a href="/en/knowledgecentre/indexofimoresolutions/pages/msc.aspx">x</a>')
    assert h.biennium_pages(top, "MSC") == ["msc-2024-25.aspx", "msc-2026-27.aspx"]
    assert h.biennium_pages('<a href="/en/knowledgecentre/indexofimoresolutions/pages/a-2025-27.aspx">',
                            "A") == ["a-2025-27.aspx"]


def test_routes():
    assert h.route("MSC", "AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE") == "lsa"
    assert h.route("MSC", "AMENDMENTS TO PART A OF THE SEAFARERS' TRAINING, CERTIFICATION AND WATCHKEEPING (STCW) CODE") == "stcw_amend"
    assert h.route("MEPC", "AMENDMENTS TO THE ANNEX OF THE PROTOCOL OF 1997 TO AMEND THE INTERNATIONAL CONVENTION "
                           "FOR THE PREVENTION OF POLLUTION FROM SHIPS") == "marpol_amend"
    assert h.route("MEPC", "AMENDMENTS TO THE NOx TECHNICAL CODE 2008") == "marpol_amend"
    # guidelines that mention MARPOL are not amendments to it
    assert h.route("MEPC", "2024 GUIDELINES AS REQUIRED BY REGULATION 13.2.2 OF MARPOL ANNEX VI") == "mepc_res"
    assert h.route("MEPC", "2024 AMENDMENTS TO THE INTERNATIONAL CONVENTION FOR THE CONTROL AND MANAGEMENT OF "
                           "SHIPS' BALLAST WATER AND SEDIMENTS, 2004") == "bwm"
    assert h.route("MSC", "AMENDMENTS TO CHAPTERS IV and V OF SOLAS") == "msc_res"
    assert h.route("A", "PROCEDURES FOR PORT STATE CONTROL, 2025") == "msc_res"
    assert h.parent_label("msc_res", "A") == "IMO Assembly Resolution"
    assert h.parent_label("lsa", "MSC") == "IMO LSA Code"


def test_administrative_titles():
    for title in ("RESULTS-BASED BUDGET FOR THE 2026-2027 BIENNIUM", "ARREARS OF CONTRIBUTIONS",
                  "RULES OF PROCEDURE OF THE ASSEMBLY", "APPRECIATION OF THE SERVICES TO THE ORGANIZATION OF MR. K. LIM",
                  "RELATIONS WITH NON-GOVERNMENTAL ORGANIZATIONS"):
        assert h.is_administrative(title), title
    for title in ("PROCEDURES FOR PORT STATE CONTROL, 2025", "GUIDELINES FOR VESSEL TRAFFIC SERVICES",
                  "INTEGRATED IMO IDENTIFICATION NUMBER SCHEME", "CODE ON ALERTS AND INDICATORS, 2025"):
        assert not h.is_administrative(title), title


def _e(code, title, notes=""):
    body, number, session = h.parse_code(code)
    return h.IndexEntry(code=code, body=body, number=number, session=session, title=title,
                        pdf_url=f"https://cdn/{code}.pdf", awaiting=False, notes=notes)


def test_window_chain_and_consolidated():
    # window: late 2021 on
    assert h.selection_reason(_e("MSC.583(111)", "AMENDMENTS TO SOLAS")) == "window"
    assert h.selection_reason(_e("MSC.494(103)", "PERFORMANCE STANDARDS FOR VDRs")) is None
    # chain: amendments to a code, from 2005
    assert h.selection_reason(_e("MSC.218(82)", "AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE")) == "chain"
    assert h.selection_reason(_e("MSC.150(77)", "AMENDMENTS TO THE LSA CODE")) is None
    # our consolidated editions already hold these
    assert h.consolidated(_e("MSC.496(105)", "AMENDMENTS TO THE INTERNATIONAL CONVENTION FOR THE SAFETY OF LIFE AT SEA, 1974"))
    assert not h.consolidated(_e("MSC.521(106)", "AMENDMENTS TO THE INTERNATIONAL CONVENTION FOR THE SAFETY OF LIFE AT SEA, 1974"))
    assert h.consolidated(_e("MSC.556(108)", "AMENDMENTS TO THE INTERNATIONAL MARITIME DANGEROUS GOODS (IMDG) CODE"))
    assert not h.consolidated(_e("MSC.587(111)", "AMENDMENTS TO THE INTERNATIONAL MARITIME DANGEROUS GOODS (IMDG) CODE"))
    assert h.consolidated(_e("MSC.417(97)", "AMENDMENTS TO PART A OF THE SEAFARERS' TRAINING, CERTIFICATION AND WATCHKEEPING (STCW) CODE"))
    assert not h.consolidated(_e("MSC.487(103)", "AMENDMENTS TO PART A OF THE SEAFARERS' TRAINING, CERTIFICATION AND WATCHKEEPING (STCW) CODE"))
    # STCW-F is its own convention
    assert not h.consolidated(_e("MSC.561(108)", "AMENDMENTS TO THE ANNEX TO THE INTERNATIONAL CONVENTION ON STANDARDS "
                                                  "OF TRAINING, CERTIFICATION AND WATCHKEEPING FOR FISHING VESSEL PERSONNEL"))


def test_plan_skips_and_keeps():
    index = {e.code: e for e in (
        _e("MSC.589(111)", "AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE"),
        _e("MSC.576(110)", "PERFORMANCE STANDARDS FOR PILOT TRANSFER ARRANGEMENTS"),
        _e("A.1200(34)", "RESULTS-BASED BUDGET FOR THE 2026-2027 BIENNIUM"),
        _e("MSC.496(105)", "AMENDMENTS TO THE INTERNATIONAL CONVENTION FOR THE SAFETY OF LIFE AT SEA, 1974"),
        _e("A.1019(26)", "AMENDMENTS TO THE CODE FOR THE IMPLEMENTATION OF MANDATORY IMO INSTRUMENTS, 2007",
           notes="Revoked by A.1054(27)"),
        _e("MSC.221(82)", "AMENDMENTS TO THE INTERNATIONAL CODE OF SAFETY FOR HIGH-SPEED CRAFT (1994 HSC CODE)",
           notes="Amends MSC.36(63)"),
    )}
    items, skipped = h.plan(index, in_corpus={"MSC.576(110)"}, manifest={})
    got = {i.code: i for i in items}
    assert set(got) == {"MSC.589(111)", "MSC.221(82)"}
    assert got["MSC.589(111)"].source == "imo_lsa" and got["MSC.589(111)"].reason == "window"
    assert got["MSC.221(82)"].source == "imo_hsc" and got["MSC.221(82)"].parent == "MSC.36(63)"
    assert skipped["in corpus"] == ["MSC.576(110)"]
    assert skipped["administrative"] == ["A.1200(34)"]
    assert skipped["in a consolidated edition"] == ["MSC.496(105)"]
    assert skipped["revoked or superseded"] == ["A.1019(26)"]


def test_plan_rechecks_certified():
    index = {"MSC.589(111)": _e("MSC.589(111)", "AMENDMENTS TO THE LSA CODE")}
    manifest = {"MSC.589(111)": {"code": "MSC.589(111)", "key": "lsa", "awaiting": True, "label": "IMO LSA Code"}}
    items, _ = h.plan(index, set(), manifest)
    assert [(i.code, i.reason, i.source) for i in items] == [("MSC.589(111)", "recertified", "imo_lsa")]
    manifest["MSC.589(111)"]["awaiting"] = False
    assert h.plan(index, set(), manifest)[0] == []


_SOLAS_AMENDMENT = """
RESOLUTION MSC.583(111) (adopted on 22 May 2026)
AMENDMENTS TO CHAPTERS IV AND V, AND THE APPENDIX OF THE INTERNATIONAL CONVENTION FOR THE SAFETY OF LIFE AT SEA, 1974
THE MARITIME SAFETY COMMITTEE,
NOTING that the amendments adopted by resolution MSC.520(106) entered into force on 1 January 2024,
1 ADOPTS, in accordance with article VIII(b)(iv) of the Convention, amendments to the Convention;
2 DETERMINES, in accordance with article VIII(b)(vi)(2)(bb) of the Convention, that the said amendments
shall be deemed to have been accepted on 1 July 2027 unless, prior to that date, ...
3 INVITES SOLAS Contracting Governments to note that, in accordance with article VIII(b)(vii)(2) of the
Convention, the amendments shall enter into force on 1 January 2028 upon their acceptance;
"""

_CODE_AMENDMENT = """
RESOLUTION MSC.575(110) (adopted on 26 June 2025)
AMENDMENTS TO THE INTERNATIONAL MARITIME SOLID BULK CARGOES (IMSBC) CODE
THE MARITIME SAFETY COMMITTEE,
NOTING resolution MSC.268(85), by which it adopted the International Maritime Solid Bulk Cargoes Code
(hereinafter referred to as "the IMSBC Code"), which has become mandatory under chapter VI of SOLAS,
1 ADOPTS amendments to the IMSBC Code, the text of which is set out in the annex;
2 DETERMINES that the said amendments shall enter into force on 1 January 2027;
"""

_REVISED_PROCEDURES = """
RESOLUTION A.1206(34) (adopted on 3 December 2025)
PROCEDURES FOR PORT STATE CONTROL, 2025
RECALLING resolution A.1185(33), by which it adopted the Procedures for Port State Control, 2023,
1 ADOPTS the Procedures for Port State Control, 2025;
4 REVOKES resolution A.1185(33).
"""


def test_dates():
    assert h.parse_dates(_SOLAS_AMENDMENT) == (date(2026, 5, 22), date(2028, 1, 1))
    assert h.parse_dates(_CODE_AMENDMENT) == (date(2025, 6, 26), date(2027, 1, 1))
    # a recital's past date is not this resolution's entry into force
    assert h.parse_dates("RESOLUTION MEPC.346(78) (adopted on 10 June 2022) NOTING that the amendments "
                         "entered into force on 1 November 2022, 1 ADOPTS the 2022 Guidelines") == (date(2022, 6, 10), None)
    # tacit acceptance only: in force six months later
    assert h.parse_dates("(adopted on 4 December 2013) 1 ADOPTS ... 2 DETERMINES that the amendments shall be "
                         "deemed to have been accepted on 1 July 2015 unless") == (date(2013, 12, 4), date(2016, 1, 1))
    assert h.status_text(date(2026, 5, 22), date(2028, 1, 1), True) == \
        "adopted 22 May 2026; entry into force 1 January 2028; certified text pending"
    assert h.status_text(date(2025, 12, 3), None, False) == "adopted 3 December 2025"


def test_session_date_fallback():
    a = h.Item(code="MEPC.364(79)", body="MEPC", session=79, title="x", pdf_url="", awaiting=False,
               reason="window", key="mepc_res")
    b = h.Item(code="MEPC.366(79)", body="MEPC", session=79, title="x", pdf_url="", awaiting=False,
               reason="window", key="mepc_res", adopted="2022-12-16")
    h.fill_session_dates([a, b])
    assert a.adopted == "2022-12-16" and a.status == "adopted 16 December 2022"


def test_parents_and_revocations():
    assert h.find_parent("AMENDMENTS TO THE IMSBC CODE", _CODE_AMENDMENT, "MSC.575(110)") == "MSC.268(85)"
    # the title names it
    assert h.find_parent("AMENDMENTS TO THE REVISED RECOMMENDATION ON TESTING OF LIFE-SAVING APPLIANCES "
                         "(RESOLUTION MSC.81(70))", "", "MSC.594(111)") == "MSC.81(70)"
    # a convention amendment has no parent resolution
    assert h.find_parent("AMENDMENTS TO CHAPTERS IV AND V OF THE INTERNATIONAL CONVENTION FOR THE SAFETY OF LIFE AT SEA",
                         _SOLAS_AMENDMENT, "MSC.583(111)") is None
    # a new edition is not an amendment: its predecessor is revoked, not a parent
    assert h.find_parent("PROCEDURES FOR PORT STATE CONTROL, 2025", _REVISED_PROCEDURES, "A.1206(34)") is None
    assert h.find_revoked(_REVISED_PROCEDURES, "A.1206(34)") == ["A.1185(33)"]
    assert h.find_revoked(_CODE_AMENDMENT, "MSC.575(110)") == []


def test_parent_is_the_recital_the_title_describes():
    # MSC.437(99): the preamble recalls the 1998 FTP Code before the 2010 one
    ftp = ("THE MARITIME SAFETY COMMITTEE, RECALLING Article 28(b) of the Convention, RECALLING ALSO "
           "resolution MSC.61(67), by which it adopted the International Code for Application of Fire Test "
           "Procedures, which has become mandatory under chapter II-2 of SOLAS, RECALLING FURTHER resolution "
           "MSC.307(88), by which it adopted the International Code for Application of Fire Test Procedures, "
           "2010 (\"the 2010 FTP Code\"), 1 ADOPTS amendments to the 2010 FTP Code")
    assert h.find_parent("AMENDMENTS TO THE INTERNATIONAL CODE FOR APPLICATION OF FIRE TEST PROCEDURES, 2010 "
                         "(2010 FTP CODE)", ftp, "MSC.437(99)") == "MSC.307(88)"
    # MSC.547(107): a footnote's "adopted by resolution A.962(23)" is not the parent
    modu = ("RECALLING that the Assembly, when adopting the Code for the Construction and Equipment of Mobile "
            "Offshore Drilling Units in 2009 by resolution A.1023(26), authorized the Committee to amend the "
            "Code, 1 ADOPTS amendments ... 1 Refer to the Guidelines on ship recycling, adopted by the "
            "Organization by resolution A.962(23), as amended")
    assert h.find_parent("AMENDMENTS TO THE CODE FOR THE CONSTRUCTION AND EQUIPMENT OF MOBILE OFFSHORE DRILLING "
                         "UNITS, 2009 (2009 MODU CODE)", modu, "MSC.547(107)") == "A.1023(26)"


def test_nice_title():
    assert h.nice_title("AMENDMENTS TO PART A OF THE SEAFARERS' TRAINING, CERTIFICATION AND WATCHKEEPING (STCW) CODE") == \
        "Amendments to Part A of the Seafarers' Training, Certification and Watchkeeping (STCW) Code"
    assert h.nice_title("PERFORMANCE STANDARDS FOR SHIPBORNE MF AND MF/HF RADIO INSTALLATIONS") == \
        "Performance Standards for Shipborne MF and MF/HF Radio Installations"
    assert h.nice_title("AMENDMENTS TO THE REVISED RECOMMENDATION (RESOLUTION MSC.81(70))") == \
        "Amendments to the Revised Recommendation (Resolution MSC.81(70))"
    assert h.nice_title("Amendments to the IS Code") == "Amendments to the IS Code"


def test_doc_scope_for_prune():
    assert h._doc_of("IMO LSA Code MSC.589(111) Ch.6", {"MSC.589(111)"}) == "MSC.589(111)"
    assert h._doc_of("IMO LSA Code MSC.48(66) Ch.6", {"MSC.589(111)"}) is None


def test_manifest_row_round_trips_to_adapter_meta():
    item = h.Item(code="MSC.589(111)", body="MSC", session=111,
                  title="AMENDMENTS TO THE INTERNATIONAL LIFE-SAVING APPLIANCE (LSA) CODE",
                  pdf_url="https://cdn/MSC.589(111).pdf", awaiting=True, reason="window", key="lsa",
                  source="imo_lsa", label="IMO LSA Code", adopted="2026-05-22", in_force="2028-01-01",
                  status="adopted 22 May 2026; entry into force 1 January 2028; certified text pending")
    row = h.manifest_row(item, date(2026, 10, 13))
    meta = imo_codes.meta_from_row(row)
    assert meta.section_number == "IMO LSA Code MSC.589(111)"
    assert meta.effective_date == date(2028, 1, 1)
    assert meta.as_of == date(2026, 10, 13)
    assert meta.title == "Amendments to the International Life-Saving Appliance (LSA) Code"
    assert meta.status.startswith("adopted 22 May 2026")


def test_parse_docs_puts_status_in_every_title(monkeypatch, tmp_path):
    from ingest.models import Section
    meta = imo_codes.CodeDocMeta(code="MSC.589(111)", title="LSA amendments", pdf_url="x",
                                 effective_date=date(2028, 1, 1), parent_label="IMO LSA Code",
                                 status="adopted 22 May 2026; entry into force 1 January 2028")

    def fake(raw_dir, m, source):
        return [Section(source=source, title_number=0, section_number=f"{m.section_number} Ch.{n}",
                        section_title=f"IMO LSA Code Chapter {n}", full_text="x" * 500,
                        up_to_date_as_of=date(2026, 10, 13)) for n in (1, 2)]
    monkeypatch.setattr(imo_codes, "_parse_doc", fake)
    secs = imo_codes.parse_docs(tmp_path, [meta], "imo_lsa")
    assert [s.section_title for s in secs] == [
        "IMO LSA Code Chapter 1 [MSC.589(111): adopted 22 May 2026; entry into force 1 January 2028]",
        "IMO LSA Code Chapter 2 [MSC.589(111): adopted 22 May 2026; entry into force 1 January 2028]",
    ]


def test_consolidated_instruments_are_never_parents():
    assert h.is_consolidated_instrument("REVISED MARPOL ANNEX VI")
    assert h.is_consolidated_instrument("AMENDMENTS TO THE ANNEX OF THE PROTOCOL OF 1997 TO AMEND THE INTERNATIONAL "
                                        "CONVENTION FOR THE PREVENTION OF POLLUTION FROM SHIPS")
    assert h.is_consolidated_instrument("ADOPTION OF THE INTERNATIONAL MARITIME DANGEROUS GOODS (IMDG) CODE")
    assert not h.is_consolidated_instrument("TECHNICAL CODE ON CONTROL OF EMISSION OF NITROGEN OXIDES FROM MARINE DIESEL ENGINES")
    assert not h.is_consolidated_instrument("INTERNATIONAL MARITIME SOLID BULK CARGOES (IMSBC) CODE")
