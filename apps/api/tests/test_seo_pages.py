"""2026-10-14 — regulation pages for search: section text, slugs and the checks
that decide whether a page is published (app/seo_pages.py)."""
from app import seo_pages as S

SEC = "46 CFR 142.315"
TEXT = (
    "(a) A towing vessel that is certificated for rivers, lakes, bays, and sounds, less than 3 nautical "
    "miles from shore on the Great Lakes, must be equipped with an approved 160–B semi-portable "
    "fire-extinguishing system to protect the engine room.\n\n"
    "(b) The owner or managing operator must ensure the system is inspected at least once every twelve "
    "months, as required by § 142.240 of this part.\n\n"
    "(c) Each extinguisher must be within 50 feet of the “engine room” entrance."
)
PAGE = {"section_number": SEC, "display_number": SEC, "source_text": TEXT, "collection": "subchapter-m"}
CORPUS = {SEC, "46 CFR 142.240"}


def good_content(**over):
    content = {
        "topic": "Fixed and semi-portable fire extinguishing systems",
        "meta_description": "Which towing vessels need a semi-portable or fixed system for the engine room.",
        "summary": "Some towing vessels must protect the engine room with an approved system.",
        "applies_to": "Towing vessels certificated for rivers, lakes, bays and sounds.",
        "requirements": [
            {"statement": "The system must be inspected at least every 12 months (see 46 CFR 142.240).",
             "quote": "must ensure the system is inspected at least once every twelve months", "paragraph": "(b)"},
            {"statement": "Each extinguisher must be within 50 feet of the engine room entrance.",
             "quote": 'Each extinguisher must be within 50 feet of the "engine room" entrance', "paragraph": "(c)"},
        ],
        "faqs": [{"question": "Does a river towboat need a 160-B system?",
                  "answer": "Yes, under paragraph (a) it needs an approved 160-B semi-portable system.",
                  "quote": "must be equipped with an approved 160-B semi-portable fire-extinguishing system"}],
        "related_sections": ["46 CFR 142.240"],
    }
    content.update(over)
    return content


def test_join_chunks_drops_headers_enrichment_and_overlap():
    chunks = [
        f"[{SEC}] Fire extinguishing\n\n[Search terms: FF, 160-B]\n\n(a) First.\n\n(b) Second.\n\n(c) Third.",
        f"[{SEC}] Fire extinguishing\n\n(b) Second.\n\n(c) Third.\n\n(d) Fourth.",
    ]
    assert S.join_chunks(chunks, SEC) == "(a) First.\n\n(b) Second.\n\n(c) Third.\n\n(d) Fourth."


def test_selection_helpers():
    assert not S.is_substantive("[Reserved]", "x" * 400)
    assert not S.is_substantive("Definitions", "short")
    assert S.is_substantive("Definitions", "x" * 400)
    assert S.slugify("46 CFR 142.315") == "46-cfr-142-315"
    assert S.slugify("COLREGS Annex II") == "colregs-annex-ii"
    assert S.slugify("NVIC 10-02 CH-1") == "nvic-10-02-ch-1"
    assert S.display_number("COLREGS Rule 11") == "COLREGs Rule 11"
    assert S.ecfr_url("46 CFR 142.315") == "https://www.ecfr.gov/current/title-46/section-142.315"
    assert S.ecfr_url("COLREGS Rule 11") is None


def test_quotes_match_through_typography_but_not_edits():
    norm = S.normalize(TEXT)
    assert S.quote_found("approved 160-B semi-portable fire-extinguishing system", norm)     # en dash in the text
    assert S.quote_found('within 50 feet of the "engine room" entrance.', norm)               # curly quotes
    assert S.quote_found("Each   extinguisher must be\nwithin 50 feet", norm)                 # whitespace
    assert not S.quote_found("within 40 feet of the engine room entrance", norm)               # a changed word
    assert not S.quote_found("must ensure ... twelve months", norm)                            # an ellipsis
    assert not S.quote_found("50 feet", norm)                                                  # too short


def test_numbers_must_come_from_the_text():
    allowed = S.source_numbers(TEXT)
    assert "12" in allowed and "50" in allowed           # "twelve" counts as 12
    assert S.stray_numbers("Inspect every 12 months; see 46 CFR 142.240(b)(1) and § 142.226.", allowed) == []
    assert S.stray_numbers("Within 60 feet of the entrance.", allowed) == ["60"]
    assert "24" in S.source_numbers("within twenty-four hours")
    assert S.stray_numbers("Rule 13 and Part 142, Subpart C, paragraph (a)(3).", set()) == []


def test_cited_sections():
    assert S.cited_sections("See 46 CFR 142.240 and § 142.226; COLREGs Rule 13, COLREGS annex ii.", "46") == {
        "46 CFR 142.240", "46 CFR 142.226", "COLREGS Rule 13", "COLREGS Annex II"}


def test_static_checks_pass_a_faithful_page():
    result = S.static_checks(PAGE, good_content(), CORPUS)
    assert result == {"ok": True, "failures": []}


def test_static_checks_catch_each_kind_of_error():
    bad_quote = good_content(requirements=[{"statement": "Inspect every 12 months.",
                                            "quote": "must inspect the system every year", "paragraph": "(b)"}])
    assert S.static_checks(PAGE, bad_quote, CORPUS)["failures"] == ["requirement 1: quote not in the text"]

    bad_number = good_content(summary="Extinguishers must be within 75 feet of the engine room.")
    failures = S.static_checks(PAGE, bad_number, CORPUS)["failures"]
    assert len(failures) == 1 and failures[0].startswith("numbers not in the text: 75")

    bad_cite = good_content(related_sections=["46 CFR 142.999"])
    assert S.static_checks(PAGE, bad_cite, CORPUS)["failures"] == [
        "sections neither in the corpus nor named in the text: 46 CFR 142.999"]
    # A reference the text itself makes passes even when the corpus lacks it.
    text_ref = {**PAGE, "source_text": TEXT + " (d) See 46 U.S.C. 3306 and 46 CFR part 67."}
    named = good_content(related_sections=["46 U.S.C. 3306", "46 CFR Part 67"])
    assert S.static_checks(text_ref, named, CORPUS)["ok"]

    assert "no requirements" in S.static_checks(PAGE, good_content(requirements=[]), CORPUS)["failures"]


def test_support_items_cover_every_statement():
    items = S.support_items(good_content())
    assert len(items) == 3 + 2 + 1      # summary, meta, applies_to, 2 requirements, 1 faq
    assert items[0]["quote"] == "" and items[3]["quote"].startswith("must ensure")


def test_writer_request_shape():
    page = {**PAGE, "section_title": "Fire extinguishing", "up_to_date_as_of": "2026-03-31"}
    params = S.request_params(page)
    assert params["model"] == S.GEN_MODEL and params["output_config"]["effort"] == "low"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "current as of 2026-03-31" in params["messages"][0]["content"]
    assert S.compose_title(page, good_content()) == f"{SEC}: Fixed and semi-portable fire extinguishing systems"
