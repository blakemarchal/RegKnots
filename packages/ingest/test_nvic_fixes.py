"""2026-09-27 — text fixes for USCG's retyped NVICs (sources/nvic_fixes.py)
and the --nvic subset parse behind a targeted re-ingest."""
import json
import logging
from datetime import date

import pytest

from ingest.models import Section
from ingest.sources import nvic, nvic_fixes
from ingest.sources.nvic_fixes import NVIC_TEXT_FIXES, apply_text_fixes


def test_fix_table_keeps_line_structure_and_section_starts():
    for number, fixes in NVIC_TEXT_FIXES.items():
        olds = [old for old, _ in fixes]
        assert len(olds) == len(set(olds)), f"NVIC {number}: repeated anchor"
        for old, new in fixes:
            assert old and old != new
            # the section split runs on these lines: a fix must not add, drop or
            # create a line that _SECTION_START reads as "N. HEADING"
            assert old.count("\n") == new.count("\n"), old
            starts = lambda s: [ln for ln in s.split("\n") if nvic._SECTION_START.match(ln)]  # noqa: E731
            assert starts(old) == starts(new), old


def test_co2_discharge_figure_is_corrected_with_a_note(caplog):
    lines = [
        "fire from carrying away the carbon dioxide, as well as limiting damage to equipment.",
        "discharge of 35% of the required quantity of CO in these systems should be completed",
        "within two minutes; slow release might result in no extinguishment.",
    ]
    with caplog.at_level(logging.WARNING):
        out = apply_text_fixes("06-72", lines)
    assert len(out) == 3 and out[0] == lines[0] and out[2] == lines[2]
    assert out[1].startswith('discharge of 85% [corrected: the USCG PDF reads "35%"; 46 CFR')
    assert out[1].endswith("] of the required quantity of CO in these systems should be completed")
    # the other 06-72 anchors are absent from this excerpt: skipped, not applied
    assert "anchor found 0 times" in caplog.text


def test_anchor_must_occur_exactly_once(monkeypatch, caplog):
    monkeypatch.setitem(NVIC_TEXT_FIXES, "99-99", [
        ("one 1300F", "one 130°F"),              # once: applied
        ("twice 700F", "twice 70°F"),            # twice: skipped
        ("absent", "never"),                     # missing: skipped
        ("split\nacross", "split\nfixed"),       # may span lines
    ])
    lines = ["one 1300F", "twice 700F", "twice 700F", "split", "across"]
    with caplog.at_level(logging.WARNING):
        out = apply_text_fixes("99-99", lines)
    assert out == ["one 130°F", "twice 700F", "twice 700F", "split", "fixed"]
    assert "anchor found 2 times" in caplog.text and "anchor found 0 times" in caplog.text


def test_nvic_without_fixes_is_untouched():
    lines = ["1. Purpose. The purpose of this circular is 35%."]
    assert apply_text_fixes("01-23", lines) is lines


def _index(tmp_path, numbers, pdfs):
    (tmp_path / "index.json").write_text(json.dumps([
        {"number": n, "title": f"T {n}", "effective_date": "2026-03-31", "pdf_url": ""}
        for n in numbers
    ]), encoding="utf-8")
    for n in pdfs:
        (tmp_path / f"{n}.pdf").write_bytes(b"%PDF-")


def _stub_parse(pdf_path, meta):
    return [Section(source="nvic", title_number=0, section_number=f"NVIC {meta.number} §1",
                    section_title=meta.title, full_text="text", up_to_date_as_of=date(2026, 3, 31),
                    parent_section_number=f"NVIC {meta.number}")]


def test_parse_source_only_parses_the_named_nvics(tmp_path, monkeypatch):
    monkeypatch.setattr(nvic, "_parse_nvic_pdf", _stub_parse)
    _index(tmp_path, ["01-23", "06-72", "10-92"], ["01-23", "06-72", "10-92"])
    assert [s.section_number for s in nvic.parse_source(tmp_path, only=["06-72"])] == ["NVIC 06-72 §1"]
    assert len(nvic.parse_source(tmp_path)) == 3


@pytest.mark.parametrize("only", [["6-72"], ["10-92"]])
def test_parse_source_only_refuses_an_unknown_number_or_missing_pdf(tmp_path, monkeypatch, only):
    monkeypatch.setattr(nvic, "_parse_nvic_pdf", _stub_parse)
    _index(tmp_path, ["06-72", "10-92"], ["06-72"])       # 10-92 has no PDF
    with pytest.raises(FileNotFoundError, match=only[0]):
        nvic.parse_source(tmp_path, only=only)


class _FakePdf:
    def __init__(self, texts):
        self.pages = [type("Page", (), {"extract_text": lambda self, t=t: t})() for t in texts]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parse_applies_the_fixes_before_the_section_split(tmp_path, monkeypatch):
    monkeypatch.setattr(nvic.pdfplumber, "open", lambda path: _FakePdf([
        "1. Purpose.\nThe purpose of the attached guide is to explain fixed systems.\n25",
        "2. Total flooding.\n"
        "discharge of 35% of the required quantity of CO in these systems should be completed\n"
        "within two minutes.",
    ]))
    meta = nvic.NvicMeta("06-72", "Guide", date(2026, 3, 31), "")
    secs = nvic._parse_nvic_pdf(tmp_path / "06-72.pdf", meta)
    assert [s.section_number for s in secs] == ["NVIC 06-72 §1", "NVIC 06-72 §2"]
    assert "discharge of 85% [corrected" in secs[1].full_text
    assert "35% of the required" not in secs[1].full_text
    assert nvic_fixes.NVIC_TEXT_FIXES["06-72"]          # the table the adapter reads
