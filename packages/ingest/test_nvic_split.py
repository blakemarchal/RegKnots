"""2026-09-27 — the NVIC split (sources/nvic.py _split_sections): the circular's
numbered paragraphs, its enclosures, every line in one section, and no two
chunks with one (section_number, chunk_index) key."""
import json
import logging
from collections import Counter
from datetime import date

import pytest

from ingest.chunker import chunk_section
from ingest.models import Section
from ingest.sources import nvic, nvic_fixes

META = nvic.NvicMeta("06-72", "Guide", date(1972, 1, 1), "")

CIRCULAR = """NAVIGATION AND VESSEL INSPECTION CIRCULAR NO. 6-72
Subj: Guide to fixed fire-fighting equipment
1. Purpose. The purpose of the attached guide is to explain fixed systems
aboard merchant vessels.
2. Cancellation. None.
3. Objectives. The guide is intended for Coast Guard technical units.
4. Revisions. It is expected that these notes will require modification.
Encl: (1) Guide to Fixed Fire-Fighting Equipment"""

ENCLOSURE = [
    """Enclosure (1) to NVIC 6-72
GUIDE TO FIXED FIRE-FIGHTING EQUIPMENT
The fire main system is the backbone of all fire-fighting systems.
1. One feature of halon that must be kept in mind is the hazard
2. A second problem concerns the protection of machinery spaces""",
    """Enclosure (1) to NVIC 6-72
1. The cylinders must be located outside of the protected space
2. The temperature range the cylinders may be exposed to
3. Halon cylinders are fitted with an overpressure relief device""",
]


def _split(pages, meta=META):
    return nvic._split_sections([p.split("\n") for p in pages], meta, paged=True)


def _keys(sections):
    return Counter((c.section_number, c.chunk_index) for s in sections for c in chunk_section(s))


def test_circular_paragraphs_and_the_enclosure():
    secs = _split([CIRCULAR] + ENCLOSURE)
    assert [s.section_number for s in secs] == [
        "NVIC 06-72", "NVIC 06-72 §1", "NVIC 06-72 §2", "NVIC 06-72 §3", "NVIC 06-72 §4",
        "NVIC 06-72 Encl.1"]
    by = {s.section_number: s for s in secs}
    # the circular's names and titles are unchanged, so its stored rows keep their hashes
    assert by["NVIC 06-72 §1"].section_title == (
        "Guide — Purpose. The purpose of the attached guide is to explain fixed systems")
    assert by["NVIC 06-72 §1"].full_text == "aboard merchant vessels."
    assert by["NVIC 06-72 §4"].full_text == "Encl: (1) Guide to Fixed Fire-Fighting Equipment"
    # the opening is kept, and the enclosure's restarting list stays in its text
    assert by["NVIC 06-72"].full_text.startswith("NAVIGATION AND VESSEL")
    encl = by["NVIC 06-72 Encl.1"]
    assert encl.section_title == "Guide — Enclosure (1)" and encl.parent_section_number == "NVIC 06-72"
    assert encl.full_text.count("\n1. ") == 2 and encl.full_text.endswith("overpressure relief device")
    assert max(_keys(secs).values()) == 1


def test_every_line_lands_in_one_section():
    secs = _split([CIRCULAR] + ENCLOSURE)
    text = [ln for s in secs for ln in s.full_text.split("\n")]
    headings = [s.section_title.split(" — ", 1)[1] for s in secs if "§" in s.section_number]
    for line in "\n".join([CIRCULAR] + ENCLOSURE).split("\n"):
        heading = line.split(". ", 1)[1] if line[:2] in ("1.", "2.", "3.", "4.") else None
        assert text.count(line) + (heading in headings) >= 1, line
    # a paragraph with no text of its own keeps its line
    assert {s.section_number: s.full_text for s in secs}["NVIC 06-72 §2"] == "Cancellation. None."


def test_out_of_order_toc_and_lowercase_numbered_lines_are_text():
    secs = _split(["""1. PURPOSE. This circular clarifies training requirements.
2. DISCUSSION. The training covers:
1. knowledge of muster lists;
2. knowledge of emergency instructions;
3. how to search accommodation spaces.
3. Security Systems and Equipment Maintenance ........ 17
3. ACTION. Officers in Charge will apply this guidance."""])
    assert [s.section_number for s in secs] == ["NVIC 06-72 §1", "NVIC 06-72 §2", "NVIC 06-72 §3"]
    body = {s.section_number: s.full_text for s in secs}["NVIC 06-72 §2"]
    assert "1. knowledge of muster lists;" in body and "3. how to search" in body
    assert "........ 17" in body


def test_an_enclosure_numbered_1_to_k_is_split():
    meta = nvic.NvicMeta("04-03", "Security", date(2003, 12, 1), "")
    secs = _split(["1. PURPOSE. This circular provides a guide.", """Enclosure (3) to NVIC 04-03
VESSEL SECURITY GUIDE
1. Instructions for Using This Guide
Use it with 33 CFR part 104.
2. Compliance documentation. 33 CFR 104.120
Each vessel owner must keep a letter.
3. Noncompliance. 33 CFR 104.125"""], meta)
    assert [s.section_number for s in secs] == [
        "NVIC 04-03 §1", "NVIC 04-03 Encl.3", "NVIC 04-03 Encl.3 §1", "NVIC 04-03 Encl.3 §2",
        "NVIC 04-03 Encl.3 §3"]
    by = {s.section_number: s for s in secs}
    assert by["NVIC 04-03 Encl.3 §2"].section_title == (
        "Security — Enclosure (3): Compliance documentation. 33 CFR 104.120")
    assert by["NVIC 04-03 Encl.3 §3"].full_text == "Noncompliance. 33 CFR 104.125"


def test_enclosures_start_at_the_lowest_number_and_replacement_pages_join_theirs():
    meta = nvic.NvicMeta("05-03", "Facility", date(2003, 10, 1), "")
    secs = _split([
        "1. PURPOSE. This circular introduces the guidance.\nEnclosures:",
        # the circular's own list of its enclosures, at the page edges
        "(1) Facility Security Plan Guide\nEnclosure (4)—Stage I (Preliminary Review) Guidance",
        "Enclosure (1) to Navigation and Inspection Circular No. 05-03\nPlan guide text.",
        "Enclosure (2) to NVIC 05-03\nChecklist text.",
        "Enclosure (1) to NVIC 05-03, CH-1\nReplacement page text.",
    ], meta)
    by = {s.section_number: s.full_text for s in secs}
    assert list(by) == ["NVIC 05-03 §1", "NVIC 05-03 Encl.1", "NVIC 05-03 Encl.2"]
    assert "Stage I (Preliminary Review)" in by["NVIC 05-03 §1"]
    assert by["NVIC 05-03 Encl.1"].endswith("Replacement page text.")


def test_one_label_on_every_page_from_the_first_is_not_an_enclosure():
    """NVIC 2-88 puts "Enclosure (1) to NVIC 2-88" on the circular's own pages."""
    meta = nvic.NvicMeta("02-88", "Inert Gas", date(1988, 3, 15), "")
    secs = _split([
        "Enclosure (1) to NVIC 2-88\nNVIC 2-88\n1. PURPOSE. This circular gives guidance.\n"
        "2. BACKGROUND. Inert gas systems keep oxygen below 8%.",
        "Enclosure (1) to NVIC 2-88\n3. DISCUSSION. Chemical tankers.",
    ], meta)
    assert [s.section_number for s in secs] == [
        "NVIC 02-88", "NVIC 02-88 §1", "NVIC 02-88 §2", "NVIC 02-88 §3"]
    # NVIC 4-97's head reads "Encl. (2) to NVIC 4-97": not the circular's "Encl:" list
    secs = _split(["Encl. (2) to NVIC 4-97\n1. PURPOSE. Guidance.", "2. DIRECTIVES AFFECTED. None"])
    assert [s.section_number for s in secs] == ["NVIC 06-72", "NVIC 06-72 §1", "NVIC 06-72 §2"]
    # a PDF whose circular pages are images starts at its first enclosure (NVIC 3-06)
    secs = _split(["", "Enclosure (1) to NVIC 3-06\nGuide one.", "Enclosure (2) to NVIC 3-06\nGuide two."])
    assert [s.section_number for s in secs] == ["NVIC 06-72 Encl.1", "NVIC 06-72 Encl.2"]


def test_without_running_heads_the_enclosure_starts_after_the_encl_list():
    meta = nvic.NvicMeta("02-99", "Streamlined Inspection", date(1999, 1, 1), "")
    secs = _split([
        "2. DIRECTIVES AFFECTED. Policy letters are cancelled.\n3. DISCUSSION.\nText.",
        "More discussion.\nEncl: (1) A Guide to the Streamlined Inspection Program\nDist: SDL",
        "TABLE OF CONTENTS\n1. Organizational Commitment\n2. Responsibility and Authority\n"
        "1. Deficiency History",
    ], meta)
    assert [s.section_number for s in secs] == ["NVIC 02-99 §2", "NVIC 02-99 §3", "NVIC 02-99 Encl."]
    assert secs[-1].section_title == "Streamlined Inspection — Enclosure"


def test_a_document_with_no_paragraphs_or_enclosures_is_one_section():
    secs = _split(["Subj: Something\nA plain letter.", "Its second page."])
    assert [(s.section_number, s.section_title) for s in secs] == [("NVIC 06-72", "Guide")]
    assert secs[0].full_text == "Subj: Something\nA plain letter.\nIts second page."


class _FakePdf:
    def __init__(self, texts):
        self.pages = [type("Page", (), {"extract_text": lambda self, t=t: t})() for t in texts]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_fix_that_changes_the_line_count_falls_back_to_lines(tmp_path, monkeypatch, caplog):
    monkeypatch.setitem(nvic_fixes.NVIC_TEXT_FIXES, "99-99", [("one line", "one\nline")])
    monkeypatch.setattr(nvic.pdfplumber, "open", lambda path: _FakePdf([
        "1. PURPOSE. one line of text.", "Enclosure (1) to NVIC 99-99\nGuide text."]))
    meta = nvic.NvicMeta("99-99", "T", date(2026, 1, 1), "")
    with caplog.at_level(logging.WARNING):
        secs = nvic._parse_nvic_pdf(tmp_path / "99-99.pdf", meta)
    assert "changed the line count" in caplog.text
    assert [s.section_number for s in secs] == ["NVIC 99-99 §1", "NVIC 99-99 Encl.1"]


def _index(raw, numbers):
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "index.json").write_text(json.dumps([
        {"number": n, "title": f"T {n}", "effective_date": "2000-01-01", "pdf_url": ""}
        for n in numbers
    ]), encoding="utf-8")


def test_a_scanned_nvic_is_read_from_its_ocr_text(tmp_path, monkeypatch):
    raw, ocr = tmp_path / "raw", tmp_path / "ocr"
    _index(raw, ["01-00"])
    (raw / "01-00.pdf").write_bytes(b"%PDF-")      # no text layer
    ocr.mkdir()
    (ocr / "01-00.txt").write_text(
        "[--- pages 1-3 ---]\n\n1. PURPOSE. This circular publishes the guide.\n2. ACTION. Apply it.\n"
        "Enclosure (1) to NVIC 1-00\nGuide text.\n1. First item\n1. First item of another list\n",
        encoding="utf-8")
    monkeypatch.setattr(nvic, "_parse_nvic_pdf", lambda *a: pytest.fail("the PDF has no text"))
    secs = nvic.parse_source(raw, ocr_dir=ocr)
    assert [s.section_number for s in secs] == ["NVIC 01-00 §1", "NVIC 01-00 §2", "NVIC 01-00 Encl.1"]
    assert not any("--- pages" in s.full_text for s in secs)
    assert nvic.parse_source(raw, only=["01-00"], ocr_dir=ocr)


def test_extra_documents_are_parsed_when_their_pdf_is_present(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    _index(raw, [])
    seen = []
    monkeypatch.setattr(nvic, "_parse_nvic_pdf", lambda path, meta: seen.append(path.name) or [
        Section(source="nvic", title_number=0, section_number=f"NVIC {meta.number} §1",
                section_title=meta.title, full_text="text", up_to_date_as_of=meta.effective_date,
                parent_section_number=f"NVIC {meta.number}")])
    assert nvic.parse_source(raw, ocr_dir=tmp_path / "ocr") == []   # no PDF: skipped
    (raw / "NVIC 04-08 Ch-2.pdf").write_bytes(b"%PDF-")
    secs = nvic.parse_source(raw, only=["04-08 Ch-2"], ocr_dir=tmp_path / "ocr")
    assert [s.section_number for s in secs] == ["NVIC 04-08 Ch-2 §1"]
    assert seen == ["NVIC 04-08 Ch-2.pdf"]


@pytest.mark.parametrize("section,document", [
    ("NVIC 06-72", "NVIC 06-72"),
    ("NVIC 06-72 §4", "NVIC 06-72"),
    ("NVIC 06-72 Encl.1", "NVIC 06-72"),
    ("NVIC 04-03 Encl.3 §12", "NVIC 04-03"),
    ("NVIC 02-99 Encl.", "NVIC 02-99"),
    ("NVIC 04-08 Ch-2 §3", "NVIC 04-08 Ch-2"),
    ("NVIC 1-66 §2", "NVIC 1-66"),
    ("NVIC 06-72 Appendix A", None),
    ("46 CFR 34.15-5", None),
])
def test_prune_scope(section, document):
    assert nvic.prune_scope(section) == document
