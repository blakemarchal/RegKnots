"""Authority-tier mapping for retrieved sources.

Sprint D3 — pairs with the AUTHORITY AND APPLICABILITY block in
`packages/rag/rag/prompts.py`. Every chunk built into the context
carries a tier label so the synthesizer can reason about how to weight
sources when they conflict.

Tier semantics (read carefully — "higher tier wins" only applies on
conflict within the same subject matter):

    Tier 1 — Binding statute / treaty
        Federal regulations (46/33/49 CFR), international treaties
        (SOLAS, COLREGs, STCW, ISM Code). These ARE the requirement.

    Tier 2 — Federal interpretive guidance
        NVICs, NMC Policy Letters, NMC Application Checklists.
        Authoritative interpretation of Tier 1 rules.

    Tier 3 — Time-sensitive operational notice
        USCG bulletins (MSIBs, ALCOASTs, NMC announcements). Always
        time-stamped; operational rather than regulatory.

    Tier 4 — Domain-specific reference standard
        ERG (the authoritative source for hazardous materials first
        response). Tier 4 is NOT "low priority" — it is the correct
        source within its domain. The prompt explicitly protects Tier 4
        from being deprioritized when it is the right answer source
        (e.g., hazmat emergency response).

Supplements (SOLAS/STCW/ISM supplements) inherit their parent's tier.
"""
from __future__ import annotations

# Mapping from the `source` column value (see migration 0045's check
# constraint for the canonical list) to authority tier.
_SOURCE_TO_TIER: dict[str, int] = {
    # Tier 1 — binding statute / treaty
    "cfr_33": 1,
    "cfr_46": 1,
    "cfr_49": 1,
    "usc_46": 1,
    "solas": 1,
    "solas_supplement": 1,
    "colregs": 1,
    "stcw": 1,
    "stcw_supplement": 1,
    "ism": 1,
    "ism_supplement": 1,
    # Tier 2 — federal interpretive guidance
    "nvic": 2,
    "nmc_policy": 2,
    "nmc_checklist": 2,
    # Tier 3 — operational notice
    "uscg_bulletin": 3,
    # Tier 4 — domain reference standard
    "erg": 4,
}

_TIER_LABEL: dict[int, str] = {
    1: "Tier 1 — binding regulation/treaty",
    2: "Tier 2 — federal interpretive guidance",
    3: "Tier 3 — operational notice (time-sensitive)",
    4: "Tier 4 — domain reference standard",
}


def tier_for_source(source: str | None) -> int:
    """Return the authority tier for a given source column value.

    Unknown sources default to Tier 2 (treated as interpretive guidance).
    This is a safe default — better to have the synthesizer treat an
    unmapped source as guidance-level than as binding regulation.
    """
    if not source:
        return 2
    return _SOURCE_TO_TIER.get(source, 2)


def tier_label(tier: int) -> str:
    """Human-readable label shown in the context block."""
    return _TIER_LABEL.get(tier, f"Tier {tier}")
