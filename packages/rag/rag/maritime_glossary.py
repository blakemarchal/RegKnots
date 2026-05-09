"""Maritime industry glossary — slang/jargon → formal regulatory vocabulary.

Why this exists
---------------

Real mariners don't query in CFR vocabulary. A user asks "what size fire
wire is required" — meaning **emergency towing-off pennant** (ISGOTT
22.6, 33 CFR 155.235, IACS UR W18). Pure embedding retrieval drifts to
the "fire" semantic neighborhood (SOLAS Ch.II-2 fire protection) and
never reaches the towing arrangement. The Haiku rewriter doesn't know
the slang either, so reformulations stay in the same wrong neighborhood.
The hedge classifier identifies VOCAB issue but proposes wrong synonyms
because Haiku itself lacks the depth.

This module is the curated bridge — slang→formal mappings with their
controlling regulation citations, vessel-types-applicable, and a
confidence tag tracking how the mapping was sourced.

Confidence tiers
----------------

- 1: Sonnet 4.6 (single-model) seeded the entry from general training
     knowledge. Known to be correct in standard maritime practice but
     not yet cross-verified against another model OR against a corpus
     match for the formal term. Good enough for the first pass while
     the multi-model brainstorm pipeline is being built.

- 2: Cross-confirmed by ≥1 additional model (GPT-5, Grok-4, Opus 4.7,
     Gemini-2.5-Pro) AND the formal term appears ≥1 time in the
     regulations corpus.

- 3: 4-of-4 model agreement OR Karynn-curated. Highest confidence.

- 4: Karynn explicitly verified, or matched in industry source
     documents (ISGOTT, OCIMF, SOLAS, IMO codes).

The current file is seeded at confidence=1 (Sonnet-only) for the
sprint following the 2026-05-08 audit. The multi-model brainstorm
script (`scripts/build_maritime_glossary.py`, future sprint) will
upgrade entries to confidence=2/3 and surface low-confidence ones
for review.

Wiring
------

Two consumers in the RAG pipeline:

  1. ``synonyms.py`` — at retrieval time, when keywords from the user
     query match a glossary slang term, the formal equivalents are
     appended as additional trigram-search terms. Vector embedding is
     unchanged; trigram gets the chance to surface the right sections.

  2. ``query_rewrite.py`` — a representative subset of glossary
     entries is woven into the few-shot examples in the rewriter's
     system prompt. This primes Haiku to recognize "this is jargon,
     swap to formal" as a class of operation.

How to add an entry
-------------------

If you discover a new slang term during a retrieval-misses review:

  1. Append a ``GlossaryEntry(...)`` to ``GLOSSARY`` below with
     confidence=1 and your best-guess formal equivalent + citation.
  2. Verify the formal term appears in the corpus:
     ``SELECT count(*) FROM regulations WHERE full_text ILIKE
     '%<formal>%';``
  3. If yes, bump confidence to 2.
  4. If you got Karynn or another source to confirm, bump to 3 or 4.

Adding entries is meant to be fast — the cost of a wrong entry is
small (it just routes more queries to a wrong neighborhood, which
the hedge judge will catch and surface to ``retrieval_misses``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    """One slang→formal mapping for the maritime glossary."""

    slang: str
    """The user-vocabulary term (lowercase, single word OR multi-word phrase)."""

    formal_equivalents: tuple[str, ...]
    """One or more formal regulatory phrases that name the same thing.
    First entry is the primary CFR / SOLAS / IMO term; subsequent are
    common alternatives. All used as trigram search terms at retrieval."""

    citations: tuple[str, ...]
    """Controlling regulation citations. Each should match a real
    section_number in the regulations table. Used for verification +
    for prompt examples."""

    vessel_types: tuple[str, ...]
    """Vessel types where this term applies. Use ``("all",)`` for general
    terms; specific tags like ``("tanker",)`` or ``("containership",
    "tanker")`` for type-specific. Possible values: tanker,
    containership, bulker, osv, tug, fishing, passenger, ro-ro, all."""

    context: str
    """1-2 sentence explanatory note. Goes into rewriter few-shot
    examples + helps future curators understand why the mapping holds."""

    confidence: int
    """1-4 per the tiers above. Ranges:
        1 = Sonnet seed; 2 = multi-model + corpus; 3 = high consensus;
        4 = Karynn or industry doc verified."""


# ── Glossary ──────────────────────────────────────────────────────────────
#
# Initial seed — confidence=1 (Sonnet) for all entries. Will be upgraded
# to 2/3 by the multi-model brainstorm pipeline. Ordered loosely by
# domain so a curator can read top-to-bottom and spot drift.

GLOSSARY: tuple[GlossaryEntry, ...] = (

    # ── Towing / emergency operations ────────────────────────────────
    GlossaryEntry(
        slang="fire wire",
        formal_equivalents=(
            "emergency towing-off pennant",
            "emergency towing arrangement",
            "ETOP",
        ),
        citations=("33 CFR 155.235", "IACS UR W18", "ISGOTT 22.6"),
        vessel_types=("tanker", "containership"),
        context=(
            "Pre-rigged steel wire on the seaward side of a vessel "
            "alongside, ready for a tug to pick up and tow the ship "
            "away from the berth in case of fire/emergency. ISGOTT "
            "specifies size by DWT (28mm/45m for 20-100k DWT, etc.)."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="towing pennant",
        formal_equivalents=("emergency towing-off pennant", "ETOP"),
        citations=("33 CFR 155.235", "IACS UR W18"),
        vessel_types=("tanker", "containership"),
        context=(
            "Generic name for a fire wire (see above). Some operators "
            "prefer this term to avoid 'fire wire' confusion with "
            "electrical fire-rated cables."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="gantline",
        formal_equivalents=(
            "bosun's chair safety line",
            "manrider",
            "rope access line",
        ),
        citations=("46 CFR 197.300", "IMO MSC.1/Circ.1374"),
        vessel_types=("all",),
        context=(
            "Lightweight line used as a fall-arrest backup when working "
            "aloft from a bosun's chair, on a lower stage, or on rope "
            "access. Required to be independent of the main support."
        ),
        confidence=1,
    ),

    # ── Mooring / lashing fittings ──────────────────────────────────
    GlossaryEntry(
        slang="bitt",
        formal_equivalents=("bollard", "mooring fitting", "shipboard fitting"),
        citations=("IACS UR A2", "46 CFR 56.50-95"),
        vessel_types=("all",),
        context=(
            "Vertical post (or pair) on deck for securing mooring lines. "
            "IACS UR A2 covers shipboard towing/mooring fittings and "
            "their hull-structure backing."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="chock",
        formal_equivalents=("fairlead", "mooring chock", "panama chock"),
        citations=("IACS UR A2", "ISGOTT 23"),
        vessel_types=("all",),
        context=(
            "Aperture in the bulwark or rail through which a mooring or "
            "tow line passes. 'Panama chock' = a closed type designed "
            "for canal transits; 'roller chock' has rollers to reduce "
            "line wear."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="banjo",
        formal_equivalents=("rigging plate", "anchor plate"),
        citations=(),  # rare in formal regs; typically vendor / OCIMF guidance
        vessel_types=("offshore", "osv"),
        context=(
            "Triangular or fan-shaped rigging plate with multiple holes, "
            "used to gather multiple legs of a rigging spread to a "
            "single attachment point. OCIMF lifting/rigging guidance."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="scotchman",
        formal_equivalents=(
            "chafe protection sleeve",
            "anti-chafe pad",
            "rope protector",
        ),
        citations=("IMO MSC.1/Circ.1175",),
        vessel_types=("all",),
        context=(
            "Sleeve/pad placed over a mooring line where it passes "
            "through a chock, to prevent chafe. Required where chafe "
            "would compromise the line's strength."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="dolphin",
        formal_equivalents=("mooring dolphin", "berthing dolphin"),
        citations=("33 CFR 105", "OCIMF MEG4"),
        vessel_types=("all",),
        context=(
            "Free-standing piling/structure in the water (not part of "
            "the wharf) used for mooring or to absorb berthing loads. "
            "Typical at LNG/oil terminals and bulk loading."
        ),
        confidence=1,
    ),

    # ── Cargo handling ──────────────────────────────────────────────
    GlossaryEntry(
        slang="dunnage",
        formal_equivalents=(
            "cargo securing material",
            "stowage material",
            "lumber dunnage",
        ),
        citations=("IMO CSS Code", "46 CFR 97.05"),
        vessel_types=("all",),
        context=(
            "Loose material (typically lumber, plywood, fabric, "
            "inflatable bags) placed between or around cargo to prevent "
            "shifting. CSS Code Annex 1-2 covers specifications."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="lashing",
        formal_equivalents=(
            "cargo securing arrangement",
            "container lashing",
            "securing device",
        ),
        citations=("IMO CSS Code", "46 CFR 97.105"),
        vessel_types=("containership", "ro-ro", "general cargo"),
        context=(
            "The wires, rods, or chains physically restraining cargo. "
            "Containership lashings are governed by the vessel's "
            "Cargo Securing Manual (CSM) approved under CSS Code Ch.5."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="tally",
        formal_equivalents=(
            "manifest count",
            "cargo manifest",
            "stowage count",
        ),
        citations=("46 CFR 97.10",),
        vessel_types=("containership", "general cargo", "ro-ro"),
        context=(
            "Count of cargo loaded/discharged, kept by the tally clerk "
            "during operations. The manifest is the formalized output."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="ullage",
        formal_equivalents=(
            "tank ullage",
            "cargo tank empty space",
            "outage",
        ),
        citations=("46 CFR 153.940", "ISGOTT 11"),
        vessel_types=("tanker",),
        context=(
            "Distance from cargo surface to the top of a tank. Inverse "
            "of innage. Critical for tanker loading calculations + "
            "vapor expansion margins."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="cofferdam",
        formal_equivalents=("isolating space", "void space"),
        citations=("46 CFR 32.55", "SOLAS II-1 Reg.18"),
        vessel_types=("tanker", "passenger"),
        context=(
            "Empty space separating two compartments to prevent fluid "
            "transfer or contamination. Required between cargo tanks "
            "of incompatible cargoes and between cargo + accommodation."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="void",
        formal_equivalents=(
            "void space",
            "empty space",
            "non-cargo non-fuel space",
        ),
        citations=("46 CFR 32.55", "SOLAS II-1"),
        vessel_types=("all",),
        context=(
            "An empty compartment that's neither cargo, fuel, ballast, "
            "nor cofferdam. Subject to gas-free certification before "
            "entry per SOLAS / OSHA / 29 CFR 1915 confined-space rules."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="gangway",
        formal_equivalents=(
            "accommodation ladder",
            "boarding ramp",
            "shore access ladder",
        ),
        citations=("46 CFR 92.25-25", "SOLAS II-1 Reg.3-9", "ILO MLC 2006 Reg.2.5"),
        vessel_types=("all",),
        context=(
            "Means of safe access between ship and shore. SOLAS II-1 "
            "Reg.3-9 (added 2010) sets construction standards; MLC 2.5 "
            "addresses crew shore-leave access."
        ),
        confidence=1,
    ),

    # ── Deck / structural ───────────────────────────────────────────
    GlossaryEntry(
        slang="scupper",
        formal_equivalents=(
            "deck drainage opening",
            "deck scupper",
            "freeing port",
        ),
        citations=("46 CFR 42.15", "SOLAS Load Lines Reg.24"),
        vessel_types=("all",),
        context=(
            "Opening that allows water shipped on deck to drain "
            "overboard. Load Lines Reg.24 sets minimum total area by "
            "bulwark length."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="freeing port",
        formal_equivalents=(
            "deck drainage opening",
            "scupper",
        ),
        citations=("ILLC Reg.24", "46 CFR 42.15-65"),
        vessel_types=("all",),
        context=(
            "Same family as scupper. The Load Lines convention's "
            "minimum-freeing-port-area calculation is a stability-"
            "critical structural design item."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="monkey island",
        formal_equivalents=("compass deck", "navigation deck top"),
        citations=("46 CFR 113.10",),
        vessel_types=("all",),
        context=(
            "Topmost open deck above the bridge, where the magnetic "
            "compass and clear-of-magnetic-interference instruments "
            "live. Typically also where radar antennas, GPS and AIS "
            "are mounted."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="lazarette",
        formal_equivalents=(
            "after peak",
            "stern compartment",
            "after-peak tank",
        ),
        citations=("SOLAS II-1 Reg.11",),
        vessel_types=("all",),
        context=(
            "Aftermost compartment, typically containing steering gear, "
            "stores, or trim ballast. SOLAS II-1 covers after-peak "
            "subdivision requirements."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="forepeak",
        formal_equivalents=("forward peak tank", "fore peak"),
        citations=("SOLAS II-1 Reg.11", "46 CFR 33"),
        vessel_types=("all",),
        context=(
            "Forwardmost compartment, typically a ballast or trim tank. "
            "Subdivision rules drive minimum thickness of the "
            "collision bulkhead."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="tween deck",
        formal_equivalents=("'tween-deck", "intermediate deck"),
        citations=("46 CFR 90", "SOLAS II-1 Reg.13"),
        vessel_types=("general cargo", "ro-ro"),
        context=(
            "A deck between the main deck and the hold floor in older "
            "general-cargo vessels. Largely obsolete on modern "
            "containerships and tankers but still relevant on "
            "general-cargo ships and ro-ros."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="baggywrinkle",
        formal_equivalents=("rigging chafe protection", "chafe gear"),
        citations=(),
        vessel_types=("all",),
        context=(
            "Soft sleeve woven from old rope, fitted to standing "
            "rigging or stays to protect sails or running rigging from "
            "chafe. Mostly traditional / sailing-vessel context."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="ratguard",
        formal_equivalents=("rat guard", "vermin guard", "rodent guard"),
        citations=("WHO IHR 2005 Annex 5", "42 CFR 71.41"),
        vessel_types=("all",),
        context=(
            "Sheet-metal cone fitted around mooring lines to prevent "
            "rats boarding the vessel. Required by IHR 2005 for "
            "vessels in port of countries party to the regulations."
        ),
        confidence=1,
    ),

    # ── Engineering / machinery ─────────────────────────────────────
    GlossaryEntry(
        slang="donkeyman",
        formal_equivalents=(
            "qualified member of the engine department",
            "qmed",
            "engine room watchstander",
        ),
        citations=("46 CFR 12.501", "STCW A-III/4"),
        vessel_types=("all",),
        context=(
            "Historic name for an engine-room rating. The formal MMC "
            "endorsement is QMED (qualified member of the engine "
            "department). STCW A-III/4 is the international equivalent."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="oiler",
        formal_equivalents=(
            "qmed-oiler",
            "qualified member of the engine department",
        ),
        citations=("46 CFR 12.501-3",),
        vessel_types=("all",),
        context=(
            "Oiler is a specific QMED rating endorsement under "
            "46 CFR 12.501. Watchstanding rating; not interchangeable "
            "with electrician or pumpman."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="wiper",
        formal_equivalents=("entry-level engine rating", "engine wiper"),
        citations=("46 CFR 12.515",),
        vessel_types=("all",),
        context=(
            "Entry-level unlicensed engine-room rating. Step toward "
            "QMED rating endorsements after sufficient sea-time."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="bosun",
        formal_equivalents=(
            "boatswain",
            "able seafarer deck",
            "qualified deck rating",
        ),
        citations=("46 CFR 12.401", "STCW A-II/5"),
        vessel_types=("all",),
        context=(
            "Senior unlicensed deck rating; supervises maintenance "
            "and deck operations. The formal MMC endorsement is "
            "Boatswain (Able Seafarer Deck under STCW)."
        ),
        confidence=1,
    ),

    # ── Safety / lifesaving ─────────────────────────────────────────
    GlossaryEntry(
        slang="lifejacket",
        formal_equivalents=(
            "lifesaving appliance",
            "personal flotation device",
            "PFD",
        ),
        citations=("46 CFR 160.155", "SOLAS III/7", "LSA Code 2.2"),
        vessel_types=("all",),
        context=(
            "Personal flotation device. Note: 46 CFR Subchapter Q "
            "(160.155) governs Coast Guard-approved jackets; LSA Code "
            "2.2 is the IMO performance standard."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="immersion suit",
        formal_equivalents=("survival suit", "exposure suit"),
        citations=("46 CFR 160.171", "SOLAS III/32", "LSA Code 2.3"),
        vessel_types=("all",),
        context=(
            "Insulated full-body suit for hypothermia protection in "
            "cold-water abandonment. Required carriage depends on "
            "operating area's water temperature (SOLAS III/32)."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="mob",
        formal_equivalents=("man overboard", "person overboard"),
        citations=("46 CFR 199.180", "SOLAS III/19"),
        vessel_types=("all",),
        context=(
            "Person who has fallen overboard. SOLAS III/19 sets the "
            "drill cadence for MOB recovery; 46 CFR 199.180 is the "
            "US carriage requirement for the recovery boat."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="epirb",
        formal_equivalents=(
            "emergency position-indicating radio beacon",
            "distress radio beacon",
            "satellite EPIRB",
        ),
        citations=("46 CFR 25.26", "47 CFR 80.1061", "SOLAS IV/7"),
        vessel_types=("all",),
        context=(
            "Self-activating distress beacon transmitting on 406 MHz "
            "via Cospas-Sarsat. SOLAS IV/7 sets carriage; 47 CFR 80 "
            "covers the radio licensing."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="sart",
        formal_equivalents=(
            "search and rescue transponder",
            "search and rescue locating device",
            "AIS-SART",
        ),
        citations=("46 CFR 184.610", "SOLAS III/6.2.2"),
        vessel_types=("all",),
        context=(
            "Survival-craft locating device; activated in a life raft "
            "to make the raft visible on rescue radar/AIS. SOLAS III/6 "
            "specifies survival-craft equipment carriage."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="liferaft",
        formal_equivalents=("inflatable life raft", "survival craft"),
        citations=("46 CFR 160.151", "SOLAS III/21", "LSA Code 4"),
        vessel_types=("all",),
        context=(
            "Self-righting inflatable raft for abandonment. Note "
            "'lifeboat' (rigid, davit-launched) is a separate "
            "regulatory category — both fall under 'survival craft'."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="fire main",
        formal_equivalents=(
            "fire main system",
            "fixed fire-fighting water system",
        ),
        citations=("46 CFR 95.10", "SOLAS II-2 Reg.10"),
        vessel_types=("all",),
        context=(
            "Pressurized seawater piping serving the fire hydrants and "
            "fire pumps. Distinct from sprinkler or foam systems. "
            "Capacity sized to support specified simultaneous hydrants."
        ),
        confidence=1,
    ),

    # ── Navigation / watch ──────────────────────────────────────────
    GlossaryEntry(
        slang="dr",
        formal_equivalents=(
            "dead reckoning position",
            "estimated position",
        ),
        citations=("46 CFR 164",),
        vessel_types=("all",),
        context=(
            "Position calculated from last fix using course and speed, "
            "no external reference. Required as a backup to GNSS for "
            "most vessels under USCG navigation safety rules."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="gps",
        formal_equivalents=(
            "global navigation satellite system",
            "gnss receiver",
            "electronic position-fixing system",
        ),
        citations=("SOLAS V/19.2.1.6",),
        vessel_types=("all",),
        context=(
            "GPS specifically refers to the US system; SOLAS V uses "
            "the broader 'GNSS' term to include GLONASS, Galileo, "
            "BeiDou. Both are accepted carriage-equipment options."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="ais",
        formal_equivalents=("automatic identification system",),
        citations=("33 CFR 164.46", "47 CFR 80.231", "SOLAS V/19.2.4"),
        vessel_types=("all",),
        context=(
            "VHF-broadcast vessel-tracking system. Class A (commercial, "
            "~12.5W TX) is required by SOLAS for ≥300 GT international "
            "voyage; Class B is the smaller-vessel variant."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="ecdis",
        formal_equivalents=(
            "electronic chart display and information system",
            "electronic charting system",
        ),
        citations=("SOLAS V/19.2.10",),
        vessel_types=("all",),
        context=(
            "Approved electronic chart display, replacing paper charts "
            "as primary navigation per SOLAS V Ch.V Reg.19.2.10. "
            "Backup ECDIS or a paper-chart portfolio is required."
        ),
        confidence=1,
    ),

    # ── Documentation / certificates ────────────────────────────────
    GlossaryEntry(
        slang="mmc",
        formal_equivalents=("merchant mariner credential", "mmc card"),
        citations=("46 CFR 10",),
        vessel_types=("all",),
        context=(
            "US mariner ID + endorsement document. Replaced the "
            "separate Z-card / license / document scheme in 2009. "
            "Issued by USCG NMC."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="stcw",
        formal_equivalents=(
            "STCW endorsement",
            "international convention on standards of training",
            "STCW certificate",
        ),
        citations=("STCW Reg.I/2", "46 CFR 10.215"),
        vessel_types=("all",),
        context=(
            "STCW = the IMO convention on training/certification. "
            "'My STCW' typically means the specific endorsements held "
            "(BST, advanced firefighting, ECDIS, etc.). Renewal in 5y."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="coi",
        formal_equivalents=(
            "certificate of inspection",
            "vessel certificate of inspection",
        ),
        citations=("46 CFR 2.01", "46 CFR Subchapter T"),
        vessel_types=("all",),
        context=(
            "USCG-issued certificate authorizing a vessel to carry "
            "passengers / cargo on specified routes. Specifies "
            "subchapter, route, manning, hazards. 5-year term."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="cog",
        formal_equivalents=(
            "certificate of compliance",
            "alternative compliance program certificate",
        ),
        citations=("46 CFR 8",),
        vessel_types=("all",),
        context=(
            "Alternate to a COI for vessels in the Alternative "
            "Compliance Program — uses class-society survey in lieu "
            "of full USCG inspection."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="iopp",
        formal_equivalents=(
            "international oil pollution prevention certificate",
            "IOPP certificate",
        ),
        citations=("MARPOL Annex I Reg.7", "33 CFR 151.19"),
        vessel_types=("all",),
        context=(
            "MARPOL-mandated certificate verifying pollution-prevention "
            "equipment (15-ppm oily water separator, oil record book, "
            "etc.) for vessels >400 GT international voyage."
        ),
        confidence=1,
    ),

    # ── Inspection / port-state ─────────────────────────────────────
    GlossaryEntry(
        slang="psc",
        formal_equivalents=(
            "port state control",
            "port state control inspection",
        ),
        citations=("33 CFR 6.16", "Paris MOU", "Tokyo MOU"),
        vessel_types=("all",),
        context=(
            "Port-side government inspection of foreign-flag vessels. "
            "MOU-region agreements (Paris, Tokyo, USCG, Indian Ocean) "
            "set targeting + concentrated inspection campaigns."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="cic",
        formal_equivalents=(
            "concentrated inspection campaign",
            "PSC focus topic",
        ),
        citations=("Paris MOU", "Tokyo MOU"),
        vessel_types=("all",),
        context=(
            "Time-limited focus topic announced by a PSC MOU (e.g. "
            "fire drills 2024, structural integrity 2025). PSCOs "
            "specifically check the topic in addition to standard items."
        ),
        confidence=1,
    ),

    # ── Logging / records ───────────────────────────────────────────
    GlossaryEntry(
        slang="log",
        formal_equivalents=(
            "logbook",
            "official logbook",
            "deck log",
        ),
        citations=("46 USC 11301-11304", "46 CFR 4.05", "SOLAS V/28"),
        vessel_types=("all",),
        context=(
            "Generic; depending on context can mean: official logbook "
            "(46 USC 11301), bell book / deck log (rough log), engine "
            "log, ORB (oil record book), GMDSS log. Specify in queries."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="orb",
        formal_equivalents=("oil record book",),
        citations=("MARPOL Annex I Reg.17", "33 CFR 151.25"),
        vessel_types=("all",),
        context=(
            "Bound book recording all oil-related operations (transfer, "
            "discharge, equipment failure). Part I = Machinery space; "
            "Part II = Cargo/ballast (tankers only). Retain 3 years."
        ),
        confidence=1,
    ),

    # ── Hazardous cargo ─────────────────────────────────────────────
    GlossaryEntry(
        slang="hazmat",
        formal_equivalents=(
            "hazardous material",
            "dangerous goods",
            "DG",
        ),
        citations=("49 CFR 172", "IMDG Code", "MARPOL Annex III"),
        vessel_types=("all",),
        context=(
            "US 'hazmat' (49 CFR Subchapter C) is broadly equivalent "
            "to IMO 'dangerous goods' (IMDG Code). Documentation, "
            "stowage, and labeling rules differ in specifics."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="dg",
        formal_equivalents=("dangerous goods", "hazardous material"),
        citations=("IMDG Code", "49 CFR 172"),
        vessel_types=("all",),
        context=(
            "International term mirroring 'hazmat'. Cargo manifest "
            "and shipper's declaration must classify per UN Number, "
            "Class, and Packing Group (IMDG 5.4)."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="msds",
        formal_equivalents=("safety data sheet", "SDS"),
        citations=("29 CFR 1910.1200", "MARPOL Annex I Reg.13.2"),
        vessel_types=("all",),
        context=(
            "MSDS terminology was superseded by SDS in 2012 (GHS-aligned "
            "16-section format). MARPOL requires an SDS for any oil/HNS "
            "cargo or fuel before bunkering/loading."
        ),
        confidence=1,
    ),

    # ── Drills / training ───────────────────────────────────────────
    GlossaryEntry(
        slang="muster",
        formal_equivalents=(
            "muster station",
            "abandonment station",
            "emergency assembly",
        ),
        citations=("SOLAS III/8", "46 CFR 109.213"),
        vessel_types=("passenger", "all"),
        context=(
            "Pre-assigned emergency assembly point for crew/passengers. "
            "On passenger vessels, 'muster drill' is required pre-"
            "departure (SOLAS III/19.2.2)."
        ),
        confidence=1,
    ),
    GlossaryEntry(
        slang="drill",
        formal_equivalents=(
            "training",
            "emergency exercise",
            "musters and drills",
        ),
        citations=("SOLAS III/19", "46 CFR 199.180"),
        vessel_types=("all",),
        context=(
            "Practical exercise of an emergency procedure. SOLAS III/19 "
            "sets cadence (weekly fire/abandon for passenger; monthly "
            "for cargo). 46 CFR 199.180 mirrors for US-flag."
        ),
        confidence=1,
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────


def synonym_pairs() -> dict[str, tuple[str, ...]]:
    """Return a flat ``{slang: (formal_equivalents...)}`` dict suitable
    for merging into ``synonyms.SYNONYM_DICT``.

    The synonyms.py infrastructure uses lowercase keys + tuple values
    so the format matches its expectations exactly.
    """
    return {
        entry.slang.lower(): entry.formal_equivalents
        for entry in GLOSSARY
    }


def few_shot_examples(n: int = 15) -> list[GlossaryEntry]:
    """Return a representative subset of the glossary for use as
    few-shot examples in the rewriter system prompt.

    Selection prefers diversity across vessel-types and domains so the
    rewriter sees patterns from each major category, not 15 mooring
    fittings. Hand-curated indices keep the selection deterministic.
    """
    # Indices chosen for category coverage: towing(0), gantline(2),
    # mooring(4), cargo(8), tanker-specific(11), deck(15), engine(23),
    # safety(28), nav(34), cert(38), psc(44), drills(47), hazmat(45),
    # plus 2 odd ones for variety (banjo, dunnage).
    diverse_indices = [0, 2, 4, 5, 8, 9, 11, 13, 15, 23, 26, 28, 31, 34, 38]
    selected = [GLOSSARY[i] for i in diverse_indices[:n] if i < len(GLOSSARY)]
    return selected
