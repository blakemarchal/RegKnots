"""2026-09-25 — SOLAS section naming from headers.txt (real lines from data/raw/solas)."""
import pytest

from ingest.sources import solas as S


@pytest.mark.parametrize("title,section,parent", [
    ("Chapter I: General provisions; Part A: Application, definitions, etc.", "SOLAS Ch.I Part A", "SOLAS Ch.I"),
    ("Chapter II-1: Construction – Structure, subdivision and stability, machinery and electrical "
     "installations; Part A-1: Structure of ships", "SOLAS Ch.II-1 Part A-1", "SOLAS Ch.II-1"),
    ("Chapter II-1: Construction – Structure, subdivision and stability, machinery and electrical "
     "installations; Part B-1: Stability", "SOLAS Ch.II-1 Part B-1", "SOLAS Ch.II-1"),
    ("Chapter II-2: Construction – Fire protection, fire detection and fire extinction; "
     "Part C: Suppression of fire", "SOLAS Ch.II-2 Part C", "SOLAS Ch.II-2"),
    ("Chapter III: Life-saving appliances and arrangements; Part B: Requirements for ships and "
     "life-saving appliances", "SOLAS Ch.III Part B", "SOLAS Ch.III"),
    ("Chapter V: Safety of navigation", "SOLAS Ch.V", "SOLAS Ch.V"),
    ("Chapter VII: Carriage of dangerous goods; Part A-1: Carriage of dangerous goods in solid form in bulk",
     "SOLAS Ch.VII Part A-1", "SOLAS Ch.VII"),
    ("Chapter XI-1: Special measures to enhance maritime safety", "SOLAS Ch.XI-1", "SOLAS Ch.XI-1"),
    ("Chapter XI-2: Special measures to enhance maritime security", "SOLAS Ch.XI-2", "SOLAS Ch.XI-2"),
    ("Unified interpretations for chapter II-1", "SOLAS Unified interpretations for chapter II-1", "SOLAS"),
    ("Unified interpretations for chapter II-2", "SOLAS Unified interpretations for chapter II-2", "SOLAS"),
    ("Articles of the International Convention for the Safety of Life at Sea, 1974", "SOLAS Articles", "SOLAS"),
    ("Articles of the Protocol of 1988 relating to the International Convention for the Safety of Life at Sea, 1974",
     "SOLAS Protocol 1988 Articles", "SOLAS"),
    ("Appendix: Certificates: Form of safety certificate for passenger ships",
     "SOLAS Appendix Certificates: Form of safety certificate for passenger ships", "SOLAS"),
    ("Appendix: Certificates: Records of equipment", "SOLAS Appendix Certificates: Records of equipment", "SOLAS"),
    ("Annex 1: Certificates and documents required to be carried on board ships 1", "SOLAS Annex 1", "SOLAS Annexes"),
    # the older headers.txt format still parses
    ("Chapter I Part A - General", "SOLAS Ch.I Part A", "SOLAS Ch.I"),
])
def test_section_names(title, section, parent):
    assert S._format_section_number(title) == section
    assert S._format_parent(title) == parent


def test_regulation_header_accepts_hyphenated_numbers():
    text = ("Regulation 3 Definitions relating to parts C, D and E\n...\n"
            "Regulation 3-1 Structural, mechanical and electrical requirements for ships\n...\n"
            "Regulation 35-1 Bilge pumping arrangements\n")
    assert [m.group(1) for m in S._REGULATION_HEADER.finditer(text)] == ["3", "3-1", "35-1"]


def test_ii_1_and_ii_2_regulations_get_distinct_names(tmp_path):
    body = "Some regulation text that is long enough to count as a real regulation. " * 4
    (tmp_path / "headers.txt").write_text(
        "43-48: Chapter II-1: Construction – Structure, subdivision and stability; Part B-2: Subdivision\n"
        "202-250: Chapter II-2: Construction – Fire protection; Part C: Suppression of fire\n",
        encoding="utf-8")
    (tmp_path / "43-48.txt").write_text(f"Regulation 10 Construction of watertight bulkheads\n{body}\n", encoding="utf-8")
    (tmp_path / "202-250.txt").write_text(f"Regulation 10 Fire fighting\n{body}\n", encoding="utf-8")
    names = [s.section_number for s in S.parse_source(tmp_path)]
    assert names == ["SOLAS Ch.II-1 Reg.10", "SOLAS Ch.II-2 Reg.10"]


def test_duplicate_sections_are_merged_not_overwritten():
    from ingest.models import Section
    from datetime import date

    def sec(num, text):
        return Section(source="solas", title_number=0, section_number=num, section_title="",
                       full_text=text, up_to_date_as_of=date(2026, 5, 22))
    out = S._merge_duplicate_sections([sec("SOLAS Articles", "a"), sec("SOLAS Ch.V", "v"), sec("SOLAS Articles", "b")])
    assert [s.section_number for s in out] == ["SOLAS Articles", "SOLAS Ch.V"]
    assert out[0].full_text == "a\n\nb"
