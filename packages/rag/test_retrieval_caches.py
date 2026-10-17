"""2026-10-17 — latency audit fixes that must not change results: the keyword
lane's per-process caches and the shared OpenAI embedding client."""
import asyncio

from rag import retriever as R


class _CountingPool:
    def __init__(self, freq=3):
        self.freq = freq
        self.fetchval_calls = 0
        self.fetch_calls = []

    async def fetchval(self, sql, *args):
        self.fetchval_calls += 1
        await asyncio.sleep(0.01)          # long enough for concurrent searches to overlap
        return self.freq

    async def fetch(self, sql, *args):
        self.fetch_calls.append(sql)
        await asyncio.sleep(0.01)
        if "DISTINCT ON" in sql:
            return [{"id": 7}, {"id": 9}]
        return [{"id": i, "source": "cfr_46", "section_number": f"46 CFR {i}", "section_title": "t",
                 "full_text": "x", "similarity": 0.5} for i in args[0]][::-1]   # any order back


def _reset():
    R._KW_FREQ_CACHE.clear()
    R._KW_PICK_CACHE.clear()
    R._KW_INFLIGHT.clear()


def test_four_concurrent_searches_share_one_lookup_per_keyword():
    _reset()
    pool = _CountingPool()

    async def run():
        return await asyncio.gather(*[
            R._broad_keyword_search(["davit", "Davit"], pool, allowed_jurisdictions=["us", "intl"],
                                    query_vec="[0.1]")
            for _ in range(4)])

    results = asyncio.run(run())
    assert pool.fetchval_calls == 1                                   # one frequency check, any case
    assert sum("DISTINCT ON" in s for s in pool.fetch_calls) == 1     # one pick
    for rows, passed in results:
        assert [r["id"] for r in rows] == [7, 9]                      # the pick's order is kept
        assert passed == ["davit", "Davit"]


def test_a_common_word_is_skipped_from_the_cache_too():
    _reset()
    pool = _CountingPool(freq=10_000)
    for _ in range(3):
        rows, passed = asyncio.run(R._broad_keyword_search(["towing"], pool))
        assert rows == [] and passed == []
    assert pool.fetchval_calls == 1 and pool.fetch_calls == []


def test_the_cache_expires(monkeypatch):
    _reset()
    pool = _CountingPool()
    asyncio.run(R._broad_keyword_search(["davit"], pool))
    monkeypatch.setattr(R, "_KW_CACHE_TTL_S", -1.0)
    asyncio.run(R._broad_keyword_search(["davit"], pool))
    assert pool.fetchval_calls == 2


def test_a_failed_lookup_is_not_cached():
    _reset()

    class Broken(_CountingPool):
        async def fetchval(self, sql, *args):
            self.fetchval_calls += 1
            raise RuntimeError("db down")

    pool = Broken()
    for _ in range(2):
        try:
            asyncio.run(R._broad_keyword_search(["davit"], pool))
        except RuntimeError:
            pass
    assert pool.fetchval_calls == 2 and R._KW_FREQ_CACHE == {}


def test_embedding_client_is_reused_within_a_loop_and_not_across_loops():
    async def two():
        return R._openai_client("sk-test"), R._openai_client("sk-test"), len(R._OAI_CLIENTS)

    a1, a2, _ = asyncio.run(two())
    b1, _, entries = asyncio.run(two())
    assert a1 is a2 and b1 is not a1
    assert entries == 1          # the first (closed) loop's client was dropped


class _SidePool:
    def __init__(self, side, main, fail=False):
        self.side, self.main, self.fail, self.calls = side, main, fail, []

    async def fetchrow(self, sql, *args):
        if self.fail:
            raise RuntimeError('relation "regulation_vectors" does not exist')
        return {"side": self.side, "main": self.main}

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []


def test_group_queries_read_the_side_table_only_when_it_is_complete(monkeypatch):
    monkeypatch.setattr(R, "_SIDE_TABLE_READY", None)
    pool = _SidePool(111, 111)
    asyncio.run(R._fetch_group(pool, "[0.1]", ["nvic"], 6, ["us"]))
    sql, args = pool.calls[-1]
    assert "FROM regulation_vectors" in sql and "jurisdictions && $4::text[]" in sql
    assert args == ("[0.1]", 6, ["nvic"], ["us"])

    # No jurisdiction filter: the old query, whose cached plan uses the HNSW index (fast, and
    # the results the harness measured); the exact side table there lowered MRR.
    pool = _SidePool(111, 111)
    asyncio.run(R._fetch_group(pool, "[0.1]", ["nvic"], 6, None))
    sql, args = pool.calls[-1]
    assert "regulation_vectors" not in sql and "FROM regulations" in sql and args == ("[0.1]", 6, ["nvic"])

    for short in (_SidePool(5, 111), _SidePool(0, 0, fail=True)):      # incomplete, or no table
        monkeypatch.setattr(R, "_SIDE_TABLE_READY", None)
        asyncio.run(R._fetch_group(short, "[0.1]", ["nvic"], 6, ["us"]))
        assert "regulation_vectors" not in short.calls[-1][0] and "FROM regulations" in short.calls[-1][0]
        assert R._SIDE_TABLE_READY is False
