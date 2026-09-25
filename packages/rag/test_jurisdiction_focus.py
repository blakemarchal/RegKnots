"""2026-09-24 (roadmap item 6) — users.jurisdiction_focus scopes retrieval
when the vessel's flag is Unknown (50 of 56 profiles on prod)."""
import asyncio
from uuid import uuid4

import pytest

import rag.engine as engine
from rag.jurisdiction import allowed_jurisdictions, focus_to_jurisdiction
from rag.models import RouteDecision


def test_focus_to_jurisdiction_maps_single_flag_codes_only():
    assert focus_to_jurisdiction("us") == "us"
    assert focus_to_jurisdiction(" UK ") == "uk"
    assert focus_to_jurisdiction("international_mixed") is None
    assert focus_to_jurisdiction("zz") is None
    assert focus_to_jurisdiction("") is None
    assert focus_to_jurisdiction(None) is None


UNKNOWN = {"vessel_type": "Containership", "flag_state": "Unknown"}


def test_focus_fills_in_for_an_unknown_flag():
    assert allowed_jurisdictions("fire drill frequency", UNKNOWN, "us") == {"us", "intl"}
    assert allowed_jurisdictions("fire drill frequency", None, "uk") == {"uk", "intl"}


def test_a_recognized_vessel_flag_always_wins():
    us_flag = {"vessel_type": "Containership", "flag_state": "United States"}
    assert allowed_jurisdictions("fire drill frequency", us_flag, "uk") == {"us", "intl"}


def test_no_single_flag_signal_keeps_the_filter_off():
    assert allowed_jurisdictions("fire drill frequency", UNKNOWN, "international_mixed") is None
    assert allowed_jurisdictions("fire drill frequency", UNKNOWN, None) is None


def test_explicit_query_jurisdiction_still_adds_to_the_focus():
    got = allowed_jurisdictions("What does the MCA require under UK rules?", UNKNOWN, "us")
    assert {"us", "uk", "intl"} <= got


class _Captured(BaseException):
    pass


class _Pool:
    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return None


def test_chat_passes_the_users_focus_to_retrieval(monkeypatch):
    seen = {}

    async def route(query, client):
        return RouteDecision(score=2, model="claude-sonnet-5", is_off_topic=False)

    async def retrieve(**kw):
        seen.update(kw)
        return []

    class _Messages:
        def stream(self, **kw):
            raise _Captured()

    client = type("Client", (), {"messages": _Messages()})()
    monkeypatch.setattr(engine, "route_query", route)
    monkeypatch.setattr(engine, "retrieve_enhanced", retrieve)

    async def run():
        with pytest.raises(_Captured):
            async for _ in engine.chat_with_progress(
                query="fire drill frequency", conversation_history=[], vessel_profile=UNKNOWN,
                pool=_Pool(), anthropic_client=client, openai_api_key="", conversation_id=uuid4(),
                user_jurisdiction_focus="us", query_rewrite_enabled=False, reranker_enabled=False,
            ):
                pass

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert seen["jurisdiction_focus"] == "us"
    assert seen["vessel_profile"] == UNKNOWN          # the profile itself is not rewritten
