"""Generate synthetic 'sailor-speak' queries for the RAG eval (Sprint D4).

Uses Claude Sonnet to produce mariner-voice variants of maritime
compliance questions across a fixed topic taxonomy. Output is written
to `data/eval/sailor_queries.json` and loaded by
`scripts/eval_rag_baseline.py` as a third eval subset alongside
regulatory-register and naturalistic.

Design notes:
- Seed the generator with Karynn's actual phrasings so the synthetic set
  inherits real-mariner register rather than Claude's prior about how
  mariners talk.
- Each topic produces 3 variants (formal-lite, working-mariner, old-salt).
- Every query is tagged with a vessel_code so the eval knows which vessel
  profile to run it against (or V0 for no-vessel queries).
- No `expected` regex patterns. Synthetic queries are graded on a
  simpler rubric in the eval: A = no hedge + at least one cite; A− =
  hedged (D2.1b demotion); F = unverified citation. This is intentional
  — we don't know the "right" answer for synthetic queries, only whether
  the system behaved well.

Usage (on the VPS — requires ANTHROPIC_API_KEY via settings):
    cd /opt/RegKnots
    uv run --project apps/api python scripts/generate_sailor_queries.py

Re-run any time you want a fresh set. The output is committed to the
repo so eval reproducibility doesn't depend on the generator running
during every eval.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from anthropic import AsyncAnthropic

from app.config import settings


# ── Topic taxonomy ──────────────────────────────────────────────────────
#
# 30 topics × 3 variants = 90 queries. Each topic declares which vessel
# profiles it's relevant to. The generator picks one vessel_code per
# variant (rotating if multiple candidates) so we get coverage across
# vessel types.

TOPICS: list[dict] = [
    # Credentialing
    {"key": "mmc_renewal", "domain": "credentialing", "vessels": ["V1", "V5"],
     "hint": "renewing a merchant mariner credential, timing, medical certs"},
    {"key": "entry_mariner", "domain": "credentialing", "vessels": ["V0", "V5"],
     "hint": "starting a maritime career, first credential, sea service"},
    {"key": "mate_advancement", "domain": "credentialing", "vessels": ["V1", "V5"],
     "hint": "advancing from AB to Mate or Mate to Master, sea time requirements"},
    {"key": "military_service", "domain": "credentialing", "vessels": ["V1"],
     "hint": "Navy/Coast Guard service counting toward MMC, which documents"},
    {"key": "toar_towing", "domain": "credentialing", "vessels": ["V5"],
     "hint": "Towing Officer Assessment Record, apprentice mate of towing"},

    # Medical
    {"key": "medical_cert_ext", "domain": "medical", "vessels": ["V1", "V5"],
     "hint": "medical certificate extension, expiry, renewal during voyage"},
    {"key": "disqualifying_conditions", "domain": "medical", "vessels": ["V0", "V1"],
     "hint": "medical conditions that disqualify or require waiver, diabetes, cardiac"},

    # Fire protection
    {"key": "scba_requirements", "domain": "fire", "vessels": ["V1", "V2", "V5"],
     "hint": "SCBA / breathing apparatus, fireman's outfit, recent alerts"},
    {"key": "co2_fixed_system", "domain": "fire", "vessels": ["V1", "V5"],
     "hint": "fixed CO2 system, engine room, cargo spaces, maintenance"},
    {"key": "fire_drill_schedule", "domain": "fire", "vessels": ["V1", "V2"],
     "hint": "frequency of fire drills, abandon ship drills, crew training"},
    {"key": "extinguisher_inspection", "domain": "fire", "vessels": ["V1"],
     "hint": "portable extinguisher inspection intervals, recent recalls"},

    # LSA / rescue
    {"key": "lifeboat_lowering", "domain": "lsa", "vessels": ["V1"],
     "hint": "lifeboat lowering to embarkation deck, inspection intervals"},
    {"key": "station_bill", "domain": "lsa", "vessels": ["V1", "V2"],
     "hint": "station bill posting, muster stations, required content"},
    {"key": "liferaft_service", "domain": "lsa", "vessels": ["V1"],
     "hint": "liferaft annual servicing, certificate, approved facilities"},

    # Navigation
    {"key": "colregs_crossing", "domain": "nav", "vessels": ["V1", "V5"],
     "hint": "crossing / overtaking / head-on situations, right of way"},
    {"key": "vdr_beacon", "domain": "nav", "vessels": ["V1"],
     "hint": "VDR beacon battery replacement interval, annual performance test"},
    {"key": "required_pubs", "domain": "nav", "vessels": ["V1"],
     "hint": "required nautical publications, chart corrections, annual light list"},

    # Hazmat / cargo
    {"key": "hazmat_response", "domain": "hazmat", "vessels": ["V1", "V2"],
     "hint": "emergency response to a chemical spill, ERG guide lookup"},
    {"key": "vgm_compliance", "domain": "hazmat", "vessels": ["V1"],
     "hint": "verified gross mass, container weight verification, SOLAS VI Reg 2"},
    {"key": "imdg_requirement", "domain": "hazmat", "vessels": ["V1"],
     "hint": "IMDG code on board, dangerous goods manifest, class placarding"},

    # Environmental
    {"key": "oil_record_book", "domain": "env", "vessels": ["V2"],
     "hint": "oil record book entries, MARPOL Annex I, retention period"},
    {"key": "ballast_water", "domain": "env", "vessels": ["V1"],
     "hint": "ballast water management, exchange vs treatment, record keeping"},
    {"key": "garbage_management", "domain": "env", "vessels": ["V1", "V5"],
     "hint": "garbage management plan, MARPOL Annex V, placards"},

    # Port / operational
    {"key": "port_arrival_docs", "domain": "port", "vessels": ["V1"],
     "hint": "notice of arrival, NOAD, port state control prep, documents"},
    {"key": "psc_inspection", "domain": "port", "vessels": ["V1"],
     "hint": "PSC inspector arrives, what documents, common deficiencies"},
    {"key": "river_conditions", "domain": "port", "vessels": ["V5"],
     "hint": "river height restrictions, port conditions, MSIB lookups"},

    # Labor / crew
    {"key": "mlc_compliance", "domain": "labor", "vessels": ["V1"],
     "hint": "Maritime Labour Convention, hours of work/rest, wages"},
    {"key": "foreign_articles", "domain": "labor", "vessels": ["V1"],
     "hint": "foreign articles, breaking articles, discharge timing"},
    {"key": "crew_sign_on", "domain": "labor", "vessels": ["V1"],
     "hint": "crew member sign-on documents, articles of agreement, manning"},

    # Security / international
    {"key": "hra_transit", "domain": "security", "vessels": ["V1"],
     "hint": "high risk area transit, Gulf of Aden, piracy precautions"},
]


GENERATION_PROMPT = """\
You are generating synthetic "sailor-speak" test queries for a maritime
compliance RAG system. The system is being stress-tested against real-world
working-mariner voice, not lawyer-phrased questions.

STYLE — mimic actual working mariners:
- Sometimes imprecise but always SPECIFIC about the situation (vessel type, \
cargo, route, time of day, etc.).
- Use industry slang where natural: "old man" for Master, "OS" for ordinary \
seaman, "AB" for Able Seaman, "TWIC," "CG-719," "fathometer," "slops," \
"bunkering," "trimming," etc.
- Some queries should be one-sentence; some should frame a scenario first.
- Variants should feel like three DIFFERENT mariners asking about the same \
topic — not the same mariner's three drafts.

Do NOT:
- Write queries that sound like regulation section headers.
- Use overly formal vocabulary ("regulatory requirements governing...").
- Include CFR/SOLAS citations in the query itself — that's our job to provide.

TOPIC: {domain} — {hint}
VESSEL CONTEXT HINT: {vessel_label}

Write exactly 3 variants. Each variant on its own line, NO numbering, NO \
commentary, NO markdown. Just the raw question text, one per line.
"""


VESSEL_LABELS = {
    "V0": "no specific vessel (general maritime question)",
    "V1": "containership on international routes, 75,000+ GT",
    "V2": "coastal crude tanker, 30,000 GT",
    "V3": "small Subchapter T passenger vessel, 65 GT, inland",
    "V5": "inland Mississippi towing vessel, 198 GT, Subchapter M",
    "V7": "offshore supply vessel, 850 GT",
}


async def generate_one(client: AsyncAnthropic, topic: dict, vessel_code: str) -> list[str]:
    """Generate 3 mariner-voice variants for a single (topic, vessel) pair."""
    prompt = GENERATION_PROMPT.format(
        domain=topic["domain"],
        hint=topic["hint"],
        vessel_label=VESSEL_LABELS.get(vessel_code, vessel_code),
    )
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    variants = [line.strip() for line in text.splitlines() if line.strip()]
    # Drop anything that looks like a preamble / numbering / quotes wrapper
    cleaned = []
    for v in variants:
        if v[:2] in {"1.", "2.", "3.", "- "}:
            v = v[2:].strip()
        v = v.strip("\"'")
        if v and len(v) > 10:
            cleaned.append(v)
    return cleaned[:3]


async def main() -> int:
    out_path = Path("/opt/RegKnots/data/eval/sailor_queries.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    records: list[dict] = []
    qid_counter = 1
    try:
        sem = asyncio.Semaphore(3)

        async def gen(topic: dict, vessel_code: str):
            async with sem:
                try:
                    variants = await generate_one(client, topic, vessel_code)
                    return topic, vessel_code, variants
                except Exception as exc:
                    print(f"  FAIL {topic['key']}/{vessel_code}: {exc}")
                    return topic, vessel_code, []

        tasks = []
        for topic in TOPICS:
            # Pick the first vessel as the primary; second vessel optional
            for vessel_code in topic["vessels"][:1]:
                tasks.append(gen(topic, vessel_code))

        for fut in asyncio.as_completed(tasks):
            topic, vessel_code, variants = await fut
            for v in variants:
                records.append({
                    "qid": f"S-{qid_counter:03d}",
                    "topic": topic["key"],
                    "domain": topic["domain"],
                    "vessel_code": vessel_code,
                    "query": v,
                })
                qid_counter += 1
            print(f"  [{topic['key']:<24}] {vessel_code}: generated {len(variants)}")

        records.sort(key=lambda r: r["qid"])

        out_path.write_text(
            json.dumps({"topics": len(TOPICS), "queries": records}, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"Wrote {len(records)} queries → {out_path}")
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
