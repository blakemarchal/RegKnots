"""2026-09-26 — MARPOL Annex chapters split into one section per regulation,
and the duplicate-section merge shared by SOLAS, MARPOL and IMDG."""
import logging

from ingest.sources import imdg, marpol


def _meta(section_number, title="Annex I Chapter 2 — Surveys and certification"):
    return {"section_number": section_number, "section_title": title,
            "parent_section_number": section_number.rsplit(" Ch.", 1)[0]}


CH2 = _meta("MARPOL Annex I Ch.2")


def _split(text, meta=CH2):
    return {s.section_number: s for s in marpol._split_into_regulations(text, meta)}


def test_headings_split_and_page_running_heads_are_dropped():
    text = "\n".join([
        "Chapter 2 – Surveys and certification",
        "",
        "Regulation 5",
        "Equivalents",
        "",
        "1 The Administration may allow any fitting to be fitted in a ship as an alternative.",
        "",
        "Annex I: Regulations for the prevention of pollution by oil",
        "Regulation 6",                      # running head of the next page
        "",
        "2 The Administration shall communicate to the Organization particulars thereof.",
        "",
        "[NOTE: assembled from split-page retry]",
        "",
        "Regulation 6",
        "Surveys",
        "",
        "1 Every oil tanker of 150 gross tonnage and above shall be subject to the surveys.",
    ])
    regs = _split(text)
    assert list(regs) == ["MARPOL Annex I Reg.5", "MARPOL Annex I Reg.6"]
    r5, r6 = regs["MARPOL Annex I Reg.5"], regs["MARPOL Annex I Reg.6"]
    assert (r5.section_title, r6.section_title) == ("Equivalents", "Surveys")
    assert r5.parent_section_number == "MARPOL Annex I Ch.2"
    # the page after the running head is still regulation 5
    assert "2 The Administration shall communicate" in r5.full_text
    assert "Annex I: Regulations" not in r5.full_text and "[NOTE" not in r5.full_text
    assert r5.full_text.count("Regulation") == 1 and r6.full_text.startswith("Regulation 6\nSurveys")


def test_heading_variants_markdown_footnote_letter_suffix_two_line_title():
    text = "\n".join([
        "**Regulation 12**",
        "*Tanks for all residues (sludge)*",
        "",
        "1 Every ship of 400 gross tonnage and above shall be provided with a tank or tanks.",
        "",
        "Regulation 12A*",
        "Oil fuel tank protection",
        "for ships delivered on or after 1 August 2010",
        "",
        "1 This regulation shall apply to all ships with an aggregate oil fuel capacity of 600 m3.",
        "",
        "Regulation 14",
        "Sulphur oxides (SO_x) and particulate matter",
        "",
        "1 The sulphur content of fuel oil used on board ships shall not exceed 0.50% m/m.",
    ])
    regs = _split(text, _meta("MARPOL Annex I Ch.3", "Annex I Chapter 3 — Machinery spaces"))
    assert list(regs) == ["MARPOL Annex I Reg.12", "MARPOL Annex I Reg.12A", "MARPOL Annex I Reg.14"]
    assert regs["MARPOL Annex I Reg.12"].section_title == "Tanks for all residues (sludge)"
    assert regs["MARPOL Annex I Reg.12A"].section_title == (
        "Oil fuel tank protection for ships delivered on or after 1 August 2010")
    assert regs["MARPOL Annex I Reg.14"].section_title == "Sulphur oxides (SOx) and particulate matter"
    assert "600 m3" not in regs["MARPOL Annex I Reg.12"].full_text


def test_a_regulation_line_followed_by_paragraph_text_is_not_a_heading():
    text = "Regulation 1\nDefinitions\n\n1 Oil means petroleum in any form.\n\nRegulation 2\n\n39 Electronic Record Book means a device."
    regs = _split(text, _meta("MARPOL Annex I Ch.1", "Annex I Chapter 1 — General"))
    assert list(regs) == ["MARPOL Annex I Reg.1"]
    assert "39 Electronic Record Book" in regs["MARPOL Annex I Reg.1"].full_text


def test_only_annex_chapters_are_split():
    text = "Regulation 1\nDefinitions\n\n1 Oil means petroleum in any form."
    for sn in ("MARPOL Annex I App.II", "MARPOL Annex I UI", "MARPOL Articles",
               "MARPOL Additional Information 3", "MARPOL Protocol I"):
        assert marpol._split_into_regulations(text, _meta(sn)) == []


def test_ocr_fixes_open_a_lost_heading_and_move_out_of_order_pages(monkeypatch):
    monkeypatch.setitem(marpol._OCR_FIXES, "MARPOL Annex I Ch.4", [
        ("continue", "27", None, "27.3.2 text"),
        ("start", "26", "Limitation of size and arrangement of cargo tanks", "26.5 text"),
        ("continue", "28", None, "28.2.2 text"),
    ])
    text = "\n".join([
        "Regulation 25", "Hypothetical outflow of oil", "", "25.1 text", "",
        "27.3.2 text", "",                                   # a Reg.27 page, out of order
        "Regulation 28", "Subdivision and damage stability", "", "28.1 text", "",
        "26.5 text", "",                                     # Reg.26, heading page not scanned
        "Regulation 27", "Intact stability", "", "27.1 text", "",
        "28.2.2 text", "",
        "Regulation 29", "Slop tanks", "", "29.1 text",
    ])
    regs = _split(text, _meta("MARPOL Annex I Ch.4", "Annex I Chapter 4 — Cargo area"))
    assert sorted(regs) == [f"MARPOL Annex I Reg.{n}" for n in (25, 26, 27, 28, 29)]
    assert "27.3.2" not in regs["MARPOL Annex I Reg.25"].full_text
    r27 = regs["MARPOL Annex I Reg.27"].full_text
    assert r27.index("27.1 text") < r27.index("27.3.2 text")
    r28 = regs["MARPOL Annex I Reg.28"].full_text
    assert r28.index("28.1 text") < r28.index("28.2.2 text") and "26.5" not in r28
    r26 = regs["MARPOL Annex I Reg.26"]
    assert r26.section_title == "Limitation of size and arrangement of cargo tanks"
    assert r26.full_text.startswith("Regulation 26\n") and marpol._MISSING_START_NOTE in r26.full_text


def test_a_missing_fix_anchor_and_a_numbering_gap_are_logged(monkeypatch, caplog):
    monkeypatch.setitem(marpol._OCR_FIXES, "MARPOL Annex I Ch.2",
                        [("start", "10", "Duration and validity of certificate", "not in this text")])
    text = "Regulation 9\nForm of certificate\n\n1 text\n\nRegulation 11\nPort State control\n\n1 text"
    with caplog.at_level(logging.WARNING):
        regs = _split(text)
    assert list(regs) == ["MARPOL Annex I Reg.9", "MARPOL Annex I Reg.11"]
    assert "anchor found 0 times" in caplog.text and "no heading for Reg.10" in caplog.text


def test_title_fix_for_an_ocr_error():
    text = "Regulation 24\nRequired EEXI\n\n1 For each new ship, the attained EEDI shall be as follows."
    regs = _split(text, _meta("MARPOL Annex VI Ch.4", "Annex VI Chapter 4 — Carbon intensity"))
    assert regs["MARPOL Annex VI Reg.24"].section_title == "Required EEDI"


def test_misfiled_page_moves_to_its_section(tmp_path):
    (tmp_path / "headers.txt").write_text(
        "208-216: Annex II Appendix IV — Standard format for the Procedures and Arrangements Manual\n"
        "227-230: Annex III Chapter 1 — General\n", encoding="utf-8")
    (tmp_path / "208-216.txt").write_text("Section 1 – Main features of MARPOL Annex II\n\n1.1 text", encoding="utf-8")
    (tmp_path / "227-230.txt").write_text("\n".join([
        "Regulation 9", "Port State control on operational requirements", "", "1 A ship in port.", "",
        "Annex II: Regulations for the control of pollution by noxious liquid substances in bulk", "",
        "Section 2 – Description of the ship's equipment and arrangements", "", "2.1 This section contains",
    ]), encoding="utf-8")
    secs = {s.section_number: s for s in marpol.parse_source(tmp_path)}
    assert set(secs) == {"MARPOL Annex II App.IV", "MARPOL Annex III Reg.9"}
    app = secs["MARPOL Annex II App.IV"].full_text
    assert app.startswith("Section 1") and app.endswith("2.1 This section contains")
    reg9 = secs["MARPOL Annex III Reg.9"].full_text
    assert "Section 2" not in reg9 and "Annex II:" not in reg9


def test_imdg_duplicate_headers_merge_instead_of_overwriting(tmp_path, caplog):
    (tmp_path / "headers.txt").write_text("0-6: Foreword\n80-80: Part 3\n284-285: Foreword\n286-286: Part 3\n",
                                          encoding="utf-8")
    for name, body in [("0-6", "Volume 1 foreword"), ("80-80", "Part 3 is in volume 2"),
                       ("284-285", "Volume 2 contents"), ("286-286", "PART 3 DANGEROUS GOODS LIST")]:
        (tmp_path / f"{name}.txt").write_text(body, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        secs = imdg.parse_source(tmp_path)
    assert [s.section_number for s in secs] == ["IMDG Foreword", "IMDG Part 3"]
    assert secs[0].full_text == "Volume 1 foreword\n\nVolume 2 contents"
    assert "duplicate section_number 'IMDG Foreword'" in caplog.text
