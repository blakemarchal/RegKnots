"""Retrieval latency bench on the prod box (read-only; OpenAI embeddings only, no Claude).

Reproduces retrieve_enhanced's DB fan-out (primary + 3 reformulations, concurrently)
with the API's pool shape, and measures wall time, per-group query time, and CPU:
host us/sy/st/idle over each scenario and CPU-seconds burned by the postgres container.
Run from /opt/RegKnots/apps/api with the api venv's python.
"""
import asyncio
import glob
import json
import os
import resource
import statistics
import sys
import time

import asyncpg

sys.path.insert(0, "/opt/RegKnots/apps/api")
from app.config import settings  # noqa: E402
from rag import retriever as R  # noqa: E402

import logging  # noqa: E402
logging.basicConfig(level=logging.WARNING)

TOW = {"vessel_name": "Bench", "vessel_type": "Towing / Tugboat", "flag_state": "United States"}
BOX = {"vessel_name": "Bench", "vessel_type": "Containership", "flag_state": "United States"}
SETS = {
    "towboat (10-16 free question)": (TOW, [
        "life saving device requirements for a 7-person crew on a US-flag towing vessel",
        "46 CFR 28 lifesaving equipment fishing and towing vessel manning",
        "personal flotation device carriage requirements uninspected towing vessel",
        "lifesaving appliance requirements towing vessel 46 CFR 137 crew capacity",
    ]),
    "containership (SOLAS III/20)": (BOX, [
        "how often must lifeboats and rescue boats be inspected and serviced",
        "SOLAS Chapter III Regulation 20 operational readiness maintenance and inspections",
        "weekly and monthly inspection of survival craft launching appliances",
        "annual thorough examination of lifeboat release gear and davits",
    ]),
}

_PG_CPU = None


def pg_cpu_usec() -> int:
    global _PG_CPU
    if _PG_CPU is None:
        cid = os.environ.get("PG_CID", "")
        hits = glob.glob(f"/sys/fs/cgroup/system.slice/docker-{cid}*.scope/cpu.stat")
        _PG_CPU = hits[0] if hits else ""
    if not _PG_CPU:
        return 0
    for line in open(_PG_CPU):
        if line.startswith("usage_usec"):
            return int(line.split()[1])
    return 0


def host_cpu() -> list[int]:
    return [int(x) for x in open("/proc/stat").readline().split()[1:9]]


def self_cpu() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


class Meter:
    def __enter__(self):
        self.t, self.h, self.p, self.s = time.perf_counter(), host_cpu(), pg_cpu_usec(), self_cpu()
        return self

    def __exit__(self, *a):
        self.wall = time.perf_counter() - self.t
        h2 = host_cpu()
        d = [b - a for a, b in zip(self.h, h2)]
        tot = sum(d) or 1
        user, nice, system, idle, iowait, irq, softirq, steal = d
        self.host = {"us": round(100 * (user + nice) / tot), "sy": round(100 * (system + irq + softirq) / tot),
                     "id": round(100 * idle / tot), "wa": round(100 * iowait / tot), "st": round(100 * steal / tot)}
        self.pg_cpu = (pg_cpu_usec() - self.p) / 1e6
        self.py_cpu = self_cpu() - self.s


GROUP_T: list[tuple[str, float, int]] = []
_orig_fetch_group = R._fetch_group
_orig_lane = R._fetch_vessel_lane
_orig_kw = R._broad_keyword_search
_orig_id = R._identifier_search


GROUP_ARGS: dict[str, tuple] = {}


async def timed_fetch_group(pool, vec, sources, k, juris=None):
    t = time.perf_counter()
    rows = await _orig_fetch_group(pool, vec, sources, k, juris)
    name = "group:" + ",".join(sources)[:60]
    GROUP_ARGS[name] = (vec, list(sources), k, juris)
    GROUP_T.append((name, time.perf_counter() - t, len(rows)))
    return rows


async def timed_lane(pool, vec, parts, k):
    t = time.perf_counter()
    rows = await _orig_lane(pool, vec, parts, k)
    GROUP_T.append(("vessel_lane", time.perf_counter() - t, len(rows)))
    return rows


async def timed_kw(*a, **kw):
    t = time.perf_counter()
    rows = await _orig_kw(*a, **kw)
    GROUP_T.append(("keyword_search", time.perf_counter() - t, len(rows)))
    return rows


async def timed_id(*a, **kw):
    t = time.perf_counter()
    rows = await _orig_id(*a, **kw)
    GROUP_T.append(("identifier_search", time.perf_counter() - t, len(rows)))
    return rows


R._fetch_group = timed_fetch_group
R._fetch_vessel_lane = timed_lane
R._broad_keyword_search = timed_kw
R._identifier_search = timed_id

VEC: dict[str, str] = {}
_orig_embed_queries = R._embed_queries


async def cached_embed_queries(key, queries):
    missing = [q for q in queries if q not in VEC]
    if missing:
        for q, v in zip(missing, await _orig_embed_queries(key, missing)):
            VEC[q] = v
    return [VEC[q] for q in queries]


R._embed_queries = cached_embed_queries


async def one(pool, q, profile, limit):
    t = time.perf_counter()
    rows = await R.retrieve(query=q, pool=pool, openai_api_key=settings.openai_api_key,
                            vessel_profile=profile, limit=limit)
    return time.perf_counter() - t, len(rows)


async def fanout(pool, qs, profile):
    """retrieve_enhanced's shape: primary at the wide pool (30) + 3 reformulations at 8, concurrently."""
    return await asyncio.gather(one(pool, qs[0], profile, 30), *[one(pool, q, profile, 8) for q in qs[1:]])


def fmt(m: Meter) -> str:
    return (f"wall {m.wall:5.2f}s | host us {m.host['us']}% sy {m.host['sy']}% st {m.host['st']}% "
            f"id {m.host['id']}% wa {m.host['wa']}% | postgres cpu {m.pg_cpu:5.2f}s "
            f"({m.pg_cpu / max(m.wall, 1e-6):.2f} cores) | bench-python cpu {m.py_cpu:4.2f}s")


async def main():
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    out = {}
    # Embedding latency (OpenAI), as prod does it: a new client per call.
    emb = []
    for q in ["lifeboat davit inspection interval", "towing vessel fire extinguisher count",
              "ballast water record book retention"]:
        t = time.perf_counter()
        await _orig_embed_queries(settings.openai_api_key, [q])
        emb.append(time.perf_counter() - t)
    print("embedding call (shared client):", [round(x, 2) for x in emb])
    for name, (profile, qs) in SETS.items():
        await cached_embed_queries(settings.openai_api_key, qs)
    pool10 = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    # warm caches (source stats, available sources, buffers)
    for name, (profile, qs) in SETS.items():
        await fanout(pool10, qs, profile)

    for name, (profile, qs) in SETS.items():
        print(f"\n## {name}")
        # A. each retrieve() alone
        GROUP_T.clear()
        alone = []
        with Meter() as m:
            for q in qs:
                alone.append((await one(pool10, q, profile, 8))[0])
        print(f"A. one at a time (4 calls): per call {[round(x, 2) for x in alone]} | {fmt(m)}")
        per_group = sorted(GROUP_T, key=lambda x: -x[1])
        n_groups = len([g for g in GROUP_T if g[0].startswith('group:')]) / 4
        print(f"   ~{n_groups:.0f} group queries per call; slowest single queries (one call at a time, pool 10):")
        agg: dict[str, list[float]] = {}
        for g, t, n in GROUP_T:
            agg.setdefault(g, []).append(t)
        for g, ts in sorted(agg.items(), key=lambda kv: -statistics.mean(kv[1]))[:8]:
            print(f"     {statistics.mean(ts) * 1000:7.0f} ms  {g}")
        tot_q = sum(t for _, t, _ in GROUP_T)
        print(f"   sum of all query times {tot_q:.2f}s over {len(GROUP_T)} queries")
        slow = [g for g, _ in sorted(agg.items(), key=lambda kv: -statistics.mean(kv[1])) if g in GROUP_ARGS][:3]
        for g in slow:
            vec, srcs, k, juris = GROUP_ARGS[g]
            sql = ("EXPLAIN (ANALYZE, BUFFERS) SELECT id, source, section_number, section_title, full_text, "
                   "1 - (embedding <=> $1::vector) AS similarity FROM regulations WHERE embedding IS NOT NULL "
                   "AND source = ANY($3) " + ("AND jurisdictions && $4::text[] " if juris is not None else "") +
                   "ORDER BY embedding <=> $1::vector LIMIT $2")
            args = [vec, k, srcs] + ([juris] if juris is not None else [])
            plan = [r[0] for r in await pool10.fetch(sql, *args)]
            keep = [p.strip() for p in plan if any(w in p for w in ("Scan", "Sort", "Limit", "Buffers", "Execution", "Rows Removed", "Heap Blocks"))]
            print(f"   EXPLAIN {g}  k={k}:")
            for p in keep[:9]:
                print(f"       {p[:150]}")
        # B. the prod fan-out: 4 concurrent, pool 10
        for rnd in range(3):
            GROUP_T.clear()
            with Meter() as m:
                res = await fanout(pool10, qs, profile)
            print(f"B{rnd + 1}. 4 concurrent, pool 10: calls {[round(r[0], 2) for r in res]} | {fmt(m)}")
        # C. same with pool 20
        pool20 = await asyncpg.create_pool(dsn, min_size=2, max_size=20)
        await fanout(pool20, qs, profile)
        for rnd in range(2):
            with Meter() as m:
                res = await fanout(pool20, qs, profile)
            print(f"C{rnd + 1}. 4 concurrent, pool 20: calls {[round(r[0], 2) for r in res]} | {fmt(m)}")
        await pool20.close()
        # D. primary only (what the fan-out would cost without reformulations)
        with Meter() as m:
            r = await one(pool10, qs[0], profile, 30)
        print(f"D. primary alone (no reformulations): {r[0]:.2f}s | {fmt(m)}")
    await pool10.close()


if __name__ == "__main__":
    asyncio.run(main())
