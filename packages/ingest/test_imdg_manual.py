"""The hand-curated IMDG 3.2 rows (ingest/sources/imdg_manual.py), rebuilt 2026-10-17
from BAM DGG-Info (IMDG Code Amendment 42-24) after most of the original rows turned out
wrong. Run: uv run pytest test_imdg_manual.py"""
import re

import pytest

from ingest.chunker import chunk_section
from ingest.sources import imdg_manual as M

BY_UN = {e.un_number: e for e in M.UN_ENTRIES}
SECTIONS = {s.section_number: s for s in M.parse_source(None)}


def test_thirty_entries_each_once():
    assert len(M.UN_ENTRIES) == 30
    assert len(BY_UN) == 30
    assert all(s.endswith("(manual)") for s in SECTIONS)  # prune.py keeps "(manual)" rows


@pytest.mark.parametrize("entry", M.UN_ENTRIES, ids=lambda e: str(e.un_number))
def test_every_code_has_its_meaning(entry):
    text = entry.render()
    for row in entry.rows:
        assert row.stowage_category in M._STOWAGE_CATEGORY
        assert f"Stowage category {row.stowage_category}:" in text
        for code in M._codes(row.stowage_codes):
            assert f"- {code}: {M._STOWAGE_CODES[code]}" in text
        for code in M._codes(row.segregation_codes):
            assert f"- {code}: {M._SEGREGATION_CODES[code]}" in text
        if row.segregation_group:
            assert M._SEGREGATION_GROUPS[row.segregation_group] in text
    for code in M._codes(entry.ems):
        assert M._EMS[code.rstrip("!")] in text


@pytest.mark.parametrize("entry", M.UN_ENTRIES, ids=lambda e: str(e.un_number))
def test_row_text_names_the_entry(entry):
    text = entry.render()
    assert text.startswith("[IMDG 3.2 — Dangerous Goods List, Amendment 42-24]\n")
    assert SECTIONS[entry.section_number].section_title == f"UN {entry.un_number} — {entry.proper_shipping_name}"
    # no template leftovers
    assert "None" not in text and "{" not in text


@pytest.mark.parametrize("entry", M.UN_ENTRIES, ids=lambda e: str(e.un_number))
def test_entry_chunks_carry_the_values_and_the_source_note(entry):
    chunks = chunk_section(SECTIONS[entry.section_number])
    assert 1 <= len(chunks) <= 2
    first = chunks[0].chunk_text
    assert M._ATTRIBUTION in first and "dl-de/by-2-0" in first     # BAM's licence: source note with the data
    assert "Stowage category" in first and "Special provisions" in first.replace("special provisions", "Special provisions")


# The values the 2026-10-17 check found wrong in the original rows, as BAM gives them.
@pytest.mark.parametrize("un, field, expected", [
    (2014, "stowage_category", "D"),
    (2014, "segregation_codes", "SG16, SG59, SG72"),
    (3532, "stowage_category", "D"),
    (3532, "limited_quantity", "0"),
    (3534, "stowage_codes", "SW1, SW3"),
    (1167, "stowage_category", "E"),
    (1170, "stowage_category", "A"),
    (1972, "stowage_category", "D"),
    (1789, "stowage_category", "C"),
    (1830, "stowage_codes", "SW15"),
    (3528, "stowage_category", "E"),
    (3480, "segregation_codes", ""),
    (1011, "segregation_codes", ""),
    (1075, "limited_quantity", "0"),
])
def test_corrected_values(un, field, expected):
    assert getattr(BY_UN[un].rows[0], field) == expected


def test_lithium_ion_batteries():
    e = BY_UN[3480]
    row = e.rows[0]
    assert (e.class_, row.stowage_category, row.stowage_codes) == ("9", "A", "SW19")
    assert "377" in row.special_provisions
    text = e.render()
    assert "Packing group: none" in text
    assert "Limited quantity: 0 (not permitted as a limited quantity)" in text
    assert "stowage category C, unless transported on a short international voyage" in text


def test_packing_groups_render_one_line_each():
    text = BY_UN[1993].render()
    assert "Packagings: P001" in text  # same for every packing group: stated once
    pg = [line for line in text.splitlines() if line.startswith("Packing group ")]
    assert len(pg) == 3
    assert "stowage category E" in pg[0] and "stowage category B" in pg[1] and "stowage category A" in pg[2]
    assert "S-E (special case" in text


def test_hydrogen_peroxide_subsidiary_hazard():
    text = BY_UN[2014].render()
    assert "Class: 5.1; subsidiary hazard 8" in text
    assert "Segregation group: SGG16 (peroxides)" in text
    assert re.search(r"Stowage category D: .* on deck only; other passenger ships prohibited", text)


def test_marine_pollutant_mark():
    assert "Marine pollutant mark (P): yes" in BY_UN[1547].render()
    assert "Marine pollutant mark (P): not marked" in BY_UN[1202].render()
