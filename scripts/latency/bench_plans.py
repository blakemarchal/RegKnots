"""Which plan do the group queries really run with? (read-only)

asyncpg prepares each statement once per connection; after 5 executions Postgres
may switch the statement to a generic plan. Runs the 23 group queries of one
search on one connection under plan_cache_mode auto / force_custom_plan /
force_generic_plan, with wall time, postgres CPU, rows returned, and the
HNSW-index / seq-scan counters.
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

SQL = """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
              AND source = ANY($3)
              AND jurisdictions && $4::text[]
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """
_CG = None


def pg_cpu() -> float:
    global _CG
    if _CG is None:
        _CG = glob.glob(f"/sys/fs/cgroup/system.slice/docker-{os.environ.get('PG_CID', '')}*.scope/cpu.stat")[0]
    for line in open(_CG):
        if line.startswith("usage_usec"):
            return int(line.split()[1]) / 1e6
    return 0.0


async def counters(pool):
    await asyncio.sleep(1.2)
    return await pool.fetchrow(
        "select (select idx_scan from pg_stat_user_indexes where indexrelname='idx_regulations_embedding') hnsw, "
        "(select seq_scan from pg_stat_user_tables where relname='regulations') seq, "
        "(select sum(idx_scan) from pg_stat_user_indexes where relname='regulations' "
        " and indexrelname <> 'idx_regulations_embedding') other_idx")


async def main():
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    profile = {"vessel_name": "Bench", "vessel_type": "Containership", "flag_state": "United States"}
    q = "how often must lifeboats and rescue boats be inspected and serviced"
    vec = (await R._embed_queries(settings.openai_api_key, [q]))[0]
    juris = list(allowed_jurisdictions(q, profile, None) or [])
    planned = R._plan_groups(await R._get_available_sources(pool), await R._get_source_stats(pool), juris)
    print(f"{len(planned)} groups, jurisdictions {juris}")
    for mode in ("auto", "force_custom_plan", "force_generic_plan"):
        async with pool.acquire() as conn:
            await conn.execute(f"SET plan_cache_mode = {mode}")
            for rnd in range(2):  # round 1 primes the statement cache; round 2 is the steady state
                before = await counters(pool)
                c, t = pg_cpu(), time.perf_counter()
                rows = 0
                empty = 0
                for _, srcs, k in planned:
                    got = await conn.fetch(SQL, vec, k, srcs, juris)
                    rows += len(got)
                    empty += (len(got) < k)
                wall, cpu = time.perf_counter() - t, pg_cpu() - c
                after = await counters(pool)
                print(f"{mode:20} round {rnd + 1}: wall {wall * 1000:6.0f} ms  postgres cpu {cpu * 1000:6.0f} ms  "
                      f"rows {rows:3d} (groups short of k: {empty:2d})  hnsw scans +{after['hnsw'] - before['hnsw']}  "
                      f"seq scans +{after['seq'] - before['seq']}  other index scans +{after['other_idx'] - before['other_idx']}")
            if mode == "force_generic_plan":
                plan = await conn.fetch("EXPLAIN " + SQL, vec, 6, ["nvic", "uscg_cvc", "uscg_towing"], juris)
                print("generic plan:")
                for r in plan:
                    print("    " + r[0][:140])
            await conn.execute("RESET plan_cache_mode")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
