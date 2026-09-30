"""2026-09-30 — CFR citations the model writes one way and the corpus stores
another (rag/citation_norm.py), and where they are used."""
from rag import retriever as R
from rag.citation_norm import cfr_variants


def test_inland_rules_sections_are_padded_only_where_ecfr_pads_them():
    assert cfr_variants("33", "83.5") == ["33 CFR 83.05"]
    assert cfr_variants("33", "87.1") == ["33 CFR 87.01"]
    assert cfr_variants("33", "83.05") == []   # already stored form
    assert cfr_variants("33", "81.1") == []    # Part 81 really is 81.1
    assert cfr_variants("33", "89.3") == []
    assert cfr_variants("46", "83.5") == []    # only Title 33


def test_redesignated_medical_section():
    assert cfr_variants("46", "10.215") == ["46 CFR 10.302"]


def test_retriever_looks_up_the_stored_form_too():
    ids = [i for i in R._extract_identifiers("33 CFR 87.1 distress signals") if i["type"] == "cfr_section"]
    assert [i["section_number"] for i in ids] == ["33 CFR 87.1", "33 CFR 87.01"]
    assert all(i["source_filter"] == ("cfr_33",) for i in ids)


def test_new_scoped_titles_resolve_as_corpus_sections():
    ids = [i for i in R._extract_identifiers("40 CFR 139.21 graywater") if i["type"] == "cfr_section"]
    assert ids[0]["section_number"] == "40 CFR 139.21" and ids[0]["source_filter"] == ("cfr_40",)


def test_waterway_terms_lift_the_bulletin_group_as_whole_words_only():
    # "below waterline" contains "low water"; the group gets +0.20
    assert R._source_affinity("Which openings below waterline need watertight closures?").get("uscg_bulletin") is None
    assert R._source_affinity("high water tow size limits on the Lower Mississippi").get("uscg_bulletin") == 0.20
    assert R._source_affinity("Do I check in with VTS before Algiers Point?").get("uscg_bulletin") == 0.20
