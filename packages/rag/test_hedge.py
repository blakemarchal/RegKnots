"""Regression tests for hedge phrase detection (Sprint D6.84 hotfix +
D6.86 soft-hedge expansion).

Each new lexicon variant added to packages/rag/rag/hedge.py should
have a positive case here that exercises the literal production prose
that motivated the pattern, plus a negative case that confirms a
related-but-legitimate regulatory statement does NOT trigger.

Usage:
    uv run python test_hedge.py     (standalone)
    uv run pytest test_hedge.py     (pytest discovery)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag.hedge import detect_hedge


def _ok() -> None:
    print("  PASS")


def _fail(msg: str) -> None:
    print(f"  FAIL -- {msg}")
    raise AssertionError(msg)


def _expect_match(text: str, label: str) -> None:
    m = detect_hedge(text)
    if m is None:
        _fail(f"{label}: expected hedge match but got None  -- {text!r}")


def _expect_no_match(text: str, label: str) -> None:
    m = detect_hedge(text)
    if m is not None:
        _fail(f"{label}: expected NO match but got {m!r}  -- {text!r}")


# ── D6.84 hotfix — full-form "did not surface" / "cannot fully answer" ─


def test_d684_full_form_did_not_surface() -> None:
    print("test_d684_full_form_did_not_surface")
    _expect_match(
        "Based on the retrieved regulation context, I did not surface a "
        "specific requirement stating whether watertight door gaskets must "
        "be open-cell or closed-cell.",
        "full-form 'did not surface'",
    )
    _expect_match("I didn't surface a specific requirement.", "contracted 'didn't surface'")
    _expect_match("Cannot fully answer this from the verified context.", "cannot fully answer (full form)")
    _expect_match("Can't fully answer this from the verified context.", "can't fully answer (contracted)")
    _ok()


# ── D6.86 — soft regulatory-silence prose ─────────────────────────────


def test_d686_does_not_specify() -> None:
    print("test_d686_does_not_specify")
    _expect_match(
        "The retrieved regulation context does not specify whether gaskets "
        "must be open-cell or closed-cell material.",
        "regulation context does not specify",
    )
    _expect_match(
        "46 CFR 174.100 does not specify cell type.",
        "does not specify cell",
    )
    _expect_match(
        "but does not prescribe the cell type",
        "does not prescribe the cell",
    )
    _ok()


def test_d686_focus_on_performance() -> None:
    print("test_d686_focus_on_performance")
    _expect_match(
        "Both 46 CFR 174.100 and SOLAS Ch.II-1 Reg.16 focus on performance "
        "rather than cell structure.",
        "focus on performance rather than",
    )
    _expect_match(
        "These regulations focuses on performance rather than design.",
        "focuses on performance rather than (verb form)",
    )
    _ok()


def test_d686_no_regulatory_specification() -> None:
    print("test_d686_no_regulatory_specification")
    _expect_match(
        "There is no regulatory specification for cell structure in the corpus.",
        "no regulatory specification",
    )
    _expect_match(
        "The internal cell structure is not a regulatory specification.",
        "is not a regulatory specification",
    )
    _ok()


def test_d686_performance_based_not_x_based() -> None:
    print("test_d686_performance_based_not_x_based")
    _expect_match(
        "These are performance-based, not structure-based requirements.",
        "performance-based, not structure-based",
    )
    _expect_match(
        "Performance based, not material based.",
        "performance based, not material based (space variant)",
    )
    _ok()


def test_d686_no_x_mandate() -> None:
    print("test_d686_no_x_mandate")
    _expect_match("no cell-structure mandate", "no cell-structure mandate")
    _expect_match("no specific specification", "no specific specification")
    _expect_match("no material mandate", "no material mandate")
    _ok()


# ── False-positive checks: legitimate regulatory factual statements ──
# These should NOT trigger any pattern; if they do, the regex is over-
# matching and will cause spurious hedge-judge invocations + web
# fallback fires on confident answers.


def test_no_false_positives_on_regulatory_facts() -> None:
    print("test_no_false_positives_on_regulatory_facts")
    legitimate_statements = [
        "Subchapter T applies to small passenger vessels carrying 6 or fewer passengers for hire.",
        "46 CFR 199.180 requires quarterly inspection of survival craft.",
        "The vessel must carry a minimum of 4 fire extinguishers.",
        "Watertight doors shall be of approved type per SOLAS Ch.II-1 Reg.13.",
        "Compatibility with the cargo is the controlling regulatory specification.",
        "A bowline knot is the standard fix for a temporary loop in a line.",
        "The COI specifies the manning requirement for this vessel.",
        "Title 46 CFR Subchapter F covers marine engineering.",
        "Performance criteria are listed in 46 CFR 174.100.",
    ]
    for text in legitimate_statements:
        _expect_no_match(text, "no FP on regulatory fact")
    _ok()


# ── Runner ───────────────────────────────────────────────────────────


def _run_all() -> None:
    test_d684_full_form_did_not_surface()
    test_d686_does_not_specify()
    test_d686_focus_on_performance()
    test_d686_no_regulatory_specification()
    test_d686_performance_based_not_x_based()
    test_d686_no_x_mandate()
    test_no_false_positives_on_regulatory_facts()


if __name__ == "__main__":
    print("Running hedge.py regression tests...")
    _run_all()
    print("\nAll hedge.py tests PASSED")
