"""Where Postgres spends its CPU in one retrieve() call (read-only; OpenAI embeddings only).

Runs each phase of retrieve() on its own, one at a time, and reads the postgres
container's CPU counter around it: the group fan-out, each group query, the vessel
lane, identifier search, keyword search (each keyword's frequency check), and the
whole retrieve() for comparison.
"""
import asyncio
import glob
import os
import sys
import time

import asyncpg

sys.path.insert(0, "/opt/RegKnots/apps/api")
from app.config import settings  # noqa: E402
from rag import retriever as R  # noqa: E402
from rag.jurisdiction import allowed_jurisdictions  # noqa: E402
from rag.synonyms import expand_intent, expand_keywords  # noqa: E402

import logging  # noqa: E402
logging.basicConfig(level=logging.WARNING)

TOW = {"vessel_name": "Bench", "vessel_type": "Towing / Tugboat", "flag_state": "United States"}
BOX = {"vessel_name": "Bench", "vessel_type": "Containership", "flag_state": "United States"}
CASES = [
    (TOW, "life saving device requirements for a 7-person crew on a US-flag towing vessel"),
    (TOW, "lifesaving appliance requirements towing vessel 46 CFR 137 crew capacity"),
    (BOX, "SOLAS Chapter III Regulation 20 operational readiness maintenance and inspections"),
]
_CG = None


def pg_cpu() -> float:
    global _CG
    if _CG is None:
        hits = glob.glob(f"/sys/fs/cgroup/system.slice/docker-{os.environ.get('PG_CID', '')}*.scope/cpu.stat")
        _CG = hits[0] if hits else ""
    for line in open(_CG):
        if line.startswith("usage_usec"):
            return int(line.split()[1]) / 1e6
    return 0.0


async def measure(label, fn):
    c, t = pg_cpu(), time.perf_counter()
    res = await fn()
    wall, cpu = time.perf_counter() - t, pg_cpu() - c
    print(f"  {label:58} wall {wall * 1000:7.0f} ms   postgres cpu {cpu * 1000:7.0f} ms")
    return res, wall, cpu


async def main():
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    vecs = await R._embed_queries(settings.openai_api_key, [q for _, q in CASES])
    available = await R._get_available_sources(pool)
    stats = await R._get_source_stats(pool)
    for (profile, q), vec in zip(CASES, vecs):
        print(f"\n## {q}")
        juris = allowed_jurisdictions(q, profile, None)
        juris = list(juris) if juris is not None else None
        planned = R._plan_groups(available, stats, juris)
        # whole call, twice (the second is the warm number)
        for i in range(2):
            await measure(f"retrieve() whole call, run {i + 1}",
                          lambda: R.retrieve(query=q, pool=pool, openai_api_key=settings.openai_api_key,
                                             vessel_profile=profile, limit=8))
        await measure(f"{len(planned)} group queries, concurrent (as retrieve does)",
                      lambda: asyncio.gather(*[R._fetch_group(pool, vec, s, k, juris) for _, s, k in planned]))
        per = []
        for name, s, k in planned:
            c, t = pg_cpu(), time.perf_counter()
            rows = await R._fetch_group(pool, vec, s, k, juris)
            per.append((pg_cpu() - c, time.perf_counter() - t, name, len(rows)))
        tot_cpu = sum(p[0] for p in per)
        print(f"  {len(planned)} group queries one by one: total wall {sum(p[1] for p in per) * 1000:.0f} ms, "
              f"postgres cpu {tot_cpu * 1000:.0f} ms; heaviest:")
        for cpu, wall, name, n in sorted(per, reverse=True)[:5]:
            print(f"      {name:22} cpu {cpu * 1000:6.0f} ms  wall {wall * 1000:6.0f} ms  rows {n}")
        parts = R._vessel_lane_parts(profile)
        if parts:
            await measure("vessel lane (cfr_46 parts, exact cosine)",
                          lambda: R._fetch_vessel_lane(pool, vec, parts, R._VESSEL_LANE_K))
        ids = R._extract_identifiers(q)
        if ids:
            await measure(f"identifier search {[i['value'] for i in ids]}",
                          lambda: R._identifier_search(ids, pool, allowed_jurisdictions=juris, query_vec=vec))
        kws = R._extract_keywords(q)
        syn_added = set()
        if kws:
            kws, smap = expand_keywords(kws)
            syn_added = {s for v in smap.values() for s in v}
            kws, intent = expand_intent(q, kws)
            syn_added |= set(intent or ())
            await measure(f"keyword search, {len(kws)} keywords",
                          lambda: R._broad_keyword_search(kws, pool, synonym_keywords=syn_added,
                                                          allowed_jurisdictions=juris, query_vec=vec))
            scale = await R._keyword_cap_scale(pool)
            for kw in kws:
                cap = round((R._MAX_SYNONYM_FREQ if kw in syn_added else R._MAX_KEYWORD_FREQ) * scale)
                await measure(f"   frequency check '{kw}' (cap {cap})",
                              lambda: pool.fetchval("SELECT count(*) FROM (SELECT 1 FROM regulations WHERE "
                                                    "full_text ILIKE '%' || $1 || '%' LIMIT $2) sub", kw, cap + 1))
    print("\n## plans")
    for kw in ("towing", "flotation", "davit"):
        plan = await pool.fetch("EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM (SELECT 1 FROM regulations "
                                "WHERE full_text ILIKE '%' || $1 || '%' LIMIT 224) sub", kw)
        print(f"  frequency check '{kw}':")
        for r in plan:
            line = r[0].strip()
            if any(w in line for w in ("Scan", "Limit", "Buffers", "Execution", "Rows Removed", "Heap Blocks", "Recheck")):
                print(f"      {line[:150]}")
    await pool.close()


asyncio.run(main())
