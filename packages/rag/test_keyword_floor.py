"""2026-09-30 — keyword hits take the synthetic first-place score only near
the best vector hit (retriever._KW_BOOST_MAX_GAP)."""
import asyncio

from rag import retriever as R


def test_merge_sim_keeps_a_distant_hits_own_similarity():
    assert R._merge_sim({"similarity": 0.56}, 0.60, floor=0.48) == 0.60   # near: synthetic
    assert R._merge_sim({"similarity": 0.31}, 0.60, floor=0.48) == 0.31   # far: its own
    assert R._merge_sim({"similarity": 0.0}, 0.65, floor=None) == 0.65    # identifiers: no floor


def test_keyword_search_scores_rows_by_the_query_vector():
    calls = []

    class Pool:
        async def fetchval(self, sql, *args):
            return 3                                   # under the frequency cap

        async def fetch(self, sql, *args):
            calls.append((sql, args))
            return [{"id": 1, "source": "nvic", "section_number": "NVIC 01-95 §6",
                     "section_title": "t", "full_text": "wanted", "similarity": 0.31}]

    rows, passed = asyncio.run(R._broad_keyword_search(["wanted"], Pool(), query_vec="[0.1,0.2]"))
    sql, args = calls[0]
    assert "embedding <=> $3::vector" in sql and args[-1] == "[0.1,0.2]"
    assert passed == ["wanted"] and rows[0]["similarity"] == 0.31

    calls.clear()
    asyncio.run(R._broad_keyword_search(["wanted"], Pool(), allowed_jurisdictions=["us"], query_vec="[0.1]"))
    sql, args = calls[0]
    assert "embedding <=> $4::vector" in sql and args[2] == ["us"] and args[3] == "[0.1]"

    calls.clear()
    asyncio.run(R._broad_keyword_search(["wanted"], Pool()))     # no vector: the old 0.0
    assert "0.0 AS similarity" in calls[0][0] and len(calls[0][1]) == 2
