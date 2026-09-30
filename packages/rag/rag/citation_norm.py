"""CFR citations the model writes one way and the corpus stores another (2026-09-30).

Unverified citations in the log were mostly numbering the model remembers
(docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §2):

  - The Inland Navigation Rules and their annexes (33 CFR 83, 84, 86, 87, 88)
    number sections with two digits: Rule 5 is 33 CFR 83.05, the distress
    signals are 87.01-87.03. "33 CFR 83.5" / "33 CFR 87.1" found nothing.
    Parts 81, 82, 89 and 90 really are 81.1, 89.3 … (checked against eCFR).
  - 46 CFR 10.215 (medical and physical requirements) moved to Part 10
    Subpart C; the requirements are now 46 CFR 10.302 (10.301-10.306).

cfr_variants() returns the stored section_numbers such a citation may mean, for
the answer verifier (engine) and the retriever's citation lookup.
"""
from __future__ import annotations

import re

# section_number the model cites -> where the text lives now
REDESIGNATED: dict[str, tuple[str, ...]] = {
    "46 CFR 10.215": ("46 CFR 10.302",),
}

# Parts whose sections are numbered NN.0N (eCFR, 2026-09-28)
_TWO_DIGIT_SECTIONS: dict[str, frozenset[int]] = {
    "33": frozenset({83, 84, 86, 87, 88}),
}


def cfr_variants(title: str, section: str) -> list[str]:
    """Other section_numbers that "<title> CFR <section>" may refer to."""
    out = list(REDESIGNATED.get(f"{title} CFR {section}", ()))
    m = re.fullmatch(r"(\d+)\.(\d)", section or "")
    if m and int(m.group(1)) in _TWO_DIGIT_SECTIONS.get(title, ()):
        out.append(f"{title} CFR {m.group(1)}.0{m.group(2)}")
    return out
