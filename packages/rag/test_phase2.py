"""2026-10-08 — answer pipeline phase 2: coverage check and web research."""
import asyncio
from types import SimpleNamespace

import rag.coverage as C
import rag.web_research as W


class _Res:
    def __init__(self, data):
        self.data = data


def test_coverage_parses_and_caps(monkeypatch):
    async def fake(client, **kw):
        assert "LIBRARY TEXT" in kw["messages"][0]["content"]
        return _Res({"coverage": "partial", "missing": [
            {"item": f"fact {i}", "search_query": f"q {i}"} for i in range(5)]})
    monkeypatch.setattr("rag.llm.create_json", fake)
    cov = asyncio.run(C.check_coverage(None, question="q", library_text="text", vessel_line="Containership"))
    assert cov.status == "partial" and [m.item for m in cov.missing] == ["fact 0", "fact 1"]


def test_coverage_full_has_no_missing_and_failure_is_full(monkeypatch):
    async def full(client, **kw):
        return _Res({"coverage": "full", "missing": [{"item": "x", "search_query": "y"}]})
    monkeypatch.setattr("rag.llm.create_json", full)
    assert asyncio.run(C.check_coverage(None, question="q", library_text="t")).missing == []

    async def boom(client, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("rag.llm.create_json", boom)
    cov = asyncio.run(C.check_coverage(None, question="q", library_text="t"))
    assert cov.status == "full" and cov.missing == [] and cov.error == "RuntimeError"


def test_vessel_line():
    assert C.vessel_line({"vessel_type": "Containership", "flag_state": "United States", "gross_tonnage": 74642,
                          "route_types": ["international"]}) == "Containership, United States flag, 74642 GT, international"
    assert C.vessel_line(None) == ""


def _response(json_text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json_text)])


def test_research_keeps_trusted_sources_and_verifies_quotes(monkeypatch):
    payload = ('{"found": true, "answer": "In force 1 January 2028.", "sources": ['
               '{"url": "https://wwwcdn.imo.org/MSC.576(110).pdf", "title": "MSC.576(110)", "publisher": "IMO", '
               '"quote": "shall enter into force on 1 January 2028"},'
               '{"url": "https://randomblog.example.com/post", "title": "blog", "publisher": "x", "quote": "y"}]}')

    async def fake_create(client, **kw):
        assert kw["model"] == W.RESEARCH_MODEL and kw["tools"][0]["type"] == "web_search_20250305"
        return _response(payload)

    async def fake_fetch(url, client):
        return "The amendments shall enter into force on 1 January 2028."
    monkeypatch.setattr("rag.llm.messages_create", fake_create)
    monkeypatch.setattr(W, "fetch_source_text", fake_fetch)
    items = [C.MissingItem("entry into force of MSC.576(110)", "IMO MSC.576(110) entry into force")]
    [f] = asyncio.run(W.research(None, items, question="q"))
    assert f.found and len(f.sources) == 1 and f.sources[0].verified          # the blog is dropped
    assert f.sources[0].label == "Web: wwwcdn.imo.org — MSC.576(110)"
    block = W.format_block([f])
    assert "[Web: wwwcdn.imo.org — MSC.576(110)]" in block and "(verified on the page)" in block
    assert W.sources_payload([f])[0]["url"].endswith("MSC.576(110).pdf")
    assert W.externally_sourced("MSC.576(110)", [f]) and not W.externally_sourced("MSC.999(1)", [f])


def test_research_not_found_timeout_and_errors(monkeypatch):
    async def slow(client, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr("rag.llm.messages_create", slow)
    items = [C.MissingItem("a", "qa")]
    [f] = asyncio.run(W.research(None, items, question="q", budget_s=0.05))
    assert not f.found and f.error == "timeout"
    assert "NOT FOUND on official websites" in W.format_block([f])

    async def broken(client, **kw):
        raise ValueError("bad request")
    monkeypatch.setattr("rag.llm.messages_create", broken)
    [f] = asyncio.run(W.research(None, items, question="q"))
    assert not f.found and f.error.startswith("ValueError")


def test_web_sourced_citations_are_not_unverified():
    from rag.engine import _drop_web_sourced
    f = W.Finding(item="i", search_query="q", found=True, answer="See MSC.576(110) para 3.5.",
                  sources=[W.WebSource(url="https://imo.org/x", title="t", publisher="IMO", domain="imo.org", quote="")])
    assert _drop_web_sourced(["MSC.576(110)", "46 CFR 999.1"], [f]) == ["46 CFR 999.1"]
    assert _drop_web_sourced(["MSC.576(110)"], None) == ["MSC.576(110)"]


def test_engine_carries_the_phase2_flags():
    import inspect

    import rag.engine as E
    for fn in (E.chat, E.chat_with_progress):
        params = inspect.signature(fn).parameters
        assert params["pipeline_v2_enabled"].default is False
        assert "web_research_daily_cap" in params and "web_research_monthly_cap" in params
