"""2026-09-27 — NVIC citations in answers name enclosures and changes the way
the corpus does ("NVIC 06-72 Encl.1", "NVIC 04-03 Encl.3 §12", "NVIC 04-08
Ch-2 §3"). Verification stays a prefix match on the NVIC number."""
from rag import engine


def _nvic(answer):
    return {c.display: c.candidates for c in engine._extract_all_text_citations(answer)
            if c.display.startswith("NVIC")}


def test_nvic_citation_forms():
    found = _nvic("See (NVIC 06-72 Encl.1), NVIC 04-03 Encl.3 §12, NVIC 06-72, Enclosure (2), "
                  "(NVIC 04-08 Ch-2 §3) and NVIC 1-86 §1.")
    assert set(found) == {"NVIC 06-72 Encl.1", "NVIC 04-03 Encl.3 §12", "NVIC 06-72 Encl.2",
                          "NVIC 04-08 Ch-2 §3", "NVIC 1-86 §1"}
    assert found["NVIC 04-03 Encl.3 §12"] == [("nvic", "NVIC 04-03%")]
    assert found["NVIC 1-86 §1"] == [("nvic", "NVIC 1-86%"), ("nvic", "NVIC 01-86%")]


def test_an_unverified_enclosure_citation_is_stripped_whole():
    out = engine._strip_unverified_citations(
        "Inspect the hull plating (NVIC 99-99 Encl.1).", ["NVIC 99-99 Encl.1"])
    assert out == "Inspect the hull plating."
