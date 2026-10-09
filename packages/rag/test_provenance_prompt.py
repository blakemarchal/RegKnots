"""2026-10-08 — the sources-and-gaps prompt (rag.prompts.PROVENANCE_*)."""
from rag.prompts import assemble_system_prompt as A

PLUMBING = ("didn't surface", "did not surface", "I didn't retrieve", "did not retrieve", "not in the excerpts",
            "retrieved context for this", "retrieved context does not", "from the retrieved context")


def test_no_example_phrase_teaches_the_model_to_describe_its_search():
    p = A(model_led=True, provenance=True)
    for phrase in PLUMBING:
        assert phrase not in p, phrase


def test_the_rules_that_matter_survive():
    p = A(model_led=True, provenance=True)
    for kept in ("SOURCES AND GAPS", "NEVER DESCRIBE YOUR OWN SEARCH", "NEVER ASSERT NON-EXISTENCE",
                 "Never invent a section number", "UN-NUMBER GROUNDING RULE", "AUTHORITY HIERARCHY",
                 "29 CFR: only OSHA", "This tool is a navigation aid only", "Always cite specific sections inline",
                 "LEAD WITH THE CONCLUSION"):
        assert kept in p, kept
    assert "NO HALLUCINATED RECOMMENDATIONS" not in p        # folded into SOURCES AND GAPS


def test_off_and_precision_mode_are_unchanged():
    assert A(model_led=True, provenance=False) == A(model_led=True)
    assert A(precision_mode=True, model_led=True, provenance=True) == A(precision_mode=True)
