"""Autonomous RAG eval harness — baseline run.

Runs ~30 questions across 5 vessel profiles through the full chat pipeline
(retrieval → Claude synthesis → citation verification) and auto-grades each
answer against an expected-source cheat sheet.

Output:
  data/eval/<timestamp>/
    ├── results.jsonl         one record per (vessel, question)
    ├── summary.md            human-readable grade distribution + failure list
    └── summary.json          machine-readable aggregates

Run on the VPS (has OPENAI_API_KEY + ANTHROPIC_API_KEY):
    cd /opt/RegKnots/apps/api
    uv run python /tmp/eval_rag_baseline.py

Grading (deterministic):
  A  — expected Part / section_number cited prominently, no wrong-subchapter
       citations present
  B  — expected source cited AND a wrong-subchapter citation also present
       (contamination case — Cassandra Q1 pattern)
  C  — expected source NOT cited, a wrong-subchapter citation IS the top or
       second citation (the retrieval-to-wrong-Subchapter failure)
  F  — expected source NOT cited AND no wrong-subchapter cited either
       (retrieval whiff — no relevant citation at all), OR answer
       contains an obvious citation that doesn't exist in the DB
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
from anthropic import AsyncAnthropic

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from app.config import settings
from rag.engine import chat
from rag.hedge import detect_hedge  # Sprint D2.1b — demote hedged answers


# ── Vessel profiles ─────────────────────────────────────────────────────

@dataclass
class VesselProfile:
    name: str
    vessel_type: str
    route_type: str
    cargo_types: list[str]
    gross_tonnage: int | None = None
    subchapter: str | None = None
    profile_dict: dict = field(init=False)

    def __post_init__(self):
        self.profile_dict = {
            "vessel_type": self.vessel_type,
            "route_type": self.route_type,
            "cargo_types": self.cargo_types,
        }


VESSELS: dict[str, VesselProfile] = {
    # V0 is the "no vessel profile" marker — used by naturalistic queries
    # that simulate a user chatting without having set up a vessel. The
    # driver passes vessel_profile=None to chat() when vessel_code=="V0".
    "V0": VesselProfile(
        name="[no profile]",
        vessel_type="",
        route_type="",
        cargo_types=[],
    ),
    "V1": VesselProfile(
        name="MAERSK Tennessee",
        vessel_type="Containership",
        route_type="international",
        cargo_types=["Containers"],
        gross_tonnage=74642,
    ),
    "V2": VesselProfile(
        name="US Atlantic Crude",
        vessel_type="Tanker",
        route_type="coastal",
        cargo_types=["Petroleum / Oil"],
        gross_tonnage=30000,
    ),
    "V3": VesselProfile(
        name="Island Explorer",
        vessel_type="Passenger Vessel",
        route_type="inland",
        cargo_types=["Passengers"],
        gross_tonnage=65,
        subchapter="T",
    ),
    "V5": VesselProfile(
        name="Mississippi Hauler",
        vessel_type="Towing / Tugboat",
        route_type="inland",
        cargo_types=[],
        gross_tonnage=198,
    ),
    "V7": VesselProfile(
        name="Gulf Supplier",
        vessel_type="OSV / Offshore Support",
        route_type="coastal",
        cargo_types=["General Cargo"],
        gross_tonnage=850,
    ),
}


# ── Test questions with expected-source cheat sheet ─────────────────────
#
# Each question declares:
#   query:       the actual question text
#   vessels:     which vessel setups to run this against
#   expected:    regex patterns that should appear in cited section_numbers
#                for an A grade. Any match counts.
#   wrong_sub:   regex patterns for section_numbers that would indicate
#                the Subchapter-mismatch failure mode (Cassandra Q1).
#                Hitting one of these in the top-2 citations = B or C.

@dataclass
class TestQuestion:
    qid: str
    query: str
    vessels: list[str]
    # Either a flat list (any-of, vessel-agnostic) OR a dict
    # {vessel_code: [patterns], "*": [fallback_patterns]} for per-vessel
    # expected citations. Use the dict form when the correct answer
    # depends on vessel type (e.g. SCBA → Subchapter I for cargo,
    # Subchapter D for tanker, Subchapter M for towing).
    expected: list[str] | dict[str, list[str]]
    wrong_sub: list[str] = field(default_factory=list)
    # Sprint D2.1: naturalistic=True means the question uses real-user
    # phrasing (career narrative, material names, operational scenarios)
    # rather than regulatory register. Reported in a separate summary
    # section to measure the paraphrase-retrieval gap.
    naturalistic: bool = False
    # Sprint D4: sailor_speak=True means the question was auto-generated
    # by scripts/generate_sailor_queries.py in mariner voice. Graded on a
    # looser rubric (A if cited + not hedged; A- if hedged; F if
    # unverified citation) since we don't know the "right" expected
    # source for synthetic queries.
    sailor_speak: bool = False


def _expected_for_vessel(q: "TestQuestion", vessel_code: str) -> list[str]:
    """Pull the per-vessel expected pattern list (or the flat list if
    the question didn't specify per-vessel expectations)."""
    exp = q.expected
    if isinstance(exp, list):
        return exp
    if vessel_code in exp:
        return exp[vessel_code]
    return exp.get("*", [])


QUESTIONS: list[TestQuestion] = [
    # ── Fire safety / SCBA / fireman's outfit ──────────────────────────
    TestQuestion(
        qid="F1",
        query="What are the regulations for SCBA packs on my vessel?",
        vessels=["V1", "V2", "V5"],
        expected={
            # V1 containership: Subchapter I firefighter's outfit, OR
            # vessel-agnostic pointers (SOLAS + NVIC 06-93).
            "V1": [r"46 CFR 96\.35-10", r"SOLAS\s*Ch\.?\s*II-2", r"NVIC 06-93"],
            # V2 tanker: Subchapter D emergency outfit.
            "V2": [r"46 CFR 35\.30-20", r"SOLAS\s*Ch\.?\s*II-2", r"NVIC 06-93"],
            # V5 towing: Subchapter M firefighter's outfit.
            "V5": [r"46 CFR 142\.226", r"SOLAS\s*Ch\.?\s*II-2", r"NVIC 06-93"],
        },
        wrong_sub=[
            r"46 CFR 195\.",       # Subchapter U (research)
            r"46 CFR 77\.",        # Subchapter H (passenger ops) for non-pax
            r"46 CFR 169\.",       # Subchapter R (sailing school)
            r"46 CFR 117\.",       # Subchapter T (small passenger)
            r"46 CFR 180\.",       # Subchapter T (small passenger LSA)
            r"29 CFR 1910",        # OSHA — never correct, we don't have it
        ],
    ),
    TestQuestion(
        qid="F2",
        query="How many firefighter's outfits does my vessel require?",
        vessels=["V1", "V2"],
        expected={
            "V1": [r"46 CFR 96\.35-10", r"SOLAS\s*Ch\.?\s*II-2"],
            "V2": [r"46 CFR 35\.30-20", r"SOLAS\s*Ch\.?\s*II-2"],
        },
        wrong_sub=[
            r"46 CFR 195\.",
            r"46 CFR 169\.",
            r"46 CFR 142\.",   # Subchapter M — wrong for V1 containership / V2 tanker
        ],
    ),
    TestQuestion(
        qid="F5",
        query="Do I need a fixed CO2 system on my vessel?",
        vessels=["V1", "V5"],
        expected={
            # V1 containership: Subchapter I CO2 rule.
            "V1": [r"46 CFR 95\.15", r"SOLAS\s*Ch\.?\s*II-2"],
            # V5 towing: Subchapter M CO2 rule OR honest-limit acknowledgment
            # of the Subchapter M applicability table not being retrieved.
            # Retrieval weakness flagged for later tuning sprint.
            "V5": [r"46 CFR 144\.240", r"Subchapter M", r"SOLAS\s*Ch\.?\s*II-2"],
        },
        wrong_sub=[
            r"46 CFR 195\.",
            r"46 CFR 28\.320",     # Fishing industry — wrong for towing
            r"46 CFR 169\.",       # Sailing school
        ],
    ),
    TestQuestion(
        qid="F7",
        query="Has there been any recent safety alert on fire extinguishers?",
        vessels=["V1", "V3"],
        expected=[
            r"Kidde",           # ACN 013/18 Kidde recall
            r"ACN 013/18",
            r"ACN 002/22",
            r"Fire Protection",
        ],
        wrong_sub=[],  # this is a bulletin query; Subchapter isn't the axis
    ),

    # ── Credentialing ───────────────────────────────────────────────────
    TestQuestion(
        qid="C1",
        query="What do I need to submit for my MMC renewal?",
        vessels=["V1", "V3", "V5"],
        expected=[
            r"MCP-FM-NMC5-01",
            r"NMC Application Acceptance",
            r"CG-719B",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="C2",
        query="Can I use Navy sea service toward my MMC?",
        vessels=["V1", "V3"],
        expected=[
            r"CG-CVC PL 15-03",
            r"NMC Military Sea Service",
            r"crediting_military",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="C3",
        query="What medical standards apply if I have type 2 diabetes?",
        vessels=["V1", "V3", "V5"],
        expected=[
            r"NVIC 04-08",
            r"Medical and Physical",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="C4",
        query="How do I get a ROUPV endorsement?",
        vessels=["V3"],
        expected=[
            r"CG-MMC PL 01-16",
            r"Restricted Operator",
            r"ROUPV",
        ],
        wrong_sub=[],
    ),

    # ── Rescue boat / LSA ───────────────────────────────────────────────
    TestQuestion(
        qid="E1",
        query="What are the rescue boat tiller requirements on my vessel?",
        vessels=["V1", "V5"],
        expected=[
            r"46 CFR 160\.156",
            r"SOLAS.*LSA",
        ],
        wrong_sub=[
            r"46 CFR 169\.",       # sailing school
            r"46 CFR 180\.",       # small passenger
        ],
    ),

    # ── Port conditions / MSIB ──────────────────────────────────────────
    TestQuestion(
        qid="P1",
        query="Are there any port conditions or MSIBs active on the Lower Mississippi?",
        vessels=["V5"],
        expected=[
            r"MSIB Vol",
            r"Carrollton",
            r"Port Condition",
            r"High Water",
            r"Low Water",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="P3",
        query="What port restrictions apply at Elizabeth River bridges in Norfolk?",
        vessels=["V1"],
        expected=[
            r"SEC VA MSIB",
            r"Elizabeth River",
            r"MSIB 168-22",
            r"MSIB 201-23",
        ],
        wrong_sub=[],
    ),

    # ── Navigation / COLREGs ────────────────────────────────────────────
    TestQuestion(
        qid="N1",
        query="Crossing situation right-of-way if I'm overtaking another vessel?",
        vessels=["V1", "V5"],
        expected=[
            r"COLREGS Rule 13",
            r"COLREGS Rule 15",
        ],
        wrong_sub=[],
    ),

    # ── Environmental ───────────────────────────────────────────────────
    TestQuestion(
        qid="V1q",
        query="What are the ballast water requirements for my vessel?",
        vessels=["V1"],
        expected=[
            r"33 CFR 151",
            r"ballast water",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="V3q",
        query="What's in my Oil Record Book entries?",
        vessels=["V2"],
        expected=[
            r"33 CFR 151\.25",
            r"MARPOL.*I",
            r"oil record",
        ],
        wrong_sub=[],
    ),

    # ── Sanity / honest-limit checks ────────────────────────────────────
    TestQuestion(
        qid="X1",
        query="What is today's date and the most recent bulletin you've seen?",
        vessels=["V1"],
        expected=[
            # We expect the answer to mention either a recent bulletin's date
            # OR an explicit acknowledgment of the ~April 2026 cutoff.
            r"2025|2026",
        ],
        wrong_sub=[],
    ),
    TestQuestion(
        qid="X4",
        query="Is NFPA 1981 required on my vessel?",
        vessels=["V1"],
        # NFPA isn't in corpus; honest answer should either cite the SOLAS
        # path that references the standard OR admit limitation.
        expected=[
            r"SOLAS",
            r"don't have",
            r"do not have",
            r"not in my",
            r"not available",
        ],
        wrong_sub=[],
    ),

    # ═══════════════════════════════════════════════════════════════════
    # Sprint D2.1 — Naturalistic-phrasing set (20 questions)
    #
    # Bold items are verbatim or near-verbatim from actual hedged user
    # queries captured in the 2026-04-22 audit. Measures the gap between
    # regulatory-register retrieval (passing 100% A today) and
    # naturalistic-phrasing retrieval (hypothesis: 55-70% A).
    # ═══════════════════════════════════════════════════════════════════

    # ── Credentialing paraphrases ──────────────────────────────────────
    TestQuestion(
        qid="N-C1",
        # VERBATIM from Karynn's 2026-04-22 conversation that hedged.
        query=(
            "If I wanted to start a career as a merchant mariner, "
            "and I chose to start from the bottom at g&h towing in Houston, "
            "what path would I need to take?"
        ),
        vessels=["V5", "V0"],
        expected=[
            r"46 CFR 10\.",
            r"46 CFR 11\.",
            r"46 CFR 12\.",
            r"NVIC 01-95",
            r"merchant mariner credential",
            r"MMC",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-C2",
        query="What's the path from deckhand to master on a towing vessel?",
        vessels=["V5"],
        expected=[
            r"46 CFR 11\.",
            r"TOAR",
            r"Towing Officer",
            r"STCW.*II/[45]",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-C3",
        query="My MMC expires next month — am I still allowed to work?",
        vessels=["V1", "V5"],
        expected=[
            r"46 CFR 10\.227",
            r"46 CFR 10\.",
            r"CG-MMC PL",
            r"grace period",
            r"expiration",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-C4",
        query=(
            "I served 4 years in the Navy as a boatswain's mate. "
            "Does that count toward an MMC?"
        ),
        vessels=["V1"],
        expected=[
            r"CG-CVC PL 15-03",
            r"military sea service",
            r"crediting_military",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── ERG / HAZMAT material-name queries ─────────────────────────────
    TestQuestion(
        qid="N-E1",
        # VERBATIM from 4 separate hedged conversations.
        query="What ERG guide covers chlorine gas?",
        vessels=["V1", "V2"],
        expected=[
            r"ERG Guide 124",
            r"Guide 124",
            r"UN1017",
            r"chlorine",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-E2",
        # VERBATIM from the 2026-04-10 hedged conversation.
        query="How do I handle an ammonia leak?",
        vessels=["V1", "V2"],
        expected=[
            r"ERG Guide 12[56]",
            r"Guide 12[56]",
            r"UN1005",
            r"anhydrous ammonia",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-E3",
        # VERBATIM from the 2026-04-10 hedged conversation.
        query="What is the emergency response for a UN1219 isopropanol spill?",
        vessels=["V1"],
        expected=[
            r"ERG Guide 129",
            r"Guide 129",
            r"UN1219",
            r"isopropanol",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-E4",
        query="What's in the ERG for hydrogen peroxide?",
        vessels=["V1"],
        expected=[
            r"ERG Guide 14[03]",
            r"Guide 14[03]",
            r"UN201[45]",
            r"UN2984",
            r"peroxide",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── SOLAS / equipment interval queries ─────────────────────────────
    TestQuestion(
        qid="N-S1",
        # VERBATIM from the 2026-04-13 hedged conversation.
        query="How often does a VDR beacon need to be changed?",
        vessels=["V1"],
        expected=[
            r"SOLAS.*V.?.?20",
            r"46 CFR 164",
            r"annual performance test",
            r"VDR",
            r"voyage data recorder",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-S2",
        query="When does my emergency fire pump need its annual test?",
        vessels=["V1", "V2"],
        expected=[
            r"46 CFR 14[67]",
            r"SOLAS.*II-2",
            r"fire pump",
            r"annual",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-S3",
        query="What's the drill schedule for fire and abandon ship?",
        vessels=["V1"],
        expected=[
            r"46 CFR 199",
            r"SOLAS.*III.*Reg\.?\s*19",
            r"weekly drill",
            r"monthly drill",
            r"fire drill",
            r"abandon ship drill",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── Maritime security / HRA ────────────────────────────────────────
    TestQuestion(
        qid="N-M1",
        # VERBATIM from the 2026-04-22 hedged conversation.
        query="What guidelines do i need to follow when transitting HRA",
        vessels=["V1"],
        expected=[
            r"NVIC",
            r"piracy",
            r"BMP",
            r"UKMTO",
            r"MSCHOA",
            r"high risk area",
            r"don't have",
            r"do not have",
            r"not in my",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-M2",
        # VERBATIM from the 2026-04-22 hedged conversation.
        query=(
            "If we take the route from the USEC around south africa to pakistan, "
            "what High Risk Waters would we sail through?"
        ),
        vessels=["V1"],
        expected=[
            r"NVIC",
            r"piracy",
            r"BMP",
            r"Gulf of Aden",
            r"HOA",
            r"Arabian Sea",
            r"don't have",
            r"do not have",
            r"not in my",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── Port / vessel operations scenarios ─────────────────────────────
    TestQuestion(
        qid="N-V1",
        query="My vessel is heading to India — what paperwork do we need at port?",
        vessels=["V1"],
        expected=[
            r"33 CFR 160",
            r"NOAD",
            r"notice of arrival",
            r"arrival notice",
            r"port state",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-V2",
        query="What documents does crew sign when they join a containership?",
        vessels=["V1"],
        expected=[
            r"46 CFR 14\.",
            r"shipping articles",
            r"articles of agreement",
            r"sign.on",
            r"46 USC",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-V3",
        query=(
            "My medical cert extension was approved by NMC — "
            "how long does it last?"
        ),
        vessels=["V1", "V5"],
        expected=[
            r"NMC",
            r"CG-MMC",
            r"medical certificate",
            r"extension",
            r"NVIC 04-08",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── Fire protection paraphrases (match F5/F1 semantics) ───────────
    TestQuestion(
        qid="N-F1",
        query="What kind of fire suppression does my engine room need?",
        vessels=["V1", "V5"],
        expected={
            "V1": [r"46 CFR 95\.", r"SOLAS.*II-2", r"CO2", r"fixed fire"],
            "V5": [r"46 CFR 144\.", r"Subchapter M", r"SOLAS.*II-2", r"fixed fire"],
        },
        wrong_sub=[
            r"46 CFR 195\.",       # Subchapter U (research)
            r"46 CFR 169\.",       # Subchapter R (sailing school)
            r"46 CFR 117\.",       # Subchapter T (small passenger)
        ],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-F2",
        query="How often do I need to inspect my life rafts?",
        vessels=["V1"],
        expected=[
            r"46 CFR 199\.180",
            r"46 CFR 199",
            r"SOLAS.*III.*Reg\.?\s*20",
            r"annual",
            r"servicing",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # ── Scenario / ops ─────────────────────────────────────────────────
    TestQuestion(
        qid="N-P1",
        query="Can we make a river run today or is the Mississippi too high?",
        vessels=["V5"],
        expected=[
            r"MSIB Vol",
            r"Carrollton",
            r"Port Condition",
            r"High Water",
            r"Low Water",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-O1",
        query="I need to log something in my Oil Record Book — what's required?",
        vessels=["V2"],
        expected=[
            r"33 CFR 151\.25",
            r"MARPOL.*I",
            r"oil record",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),

    # Sprint D4 — sailor-speak queries are loaded from JSON below
    # (scripts/generate_sailor_queries.py writes the file). They are
    # appended to QUESTIONS at import time by _load_sailor_speak().

    # ── Sprint D3 authority-tier sanity checks ─────────────────────────
    TestQuestion(
        qid="N-AUTH1",
        # Cross-tier hazmat question. Tier 4 (ERG) must not be dropped in
        # favor of Tier 1 (49 CFR HM). Both should appear — they answer
        # different aspects (response actions vs carriage regulations).
        query=(
            "We're carrying UN1219 isopropanol on an international voyage — "
            "what applies to us and what do we do if a drum ruptures?"
        ),
        vessels=["V1"],
        expected=[
            r"ERG Guide 129",
            r"Guide 129",
            r"49 CFR",
            r"UN1219",
            r"isopropanol",
        ],
        wrong_sub=[],
        naturalistic=True,
    ),
    TestQuestion(
        qid="N-AUTH2",
        # Cross-tier applicability question. SOLAS (Tier 1 international)
        # vs 46 CFR Subchapter I (Tier 1 domestic) both potentially apply.
        # Correct answer identifies which applies to a containership on an
        # international route, rather than citing both as equivalent.
        query="What fire safety requirements apply to our vessel on international routes?",
        vessels=["V1"],
        expected=[
            r"SOLAS.*II-2",
            r"46 CFR 9[56]\.",
            r"international",
            r"applies",
        ],
        wrong_sub=[
            r"46 CFR 195\.",       # Subchapter U (research)
            r"46 CFR 169\.",       # Subchapter R (sailing school)
            r"46 CFR 142\.",       # Subchapter M (towing)
        ],
        naturalistic=True,
    ),
]


# ── Sprint D4 — load sailor-speak queries from JSON ─────────────────────


def _load_sailor_speak() -> list[TestQuestion]:
    """Load synthetic sailor-speak queries from data/eval/sailor_queries.json.

    Silently returns [] if the file doesn't exist — regulatory-register +
    naturalistic still run. Run scripts/generate_sailor_queries.py to
    populate the file.
    """
    p = Path("/opt/RegKnots/data/eval/sailor_queries.json")
    if not p.exists():
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[TestQuestion] = []
    for row in payload.get("queries", []):
        out.append(TestQuestion(
            qid=row["qid"],
            query=row["query"],
            vessels=[row["vessel_code"]],
            expected=[],      # no regex cheat sheet — graded on hedge + cite presence
            wrong_sub=[],
            naturalistic=False,
            sailor_speak=True,
        ))
    return out


QUESTIONS.extend(_load_sailor_speak())


# ── Auto-grader ─────────────────────────────────────────────────────────


@dataclass
class GradeResult:
    qid: str
    vessel_code: str
    query: str
    answer: str
    citations: list[dict]   # list of {source, section_number, section_title}
    expected_matched: list[str]
    wrong_sub_matched: list[str]
    grade: str
    grade_reason: str
    model_used: str
    input_tokens: int
    output_tokens: int
    retrieved_count: int
    unverified: list[str]
    hedge_phrase: str | None = None  # Sprint D2.1b — populated if hedge detected


def _grade_answer(q: TestQuestion, citations: list[dict], answer_text: str,
                   unverified: list[str],
                   vessel_code: str) -> tuple[str, str, list[str], list[str]]:
    """Return (grade, reason, expected_matched, wrong_sub_matched).

    vessel_code is used to look up per-vessel expected patterns when the
    question's expected field is a dict (e.g., SCBA: different Subchapter
    per vessel type).
    """
    # Sprint D4 — sailor-speak queries have no `expected` regex cheat
    # sheet. Grade on a simpler rubric: F on hallucinated citation,
    # otherwise A (hedge demotion in _apply_hedge_demotion may drop it
    # to A−). The goal here is to measure the hedge rate on synthetic
    # mariner-voice queries, not to verify specific-source retrieval.
    if q.sailor_speak:
        if unverified:
            return ("F", f"Unverified citation(s): {unverified[:3]}", [], [])
        if not citations:
            return ("F", "No citations surfaced at all", [], [])
        return ("A", f"Sailor-speak clean: {len(citations)} citation(s)", [], [])

    # Compose the grading haystack: all section_numbers in citation order +
    # the answer text itself (some expected patterns like "Kidde" are text,
    # not section_numbers).
    cit_str = "\n".join(
        f"{c['source']} | {c['section_number']} | {c['section_title']}"
        for c in citations
    )
    haystack = cit_str + "\n" + answer_text

    # Which expected patterns matched at all?
    expected_patterns = _expected_for_vessel(q, vessel_code)
    expected_hits = []
    for pat in expected_patterns:
        if re.search(pat, haystack, re.IGNORECASE):
            expected_hits.append(pat)

    # Which wrong-subchapter patterns appear in the top-2 citations?
    # Top-2 because that's what the synthesizer leads with and what a user
    # would notice first. A wrong-Subchapter cite at #6 is less damaging.
    top2_cits = citations[:2]
    top2_cit_str = "\n".join(
        f"{c['source']} | {c['section_number']} | {c['section_title']}"
        for c in top2_cits
    )
    wrong_hits_top2 = []
    for pat in q.wrong_sub:
        if re.search(pat, top2_cit_str, re.IGNORECASE):
            wrong_hits_top2.append(pat)

    # Also check wrong-sub anywhere (informational only)
    wrong_hits_any = []
    for pat in q.wrong_sub:
        if re.search(pat, cit_str, re.IGNORECASE):
            wrong_hits_any.append(pat)

    # Check for unverified citations — that's an automatic F
    if unverified:
        return (
            "F",
            f"Unverified citation(s) present: {unverified[:3]}",
            expected_hits, wrong_hits_any,
        )

    if not expected_hits:
        # No expected source cited
        if wrong_hits_top2:
            return (
                "C",
                f"Expected source not cited; wrong-Subchapter citation in top 2: {wrong_hits_top2}",
                expected_hits, wrong_hits_any,
            )
        return (
            "F",
            "Expected source not cited; no wrong-Subchapter either (retrieval whiff)",
            expected_hits, wrong_hits_any,
        )

    # Expected IS cited. Grade depends on contamination.
    if wrong_hits_top2:
        return (
            "B",
            f"Expected cited AND wrong-Subchapter cite in top 2: {wrong_hits_top2}",
            expected_hits, wrong_hits_any,
        )
    if wrong_hits_any:
        # Expected cited, wrong-sub appears lower in the list — call it A-
        return (
            "A-",
            f"Expected cited; wrong-Subchapter appears lower in citations (not top-2): {wrong_hits_any}",
            expected_hits, wrong_hits_any,
        )
    return (
        "A",
        f"Expected source matched: {expected_hits[:3]}",
        expected_hits, wrong_hits_any,
    )


# ── Sprint D2.1b — hedge-phrase demotion ─────────────────────────────────

_HEDGE_DEMOTION: dict[str, str] = {
    "A": "A-",
    "A-": "B",
    # B / C / F already reflect real problems; no further demotion.
}


def _apply_hedge_demotion(
    grade: str, reason: str, hedge_phrase: str | None,
) -> tuple[str, str]:
    """If the answer contained a hedge phrase, demote A→A− and A−→B.

    Pre-D2.1b, a "partial retrieval + honest hedge" answer could grade A
    because the regex matched any peripheral citation. That rewarded the
    exact failure mode users complain about. D2.1b fixes the grader so
    hedged answers can never grade above A−.
    """
    if hedge_phrase is None:
        return grade, reason
    new_grade = _HEDGE_DEMOTION.get(grade, grade)
    if new_grade == grade:
        return grade, reason
    return new_grade, f"{reason} [DEMOTED: hedge phrase in answer — {hedge_phrase!r}]"


# ── Driver ──────────────────────────────────────────────────────────────


async def run_one(
    q: TestQuestion, vessel_code: str, pool, anthropic_client, eval_user_id,
) -> GradeResult:
    vessel = VESSELS[vessel_code]
    # V0 = simulates a user chatting without a vessel profile set. Pass
    # None so the RAG engine takes the no-profile synthesis path.
    vessel_profile_arg = None if vessel_code == "V0" else vessel.profile_dict
    conv_id = uuid4()
    # Pre-insert a real conversations row so the citation_errors FK is satisfied
    # when the RAG pipeline tries to log unverified citations. Without this
    # the FK constraint fires and we can't distinguish "retrieval failure" from
    # "harness failure." Clean up at the end.
    await pool.execute(
        "INSERT INTO conversations (id, user_id, title) "
        "VALUES ($1, $2, $3)",
        conv_id, eval_user_id, f"[eval] {q.qid}/{vessel_code}",
    )
    try:
        resp = await chat(
            query=q.query,
            conversation_history=[],
            vessel_profile=vessel_profile_arg,
            pool=pool,
            anthropic_client=anthropic_client,
            openai_api_key=settings.openai_api_key,
            conversation_id=conv_id,
            credential_context=None,
        )
    except Exception as exc:
        # Best-effort cleanup
        try:
            await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        except Exception:
            pass
        return GradeResult(
            qid=q.qid, vessel_code=vessel_code, query=q.query,
            answer=f"EXCEPTION: {type(exc).__name__}: {exc}",
            citations=[], expected_matched=[], wrong_sub_matched=[],
            grade="F", grade_reason=f"Exception during chat(): {exc}",
            model_used="n/a", input_tokens=0, output_tokens=0,
            retrieved_count=0, unverified=[],
        )
    # Always cleanup — leave no eval droppings in prod conversations/messages
    try:
        await pool.execute("DELETE FROM messages WHERE conversation_id = $1", conv_id)
        await pool.execute("DELETE FROM citation_errors WHERE conversation_id = $1", conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
    except Exception:
        pass

    citations = [
        {"source": c.source, "section_number": c.section_number,
         "section_title": c.section_title}
        for c in resp.cited_regulations
    ]
    grade, reason, exp_hits, wrong_hits = _grade_answer(
        q, citations, resp.answer, resp.unverified_citations, vessel_code,
    )
    hedge_phrase = detect_hedge(resp.answer)
    grade, reason = _apply_hedge_demotion(grade, reason, hedge_phrase)
    return GradeResult(
        qid=q.qid, vessel_code=vessel_code, query=q.query,
        answer=resp.answer, citations=citations,
        expected_matched=exp_hits, wrong_sub_matched=wrong_hits,
        grade=grade, grade_reason=reason,
        model_used=resp.model_used,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        retrieved_count=len(citations),
        unverified=resp.unverified_citations,
        hedge_phrase=hedge_phrase,
    )


async def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(f"/opt/RegKnots/data/eval/{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build task list
    tasks_plan: list[tuple[TestQuestion, str]] = []
    for q in QUESTIONS:
        for v in q.vessels:
            tasks_plan.append((q, v))

    print(f"Running {len(tasks_plan)} (question, vessel) combos...")
    print(f"Output dir: {out_dir}")

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Resolve an existing user to own the eval conversations. We never write
    # to that user's data; we just satisfy the users/conversations FK.
    eval_user_id = await pool.fetchval(
        "SELECT id FROM users WHERE email = 'blakemarchal@gmail.com' LIMIT 1"
    )
    if not eval_user_id:
        eval_user_id = await pool.fetchval("SELECT id FROM users LIMIT 1")
    print(f"Using eval_user_id: {eval_user_id}")

    results: list[GradeResult] = []
    try:
        # Concurrency=3 to avoid slamming Claude API
        sem = asyncio.Semaphore(3)

        async def _one_with_sem(q, v):
            async with sem:
                r = await run_one(q, v, pool, client, eval_user_id)
                print(f"  [{r.grade:<2}] {v}/{q.qid:<4}: {r.grade_reason[:90]}")
                return r

        tasks = [_one_with_sem(q, v) for q, v in tasks_plan]
        for fut in asyncio.as_completed(tasks):
            results.append(await fut)

        results.sort(key=lambda r: (r.vessel_code, r.qid))
    finally:
        await client.close()
        await pool.close()

    # ── Write results.jsonl ──────────────────────────────────────────────
    jsonl_path = out_dir / "results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"\nResults: {jsonl_path}")

    # ── Aggregates ───────────────────────────────────────────────────────
    from collections import Counter

    # Build qid → subset maps so the summary splits into:
    #   Regulatory-register (original hand-written cheat-sheet questions)
    #   Naturalistic (Sprint D2.1 — real user-phrasing questions)
    #   Sailor-speak (Sprint D4 — synthetic mariner-voice queries)
    naturalistic_qids = {q.qid for q in QUESTIONS if q.naturalistic}
    sailor_qids = {q.qid for q in QUESTIONS if q.sailor_speak}

    grade_dist = Counter(r.grade for r in results)
    total = len(results)
    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)

    reg_results = [r for r in results if r.qid not in naturalistic_qids and r.qid not in sailor_qids]
    nat_results = [r for r in results if r.qid in naturalistic_qids]
    sailor_results = [r for r in results if r.qid in sailor_qids]
    reg_dist = Counter(r.grade for r in reg_results)
    nat_dist = Counter(r.grade for r in nat_results)
    sailor_dist = Counter(r.grade for r in sailor_results)

    def _pct(dist: Counter, count: int, grades: tuple[str, ...]) -> float:
        if not count:
            return 0.0
        return round(100 * sum(dist[g] for g in grades) / count, 1)

    hedged_total = sum(1 for r in results if r.hedge_phrase)
    hedged_reg = sum(1 for r in reg_results if r.hedge_phrase)
    hedged_nat = sum(1 for r in nat_results if r.hedge_phrase)
    hedged_sailor = sum(1 for r in sailor_results if r.hedge_phrase)

    summary = {
        "timestamp": ts,
        "total_runs": total,
        "grade_distribution": dict(grade_dist),
        "a_or_better_pct": _pct(grade_dist, total, ("A", "A-")),
        "b_or_better_pct": _pct(grade_dist, total, ("A", "A-", "B")),
        "hedged_answers": hedged_total,
        "hedged_pct": round(100 * hedged_total / total, 1) if total else 0.0,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "regulatory_register": {
            "runs": len(reg_results),
            "grade_distribution": dict(reg_dist),
            "a_or_better_pct": _pct(reg_dist, len(reg_results), ("A", "A-")),
            "hedged_answers": hedged_reg,
        },
        "naturalistic": {
            "runs": len(nat_results),
            "grade_distribution": dict(nat_dist),
            "a_or_better_pct": _pct(nat_dist, len(nat_results), ("A", "A-")),
            "hedged_answers": hedged_nat,
        },
        "sailor_speak": {
            "runs": len(sailor_results),
            "grade_distribution": dict(sailor_dist),
            "a_or_better_pct": _pct(sailor_dist, len(sailor_results), ("A", "A-")),
            "hedged_answers": hedged_sailor,
            "hedged_pct": round(100 * hedged_sailor / len(sailor_results), 1) if sailor_results else 0.0,
        },
    }
    summary_json_path = out_dir / "summary.json"
    summary_json_path.write_text(json.dumps(summary, indent=2))

    # ── Markdown summary ─────────────────────────────────────────────────
    md = []
    md.append(f"# RAG Eval Baseline — {ts}")
    md.append("")
    md.append(f"**Total runs:** {total}")
    md.append(f"**Grade distribution:** " + ", ".join(
        f"{g}: {grade_dist[g]}" for g in ["A","A-","B","C","F"] if grade_dist[g]
    ))
    md.append(f"**A or A−:** {summary['a_or_better_pct']}%")
    md.append(f"**B or better:** {summary['b_or_better_pct']}%")
    md.append("")
    md.append(f"**LLM spend:** {total_in:,} input + {total_out:,} output tokens across {total} runs")
    md.append("")

    # ── Sprint D2.1 split: regulatory-register vs naturalistic ───────────
    md.append("## Subset comparison")
    md.append("")
    md.append("| Subset | Runs | A | A− | B | C | F | A-or-A− | Hedged |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for label, subset_results, subset_dist, hedge_n in [
        ("Regulatory-register (original)", reg_results, reg_dist, hedged_reg),
        ("Naturalistic (Sprint D2.1)", nat_results, nat_dist, hedged_nat),
        ("Sailor-speak (Sprint D4)", sailor_results, sailor_dist, hedged_sailor),
    ]:
        row = [label, str(len(subset_results))]
        for g in ("A", "A-", "B", "C", "F"):
            row.append(str(subset_dist[g]))
        row.append(f"{_pct(subset_dist, len(subset_results), ('A','A-'))}%")
        row.append(str(hedge_n))
        md.append("| " + " | ".join(row) + " |")
    md.append("")
    md.append(
        "The delta between the two A-or-A− percentages is the "
        "paraphrase-retrieval gap that Sprint D2.2 — D2.5 target."
    )
    md.append("")
    md.append("## Failures (C + F)")
    md.append("")
    fails = [r for r in results if r.grade in ("C", "F")]
    if not fails:
        md.append("(none)")
    for r in fails:
        md.append(f"### {r.vessel_code} / {r.qid}  — {r.grade}")
        md.append(f"**Query:** {r.query}")
        md.append(f"**Reason:** {r.grade_reason}")
        md.append(f"**Citations ({len(r.citations)}):**")
        for i, c in enumerate(r.citations[:5], 1):
            md.append(f"  {i}. [{c['source']}] {c['section_number']} — {c['section_title'][:80]}")
        if r.unverified:
            md.append(f"**Unverified citations:** {r.unverified}")
        md.append("")
    md.append("## B-grade contaminations")
    md.append("")
    bs = [r for r in results if r.grade == "B"]
    if not bs:
        md.append("(none)")
    for r in bs:
        md.append(f"### {r.vessel_code} / {r.qid}")
        md.append(f"**Query:** {r.query}")
        md.append(f"**Wrong-Subchapter cites in top-2:** {r.wrong_sub_matched}")
        if r.hedge_phrase:
            md.append(f"**Hedge phrase:** {r.hedge_phrase!r}")
        md.append("")

    # ── D2.1b — hedged answers (any grade) ───────────────────────────────
    md.append("## Hedged answers (Sprint D2.1b detection)")
    md.append("")
    hedged_rows = [r for r in results if r.hedge_phrase]
    if not hedged_rows:
        md.append("(none — no answer contained a hedge phrase)")
    else:
        md.append(
            f"{len(hedged_rows)} of {total} answers contained a hedge phrase. "
            "These are the answers that got cited something but still told the user "
            "they couldn't give a complete answer. Each of these is a real-world "
            "'bad answer' from the user's point of view even if the grader passes "
            "the citation check."
        )
        md.append("")
        for r in hedged_rows:
            md.append(
                f"- [{r.grade:<2}] {r.vessel_code} / {r.qid}: "
                f"`{r.query[:70]}` — hedge: {r.hedge_phrase!r}"
            )
    md.append("")
    md.append("## A / A− roll-up")
    md.append("")
    for r in results:
        if r.grade in ("A", "A-"):
            md.append(f"- [{r.grade:<2}] {r.vessel_code} / {r.qid}: `{r.query[:80]}`")

    md_path = out_dir / "summary.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"Grade distribution (all): {dict(grade_dist)}")
    print(f"A or A−: {summary['a_or_better_pct']}%")
    print(f"B or better: {summary['b_or_better_pct']}%")
    print(f"Hedged answers: {hedged_total}/{total} ({summary['hedged_pct']}%)")
    print()
    print(
        f"Regulatory-register subset:  {len(reg_results):>3} runs | "
        f"A-or-A− {summary['regulatory_register']['a_or_better_pct']}% | "
        f"dist: {dict(reg_dist)} | hedged: {hedged_reg}"
    )
    print(
        f"Naturalistic subset (D2.1):  {len(nat_results):>3} runs | "
        f"A-or-A− {summary['naturalistic']['a_or_better_pct']}% | "
        f"dist: {dict(nat_dist)} | hedged: {hedged_nat}"
    )
    if sailor_results:
        print(
            f"Sailor-speak subset (D4):    {len(sailor_results):>3} runs | "
            f"A-or-A− {summary['sailor_speak']['a_or_better_pct']}% | "
            f"dist: {dict(sailor_dist)} | hedged: {hedged_sailor} "
            f"({summary['sailor_speak']['hedged_pct']}%)"
        )
    print(f"Summary: {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
