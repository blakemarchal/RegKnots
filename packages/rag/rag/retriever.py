"""
Hybrid semantic + keyword retriever with source-diversified fetch.

Retrieval strategy:

1. Embed the query once.
2. Detect regulation identifiers in the query (UN numbers, CFR sections,
   COLREGs rules, etc.) and run keyword search for matching chunks.
3. Run one vector search per configured source group, CONCURRENTLY. Each
   group gets its own top-N candidate pool, so small sources (COLREGs: 102,
   SOLAS: 742) aren't outranked by large ones (CFR: ~33K chunks) just
   because the large sources have more chunks to draw from.
4. Merge keyword results into vector results, deduplicate by section_number.
5. Apply two soft boosts:
     - Source affinity: when the query unambiguously targets a source
       (e.g., mentions COLREGs, 46 CFR, SOLAS chapter, STCW), boost chunks
       from that source's group.
     - Vessel profile: when a vessel_profile is provided, boost chunks
       whose full_text mentions the vessel's type / route / cargo.
6. Sort by similarity + boosts, return top `limit`.

Adding a new source (e.g., MARPOL) is just a one-line edit to SOURCE_GROUPS
and an entry in _source_affinity if it has distinctive keywords. No other
code changes required — the diversified fetch adapts automatically.
"""

import asyncio
import logging
import re
import time

import asyncpg
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"

# ── Source groups ────────────────────────────────────────────────────────────
#
# Sources are grouped by regulatory body/type so related sub-sources stay
# together. Each group fetches its own top-N independently in Phase 1.
SOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "cfr": ("cfr_33", "cfr_46", "cfr_49"),
    # 46 USC (statute) gets its own group so it isn't crowded out by the
    # much larger CFR corpus during per-group diversification. Sprint D5.1.
    "usc": ("usc_46",),
    "colregs": ("colregs",),
    "solas": ("solas", "solas_supplement"),
    "nvic": ("nvic",),
    "stcw": ("stcw", "stcw_supplement"),
    "ism": ("ism", "ism_supplement"),
    # MARPOL (International Convention for the Prevention of Pollution
    # from Ships) — Sprint D6.11. Distinct group so pollution / oil
    # discharge / IOPP / sewage / garbage / Annex VI air-emissions
    # queries reliably surface MARPOL convention text alongside the U.S.
    # CFR domestic implementation in 33 CFR Subchapter O.
    "marpol": ("marpol", "marpol_supplement"),
    # IMDG Code (International Maritime Dangerous Goods Code) — Sprint
    # D6.12. Distinct group so dangerous-goods classification, packing,
    # consignment, segregation, and stowage queries reliably surface
    # the IMDG text alongside the U.S. domestic 49 CFR HazMat regs and
    # ERG response guides. UN-number identifier matching already serves
    # both ERG and IMDG via per-source diversification.
    # Sprint D6.12b — adds imdg_supplement (errata + future supplements).
    "imdg": ("imdg", "imdg_supplement"),
    "erg": ("erg",),
    # NMC policy letters + checklists share a group so the credentialing
    # corpus draws candidates together (mirrors the CFR group's 3 titles).
    "nmc": ("nmc_policy", "nmc_checklist"),
    # USCG GovDelivery bulletins — MSIBs, NMC announcements, policy-letter
    # notices, ALCOAST mentions. Distinct from 'nmc' because bulletins are
    # broader (port security, enforcement, environmental, weather) and
    # carry freshness metadata that retrieval can filter on later.
    "uscg_bulletin": ("uscg_bulletin",),
    # USCG Marine Safety Manual (CIM 16000.X). Own group so PSC /
    # inspection-procedure queries reliably surface MSM content alongside
    # the binding CFR rules they implement. Sprint D6.4.
    "uscg_msm": ("uscg_msm",),
    # WHO IHR (international health / port sanitation) — its own group so
    # port-health queries reliably surface IHR content. Sprint D5.4.
    "who": ("who_ihr",),
    # UK Maritime and Coastguard Agency notices — Sprint D6.18. RegKnots'
    # first non-US national-flag corpus. MGN is authoritative MCA guidance
    # (Tier 2, parallels NVIC). MSN carries the binding technical detail of
    # statutory instruments (Tier 1, parallels CFR section text). Grouped
    # together so any "UK" / non-US-flag / Channel-route query that surfaces
    # one type also draws candidates from the other for cross-coverage.
    "mca": ("mca_mgn", "mca_msn"),
    # AMSA Marine Orders — Sprint D6.20. Australia's primary maritime
    # regulatory instruments, made under the Navigation Act 2012.
    # Tier 1 binding for AU-flagged vessels and vessels in AU waters.
    "amsa": ("amsa_mo",),
    # LISCR Marine Notices — Sprint D6.20. Liberian flag-state guidance.
    # Tier 2 — interpretive layer above the IMO instruments.
    "liscr": ("liscr_mn",),
    # IRI Marine Notices — Sprint D6.20. Marshall Islands flag-state
    # guidance. Same posture as LISCR.
    "iri": ("iri_mn",),
    # Sprint D6.22 — fourth-wave national flags.
    "mpa": ("mpa_sc",),
    "mardep": ("mardep_msin",),
    "tc": ("tc_ssb",),
    "bma": ("bma_mn",),
    # Sprint D6.23 — Norway + Tier D international references.
    "nma": ("nma_rsv",),
    # IACS class society in its own group so technical-class queries
    # can find UR content without crowding the IMO instrument groups.
    "iacs": ("iacs_ur",),
    # IMO codes share a group — they're peer instruments to SOLAS that
    # bind specific vessel types (HSC for fast craft, IGC/IBC for
    # gas/chemical tankers, Load Lines universal, CSS via SOLAS Ch.VI).
    "imo_codes": ("imo_css", "imo_loadlines", "imo_igc", "imo_ibc", "imo_hsc"),
    # IMO reference manuals (operational guidance, not binding rule).
    "imo_ref": ("imo_iamsar",),
    # Port State Control regimes (Tokyo MOU + Paris MOU).
    "mou": ("mou_psc",),
}

# Per-group candidate pool sizes. CFR is larger because it covers three
# sub-titles (~33K total chunks) and needs room for intra-CFR diversity.
_CANDIDATES_PER_GROUP: dict[str, int] = {
    "cfr": 12,
}
_DEFAULT_CANDIDATES_PER_GROUP = 6

# Sprint D5.5 — maximum chunks retained per section_number during
# deduplication. Previously 1 (strict); now 2 so multi-chunk sections
# (e.g. 46 CFR 199.175 has 11 chunks — intro rules in chunk 0, specific
# equipment in chunks 1-8, Table 1 with quantity counts in chunks 9-10)
# can surface both a scene-setter and a specific-answer chunk in the
# same retrieval. The alternative (top-1) suppresses Table-1 style
# content behind chunk-0 intros that score higher on vector similarity.
_MAX_CHUNKS_PER_SECTION = 2

# Reverse index: source_code → group_name. Built once at module load.
_SOURCE_TO_GROUP: dict[str, str] = {
    src: group_name
    for group_name, srcs in SOURCE_GROUPS.items()
    for src in srcs
}

# ── Source-existence cache ───────────────────────────────────────────────────
#
# Populated lazily on the first retrieve() call with a single
# `SELECT DISTINCT source` query, then reused for the life of the process.
# This lets us skip groups whose sources haven't been ingested yet (e.g.,
# MARPOL before it exists) without a per-call overhead.
_AVAILABLE_SOURCES: set[str] | None = None
_AVAILABLE_SOURCES_LOCK = asyncio.Lock()


async def _get_available_sources(pool: asyncpg.Pool) -> set[str]:
    global _AVAILABLE_SOURCES
    if _AVAILABLE_SOURCES is not None:
        return _AVAILABLE_SOURCES
    async with _AVAILABLE_SOURCES_LOCK:
        if _AVAILABLE_SOURCES is not None:
            return _AVAILABLE_SOURCES
        rows = await pool.fetch(
            "SELECT DISTINCT source FROM regulations WHERE embedding IS NOT NULL"
        )
        _AVAILABLE_SOURCES = {r["source"] for r in rows}
        logger.info(
            "Retriever source cache populated: %s",
            sorted(_AVAILABLE_SOURCES),
        )
    return _AVAILABLE_SOURCES


# ── Source affinity (query-keyword → group boost) ────────────────────────────
#
# A soft nudge, NOT a filter. The diversified fetch already guarantees each
# group has candidates in the pool; these boosts just promote the clearly-
# targeted group within the final top-8.

_COLREGS_TERMS: tuple[str, ...] = (
    "colreg", "collision regulation", "rules of the road", "rule of the road",
    "72 colregs",
    "head-on", "head on situation", "crossing situation", "overtaking",
    "give-way", "give way vessel", "stand-on", "stand on vessel",
    "look-out", "lookout", "risk of collision", "narrow channel",
    "traffic separation", "restricted visibility",
    "navigation light", "navigation lights", "masthead light",
    "sidelight", "side light", "stern light", "anchor light",
    "fog signal", "sound signal", "whistle signal",
    "manoeuvring signal", "maneuvering signal",
    "shapes",
)
_COLREGS_RULE_RE = re.compile(r"\brules?\s*([0-9]{1,2})\b", re.IGNORECASE)
_COLREGS_ANNEX_RE = re.compile(r"\bannex\s*([ivx]+|[0-9])\b", re.IGNORECASE)

_SOLAS_TERMS: tuple[str, ...] = (
    "solas", "safety of life at sea", "msc.",
    "regulation ii", "regulation iii", "regulation iv", "regulation v",
    "chapter ii", "chapter iii", "chapter iv", "chapter v",
    "voyage data recorder", "lrit",
    "global maritime distress", "gmdss",
)
_SOLAS_ABBR_RE = re.compile(r"\b(?:vdr|s-vdr|epirb|sart)\b", re.IGNORECASE)

_STCW_TERMS: tuple[str, ...] = (
    "stcw", "training certification watchkeeping", "seafarer credential",
    "endorsement", "certificate of competency", "watchkeeping",
)

_NVIC_TERMS: tuple[str, ...] = (
    "nvic", "navigation vessel inspection circular",
    "uscg policy", "coast guard guidance", "coast guard policy",
)

# ISM Code keywords. Unambiguous full-phrase terms go in the tuple. The
# abbreviation regex uses word boundaries so "ism" doesn't match "prism" or
# "tourism", and "dpa"/"smc"/"doc 88" only match as standalone tokens.
_ISM_TERMS: tuple[str, ...] = (
    "ism code", "international safety management",
    "safety management system",
    "designated person ashore", "designated person",
    "document of compliance",
    "safety management certificate",
)
_ISM_ABBR_RE = re.compile(
    r"\b(?:ism|dpa|smc|doc\s*88)\b",
    re.IGNORECASE,
)

_ERG_TERMS: tuple[str, ...] = (
    # NOTE: "erg" is matched via _ERG_ABBR_RE with word boundaries — do NOT
    # put it here, because "erg" is a substring of "emergency" and would
    # false-positive on every query containing that word.
    "emergency response guidebook", "emergency response guide",
    "emergency response for", "emergency response to",
    "hazmat", "hazardous material", "dangerous goods",
    "un number", "na number", "placard",
    "isolation distance", "protective action",
    "spill", "chemical spill", "toxic inhalation",
    "guide number", "guide 1",
)
_ERG_ABBR_RE = re.compile(r"\berg\b", re.IGNORECASE)

# NMC (National Maritime Center) — credentialing, medical certificates,
# MMC processing, endorsements. These terms boost nmc_policy + nmc_checklist
# results. The NMC group is small (<25 docs) vs CFR (~33K chunks), so
# affinity boosts are especially important for surfacing this corpus.
_NMC_TERMS: tuple[str, ...] = (
    "nmc", "national maritime center",
    "merchant mariner credential", "mmc renewal", "mmc application",
    "medical certificate", "medical waiver", "cg-719", "cg719",
    "credential renewal", "credential application", "credential upgrade",
    "endorsement", "sea service", "sea time",
    "processing time", "evaluation time",
    "twic", "transportation worker",
    "mariner credential", "mariner license",
    "drug test", "physical exam",
    "stcw endorsement", "national endorsement", "officer endorsement",
    "rating endorsement",
    "raise of grade", "raise in grade", "original issuance",
    "continuity", "document of continuity", "harmonization",
    "physical evaluation", "medical requirements",
    "military sea service", "uniformed service", "credit for service",
    "psc", "proficiency in survival craft", "lifeboatman",
    "oicnw", "officer in charge of a navigational watch",
    "tankerman", "tankerman-pic", "tankerman pic",
    "able seaman", "able-bodied seaman",
    "roupv", "uninspected passenger vessel",
    "liftboat", "polar code",
    "application checklist", "acceptance checklist",
    "application guide",
)
_NMC_ABBR_RE = re.compile(
    r"\b(?:nmc|mmc|twic|cg-?719k?|oicnw|roupv|psc)\b",
    re.IGNORECASE,
)

# MARPOL — International Convention for the Prevention of Pollution from
# Ships. Detection covers Annex-specific keywords (oil discharge, NLS,
# sewage, garbage, air emissions), MEPC-issued amendment vocabulary, and
# the certificate / record-book artifacts that MARPOL governs.
_MARPOL_TERMS: tuple[str, ...] = (
    "marpol",
    # Annex I — Oil. Includes reorderings ("oil discharge"/"discharge of
    # oil") because mariners ask both ways. Substring matching means
    # both orderings need explicit terms.
    "oil discharge", "discharge of oil", "discharge limit",
    "oily mixture", "oily water separator", "ows",
    "oil record book", "iopp", "iopp certificate",
    "international oil pollution prevention",
    "oil pollution prevention", "pollution by oil", "oil pollution",
    "oily water", "oily bilge", "machinery space bilge", "bilge slop",
    "ballast tank", "segregated ballast", "slop tank", "crude oil washing",
    "double hull", "oil tanker construction",
    # Annex II — Noxious liquid substances (chemical tankers)
    "nls", "noxious liquid substances", "chemical tanker", "p&a manual",
    "procedures and arrangements manual", "cargo record book",
    "prewash procedure",
    # Annex III — Harmful packaged substances
    "harmful substances in packaged form",
    # Annex IV — Sewage
    "sewage discharge", "sewage system", "ispp",
    "international sewage pollution prevention", "marine sanitation device",
    "comminuter",
    # Annex V — Garbage
    "garbage record book", "garbage discharge", "garbage management plan",
    "food waste discharge", "plastic discharge",
    # Annex VI — Air emissions
    "air pollution", "air emissions", "sox emissions", "nox emissions",
    "sulphur content", "sulfur content", "fuel oil sulphur", "fuel oil sulfur",
    "low sulphur", "low sulfur", "scrubber", "exhaust gas cleaning",
    "iapp", "iapp certificate", "international air pollution prevention",
    "emission control area", "eca", "secaca", "emissions control area",
    "marpol annex vi", "annex vi",
    # Annex VI carbon intensity (Sprint MEPC.328 era)
    "eedi", "eexi", "cii", "carbon intensity indicator",
    "energy efficiency design index", "energy efficiency existing ship index",
    "iee certificate", "international energy efficiency",
    "fuel oil consumption data", "ship fuel oil consumption database",
    "bunker delivery note",
    # Pollution incidents / reports
    "pollution incident", "spill report", "smpep",
    "shipboard marine pollution emergency plan",
    "shipboard oil pollution emergency plan", "sopep",
    # MEPC resolution vocabulary
    "mepc", "marine environment protection committee",
)
_MARPOL_ABBR_RE = re.compile(
    # Conservative abbreviation matchers — only flag when the abbreviation
    # is unambiguously MARPOL-domain. "ECA" alone is too risky outside
    # context, but "MARPOL Annex VI" / "EEDI" / "EEXI" / "IOPP" / "IAPP" /
    # "ISPP" are distinctive.
    r"\b(?:iopp|iapp|ispp|sopep|smpep|eedi|eexi|secaca|nls)\b",
    re.IGNORECASE,
)


# IMDG Code — International Maritime Dangerous Goods Code. Detection
# covers classification (Class 1-9 + sub-class), packing/transport
# vocabulary, dangerous-goods-list artefacts (UN numbers handled
# separately via _IDENTIFIER_PATTERNS), and the EmS / MFAG / segregation
# vocabulary distinctive to IMDG vs ERG (which is response-side, not
# loading/transport-side).
_IMDG_TERMS: tuple[str, ...] = (
    "imdg", "imdg code",
    # The phrase "dangerous goods" is distinctive enough to anchor on —
    # it's the canonical operational term IMDG governs. SOLAS Ch.VII
    # also uses it but is short; IMDG owns the substantive treatment.
    "dangerous goods", "dangerous good",
    "shipping dangerous", "carriage of dangerous",
    "hazmat shipping", "hazmat declaration",
    # Class taxonomy — sub-class numbers are MUCH more specific than
    # bare "Class 4" which collides with vessel-class CFR usage.
    "class 1.1", "class 1.2", "class 1.3", "class 1.4", "class 1.5", "class 1.6",
    "class 2.1", "class 2.2", "class 2.3",
    "class 3",  # flammable liquids — distinctive enough to keep
    "class 4.1", "class 4.2", "class 4.3",
    "class 5.1", "class 5.2",
    "class 6.1", "class 6.2",
    "class 7",  # radioactive
    "class 8",  # corrosive
    "class 9",  # miscellaneous
    "explosives", "flammable liquid", "flammable solid",
    "flammable gas", "non-flammable gas", "toxic gas",
    "spontaneously combustible", "dangerous when wet", "self-reactive",
    "oxidizing substance", "organic peroxide",
    "infectious substance", "radioactive material",
    "corrosive substance", "miscellaneous dangerous",
    # Packaging / consignment vocabulary
    "packing group", "pg i", "pg ii", "pg iii",
    "packaging instruction", "pack inst", "ibc instruction",
    "portable tank", "tank instruction", "tank code",
    "imdg packaging", "outer packaging", "inner packaging",
    "intermediate bulk container", "ibc",
    "limited quantity", "excepted quantity",
    "marine pollutant",
    "proper shipping name", "psn",
    "subsidiary risk", "subsidiary hazard",
    # Stowage / segregation
    "stowage code", "segregation",
    "stowage category", "segregation table", "segregation group",
    "away from", "separated from", "separated by a complete compartment",
    "separated longitudinally",
    # Documents / declarations
    "dangerous goods declaration", "dg declaration",
    "container packing certificate", "vehicle packing certificate",
    "shipper declaration",
    # Emergency response (specifically the IMDG sub-codes — ERG itself
    # has its own affinity)
    "emergency schedule", "ems guide", "ems code",
    "medical first aid", "mfag",
    # Compliance / training
    "dangerous goods training", "imdg training",
)
_IMDG_ABBR_RE = re.compile(
    # Conservative — only IMDG-distinctive abbreviations. "EmS" + DGL
    # codes (F-A through F-H, S-A through S-Z), MFAG, IBC are
    # unambiguous in the maritime regulatory domain.
    r"\b(?:imdg|ems|mfag)\b|\b(?:F|S)-[A-Z]\b",
    re.IGNORECASE,
)


# USCG bulletin / GovDelivery — MSIBs, port security zones, NMC
# announcements, enforcement priorities, environmental advisories,
# weather/navigation alerts. Broader than NMC credentialing.
_USCG_BULLETIN_TERMS: tuple[str, ...] = (
    "bulletin", "advisory", "alert", "notice to mariners",
    "operational", "operational advisory",
    "msib", "marine safety information bulletin",
    "alcoast", "notmar",
    "port security", "marsec", "security zone", "port closure",
    "safety alert", "equipment recall", "defective",
    "enforcement priority", "psc campaign", "inspection focus",
    "concentrated inspection",
    "hurricane", "storm", "typhoon", "tsunami",
    "aid to navigation", "weather advisory", "navigation safety",
    "pollution response", "oil spill", "environmental compliance",
    "mmc process", "nmc processing", "medical certificate backlog",
    "current", "latest", "recent", "this week", "this month",
)
_USCG_BULLETIN_ABBR_RE = re.compile(
    r"\b(?:msib|alcoast|marsec|notmar)\b",
    re.IGNORECASE,
)


# UK Maritime and Coastguard Agency notices — Sprint D6.18. Terms that
# anchor a query to UK-flag / EU / non-US-jurisdiction context. Country /
# flag / route names live here; the citation-form abbreviations (MGN, MSN)
# are matched separately because they're unambiguous identifiers and
# should bypass the rest of the affinity logic.
_MCA_TERMS: tuple[str, ...] = (
    # Agency / authority
    "mca", "maritime and coastguard agency", "mcga",
    "uk flag", "british flag", "united kingdom flag", "red ensign",
    # UK-specific instruments and concepts
    "merchant shipping notice", "marine guidance note", "boatmaster",
    "uk merchant shipping", "merchant shipping act",
    # UK / EU geography that signals jurisdiction
    "channel crossing", "english channel", "dover", "dunkerque", "calais",
    "portsmouth", "felixstowe", "southampton", "harwich",
    "irish sea", "north sea uk", "thames estuary",
    "uk territorial waters", "uk waters",
    # Common UK-flag operational queries
    "mlc 2006 uk", "stcw uk implementation",
)
_MCA_ABBR_RE = re.compile(
    # Citation form: "MGN 71", "MGN 71 (M+F)", "MSN 1676 Amendment 4".
    # Also "MIN" (Marine Information Note) — not in our corpus yet but the
    # abbreviation is unambiguous in maritime context, so cheap to recognize.
    r"\b(?:MGN|MSN|MIN)\s*\d{1,4}\b",
    re.IGNORECASE,
)


def _source_affinity(query: str) -> dict[str, float]:
    """Return a boost value per source group based on query keywords.

    The diversified fetch guarantees each group has candidates — this
    function just nudges ranking when the query clearly targets a source.
    """
    q = query.lower()
    boosts: dict[str, float] = {}

    if (
        any(t in q for t in _COLREGS_TERMS)
        or _COLREGS_RULE_RE.search(q)
        or _COLREGS_ANNEX_RE.search(q)
    ):
        boosts["colregs"] = 0.20

    if any(t in q for t in _SOLAS_TERMS) or _SOLAS_ABBR_RE.search(q):
        boosts["solas"] = 0.20

    if any(t in q for t in _STCW_TERMS):
        boosts["stcw"] = 0.20

    if any(t in q for t in _NVIC_TERMS):
        boosts["nvic"] = 0.20

    if any(t in q for t in _ISM_TERMS) or _ISM_ABBR_RE.search(q):
        boosts["ism"] = 0.20

    if any(t in q for t in _ERG_TERMS) or _ERG_ABBR_RE.search(q):
        boosts["erg"] = 0.20

    if any(t in q for t in _NMC_TERMS) or _NMC_ABBR_RE.search(q):
        boosts["nmc"] = 0.20
        # Credentialing queries also benefit from CFR Parts 10-16
        boosts.setdefault("cfr", 0.10)

    if any(t in q for t in _USCG_BULLETIN_TERMS) or _USCG_BULLETIN_ABBR_RE.search(q):
        boosts["uscg_bulletin"] = 0.20

    if any(t in q for t in _MARPOL_TERMS) or _MARPOL_ABBR_RE.search(q):
        boosts["marpol"] = 0.20

    if any(t in q for t in _IMDG_TERMS) or _IMDG_ABBR_RE.search(q):
        boosts["imdg"] = 0.20
        # Hazmat queries that boost IMDG often benefit from ERG too —
        # response/transport are adjacent. Boost ERG modestly.
        boosts.setdefault("erg", 0.10)

    # Sprint D6.18 — UK MCA boost. Note: vessel-flag-driven scoping is
    # handled by the system prompt (D6.17 JURISDICTIONAL APPLICABILITY
    # section, which sees flag_state in the vessel_profile block). This
    # affinity boost is just for query-text-driven cases — explicit MGN/
    # MSN citations, UK geography mentions, "MCA" mentions. It's NOT a
    # substitute for flag-state filtering and is intentionally narrower
    # than CFR's (no broad "uk" boost without supporting context).
    if any(t in q for t in _MCA_TERMS) or _MCA_ABBR_RE.search(q):
        boosts["mca"] = 0.20
        # UK ferry queries often span MCA + IMO instruments (SOLAS, STCW,
        # ISM, MARPOL) since UK implements the IMO conventions. Modest
        # supplementary boost so the international context surfaces too.
        boosts.setdefault("solas", 0.10)

    if "cfr" in q or "code of federal" in q:
        boosts["cfr"] = 0.15
        if any(
            t in q
            for t in ("33 cfr", "title 33", "46 cfr", "title 46", "49 cfr", "title 49")
        ):
            boosts["cfr"] = 0.25

    return boosts


# ── Identifier detection (source-agnostic) ────────────────────────────────
#
# Scans the query for known regulation identifier patterns. These are
# arbitrary strings (UN1219, 46 CFR 35.10-5, Rule 14) with no semantic
# meaning — vector search cannot match them, so we fall back to keyword
# search when they are detected.

_IDENTIFIER_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Sprint D6.16 — accept optional whitespace OR hyphen between the
    # "UN" prefix and the four-digit number. Real-world queries write
    # "UN 2734", "UN-2734", and "UN2734" interchangeably; the original
    # pattern only matched the compact form, which is why a real
    # mariner asking about "UN 2734 and UN1202" had only the second
    # number trigger the keyword-search bypass — leading to the
    # confident hallucination Karynn used for marketing.
    ("un_number",    re.compile(r"\b(UN|NA)[\s\-]?(\d{4})\b", re.IGNORECASE)),
    ("erg_guide",    re.compile(r"\b(?:ERG\s+)?Guide\s+(\d{3})\b", re.IGNORECASE)),
    # Sprint D6.16b — extend the CFR section regex to match temporary
    # safety/anchorage zone notation (33 CFR 147.T01-0277) which the
    # original `[\d.]+(?:-[\d]+)?` form truncated to "147". Without this
    # the T-zone tables (5 of the 217 corpus heavy-table chunks) couldn't
    # be reached via the keyword bypass when a user typed the full
    # citation. Standard sections like "35.10-5" still match cleanly.
    ("cfr_section",  re.compile(
        r"\b(\d{1,2})\s*CFR\s*([\d.]+(?:T\d+-\d+)?(?:-[\d]+)?)\b",
        re.IGNORECASE,
    )),
    # Sprint D6.16b — Packing Instructions for hazmat. CFR stores them as
    # "PI 510"; IMDG stores them as "P001" / "P200" / "P301". Anchored on
    # the "PI" or "Packing Instruction" prefix so bare "P510" mid-prose
    # doesn't false-match. We emit two search patterns per hit (one for
    # each storage form) inside _extract_identifiers.
    ("packing_instr", re.compile(
        r"\b(?:PI\s*|Packing\s+Instruction\s+P?)(\d{3})\b",
        re.IGNORECASE,
    )),
    ("colregs_rule", re.compile(r"\b(?:COLREGs?\s+)?Rule\s+(\d{1,2})\b", re.IGNORECASE)),
    ("solas_reg",    re.compile(r"\bSOLAS\s+(Ch\.?)?([IVX]+-\d+)(?:\s*(?:Reg\.?\s*|/)(\d+))?\b", re.IGNORECASE)),
    ("nvic_number",  re.compile(r"\bNVIC\s+(\d{2}-\d{2})\b", re.IGNORECASE)),
    ("ism_section",  re.compile(r"\bISM\s+(?:Code\s+)?(\d+(?:\.\d+)?)\b", re.IGNORECASE)),
    # MARPOL — explicit "MARPOL Annex <roman>" + optional Regulation number.
    # The "MARPOL" prefix is required here so we don't false-match SOLAS or
    # ISM annexes (each of those has its own annex structure). Bare "Annex"
    # queries will still be served via the _MARPOL_TERMS source-affinity
    # boost when other MARPOL keywords are present.
    ("marpol_annex", re.compile(
        r"\bMARPOL\s+Annex\s+([IVX]+)"
        r"(?:\s+(?:Reg(?:ulation)?\.?\s*)?(\d+(?:\.\d+)?))?\b",
        re.IGNORECASE,
    )),
    ("mepc_resolution", re.compile(r"\bMEPC\.(\d+)\((\d+)\)\b", re.IGNORECASE)),
    # IMDG — Special Provision number (SP119, SP163, etc.). These are
    # short cross-references in the Dangerous Goods List that point to
    # provisions in Chapter 3.3.
    ("imdg_sp",      re.compile(r"\bSP\s*(\d{1,4})\b")),
    # IMDG — EmS (Emergency Schedule) code. F-X for fire schedules,
    # S-X for spill schedules. Distinctive enough to anchor on as an
    # identifier without ambiguity.
    ("imdg_ems",     re.compile(r"\bEmS\s*([FS]-[A-Z])\b", re.IGNORECASE)),
]


# Sprint D6.24 — implicit MARPOL Annex inference.
#
# In our corpus "Annex N" with a Roman numeral is unambiguous: only
# MARPOL is organized by numbered annexes (I oil, II NLS, III packaged
# pollutants, IV sewage, V garbage, VI air). SOLAS uses "Chapter",
# STCW uses "Chapter", ISM uses "Section", IBC/IGC use appendices.
# So when a user types "annex V exemptions" without writing the word
# MARPOL, treating it as MARPOL Annex V is high-confidence inference,
# not a guess.
#
# Triggered by: bare `Annex (I|II|III|IV|V|VI)` with no explicit
# instrument prefix elsewhere in the query.
#
# Skipped when: the query already mentions another IMO/national
# instrument by name (MARPOL, SOLAS, STCW, ISM, IBC, IGC, HSC, BWM,
# IMDG, MCA, AMSA, NMA, USCG, etc.). In those cases the explicit
# patterns above pick it up — or the user genuinely meant something
# else.
#
# Documented case driving this: 2026-04-29 user 2ndmate09 asked
# "What are the annex V exemptions for throwing plastic overboard"
# and got "MARPOL Annex V is not in the retrieved context" because
# the existing `marpol_annex` pattern requires the literal "MARPOL"
# prefix. Vector retrieval was distracted by COLREGs Rule 38
# (Exemptions), 46 CFR 199.610 (Exemptions), and 46 CFR 108.597
# (Line-throwing appliance) — all reasonable matches for "exemptions"
# and "throwing" but none answered the question.
_BARE_ANNEX_RE = re.compile(
    r"\bAnnex\s+(I|II|III|IV|V|VI)\b",
    re.IGNORECASE,
)
_OTHER_INSTRUMENT_RE = re.compile(
    r"\b(?:MARPOL|SOLAS|STCW|ISM|IBC|IGC|HSC|BWM|IMDG|"
    r"MCA|AMSA|LISCR|IRI|MPA|HKMD|NMA|BMA|CFR|USCG|NVIC|"
    r"NMC|MSM|MSIB|ALCOAST|Polar\s+Code)\b",
    re.IGNORECASE,
)


def _detect_implicit_marpol_annexes(query: str) -> list[str]:
    """Return Roman numerals from bare "Annex N" mentions when no
    other instrument is explicitly named in the query.

    Returns empty list if the query already contains MARPOL or another
    instrument prefix — those cases are handled by the explicit
    `marpol_annex` (and friends) patterns above.
    """
    if _OTHER_INSTRUMENT_RE.search(query):
        return []
    annexes: list[str] = []
    seen: set[str] = set()
    for m in _BARE_ANNEX_RE.finditer(query):
        roman = m.group(1).upper()
        if roman not in seen:
            seen.add(roman)
            annexes.append(roman)
    return annexes


def _extract_identifiers(query: str) -> list[dict]:
    """Scan query for known regulation identifier patterns.

    Returns a list of dicts with keys: type, value, pattern.
    The 'pattern' field is the substring used for database text search.
    """
    identifiers: list[dict] = []
    for id_type, regex in _IDENTIFIER_PATTERNS:
        for m in regex.finditer(query):
            if id_type == "un_number":
                prefix = m.group(1).upper()
                number = m.group(2)
                # Sprint D6.16 — emit TWO patterns per UN number:
                #   1. Compact "UN2734" — matches CFR storage style
                #      (e.g., "UN2734  I  8, 3" in 49 CFR 172.101).
                #   2. Bare "2734" with word-boundary regex — matches
                #      IMDG / ERG storage style which omits the "UN"
                #      prefix in tabular rows (e.g., "2734 Amines,
                #      liquid, corrosive..." in IMDG 3.2 or
                #      "2734 132 Amines..." in ERG Yellow). Restricted
                #      to imdg / imdg_supplement / erg sources to
                #      avoid false positives where a 4-digit number
                #      like "1202" appears as a section number, year,
                #      or paragraph reference in unrelated regs.
                identifiers.append({
                    "type": id_type,
                    "value": f"{prefix}{number}",
                    "pattern": f"{prefix}{number}",
                })
                identifiers.append({
                    "type": "un_number_bare",
                    "value": f"{prefix} {number}",
                    "pattern": number,
                    "regex": True,
                    "source_filter": ("imdg", "imdg_supplement", "erg"),
                })
            elif id_type == "erg_guide":
                identifiers.append({
                    "type": id_type,
                    "value": f"Guide {m.group(1)}",
                    "pattern": f"Guide {m.group(1)}",
                })
            elif id_type == "cfr_section":
                title = m.group(1)
                section = m.group(2)
                identifiers.append({
                    "type": id_type,
                    "value": f"{title} CFR {section}",
                    "pattern": section,
                })
            elif id_type == "colregs_rule":
                identifiers.append({
                    "type": id_type,
                    "value": f"Rule {m.group(1)}",
                    "pattern": f"Rule {m.group(1)}",
                })
            elif id_type == "solas_reg":
                identifiers.append({
                    "type": id_type,
                    "value": m.group(0),
                    "pattern": m.group(2),  # e.g. "II-2"
                })
            elif id_type == "nvic_number":
                identifiers.append({
                    "type": id_type,
                    "value": f"NVIC {m.group(1)}",
                    "pattern": m.group(1),
                })
            elif id_type == "ism_section":
                identifiers.append({
                    "type": id_type,
                    "value": f"ISM {m.group(1)}",
                    "pattern": m.group(1),
                })
            elif id_type == "marpol_annex":
                annex_roman = m.group(1).upper()
                reg_num = m.group(2)
                # Always anchor on "Annex <roman>"; if a regulation
                # number is also present, search for that too as a
                # second identifier.
                identifiers.append({
                    "type": id_type,
                    "value": f"Annex {annex_roman}",
                    "pattern": f"Annex {annex_roman}",
                })
                if reg_num:
                    identifiers.append({
                        "type": "marpol_regulation",
                        "value": f"Regulation {reg_num}",
                        "pattern": f"Regulation {reg_num}",
                    })
            elif id_type == "mepc_resolution":
                ident = f"MEPC.{m.group(1)}({m.group(2)})"
                identifiers.append({
                    "type": id_type,
                    "value": ident,
                    "pattern": ident,
                })
            elif id_type == "imdg_sp":
                # Match both compact "SP119" and spaced "SP 119" forms in
                # the corpus by using the trailing digits as the search
                # pattern. Trigram fallback handles either rendering.
                num = m.group(1)
                identifiers.append({
                    "type": id_type,
                    "value": f"SP{num}",
                    "pattern": f"SP{num}",
                })
            elif id_type == "imdg_ems":
                code = m.group(1).upper()
                identifiers.append({
                    "type": id_type,
                    "value": f"EmS {code}",
                    "pattern": code,
                })
            elif id_type == "packing_instr":
                num = m.group(1)
                # CFR storage: "PI 510" — substring match is safe.
                identifiers.append({
                    "type": "packing_instr_pi",
                    "value": f"PI {num}",
                    "pattern": f"PI {num}",
                })
                # IMDG storage: "P510" — use \m...\M word boundaries so
                # "P200" doesn't match "P2001" or "approxP200" prose.
                identifiers.append({
                    "type": "packing_instr_p",
                    "value": f"P{num}",
                    "pattern": f"P{num}",
                    "regex": True,
                })

    # Sprint D6.24 — implicit MARPOL Annex inference. Runs AFTER the
    # explicit pattern loop so we can check whether the explicit
    # `marpol_annex` already matched (don't emit duplicates).
    #
    # IMPORTANT: uses regex with PostgreSQL `\m...\M` word boundaries
    # + a source_filter to ('marpol', 'marpol_supplement'). Without
    # word-bounds, "Annex V" substring-matches "Annex VI" chunks too,
    # so a query about Annex V (garbage) would surface Annex VI (air
    # pollution) content. Without the source filter, the bypass would
    # also pull in AMSA Marine Order 95 / CFR sections that reference
    # MARPOL Annex V, drowning out the convention text itself.
    explicit_annex_values = {
        i["value"] for i in identifiers if i.get("type") == "marpol_annex"
    }
    for annex_roman in _detect_implicit_marpol_annexes(query):
        annex_value = f"Annex {annex_roman}"
        if annex_value in explicit_annex_values:
            continue
        identifiers.append({
            "type": "marpol_annex_implicit",
            "value": annex_value,
            "pattern": annex_value,
            "regex": True,
            "source_filter": ("marpol", "marpol_supplement"),
        })
    return identifiers


# ── Broad keyword extraction ───────────────────────────────────────────────
#
# Extracts substantive search terms from ANY query by stripping stopwords.
# These keywords are searched with lower confidence than identifiers, but
# they close the gap for queries like "chlorine gas" or "ammonia leak"
# where no formal identifier is present.

_STOPWORDS: frozenset[str] = frozenset(
    # articles / prepositions
    "the a an for of on in to from with by at about"
    # question / auxiliary words
    " what which how where when who does do is are was were can could"
    " should would will may might shall"
    # common verbs
    " require explain describe tell show give need help find handle"
    " apply cover covers mean uses using used have been"
    # domain-generic words (appear in nearly every chunk)
    " requirements regulations rules procedures vessel vessels ship ships"
    " aboard maritime marine must compliance section chapter part"
    " regulation rule code standard safety international"
    # source names (already handled by source affinity)
    " solas colregs stcw nvic guide emergency response".split()
)

_MAX_KEYWORD_TERMS = 4
_MIN_KEYWORD_LEN = 4
_MAX_KEYWORD_FREQ = 200  # Skip keywords appearing in > this many chunks
# Sprint D6.8 — synonyms (e.g. "logbook" 203, "lifesaving appliance" 155)
# are by design slightly broader than the user's term. Allow a higher cap
# for them specifically; bare-user keywords still cap at 200.
_MAX_SYNONYM_FREQ = 800


def _extract_keywords(query: str) -> list[str]:
    """Extract substantive search terms from query after stripping stopwords.

    Returns up to _MAX_KEYWORD_TERMS keywords, longest first (longer words
    are more specific). Only words with _MIN_KEYWORD_LEN+ characters are
    kept.
    """
    # Tokenize: keep only alphabetic words (drop numbers, punctuation)
    words = re.findall(r"[a-zA-Z]+", query.lower())
    keywords = [
        w for w in words
        if len(w) >= _MIN_KEYWORD_LEN and w not in _STOPWORDS
    ]
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    # Take longest first — more specific, fewer false positives
    unique.sort(key=len, reverse=True)
    return unique[:_MAX_KEYWORD_TERMS]


# ── Query embedding ──────────────────────────────────────────────────────────


async def _embed_query(openai_api_key: str, query: str) -> str:
    oai = AsyncOpenAI(api_key=openai_api_key)
    try:
        resp = await oai.embeddings.create(model=_EMBED_MODEL, input=[query])
    finally:
        await oai.close()
    embedding = resp.data[0].embedding
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# ── Keyword search (identifier + broad keyword) ─────────────────────────────


async def _identifier_search(
    identifiers: list[dict],
    pool: asyncpg.Pool,
    limit: int = 5,
    allowed_jurisdictions: list[str] | None = None,
) -> list[dict]:
    """Search regulations by text for structured identifiers (high confidence).

    Per-identifier dict keys honored:
      pattern        — the substring (or regex, see below) to search for
      regex          — if truthy, `pattern` is a regex compiled with
                       PostgreSQL's POSIX-extended syntax. Used for
                       bare-number UN matching with word boundaries
                       so "2734" doesn't match "12734" or "1.2.7.34".
      source_filter  — optional tuple of source codes; when set, search
                       is restricted to those sources only. Used for
                       bare-number UN searches against imdg/erg where
                       the "UN" prefix is omitted in tabular storage.

    Sprint D6.19 — `allowed_jurisdictions`, when set, intersects against
    chunk.jurisdictions via the && (overlap) operator. Same severance
    contract as the vector path.

    Returns results in the same dict format as vector search.
    """
    results: list[dict] = []
    seen_ids: set = set()
    juris_clause = " AND jurisdictions && $JN::text[] " if allowed_jurisdictions else ""
    for ident in identifiers:
        is_regex = bool(ident.get("regex"))
        source_filter = ident.get("source_filter")
        pattern = ident["pattern"]
        # Build the parameter list and clause, then renumber the JN
        # placeholder to match its position. Order: $1=pattern,
        # $2=limit, $3=source_filter (optional), $N=juris (optional).
        args: list = [pattern if not is_regex else (r"\m" + pattern + r"\M"), limit]
        clauses: list[str] = []
        if is_regex:
            clauses.append("full_text ~ $1")
        else:
            clauses.append("full_text ILIKE '%' || $1 || '%'")
        next_idx = 3
        if source_filter:
            clauses.append(f"source = ANY(${next_idx})")
            args.append(list(source_filter))
            next_idx += 1
        if allowed_jurisdictions:
            clauses.append(f"jurisdictions && ${next_idx}::text[]")
            args.append(list(allowed_jurisdictions))
            next_idx += 1
        sql = (
            "SELECT id, source, section_number, section_title, full_text, "
            "       0.0 AS similarity "
            "FROM regulations WHERE " + " AND ".join(clauses) + " LIMIT $2"
        )
        rows = await pool.fetch(sql, *args)
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(dict(r))
    return results


async def _broad_keyword_search(
    keywords: list[str],
    pool: asyncpg.Pool,
    limit: int = 5,
    synonym_keywords: set[str] | None = None,
    allowed_jurisdictions: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Search regulations by text for broad keywords (lower confidence).

    Uses the GIN trigram index for fast ILIKE lookups. Returns up to
    `limit` source-diversified results per keyword (at most one per
    source via DISTINCT ON), plus the list of keywords that passed the
    frequency cap (used by the caller for in-memory candidate boosting).

    Keywords appearing in more than _MAX_KEYWORD_FREQ chunks are skipped
    as too common to be useful (e.g., "fire" appears in hundreds of
    chunks across sources).

    Source diversity: uses DISTINCT ON (source) so each source contributes
    at most one result per keyword — the chunk with the most keyword
    occurrences. This mirrors the diversified vector search architecture
    and prevents any single large source (e.g., CFR with 33K chunks) from
    monopolizing keyword results.
    """
    results: list[dict] = []
    seen_ids: set = set()
    passed_keywords: list[str] = []
    synonym_set = synonym_keywords or set()
    for kw in keywords:
        # Synonyms get a more permissive cap because they're curated
        # corpus-vocab terms — by design slightly broader than user input.
        is_syn = kw in synonym_set
        cap = _MAX_SYNONYM_FREQ if is_syn else _MAX_KEYWORD_FREQ
        # Fast specificity check: skip overly common terms.
        freq = await pool.fetchval(
            """
            SELECT count(*) FROM (
                SELECT 1 FROM regulations
                WHERE full_text ILIKE '%' || $1 || '%'
                LIMIT $2
            ) sub
            """,
            kw,
            cap + 1,
        )
        if freq > cap:
            logger.info(
                "Keyword '%s' matches > %d chunks — too common, skipping%s",
                kw, cap, " (synonym)" if is_syn else "",
            )
            continue

        passed_keywords.append(kw)

        # Sprint D6.19 — jurisdiction filter applied inside the inner
        # subquery so DISTINCT ON sees only allowed-jurisdiction chunks.
        if allowed_jurisdictions is not None:
            rows = await pool.fetch(
                """
                SELECT id, source, section_number, section_title, full_text,
                       0.0 AS similarity
                FROM (
                    SELECT DISTINCT ON (source)
                        id, source, section_number, section_title, full_text
                    FROM regulations
                    WHERE full_text ILIKE '%' || $1 || '%'
                      AND jurisdictions && $3::text[]
                    ORDER BY source,
                             (length(full_text)
                              - length(replace(lower(full_text), lower($1), ''))
                             ) DESC
                ) sub
                ORDER BY (length(full_text)
                          - length(replace(lower(full_text), lower($1), ''))
                         ) DESC
                LIMIT $2
                """,
                kw,
                limit,
                allowed_jurisdictions,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, source, section_number, section_title, full_text,
                       0.0 AS similarity
                FROM (
                    SELECT DISTINCT ON (source)
                        id, source, section_number, section_title, full_text
                    FROM regulations
                    WHERE full_text ILIKE '%' || $1 || '%'
                    ORDER BY source,
                             (length(full_text)
                              - length(replace(lower(full_text), lower($1), ''))
                             ) DESC
                ) sub
                ORDER BY (length(full_text)
                          - length(replace(lower(full_text), lower($1), ''))
                         ) DESC
                LIMIT $2
                """,
                kw,
                limit,
            )
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(dict(r))
    return results, passed_keywords


# ── Per-group SQL fetch ──────────────────────────────────────────────────────


async def _fetch_group(
    pool: asyncpg.Pool,
    vec_literal: str,
    group_sources: list[str],
    candidates: int,
    allowed_jurisdictions: list[str] | None = None,
) -> list[dict]:
    """Fetch top-K candidates from one source group.

    Sprint D6.19 — when `allowed_jurisdictions` is provided, the SQL
    intersects against the chunk's `jurisdictions` array using the &&
    (overlap) operator, backed by the GIN index on jurisdictions.
    None = no filter (preserve generic-query default behavior).
    """
    if allowed_jurisdictions is not None:
        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
              AND source = ANY($3)
              AND jurisdictions && $4::text[]
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal,
            candidates,
            group_sources,
            allowed_jurisdictions,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
              AND source = ANY($3)
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal,
            candidates,
            group_sources,
        )
    return [dict(r) for r in rows]


# ── Public API ───────────────────────────────────────────────────────────────


async def retrieve(
    query: str,
    pool: asyncpg.Pool,
    openai_api_key: str,
    vessel_profile: dict | None = None,
    limit: int = 8,
    sources: list[str] | None = None,
) -> list[dict]:
    """Return semantically relevant regulation chunks.

    Args:
        query:          The user's question.
        pool:           asyncpg connection pool.
        openai_api_key: Key for OpenAI embeddings API.
        vessel_profile: Optional vessel profile dict for soft re-ranking.
        limit:          Max chunks to return (default 8).
        sources:        Explicit source filter (e.g. ['cfr_46']). When given,
                        the diversified fetch is skipped and a single
                        filtered query is run — preserves the citation-
                        lookup code path.

    Returns:
        List of dicts: id, source, section_number, section_title, full_text,
        similarity, plus an internal `_score` added by _rerank.
    """
    t0 = time.perf_counter()

    vec_literal = await _embed_query(openai_api_key, query)

    # Sprint D6.19 — D3 jurisdiction filter. Computes the per-query
    # allow-set from {base ∪ flag-derived ∪ query-explicit}. Returns
    # None for the "no signal" case (generic question, no profile),
    # which preserves D6.17 behavior — no SQL filter is applied and the
    # prompt-side rules handle the answer.
    from rag.jurisdiction import allowed_jurisdictions as _allowed_juris_fn
    juris_allow = _allowed_juris_fn(query, vessel_profile)
    juris_list = list(juris_allow) if juris_allow is not None else None
    if juris_list is not None:
        logger.info("Jurisdiction filter active: %s", sorted(juris_list))

    if sources:
        # Explicit source filter — single query, no diversification.
        fetch_limit = max(limit * 3, 20)
        if juris_list is not None:
            rows = await pool.fetch(
                """
                SELECT id, source, section_number, section_title, full_text,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM regulations
                WHERE embedding IS NOT NULL
                  AND source = ANY($3)
                  AND jurisdictions && $4::text[]
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vec_literal,
                fetch_limit,
                sources,
                juris_list,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, source, section_number, section_title, full_text,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM regulations
                WHERE embedding IS NOT NULL
                  AND source = ANY($3)
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vec_literal,
                fetch_limit,
                sources,
            )
        # Deduplicate by section_number — keep top _MAX_CHUNKS_PER_SECTION
        # chunks per section. Sprint D5.5: was "top 1" which suppressed
        # multi-chunk sections' specific-answer chunks behind their intro
        # chunks (see retriever.py header comment near _MAX_CHUNKS_PER_SECTION).
        candidates = []
        section_indices: dict[str, list[int]] = {}  # section_number → indices in candidates
        for r in rows:
            chunk = dict(r)
            sec = chunk.get("section_number", "")
            if sec and sec in section_indices:
                existing = section_indices[sec]
                if len(existing) < _MAX_CHUNKS_PER_SECTION:
                    # Slot available — append.
                    section_indices[sec].append(len(candidates))
                    candidates.append(chunk)
                else:
                    # At cap — replace the weakest kept chunk if this one is better.
                    weakest_idx = min(existing, key=lambda i: candidates[i]["similarity"])
                    if chunk["similarity"] > candidates[weakest_idx]["similarity"]:
                        candidates[weakest_idx] = chunk
                continue
            if sec:
                section_indices[sec] = [len(candidates)]
            candidates.append(chunk)
        active_groups: list[str] = []
    else:
        # Diversified fetch: one query per source group that has data, all
        # running concurrently on the HNSW index.
        available = await _get_available_sources(pool)
        tasks: list = []
        active_groups = []
        for group_name, group_sources in SOURCE_GROUPS.items():
            present = [s for s in group_sources if s in available]
            if not present:
                continue
            n = _CANDIDATES_PER_GROUP.get(group_name, _DEFAULT_CANDIDATES_PER_GROUP)
            active_groups.append(group_name)
            tasks.append(_fetch_group(pool, vec_literal, present, n, juris_list))

        results_per_group = await asyncio.gather(*tasks)

        candidates = []
        seen_ids: set = set()
        section_indices: dict[str, list[int]] = {}  # section_number → indices in candidates
        for group_results in results_per_group:
            for chunk in group_results:
                chunk_id = chunk["id"]
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)

                # Sprint D5.5: keep top _MAX_CHUNKS_PER_SECTION chunks per
                # section_number (was: top 1). Multi-chunk sections with
                # tables or appendices (e.g. 46 CFR 199.175 lifeboat equipment
                # Table 1) now get a shot at competing with their own
                # intro chunks instead of being silently suppressed.
                # Duplicate rows from repeat ingest runs (same section_number,
                # same content, different IDs) are handled by the same cap —
                # only the top 2 by similarity survive.
                sec = chunk.get("section_number", "")
                if sec and sec in section_indices:
                    existing = section_indices[sec]
                    if len(existing) < _MAX_CHUNKS_PER_SECTION:
                        section_indices[sec].append(len(candidates))
                        candidates.append(chunk)
                    else:
                        weakest_idx = min(existing, key=lambda i: candidates[i]["similarity"])
                        if chunk["similarity"] > candidates[weakest_idx]["similarity"]:
                            candidates[weakest_idx] = chunk
                    continue
                if sec:
                    section_indices[sec] = [len(candidates)]
                candidates.append(chunk)

    # ── Hybrid merge: two-tier keyword search ────────────────────────────
    #
    # Tier 1 (identifiers): structured patterns like UN1219, Rule 14.
    #   Synthetic score = max_sim + 0.05 (highest confidence).
    # Tier 2 (broad keywords): substantive terms like "chlorine", "ammonia".
    #   Synthetic score = max_sim + 0.02 (literal text match = strong signal).
    #
    # In-memory keyword boost: vector search may have found the right
    # chunk (e.g., ERG Guide 124) but ranked it low.  The ILIKE query
    # may not return it either (source-diversified results pick the best
    # chunk per source, which might be an index chunk rather than a guide).
    # So we also scan existing vector candidates for keyword text matches
    # and boost their scores directly — zero DB cost.
    #
    # Both tiers dedup by section_number against vector results.
    # When a keyword-matched chunk is already in the pool (same
    # section_number), we BOOST the existing chunk's similarity to the
    # keyword synthetic score instead of silently discarding the signal.
    identifiers = _extract_identifiers(query)
    keywords = _extract_keywords(query)

    # Sprint D6.8 — expand mariner-vocab keywords ("lifejacket", "log",
    # "MOB") into the corpus's formal CFR phrasing ("lifesaving
    # appliance", "logbook", "person overboard"). Conservative dict —
    # see packages/rag/rag/synonyms.py. The expanded synonyms get a
    # higher freq cap inside _broad_keyword_search so they aren't
    # falsely skipped (e.g. "logbook" hits 203 chunks, just over the
    # base cap of 200).
    synonym_added: set[str] = set()
    if keywords:
        from .synonyms import expand_keywords
        keywords, synonym_map = expand_keywords(keywords)
        if synonym_map:
            synonym_added = {s for syns in synonym_map.values() for s in syns}
            logger.info("Synonym expansion: %s", synonym_map)

    # Sprint D6.56 — intent expansion. Catches the
    # "how often + emergency equipment" failure mode where embedding
    # lands on equipment-capability sections but the answer lives in
    # drill/training sections (e.g. Brandon's "How often does a rescue
    # boat need to be launched cfr" → 199.160 vs the right 199.180).
    # Appended terms flow into synonym_added so they share the relaxed
    # freq cap (drill/training are broader than user vocab by design).
    if keywords:
        from .synonyms import expand_intent
        keywords, intent_added = expand_intent(query, keywords)
        if intent_added:
            synonym_added.update(intent_added)
            logger.info(
                "Intent expansion fired (frequency+emergency) — appended %s",
                intent_added,
            )

    id_results: list[dict] = []
    kw_results: list[dict] = []
    specific_keywords: list[str] = []
    if identifiers:
        id_results = await _identifier_search(identifiers, pool, allowed_jurisdictions=juris_list)
    if keywords:
        kw_results, specific_keywords = await _broad_keyword_search(
            keywords, pool, synonym_keywords=synonym_added,
            allowed_jurisdictions=juris_list,
        )

    max_sim = max(
        (float(c["similarity"]) for c in candidates),
        default=0.0,
    ) if candidates else 0.0

    # ── In-memory keyword boost ────────────────────────────────────────
    #
    # Scan vector candidates for keyword text matches and boost scores.
    # Only uses keywords that passed the frequency cap (specific_keywords),
    # so common words like "fire" (3453 matches) don't trigger boosting.
    if specific_keywords:
        kw_boost_sim = max_sim + 0.02
        kw_mem_boosted = 0
        for c in candidates:
            if float(c["similarity"]) >= kw_boost_sim:
                continue
            text_lower = (c.get("full_text") or "").lower()
            if any(kw in text_lower for kw in specific_keywords):
                c["similarity"] = kw_boost_sim
                kw_mem_boosted += 1
        if kw_mem_boosted:
            logger.info(
                "In-memory keyword boost: %d candidates boosted for %s",
                kw_mem_boosted, specific_keywords,
            )

    if id_results or kw_results:

        existing_sections = {
            c.get("section_number", "")
            for c in candidates
            if c.get("section_number")
        }
        existing_ids = {c["id"] for c in candidates}

        id_added = 0
        kw_added = 0
        id_boosted = 0
        kw_boosted = 0

        def _merge_chunks(
            chunks: list[dict], synthetic_sim: float, counter_name: str,
        ) -> tuple[int, int]:
            added = 0
            boosted = 0
            for chunk in chunks:
                sec = chunk.get("section_number", "")
                if chunk["id"] in existing_ids:
                    continue
                if sec and sec in existing_sections:
                    # Section already present. Either:
                    #   (a) the keyword/id hit is for a chunk we already have
                    #       a sibling of — boost the weakest sibling so the
                    #       section signals properly through rerank; OR
                    #   (b) we haven't yet filled the per-section cap, in
                    #       which case append this chunk as another sibling
                    #       (Sprint D5.5 — allows Table 1 chunks to enter
                    #       even when chunk-0 intro already got retrieved).
                    existing = section_indices.get(sec, [])
                    if len(existing) < _MAX_CHUNKS_PER_SECTION:
                        chunk["similarity"] = synthetic_sim
                        section_indices[sec].append(len(candidates))
                        candidates.append(chunk)
                        existing_ids.add(chunk["id"])
                        added += 1
                    else:
                        # At cap — boost the weakest kept chunk for this section.
                        weakest_idx = min(existing, key=lambda i: candidates[i]["similarity"])
                        if synthetic_sim > float(candidates[weakest_idx]["similarity"]):
                            candidates[weakest_idx]["similarity"] = synthetic_sim
                            boosted += 1
                    continue
                chunk["similarity"] = synthetic_sim
                candidates.append(chunk)
                if sec:
                    existing_sections.add(sec)
                    section_indices[sec] = [len(candidates) - 1]
                existing_ids.add(chunk["id"])
                added += 1
            return added, boosted

        if id_results:
            id_added, id_boosted = _merge_chunks(id_results, max_sim + 0.05, "identifier")
        if kw_results:
            kw_added, kw_boosted = _merge_chunks(kw_results, max_sim + 0.02, "keyword")

        logger.info(
            "Hybrid merge: %d identifier matches for %s, "
            "%d keyword matches for %s, %d added / %d boosted",
            len(id_results),
            [i["value"] for i in identifiers] if identifiers else "[]",
            len(kw_results),
            keywords or "[]",
            id_added + kw_added,
            id_boosted + kw_boosted,
        )

    if candidates:
        # Drop CFR chunks whose Subchapter is forbidden for this vessel type.
        # Applied BEFORE rerank so filtered-out chunks can't consume a top-N
        # slot. Non-CFR sources (SOLAS, NVIC, NMC, uscg_bulletin, ERG) pass
        # through untouched — they're vessel-agnostic in our corpus.
        candidates = _filter_by_vessel_applicability(candidates, vessel_profile)
        candidates = _rerank(candidates, query, vessel_profile)

    final = candidates[:limit]

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Retrieval: %d candidates from %d group(s) → top %d in %.1fms",
        len(candidates),
        len(active_groups) if not sources else 1,
        len(final),
        elapsed_ms,
    )

    # Log each selected chunk for retrieval debugging
    if final:
        chunk_summaries = ", ".join(
            f"{c.get('source', '?')}/{c.get('section_number', '?')} ({c.get('_score', c.get('similarity', 0)):.3f})"
            for c in final
        )
        logger.info("Selected chunks: %s", chunk_summaries)

    return final


# ── Vessel-type × CFR Subchapter applicability filter ────────────────────
#
# CFR regulations are organized by Subchapter, where each Subchapter applies
# to a specific vessel type. The same physical requirement (e.g. fireman's
# outfit) is repeated in 6+ nearly-identical chunks across Subchapters —
# one per vessel type. Vector search cannot distinguish them because the
# text is essentially identical. This filter drops CFR chunks from Parts
# that explicitly don't apply to the user's vessel type.
#
# Data source: each Subchapter's "Applicability" section (usually Part N.01-1)
# in the CFR. Values verified against the official CFR table of contents.
# Where a vessel type might apply to multiple Subchapters (e.g. a large
# passenger vessel on international routes is subject to both Subchapter
# H and SOLAS), we include both; the filter only removes Parts that are
# unambiguously outside the vessel's scope.
#
# Format: vessel_type (lowercased) → {
#     "applicable": set of Part-number string prefixes (e.g. "95", "96"),
#     "forbidden": set of Part-number string prefixes that MUST NOT appear
#                  in citations for this vessel type,
# }
# The distinction lets us default to "keep with no change" for Parts not
# listed in either set (prevents silent data loss when a Part we didn't
# map turns out to be applicable).

# Universal Parts that apply to every commercial vessel regardless of type.
# These never get filtered out; their presence in a citation is fine for
# any vessel type.
_UNIVERSAL_CFR_46_PARTS: frozenset[str] = frozenset({
    # Subchapter A — Procedures Applicable to the Public
    "1", "2", "3", "4", "5",
    # Subchapter B — Merchant Marine Officers and Seamen (credentialing)
    "10", "11", "12", "13", "14", "15", "16",
    # Subchapter C-I — Uninspected Vessels (general provisions)
    "24", "25", "26",
    # Subchapter E — Load Lines
    "40", "41", "42", "43", "44", "45", "46", "47", "48", "49",
    # Subchapter F — Marine Engineering
    "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
    "60", "61", "62", "63", "64",
    # Subchapter G — Documentation of Vessels
    "67",
    # Subchapter J — Electrical Engineering
    "110", "111", "112", "113",
    # Subchapter Q — Equipment, Construction, and Materials (type-approval
    # standards — applicable to anyone whose vessel uses the equipment)
    "159", "160", "161", "162", "163", "164",
    # Subchapter S — Subdivision and Stability
    "170", "171", "172", "173", "174",
    # Subchapter V — Marine Occupational Safety
    "196", "197",
    # Subchapter W — Lifesaving Appliance Service Facilities
    "198", "199",
})

_VESSEL_TYPE_CFR_APPLICABILITY: dict[str, dict[str, frozenset[str]]] = {
    "containership": {
        "applicable": frozenset({
            # Subchapter I — Cargo and Miscellaneous Vessels (primary)
            "90", "91", "92", "93", "94", "95", "96", "97", "98",
            "105",
            # Subchapter O — Certain Bulk Dangerous Cargoes (may apply if
            # containerized hazmat is carried; keep for edge cases)
            # Intentionally NOT marking as forbidden for OSVs that carry
            # similar cargo.
        }),
        "forbidden": frozenset({
            # Subchapter D — Tank Vessels
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            # Subchapter H — Passenger Vessels (large)
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            # Subchapter I-A — MODU
            "107", "108", "109",
            # Subchapter K — Small Passenger (≥150 pax)
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            # Subchapter L — OSV
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            # Subchapter M — Towing
            "140", "141", "142", "143", "144",
            # Subchapter R — Sailing School
            "165", "166", "167", "168", "169",
            # Subchapter T — Small Passenger (under 100 GT)
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            # Subchapter U — Oceanographic Research
            "188", "189", "190", "191", "192", "193", "194", "195",
            # Part 28 — Commercial Fishing Industry Vessels
            "28",
        }),
    },
    "bulk carrier": {
        "applicable": frozenset({
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
        }),
        "forbidden": frozenset({
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "107", "108", "109",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            "188", "189", "190", "191", "192", "193", "194", "195",
            "28",
        }),
    },
    "tanker": {
        "applicable": frozenset({
            # Subchapter D — Tank Vessels (primary)
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            # Subchapter N — Dangerous Cargoes (applies to tankers carrying
            # hazardous bulk liquids)
            "148", "149", "150", "151", "153", "154",
            # Subchapter O — Bulk Dangerous Cargoes
            "159",
        }),
        "forbidden": frozenset({
            # Cargo non-tank
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            # Large passenger
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            # MODU
            "107", "108", "109",
            # Small Passenger K
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            # OSV
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            # Towing M
            "140", "141", "142", "143", "144",
            # Sailing school
            "165", "166", "167", "168", "169",
            # Small passenger T
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            # Research U
            "188", "189", "190", "191", "192", "193", "194", "195",
            # Fishing
            "28",
        }),
    },
    "passenger vessel": {
        # Large passenger (Subchapter H). For small passenger vessels, we
        # rely on the subchapter field in the vessel_profile to switch to
        # Subchapter K or T mappings below.
        "applicable": frozenset({
            # Subchapter H primary
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            # Subchapter K applies if ≥150 pax small passenger
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            # Subchapter T applies if <100 GT small passenger
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
        }),
        "forbidden": frozenset({
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "188", "189", "190", "191", "192", "193", "194", "195",
            "28",
        }),
    },
    "ferry": {
        # Ferries are passenger vessels, usually Subchapter T or K.
        "applicable": frozenset({
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
        }),
        "forbidden": frozenset({
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "188", "189", "190", "191", "192", "193", "194", "195",
            "28",
        }),
    },
    "towing / tugboat": {
        "applicable": frozenset({
            # Subchapter M — Towing Vessels (primary, since 2016)
            "140", "141", "142", "143", "144",
            # Part 27 — fire/lifesaving for uninspected vessels ≥65ft that
            # pre-date Subchapter M phase-in
            "27",
        }),
        "forbidden": frozenset({
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "165", "166", "167", "168", "169",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            "188", "189", "190", "191", "192", "193", "194", "195",
            "28",
        }),
    },
    "osv / offshore support": {
        "applicable": frozenset({
            # Subchapter L — Offshore Supply Vessels (primary)
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            # Some OSVs carry dangerous bulk liquids → Subchapter D/O apply
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
        }),
        "forbidden": frozenset({
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            "188", "189", "190", "191", "192", "193", "194", "195",
            "28",
        }),
    },
    "fish processing": {
        "applicable": frozenset({
            # Part 28 — Commercial Fishing Industry Vessels
            "28",
        }),
        "forbidden": frozenset({
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
            "188", "189", "190", "191", "192", "193", "194", "195",
        }),
    },
    "research vessel": {
        "applicable": frozenset({
            # Subchapter U — Oceanographic Research (primary; the ONE place
            # where Part 195 actually applies — Cassandra's case in reverse)
            "188", "189", "190", "191", "192", "193", "194", "195",
        }),
        "forbidden": frozenset({
            "28",
            "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
            "70", "71", "72", "73", "74", "75", "76", "77", "78",
            "79", "80", "81", "82", "83", "84", "85", "86", "87",
            "88", "89",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "105",
            "107", "108", "109",
            "114", "115", "116", "117", "118", "119", "120", "121", "122",
            "125", "126", "127", "128", "129", "130", "131", "132",
            "133", "134", "135", "136", "137", "138", "139",
            "140", "141", "142", "143", "144",
            "165", "166", "167", "168", "169",
            "175", "176", "177", "178", "179", "180", "181", "182",
            "183", "184", "185", "186", "187",
        }),
    },
    # Other / unspecified falls through to no filter.
}


_CFR_PART_RE = re.compile(r"^(\d{1,3})\s+CFR\s+(\d{1,3})", re.IGNORECASE)


def _cfr_part_prefix(section_number: str) -> tuple[str, str] | None:
    """Extract (title, part) from a section_number string.

    Returns ('46', '95') for '46 CFR 95.05-10', or None if not a CFR citation.
    """
    if not section_number:
        return None
    m = _CFR_PART_RE.match(section_number)
    if m:
        return m.group(1), m.group(2)
    return None


def _filter_by_vessel_applicability(
    results: list[dict], vessel_profile: dict | None,
) -> list[dict]:
    """Drop 46 CFR chunks whose Part is on the vessel type's forbidden list.

    Additive filter: only removes chunks we're confident don't apply.
    Non-CFR chunks (SOLAS, NVIC, NMC, bulletins, ERG) are never filtered
    here. Unknown CFR Parts (not in applicable OR forbidden) are kept.
    No-op when vessel_profile is None or vessel_type is unknown.
    """
    if not vessel_profile:
        return results
    vt = (vessel_profile.get("vessel_type") or "").strip().lower()
    mapping = _VESSEL_TYPE_CFR_APPLICABILITY.get(vt)
    if mapping is None:
        return results
    forbidden = mapping["forbidden"]
    if not forbidden:
        return results

    kept: list[dict] = []
    dropped: list[str] = []
    for r in results:
        src = r.get("source", "")
        # Only filter CFR sources. Non-CFR (SOLAS, NVIC, NMC, bulletin) are
        # vessel-agnostic in our corpus.
        if not src.startswith("cfr_"):
            kept.append(r)
            continue
        sec = r.get("section_number", "")
        parsed = _cfr_part_prefix(sec)
        if parsed is None:
            kept.append(r)
            continue
        _title, part = parsed
        # Universal parts: never drop
        if part in _UNIVERSAL_CFR_46_PARTS:
            kept.append(r)
            continue
        # Forbidden for this vessel type: drop
        if part in forbidden:
            dropped.append(sec)
            continue
        # Applicable or unknown: keep
        kept.append(r)

    if dropped:
        logger.info(
            "Vessel-applicability filter dropped %d chunks for vessel_type=%s: %s",
            len(dropped), vt, ", ".join(dropped[:5]) + ("…" if len(dropped) > 5 else ""),
        )
    return kept


# ── Soft re-ranking ──────────────────────────────────────────────────────────


def _rerank(
    results: list[dict],
    query: str,
    vessel_profile: dict | None,
) -> list[dict]:
    """Apply vessel-profile + source-affinity boosts and sort."""
    source_boosts = _source_affinity(query)

    profile_terms: list[str] = []
    if vessel_profile:
        if vessel_profile.get("vessel_type"):
            profile_terms.append(vessel_profile["vessel_type"].lower())
        if vessel_profile.get("route_type"):
            profile_terms.append(vessel_profile["route_type"].lower())
        for cargo in vessel_profile.get("cargo_types") or []:
            profile_terms.append(cargo.lower())

    logger.info(
        "Rerank: %d candidates, source_boosts=%s, profile_terms=%s",
        len(results), source_boosts or "{}", profile_terms or "[]",
    )

    for result in results:
        text_lower = (result.get("full_text") or "").lower()
        boost = 0.0

        # Vessel profile boost
        if profile_terms:
            boost += sum(0.05 for term in profile_terms if term in text_lower)

        # Source affinity boost
        if source_boosts:
            group = _SOURCE_TO_GROUP.get(result.get("source", ""), "")
            if group in source_boosts:
                boost += source_boosts[group]

        result["_score"] = float(result["similarity"]) + boost

        if boost > 0:
            logger.debug(
                "Boost %s: sim=%.3f +%.3f → %.3f",
                result.get("section_number", ""),
                float(result["similarity"]),
                boost,
                result["_score"],
            )

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results
