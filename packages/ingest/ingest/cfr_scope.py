"""Which CFR parts a source ingests (2026-09-25).

Title 49 is mostly not maritime: rail (Parts 200-299), FMCSA trucking
(300-399), pipelines (190-199), transit accessibility (37/38) and the Surface
Transportation Board (1000+). Ingested whole, those parts competed for the CFR
group's retrieval slots. In the 2026-09-23/25 audited sessions a locomotive
rule ranked #2 for "lifeboat lowering", and 49 CFR 391 (truck-driver medical
rules) outranked the mariner-medical NVIC on the gold medical-certificate
questions (docs/sprint-audits/question-audit-2026-09-25.md §3.6).

A source missing from CFR_PART_SCOPE ingests every part.
"""

from __future__ import annotations

import re

CFR_PART_SCOPE: dict[str, frozenset[int]] = {
    "cfr_49": frozenset({
        40,                      # drug and alcohol testing (incorporated by 46 CFR 16)
        105, 106, 107, 109,      # hazmat program procedures, special permits
        171, 172, 173,           # HMR: general, HMT and communication, shippers
        176,                     # carriage by vessel
        178, 180,                # packaging specifications, qualification and maintenance
        450, 451, 452, 453,      # Coast Guard: safe containers (CSC)
        831, 850,                # NTSB investigations, incl. marine casualties
        1520,                    # TSA: sensitive security information (33 CFR 104 plans)
        1570, 1572,              # TSA: TWIC and security threat assessments
    }),
}

_PART_RE = re.compile(r"^\d+\s+CFR\s+(\d+)")


def in_scope(source: str, section_number: str) -> bool:
    parts = CFR_PART_SCOPE.get(source)
    if parts is None:
        return True
    m = _PART_RE.match(section_number or "")
    return bool(m) and int(m.group(1)) in parts


def scope_sections(source: str, sections: list) -> list:
    return [s for s in sections if in_scope(source, s.section_number)]
