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
    expected: list[str]
    wrong_sub: list[str] = field(default_factory=list)


QUESTIONS: list[TestQuestion] = [
    # ── Fire safety / SCBA / fireman's outfit ──────────────────────────
    TestQuestion(
        qid="F1",
        query="What are the regulations for SCBA packs on my vessel?",
        vessels=["V1", "V2", "V5"],
        expected=[
            r"46 CFR 96\.35-10",   # V1 containership
            r"46 CFR 35\.30-20",   # V2 tanker
            r"46 CFR 142\.226",    # V5 towing M
            r"SOLAS Ch\.II-2.*10",
        ],
        wrong_sub=[
            r"46 CFR 195\.",       # Subchapter U (research)
            r"46 CFR 77\.",        # Subchapter H (passenger ops) for non-pax
            r"46 CFR 169\.",       # Subchapter R (sailing school)
        ],
    ),
    TestQuestion(
        qid="F2",
        query="How many firefighter's outfits does my vessel require?",
        vessels=["V1", "V2"],
        expected=[
            r"46 CFR 96\.35-10",
            r"46 CFR 35\.30-20",
            r"SOLAS Ch\.II-2.*10",
        ],
        wrong_sub=[
            r"46 CFR 195\.",
            r"46 CFR 169\.",
        ],
    ),
    TestQuestion(
        qid="F5",
        query="Do I need a fixed CO2 system on my vessel?",
        vessels=["V1", "V5"],
        expected=[
            r"46 CFR 95\.15",
            r"46 CFR 144\.240",
            r"SOLAS Ch\.II-2",
        ],
        wrong_sub=[
            r"46 CFR 195\.",
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
]


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


def _grade_answer(q: TestQuestion, citations: list[dict], answer_text: str,
                   unverified: list[str]) -> tuple[str, str, list[str], list[str]]:
    """Return (grade, reason, expected_matched, wrong_sub_matched)."""
    # Compose the grading haystack: all section_numbers in citation order +
    # the answer text itself (some expected patterns like "Kidde" are text,
    # not section_numbers).
    cit_str = "\n".join(
        f"{c['source']} | {c['section_number']} | {c['section_title']}"
        for c in citations
    )
    haystack = cit_str + "\n" + answer_text

    # Which expected patterns matched at all?
    expected_hits = []
    for pat in q.expected:
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


# ── Driver ──────────────────────────────────────────────────────────────


async def run_one(
    q: TestQuestion, vessel_code: str, pool, anthropic_client, eval_user_id,
) -> GradeResult:
    vessel = VESSELS[vessel_code]
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
            vessel_profile=vessel.profile_dict,
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
        q, citations, resp.answer, resp.unverified_citations,
    )
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
    grade_dist = Counter(r.grade for r in results)
    total = len(results)
    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)

    summary = {
        "timestamp": ts,
        "total_runs": total,
        "grade_distribution": dict(grade_dist),
        "a_or_better_pct": round(100 * (grade_dist["A"] + grade_dist["A-"]) / total, 1),
        "b_or_better_pct": round(100 * (grade_dist["A"] + grade_dist["A-"] + grade_dist["B"]) / total, 1),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
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
    print(f"Grade distribution: {dict(grade_dist)}")
    print(f"A or A−: {summary['a_or_better_pct']}%")
    print(f"B or better: {summary['b_or_better_pct']}%")
    print(f"Summary: {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
