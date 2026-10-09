"""2026-09-24 — retrieval fan-out: skip source groups that cannot match the
jurisdiction filter; run group queries with pgvector's iterative HNSW scan.

Correctness contract for the skip: the same rows per group, in SOURCE_GROUPS
order, as the old one-query-per-group code (a skipped group could only return
zero rows). Verified end to end on prod with scripts/eval_retrieval.py.
"""
import asyncio

import rag.retriever as R


def _row(i, sim, source="s"):
    return {"id": i, "source": source, "section_number": f"sec{i}", "section_title": "",
            "full_text": f"text {i}", "similarity": sim}


STATS = {
    "a": (30000, frozenset({"us"})),
    "b": (900, frozenset({"intl"})),
    "c": (1200, frozenset({"au"})),
    "d": (1500, frozenset({"au"})),
    "e": (1000, frozenset({"us", "au"})),
    "f": (40, frozenset()),                       # untagged rows never match a filter
}
GROUPS = {"big": ("a",), "small": ("b",), "foreign": ("c",), "mixed": ("d", "e"), "untagged": ("f",)}


def test_plan_groups_skips_sources_that_cannot_match(monkeypatch):
    monkeypatch.setattr(R, "SOURCE_GROUPS", GROUPS)
    monkeypatch.setattr(R, "_CANDIDATES_PER_GROUP", {"big": 12})
    active = R._plan_groups(set(STATS), STATS, ["us", "intl"])
    assert active == [("big", ["a"], 12), ("small", ["b"], 6), ("mixed", ["e"], 6)]
    # no jurisdiction filter: nothing is skipped
    active = R._plan_groups(set(STATS), STATS, None)
    assert [g[0] for g in active] == ["big", "small", "foreign", "mixed", "untagged"]
    assert active[3] == ("mixed", ["d", "e"], 6)
    # sources not yet ingested are ignored, as before
    assert [g[0] for g in R._plan_groups({"a"}, STATS, None)] == ["big"]


class _Tx:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        self.log.append("BEGIN")

    async def __aexit__(self, *exc):
        self.log.append("COMMIT")
        return False


class _Conn:
    def __init__(self, log, rows):
        self.log, self.rows = log, rows

    def transaction(self):
        return _Tx(self.log)

    async def execute(self, sql):
        self.log.append(sql)

    async def fetch(self, sql, *params):
        self.log.append("FETCH")
        return self.rows


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _TxPool:
    def __init__(self, rows):
        self.log = []
        self.conn = _Conn(self.log, rows)

    def acquire(self):
        return _Acquire(self.conn)


def test_iterative_scan_is_set_locally_and_rows_come_back_sorted():
    pool = _TxPool([_row(1, 0.4), _row(2, 0.8), _row(3, 0.6)])      # relaxed order
    out = asyncio.run(R._fetch_iterative(pool, "SELECT 1", "[0.1]"))
    assert pool.log[0] == "BEGIN" and pool.log[-2:] == ["FETCH", "COMMIT"]
    setting = pool.log[1]
    assert setting.startswith("SET LOCAL hnsw.iterative_scan = relaxed_order")
    assert "SET LOCAL hnsw.max_scan_tuples" in setting        # bounded for sparse groups
    assert [c["id"] for c in out] == [2, 3, 1]


class _AnyPool:
    """Answers the keyword / identifier lookups retrieve() makes with no rows."""

    async def fetch(self, *a, **k):
        return []

    async def fetchval(self, *a, **k):
        return 0            # keyword-frequency probes expect a count


def test_retrieve_queries_only_groups_that_can_match(monkeypatch):
    monkeypatch.setattr(R, "SOURCE_GROUPS", GROUPS)
    monkeypatch.setattr(R, "_CANDIDATES_PER_GROUP", {"big": 12})

    embedded = []

    async def embed_many(key, queries):
        embedded.append(list(queries))
        return ["[0.1]", "[0.2]"][:len(queries)]

    async def available(pool):
        return set(STATS)

    async def stats(pool):
        return STATS

    calls = []

    async def fake_group(pool, vec, sources, k, juris):
        calls.append((tuple(sources), k, tuple(sorted(juris or []))))
        return [_row(len(calls) * 10, 0.7 - 0.01 * len(calls), source=sources[0])]

    lane_calls = []

    async def fake_lane(pool, vec, parts, k):
        lane_calls.append((vec, parts, k))
        # row 10 is also the first group's row: it keeps the higher similarity
        return [_row(10, 0.95, source="a"), _row(99, 0.5, source="cfr_46")]

    monkeypatch.setattr(R, "_embed_queries", embed_many)
    monkeypatch.setattr(R, "_get_available_sources", available)
    monkeypatch.setattr(R, "_get_source_stats", stats)
    monkeypatch.setattr(R, "_fetch_group", fake_group)
    monkeypatch.setattr(R, "_fetch_vessel_lane", fake_lane)
    profile = {"vessel_type": "Containership", "flag_state": "United States"}
    out = asyncio.run(R.retrieve("fire drill frequency on my vessel", _AnyPool(), "key",
                                 vessel_profile=profile, limit=8))
    assert [c[0] for c in calls] == [("a",), ("b",), ("e",)]        # foreign + untagged skipped
    assert all(c[2] == ("intl", "us") for c in calls)
    assert {10, 20, 30, 99} <= {c["id"] for c in out}
    # one embedding call for the question and its vessel phrasing
    assert embedded == [["fire drill frequency on my vessel", "fire drill frequency on my containership"]]
    assert lane_calls == [("[0.2]", R._vessel_lane_parts(profile), R._VESSEL_LANE_K)]
    assert [c["similarity"] for c in out if c["id"] == 10] == [0.95]
    assert sum(1 for c in out if c["id"] == 10) == 1
    # no "my vessel": the lane searches with the question's own embedding
    embedded.clear(), lane_calls.clear()
    asyncio.run(R.retrieve("fire drill frequency", _AnyPool(), "key", vessel_profile=profile))
    assert embedded == [["fire drill frequency"]]
    assert lane_calls == [("[0.1]", R._vessel_lane_parts(profile), R._VESSEL_LANE_K)]


def test_no_vessel_lane_without_a_mapped_type_or_us_scope(monkeypatch):
    monkeypatch.setattr(R, "SOURCE_GROUPS", {"big": ("a",)})
    embedded = []

    async def embed_many(key, queries):
        embedded.append(list(queries))
        return ["[0.1]"]

    async def available(pool):
        return {"a"}

    async def stats(pool):
        return {"a": (100, frozenset({"us", "uk"}))}

    async def fake_group(pool, vec, sources, k, juris):
        return [_row(1, 0.7, source="a")]

    async def fake_lane(*a):
        raise AssertionError("no lane expected")

    monkeypatch.setattr(R, "_embed_queries", embed_many)
    monkeypatch.setattr(R, "_get_available_sources", available)
    monkeypatch.setattr(R, "_get_source_stats", stats)
    monkeypatch.setattr(R, "_fetch_group", fake_group)
    monkeypatch.setattr(R, "_fetch_vessel_lane", fake_lane)
    for profile in (None, {"vessel_type": "Other"},
                    {"vessel_type": "Towing / Tugboat", "flag_state": "United Kingdom"}):
        asyncio.run(R.retrieve("fire drill frequency", _AnyPool(), "key", vessel_profile=profile))
    assert embedded == [["fire drill frequency"]] * 3


def test_vessel_context_query():
    tow = {"vessel_type": "Towing / Tugboat"}
    assert (R._vessel_context_query("Do I need a fixed CO2 system on my vessel?", tow)
            == "Do I need a fixed CO2 system on my towing vessel?")
    assert (R._vessel_context_query("Is our boat's EPIRB due for service?", tow)
            == "Is our towing vessel's EPIRB due for service?")
    assert R._vessel_context_query("What does our TSMS have to include?", tow) is None
    # another vessel is not the user's own
    assert R._vessel_context_query("Who gives way to the vessel on my starboard side?", tow) is None
    assert R._vessel_context_query("anything on my vessel", {"vessel_type": "Other"}) is None
    assert R._vessel_context_query("anything", None) is None


def test_vessel_lane_parts_and_pattern():
    tow = R._vessel_lane_parts({"vessel_type": "Towing / Tugboat"})
    assert tow == ["27", "136", "137", "138", "139", "140", "141", "142", "143", "144"]
    assert R._vessel_lane_parts({"vessel_type": "Other"}) is None
    assert R._vessel_lane_parts({}) is None

    class _Capture:
        async def fetch(self, sql, *params):
            self.sql, self.params = sql, params
            return [{"id": 1, "similarity": 0.5}]

    pool = _Capture()
    out = asyncio.run(R._fetch_vessel_lane(pool, "[0.1]", tow, 8))
    assert out == [{"id": 1, "similarity": 0.5}]
    assert "MATERIALIZED" in pool.sql and pool.params[0] == "[0.1]" and pool.params[2] == 8
    import re
    pat = re.compile(pool.params[1])
    assert pat.search("46 CFR 142.315") and pat.search("46 CFR 27.303") and pat.search("46 CFR 138.220")
    assert not pat.search("46 CFR 95.05-10") and not pat.search("46 CFR 270.1")
    assert not pat.search("33 CFR 138.40")


def test_reformulations_start_before_the_primary_finishes(monkeypatch):
    """2026-09-25 — the primary waits here until a reformulation retrieval has
    started; with the old ordering (reformulations after the primary) it times out."""
    from types import SimpleNamespace

    import rag.query_rewrite as QR

    async def run():
        extra_started = asyncio.Event()

        async def fake_retrieve(query, pool, openai_api_key, vessel_profile=None, limit=8,
                                sources=None, jurisdiction_focus=None):
            if query == "orig":
                await asyncio.wait_for(extra_started.wait(), 2)
                return [_row("p", 0.9)]
            extra_started.set()
            return [_row(query, 0.5)]

        async def fake_rewrite(query, anthropic_client):
            return SimpleNamespace(reformulations=["r1", "r2"])

        monkeypatch.setattr(R, "retrieve", fake_retrieve)
        monkeypatch.setattr(QR, "rewrite_query", fake_rewrite)
        return await R.retrieve_enhanced("orig", None, "key", anthropic_client=object(),
                                         query_rewrite_enabled=True, reranker_enabled=False)

    out = asyncio.run(run())
    assert {c["id"] for c in out} == {"p", "r1", "r2"}


class _PlainPool:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, sql, *params):
        self.calls.append(sql)
        return self.rows

    def acquire(self):
        raise AssertionError("group queries must not open a transaction")


def test_group_queries_are_plain_fetches():
    """2026-09-25 — the iterative scan is off for the group fan-out (harness: -0.027 MRR)."""
    assert R._GROUP_ITERATIVE_SCAN is False
    pool = _PlainPool([_row(1, 0.8), _row(2, 0.6)])
    out = asyncio.run(R._fetch_group(pool, "[0.1]", ["a"], 6, ["us"]))
    assert [c["id"] for c in out] == [1, 2] and len(pool.calls) == 1


def test_vessel_filter_applies_to_title_46_only():
    """2026-09-25 — the forbidden part lists are 46 CFR subchapters; 33/49 CFR
    parts that share a number (COFR 33 CFR 138, hazmat-by-vessel 49 CFR 176,
    safety zones 33 CFR 165) were being dropped for every mapped vessel type."""
    def c(sec, source):
        return {"id": sec, "source": source, "section_number": sec}
    chunks = [c("46 CFR 34.01-1", "cfr_46"), c("46 CFR 199.180", "cfr_46"), c("46 CFR 95.10-1", "cfr_46"),
              c("33 CFR 138.20", "cfr_33"), c("33 CFR 165.1", "cfr_33"), c("33 CFR 83.22", "cfr_33"),
              c("49 CFR 176.83", "cfr_49"), c("SOLAS Ch.III Reg.20", "solas")]
    kept = R._filter_by_vessel_applicability(chunks, {"vessel_type": "Containership"})
    assert [k["id"] for k in kept] == [k["id"] for k in chunks if k["id"] != "46 CFR 34.01-1"]


def test_no_route_boost():
    """2026-10-09 — routes don't boost: prod (route_types) never had it, and
    the harnesses' route_type read measured worse. Both keys rank alike."""
    def chunks():
        return [{"id": "a", "source": "x", "full_text": "Inland waters rule", "similarity": 0.5},
                {"id": "b", "source": "x", "full_text": "Ocean rule", "similarity": 0.5}]

    def score(profile):
        return {c["id"]: round(c["_score"], 3) for c in R._rerank(chunks(), "q", profile)}

    for profile in ({"route_types": ["inland"]}, {"route_type": "inland"}, {}):
        assert score(profile) == {"a": 0.5, "b": 0.5}
    # the cargo and vessel-type terms still apply
    assert score({"vessel_type": "Towing / Tugboat", "cargo_types": ["ocean"]})["b"] == 0.55


def test_towing_keeps_all_of_subchapter_m():
    """2026-10-09 — 46 CFR 136-139 (certification, compliance, TSMS, TPOs) are
    Subchapter M; the towing map had them forbidden. OSVs (Subchapter L,
    Parts 125-134) now drop them."""
    def c(sec):
        return {"id": sec, "source": "cfr_46", "section_number": sec}
    sub_m = [c(f"46 CFR {p}.100") for p in range(136, 145)]
    other = [c("46 CFR 95.05-10"), c("46 CFR 125.100")]
    kept = R._filter_by_vessel_applicability(sub_m + other, {"vessel_type": "Towing / Tugboat"})
    assert [k["id"] for k in kept] == [k["id"] for k in sub_m]
    kept = R._filter_by_vessel_applicability(sub_m + other, {"vessel_type": "OSV / Offshore Support"})
    assert [k["id"] for k in kept] == ["46 CFR 125.100"]
    for mapping in R._VESSEL_TYPE_CFR_APPLICABILITY.values():
        assert not mapping["applicable"] & mapping["forbidden"]
