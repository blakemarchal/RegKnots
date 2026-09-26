"""2026-09-26 — enrichment from the alias cache only, with no API call.

A plain re-ingest overwrites alias-enriched rows with plain text; this mode
keeps cached aliases on re-ingests that must not spend Anthropic credits."""
import asyncio
import hashlib
import json
import os
import sys
from datetime import date

from ingest import cli
from ingest.enricher import AliasEnricher
from ingest.models import Chunk


def _chunk(section, text):
    return Chunk(source="marpol", title_number=0, section_number=section, section_title="t",
                 chunk_index=0, chunk_text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                 token_count=12, up_to_date_as_of=date(2022, 11, 1))


def test_cache_only_mode_applies_cached_aliases_and_calls_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("REGKNOTS_ENRICH_MODE", "cache")
    cached = _chunk("MARPOL Annex I Reg.14", "[MARPOL Annex I Reg.14] Oil filtering equipment\n\n1 Any ship")
    plain = _chunk("MARPOL Annex I Reg.15", "[MARPOL Annex I Reg.15] Control of discharge of oil\n\n1 Any")
    (tmp_path / "marpol.json").write_text(json.dumps({cached.content_hash: ["oily water separator", "OWS"]}))

    async def no_api(*args, **kwargs):
        raise AssertionError("cache-only mode called the API")

    async def run():
        enricher = AliasEnricher(api_key="test-key", cache_dir=tmp_path)
        monkeypatch.setattr(enricher, "_generate_aliases", no_api)
        monkeypatch.setattr(enricher, "_prefill_cache_via_batch", no_api)
        try:
            return await enricher.enrich_chunks([cached, plain], "marpol")
        finally:
            await enricher.close()

    out = asyncio.run(run())
    assert "[Search terms: oily water separator, OWS]" in out[0].chunk_text
    assert out[0].content_hash != cached.content_hash
    assert out[1] is plain


def test_enrich_cache_only_flag_turns_enrichment_on_in_cache_mode(monkeypatch):
    monkeypatch.setenv("REGKNOTS_ENRICH_MODE", "batch")     # restored after the test
    seen = {}

    async def fake_run(sources, mode, **kwargs):
        seen.update(kwargs, sources=sources, mode=mode)

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["ingest", "--source", "marpol", "--enrich-cache-only", "--no-notify"])
    cli.main()
    assert seen["enrich"] is True and seen["sources"] == ["marpol"]
    assert os.environ["REGKNOTS_ENRICH_MODE"] == "cache"
