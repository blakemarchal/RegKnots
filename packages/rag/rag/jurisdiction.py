"""
Sprint D6.19 — multi-flag corpus severance (D3 architecture).

The runtime side of the `jurisdictions` column on `regulations`. Two
responsibilities:

  1. SOURCE_TO_JURISDICTIONS — authoritative mapping used by the ingest
     pipeline at write time. Must match alembic 0058 backfill.

  2. allowed_jurisdictions(query, vessel_profile) — at retrieval time,
     compute the per-query allow-set as:

         base ∪ flag-derived ∪ query-explicit

     A chunk surfaces only if `chunk.jurisdictions && allowed_set` is
     non-empty (PostgreSQL array overlap, applied at SQL level by the
     retriever). The function returns None to signal "no filter" — the
     prompt-side D6.17 jurisdictional rules then handle the answer.

Design principles:
  * **Default-deny on flag**: a US-flag user cannot see UK chunks
    unless they explicitly invoke "MCA" / "MGN" / etc. in the query.
  * **Cross-jurisdiction is unlocked by the user, not by us**: if the
    UK-flag user types "33 CFR 199" we add 'us' to the allow-list.
  * **No flag + no signal = no filter**: avoids silently anchoring
    generic queries to US (the historical bias). The prompt asks the
    user instead.
  * **Universal ('intl') is always allowed** so SOLAS/STCW/COLREGs
    surface for every query.
"""

from __future__ import annotations

import re

# ── Source → jurisdiction tags ────────────────────────────────────────────
#
# KEEP IN SYNC with apps/api/alembic/versions/0058_add_jurisdictions_column.py.
# Both files are authoritative for their layer (DB on initial backfill,
# this module on every new ingest write).
SOURCE_TO_JURISDICTIONS: dict[str, list[str]] = {
    # US national / federal
    "cfr_33":           ["us"],
    "cfr_46":           ["us"],
    "cfr_49":           ["us"],
    "usc_46":           ["us"],
    "nvic":             ["us"],
    "nmc_policy":       ["us"],
    "nmc_checklist":    ["us"],
    # USCG NMC exam bank (Sprint D6.83 — backfilled D6.97 follow-up).
    # The exam bank is US-only content for USCG merchant-mariner
    # credentialing; a non-US-flag mariner's compliance query should
    # not be answered out of US license-exam material.
    "nmc_exam_bank":    ["us"],
    "uscg_msm":         ["us"],
    "uscg_bulletin":    ["us"],
    # UK national
    "mca_mgn":          ["uk"],
    "mca_msn":          ["uk"],
    # UK MCA Code of Safe Working Practices for Merchant Seafarers
    # (COSWP) — Sprint D6.97 #54 (2026-05-27). Primarily authored for
    # UK-registered ships but widely referenced across UK-influenced
    # flag operations (Bermuda, Cayman, Isle of Man Red Ensign Group).
    "coswp":            ["uk"],
    # Australian national
    "amsa_mo":          ["au"],
    # Australian statutes — Navigation Act 2012, Marine Safety (DCV)
    # National Law Act 2012 (Sprint D6.97 AU phase 1c — backfilled).
    "au_statutes":      ["au"],
    # NSCV — National Standard for Commercial Vessels (Australian DCV
    # standard, Sprint D6.97 AU phase 1b — backfilled).
    "nscv":             ["au"],
    # Liberian (LISCR) national
    "liscr_mn":         ["lr"],
    # Marshall Islands (IRI) national
    "iri_mn":           ["mh"],
    # Singapore national (Sprint D6.22)
    "mpa_sc":           ["sg"],
    # Hong Kong (Sprint D6.22)
    "mardep_msin":      ["hk"],
    # Cyprus national (Sprint D6.43 — backfilled D6.97 follow-up)
    "cy_dms":           ["cy"],
    # Panama national (Sprint D6.44 — backfilled D6.97 follow-up)
    "pa_mmc":           ["pa"],
    # Canada (Sprint D6.22)
    "tc_ssb":           ["ca"],
    # Bahamas (Sprint D6.22)
    "bma_mn":           ["bs"],
    # France (Sprint D6.46) — first French-language flag-state pilot.
    "fr_transport":     ["fr"],
    # Sprint D6.47 — multilingual flag-state expansion.
    "bg_verkehr":       ["de"],
    "dgmm_es":          ["es"],
    "it_capitaneria":   ["it"],
    "gr_ynanp":         ["gr"],
    # Sprint D6.50 — OCIMF (international industry guidance).
    "ocimf":            ["intl"],
    # Sprint D6.93 — class society rules. Class society scope is per
    # vessel, not per flag (ABS classes Liberian/MH/SG-flag vessels in
    # large numbers; same for Lloyd's). Tagging the society's HQ flag
    # would silently exclude these from non-US/non-UK queries that
    # legitimately need them. 'intl' mirrors the IACS UR / SOLAS
    # posture: universally available, and the synthesizer disambiguates
    # which society applies via vessel profile / query mention at
    # answer time.
    "abs_mvr":          ["intl"],
    "lr_lifting_code":  ["intl"],
    "lr_rules":         ["intl"],
    # Norway (Sprint D6.23) — first non-English flag (but content is in English)
    "nma_rsv":          ["no"],
    # Sprint D6.23 — Tier D international references. All tagged 'intl'
    # because they bind/reference every flag that has adopted the
    # underlying IMO instruments.
    "iacs_ur":          ["intl"],
    "imo_css":          ["intl"],
    "imo_loadlines":    ["intl"],
    "imo_igc":          ["intl"],
    "imo_ibc":          ["intl"],
    "imo_hsc":          ["intl"],
    "imo_iamsar":       ["intl"],
    # Sprint D6.97 #48 — IMO graphical-symbol Assembly resolutions
    # (A.952(23) FCP symbols, A.760(18) + A.1116(30) LSA symbols).
    "imo_symbols":      ["intl"],
    # Sprint D6.97 #53/#57 — IMO numbered-resolution harvest Phase 1.
    # MEPC pollution-equipment + MSC/Assembly safety resolutions. All
    # bind every flag that has adopted the underlying IMO instruments.
    "imo_mepc":         ["intl"],
    "imo_msc":          ["intl"],
    "mou_psc":          ["intl"],
    # International (universal — bind every flag on intl voyages)
    "solas":            ["intl"],
    "solas_supplement": ["intl"],
    "colregs":          ["intl"],
    "stcw":             ["intl"],
    "stcw_supplement":  ["intl"],
    "ism":              ["intl"],
    "ism_supplement":   ["intl"],
    "marpol":           ["intl"],
    "marpol_supplement":["intl"],
    "imdg":             ["intl"],
    "imdg_supplement":  ["intl"],
    "who_ihr":          ["intl"],
    # Dual-tagged: ERG is a US DOT publication BUT is the de-facto
    # international first-responder reference for hazmat. Tagging dual
    # so UN-number queries surface it under any flag.
    "erg":              ["us", "intl"],
}


def jurisdictions_for_source(source: str) -> list[str]:
    """Return the jurisdiction tags for a source, or ['intl'] if unknown.

    Unknown-source default to 'intl' so the chunk is never accidentally
    invisible — preferable to '[]' which would suppress it under every
    allow-set, since '∅ && X' is always false.
    """
    return SOURCE_TO_JURISDICTIONS.get(source, ["intl"])


# ── Flag string → jurisdiction code ───────────────────────────────────────
#
# Maps the freeform `vessel.flag_state` value users enter to the canonical
# 2-letter jurisdiction codes used in the chunk tags. Generous matching
# (case-insensitive substring) so "United States" / "USA" / "US" all
# normalize to 'us'. Falls back to None for unknown / "Unknown" / blank.

_FLAG_ALIASES: dict[str, list[str]] = {
    "us": ["united states", "usa", "u.s.a", "u.s.", "us flag", "american"],
    "uk": ["united kingdom", "uk flag", "british", "great britain", "england"],
    "au": ["australia", "australian"],
    "ca": ["canada", "canadian"],
    "sg": ["singapore", "singaporean"],
    "nz": ["new zealand", "kiwi"],
    "lr": ["liberia", "liberian"],
    "mh": ["marshall islands", "marshallese"],
    "pa": ["panama", "panamanian"],
    "bs": ["bahamas", "bahamian"],
    "mt": ["malta", "maltese"],
    "fr": ["france", "french"],
    "de": ["germany", "german"],
    "no": ["norway", "norwegian"],
    "gr": ["greece", "greek"],
    "it": ["italy", "italian"],
    "es": ["spain", "spanish"],
    "nl": ["netherlands", "dutch"],
    "be": ["belgium", "belgian"],
    "ie": ["ireland", "irish"],
    "jp": ["japan", "japanese"],
    "cn": ["china", "chinese"],
    "kr": ["korea", "korean"],
    "hk": ["hong kong"],
    "cy": ["cyprus", "cypriot"],
}


def flag_to_jurisdiction(flag_state: str | None) -> str | None:
    """Map a freeform flag string to a jurisdiction code.

    Returns None for blank, "Unknown", or unmapped flags — the caller
    should treat None as "no flag-derived jurisdiction" and fall back
    to query-signal layer + base.
    """
    if not flag_state:
        return None
    norm = flag_state.strip().lower()
    if not norm or norm in {"unknown", "none", "n/a", "tbd", "?"}:
        return None
    for code, aliases in _FLAG_ALIASES.items():
        if norm == code:
            return code
        for alias in aliases:
            if alias in norm:
                return code
    return None


# ── Query-text signal detection ───────────────────────────────────────────
#
# Patterns that indicate the user is explicitly asking about a particular
# jurisdiction's regulations, regardless of what flag they fly. A UK-flag
# user typing "what does 33 CFR say about lifejackets?" must be allowed
# to retrieve CFR. The match is conservative — only triggers on
# unambiguous citation forms or explicit jurisdiction mentions.

_QUERY_JURISDICTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # US — distinctive: CFR section pattern, USCG, "Coast Guard", US flag.
    ("us", re.compile(
        r"\b\d{1,2}\s*CFR\b"           # "33 CFR" / "46 CFR" / "49 CFR"
        r"|\bUSCG\b"
        r"|\bU\.?S\.?\s*Coast\s+Guard\b"
        r"|\bUS-?flag(?:ged)?\b"
        r"|\bAmerican[-\s]flag\b"
        r"|\bUnited\s+States\s+flag\b"
        r"|\bUSA?\s+flag\b"
        r"|\bSubchapter\s+[A-Z]\b"     # USCG subchapter notation
        r"|\b(?:NVIC|MSIB|ALCOAST)\s+\d"  # US guidance citations
        r"|\bNational\s+Maritime\s+Center\b"
        r"|\bCG-?\d{3}\b",             # Form numbers (CG-719, etc.)
        re.IGNORECASE,
    )),
    # UK — MGN / MSN / MCA citation forms or explicit UK references.
    ("uk", re.compile(
        r"\b(?:MGN|MSN|MIN)\s+\d"
        r"|\bMCA\b"
        r"|\bUK[-\s]flag(?:ged)?\b"
        r"|\bBritish[-\s]flag\b"
        r"|\bUnited\s+Kingdom\s+flag\b"
        r"|\bRed\s+Ensign\b"
        r"|\bMaritime\s+(?:and\s+)?Coastguard\s+Agency\b"
        # Sprint D6.97 #54 — COSWP unlocks UK jurisdiction when
        # explicitly invoked. A US-flag user asking "what does
        # COSWP say about enclosed-space entry" expects to retrieve
        # the UK MCA Code of Safe Working Practices.
        r"|\bCOSWP\b"
        r"|\bCode\s+of\s+Safe\s+Working\s+Practices\b",
        re.IGNORECASE,
    )),
    # Australia
    ("au", re.compile(
        r"\bAMSA\b"
        r"|\bMarine\s+Order\s+\d"
        r"|\bAustralian[-\s]flag\b"
        r"|\bAustralia(?:n)?\s+flag\b",
        re.IGNORECASE,
    )),
    # Canada
    ("ca", re.compile(
        r"\bTransport\s+Canada\b"
        r"|\bCanadian[-\s]flag\b"
        r"|\bTP\s+\d{3}\b"             # TP-numbered standards
        r"|\bMSB\s+\d",                # Marine Safety Bulletin
        re.IGNORECASE,
    )),
    # Singapore
    ("sg", re.compile(
        r"\bMPA\s+(?:Singapore|circular|notice)"
        r"|\bSingapore[-\s]flag(?:ged)?\b"
        r"|\bMaritime\s+Port\s+Authority",
        re.IGNORECASE,
    )),
    # New Zealand
    ("nz", re.compile(
        r"\bMaritime\s+NZ\b"
        r"|\bMaritime\s+New\s+Zealand\b"
        r"|\bMNZ\s+(?:rule|notice)"
        r"|\bNew\s+Zealand[-\s]flag",
        re.IGNORECASE,
    )),
    # Liberia
    ("lr", re.compile(
        r"\bLISCR\b"
        r"|\bLiberian[-\s]flag\b"
        r"|\bLiberia\s+(?:registry|flag)",
        re.IGNORECASE,
    )),
    # Marshall Islands
    ("mh", re.compile(
        r"\bMarshall\s+Islands\b"
        r"|\bMI[-\s]flag\b"
        r"|\bIRI\s+(?:marine|notice)",
        re.IGNORECASE,
    )),
    # Bahamas (Sprint D6.22 — bma_mn ingested but routing was missing)
    ("bs", re.compile(
        r"\bBahamas\b"
        r"|\bBahamian[-\s]flag\b"
        r"|\bBMA\s+(?:Marine\s+Notice|MN|circular)\b",
        re.IGNORECASE,
    )),
    # France (Sprint D6.46 — fr_transport)
    # Patterns must be specific enough not to match generic "freight" or
    # ambiguous tokens. Anchored on the word "France"/"French" and on
    # actual French regulatory citation forms.
    ("fr", re.compile(
        r"\bFrance\b"
        r"|\bFrench[-\s]flag\b"
        r"|\bFrench\s+(?:maritime|navigation|registry|register|"
        r"vessel|ship|administration|regulation|law|rule|rules|"
        r"requirement|requirements|code|article)\b"
        r"|\bDAM\b"
        r"|\bAffaires\s+Maritimes\b"
        r"|\bCode\s+des\s+transports\b"
        r"|\b(?:Article\s+)?(?:L|R|D)\s*5\d{3}-\d"  # Article L5111-1 etc.
        r"|\bL[ée]gifrance\b"
        r"|\bnavires?\s+fran[çc]ais\b"
        r"|\bpavillon\s+fran[çc]ais\b",
        re.IGNORECASE,
    )),
    # Germany (Sprint D6.47 — bg_verkehr)
    ("de", re.compile(
        r"\bGermany\b"
        r"|\bGerman[-\s]flag\b"
        r"|\bGerman\s+(?:maritime|navigation|registry|vessel|ship|"
        r"administration|regulation|law|rule|rules|requirement|requirements)\b"
        r"|\bBG\s+Verkehr\b"
        r"|\bdeutsche-flagge\b"
        r"|\bBSH\b"
        r"|\bSeeArbG\b"
        r"|\bSeearbeitsgesetz\b"
        r"|\bSchSV\b"
        r"|\bdeutsche[rs]?\s+(?:Schiff|Flagge|Schifffahrt)\b"
        r"|\bRundschreiben\b",
        re.IGNORECASE,
    )),
    # Spain (Sprint D6.47 — dgmm_es)
    ("es", re.compile(
        r"\bSpain\b"
        r"|\bSpanish[-\s]flag\b"
        r"|\bSpanish\s+(?:maritime|navigation|registry|vessel|ship|"
        r"administration|regulation|law|rule|rules|requirement|"
        r"requirements|merchant\s+marine)\b"
        r"|\bDGMM\b"
        r"|\bDirecci[óo]n\s+General\s+de\s+la\s+Marina\s+Mercante\b"
        r"|\bMarina\s+Mercante\s+espa[ñn]ola\b"
        r"|\bReal\s+Decreto\s+\d"
        r"|\bRD\s+\d{1,4}/\d{4}\b"
        r"|\bBOE-A-\d{4}\b"
        r"|\bbuque\s+espa[ñn]ol\b"
        r"|\bpabell[óo]n\s+espa[ñn]ol\b",
        re.IGNORECASE,
    )),
    # Italy (Sprint D6.47 — it_capitaneria)
    ("it", re.compile(
        r"\bItaly\b"
        r"|\bItalian[-\s]flag\b"
        r"|\bItalian\s+(?:maritime|navigation|registry|vessel|ship|"
        r"administration|regulation|law|rule|rules|requirement|"
        r"requirements|coast\s+guard)\b"
        r"|\bCapitanerie?\s+di\s+Porto\b"
        r"|\bGuardia\s+Costiera\b"
        r"|\bMinistero\s+(?:delle|dei)\s+(?:Infrastrutture|Trasporti)\b"
        r"|\bMIT\s+(?:lavoro|decreto|circolare)\b"
        r"|\bCircolare\s+(?:SG|Serie\s+Generale)\b"
        r"|\bOrdinanza\s+\d+/\d{4}\b"
        r"|\bnave\s+italiana\b"
        r"|\bbandiera\s+italiana\b",
        re.IGNORECASE,
    )),
    # Norway (Sprint D6.23 + D6.46 expansion — nma_rsv)
    ("no", re.compile(
        r"\bNorway\b"
        r"|\bNorwegian[-\s]flag\b"
        r"|\bNorwegian\s+(?:maritime|navigation|registry|vessel|ship|"
        r"administration|regulation|law|rule|rules|requirement|requirements)\b"
        r"|\bNMA\b"
        r"|\bSj[øo]fartsdirektoratet\b"
        r"|\b(?:NIS|NOR)[-\s](?:registry|register|ship)\b"
        r"|\b(?:NMA|sdir\.no)\s+(?:circular|rundskriv)\b"
        r"|\bRSR\s+\d|\bRSV\s+\d"
        r"|\bnorske\s+skip\b",
        re.IGNORECASE,
    )),
    # Greece (Sprint D6.47 — gr_ynanp scaffolded; ingest blocked by Akamai)
    ("gr", re.compile(
        r"\bGreece\b"
        r"|\bGreek[-\s]flag\b"
        r"|\bGreek\s+(?:maritime|navigation|registry|vessel|ship|"
        r"administration|regulation|law|rule|rules|requirement|requirements)\b"
        r"|\bHMSA\b"
        r"|\bYNANP\b"
        r"|\bHellenic\s+(?:Coast\s+Guard|Ministry\s+of\s+Maritime|Maritime)\b"
        r"|\b(?:ΥΑ|ΠΔ|ΦΕΚ)\s+\d"   # Greek-script citation forms
        r"|\b(?:YA|PD|FEK)\s+\d{1,5}/\d{4}\b"  # transliterated forms
        r"|\bελληνικ[όά]\s+(?:πλοί|σκάφος)",
        re.IGNORECASE,
    )),
    # Hong Kong (mardep_msin)
    ("hk", re.compile(
        r"\bHong\s+Kong\b"
        r"|\bHK[-\s]flag(?:ged)?\b"
        r"|\bMARDEP\b"
        r"|\bHong\s+Kong\s+Marine\s+Department\b"
        r"|\bMSIN\s+\d",
        re.IGNORECASE,
    )),
    # Japan (no corpus yet — pattern future-proofs the routing)
    ("jp", re.compile(
        r"\bJapan\b"
        r"|\bJapanese[-\s]flag\b"
        r"|\bJapanese\s+(?:maritime|navigation|registry|vessel|ship)\b"
        r"|\bClassNK\b"
        r"|\bJG\s+(?:circular|notice)"
        r"|\bMLIT\s+(?:Japan|circular)",
        re.IGNORECASE,
    )),
    # Korea (no corpus yet)
    ("kr", re.compile(
        r"\bKorea\b"
        r"|\bKorean[-\s]flag\b"
        r"|\bKorean\s+(?:maritime|navigation|registry|vessel|ship)\b"
        r"|\bKorean\s+Register\b"
        r"|\bKR\s+(?:circular|notice|class)",
        re.IGNORECASE,
    )),
    # China (no corpus yet)
    ("cn", re.compile(
        r"\bChinese[-\s]flag\b"
        r"|\bChinese\s+(?:maritime|navigation|registry|vessel|ship)\b"
        r"|\bCCS\s+(?:rules|circular|class)\b"
        r"|\bChina\s+(?:Classification\s+Society|MSA|Maritime)\b",
        re.IGNORECASE,
    )),
]


def jurisdictions_in_query(query: str) -> set[str]:
    """Detect explicit jurisdiction references in the query text.

    Returns the set of 2-letter codes the user is asking about. Empty
    set means no explicit reference — caller falls back to flag layer.
    """
    found: set[str] = set()
    for code, pattern in _QUERY_JURISDICTION_PATTERNS:
        if pattern.search(query):
            found.add(code)
    return found


# ── Public API: compute the allow-set ─────────────────────────────────────

def allowed_jurisdictions(
    query: str,
    vessel_profile: dict | None,
) -> set[str] | None:
    """Compute the retrieval allow-set for a query.

    Returns:
        - set[str] of allowed jurisdiction codes (always includes 'intl')
        - None if no signal of any kind — caller should NOT apply a
          jurisdiction filter and let the prompt-side D6.17 rules handle
          the answer (i.e., model leads SOLAS, asks for flag).

    The four cases:

      1. Vessel has a recognized flag         → {flag, 'intl'} (+ query-explicit)
      2. No flag, query has explicit jurisdiction → {explicit, 'intl'}
      3. Flag + query mentions different jurisdiction → {flag, query-explicit, 'intl'}
      4. No flag, no explicit reference        → None (no filter)
    """
    allowed: set[str] = {"intl"}

    flag_juris = flag_to_jurisdiction((vessel_profile or {}).get("flag_state"))
    if flag_juris:
        allowed.add(flag_juris)

    explicit = jurisdictions_in_query(query)
    allowed |= explicit

    # If the only thing in the allow-set is 'intl' (no flag, no query
    # signal), return None to disable the filter. This preserves the
    # historical generic-query behavior and lets the prompt-side rules
    # decide how to scope the answer (D6.17 clarifying-question rule).
    if allowed == {"intl"}:
        return None

    return allowed
