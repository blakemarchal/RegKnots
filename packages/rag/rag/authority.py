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
    # UK Merchant Shipping Notices (MSN) — Sprint D6.18. Carry the
    # technical specification behind UK Statutory Instruments (e.g.
    # MSN 1676 holds the binding LSA detail referenced by the Merchant
    # Shipping (Life-Saving Appliances) Regulations). For a UK-flagged
    # vessel they are binding alongside the SI itself.
    "mca_msn": 1,
    # AMSA Marine Orders — Sprint D6.20. Australia's primary maritime
    # regulatory instruments, made under the Navigation Act 2012.
    # Tier 1 (binding) for Australian-flagged vessels and for any
    # vessel in Australian waters or calling at an Australian port.
    "amsa_mo": 1,
    # LISCR Marine Notices — Sprint D6.20. Liberian flag-state
    # implementation guidance for IMO conventions. Tier 2 (interpretive
    # guidance) — they tell Liberian-flagged vessels HOW to comply with
    # the binding IMO instruments; the IMO instruments themselves remain
    # the Tier 1 source.
    "liscr_mn": 2,
    # IRI Marine Notices — Sprint D6.20. Marshall Islands flag-state
    # implementation guidance. Same posture as LISCR — Tier 2.
    "iri_mn": 2,
    # Singapore MPA Shipping Circulars — Sprint D6.22. Singapore-flag
    # binding regulatory guidance. Tier 1 for SG-flag.
    "mpa_sc": 1,
    # Hong Kong Marine Department MSINs — Sprint D6.22. HK-flag binding
    # technical guidance equivalent to UK MSNs. Tier 1.
    "mardep_msin": 1,
    # Transport Canada Ship Safety Bulletins — Sprint D6.22. Advisory
    # bulletins (binding regs live in CSA + Marine Personnel Regs which
    # are not in this corpus). Tier 2.
    "tc_ssb": 2,
    # Bahamas Maritime Authority Marine Notices — Sprint D6.22. Open
    # registry guidance, same posture as LISCR/IRI. Tier 2.
    "bma_mn": 2,
    # Norway NMA circulars — Sprint D6.23. Tier 1 binding for NO-flag.
    "nma_rsv": 1,
    # IACS Unified Requirements — Sprint D6.23. Domain technical
    # reference standard (class survey scope). Tier 4 — same protection
    # ERG gets: authoritative within domain, doesn't outrank SOLAS for
    # questions outside class-survey scope.
    "iacs_ur": 4,
    # IMO codes that supplement SOLAS — Sprint D6.23. Tier 1 binding
    # for the vessel types they govern (peers of SOLAS, not subordinate).
    "imo_css": 1,
    "imo_loadlines": 1,
    "imo_igc": 1,
    "imo_ibc": 1,
    "imo_hsc": 1,
    # IAMSAR Vol III — reference manual for shipboard SAR. Tier 4.
    "imo_iamsar": 4,
    # MOU PSC reports + deficiency codes — Tier 3 time-sensitive
    # operational notices. Always cite with publication date.
    "mou_psc": 3,
    # Tier 2 — federal interpretive guidance
    "nvic": 2,
    "nmc_policy": 2,
    "nmc_checklist": 2,
    # UK Marine Guidance Notes (MGN) — authoritative MCA interpretation
    # of UK regs / IMO instruments. Parallels NVIC. Not itself binding
    # but routinely cited by MCA inspectors and Paris MOU PSC officers.
    "mca_mgn": 2,
    # USCG Marine Safety Manual (CIM 16000.X) — Coast Guard internal
    # operational procedures and inspector guidance. Tier 2 because it's
    # how USCG personnel implement the binding 33/46/49 CFR rules; not
    # itself binding regulation, but authoritative for how PSC and
    # inspection programs are conducted in practice.
    "uscg_msm": 2,
    # Tier 3 — operational notice
    "uscg_bulletin": 3,
    # Tier 4 — domain reference standard
    "erg": 4,
    # WHO IHR 2005 is an international treaty adopted by the World Health
    # Assembly and binding on member states. Tier 1 for port-health
    # questions; the Secretary of HHS implements domestically via
    # 42 CFR 71 (not in corpus — WHO IHR is the authoritative source
    # users should cite for ship sanitation certificates and port health).
    "who_ihr": 1,
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
