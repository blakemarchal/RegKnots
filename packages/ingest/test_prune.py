"""2026-09-25 — pruning rows a re-parse no longer produces, and the cfr_49 part scope."""
import asyncio
from types import SimpleNamespace

import pytest

from ingest import cfr_scope, prune


def _chunk(sec, idx):
    return SimpleNamespace(section_number=sec, chunk_index=idx)


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        return self.rows


def _row(sec, idx, created="2026-05-24"):
    return {"id": f"{sec}#{idx}", "section_number": sec, "chunk_index": idx, "created": created}


def test_produced_keys_reports_duplicates():
    keys, dups = prune.produced_keys([_chunk("A", 0), _chunk("A", 1), _chunk("B", 0), _chunk("A", 0)])
    assert keys == {("A", 0), ("A", 1), ("B", 0)}
    assert dups == [("A", 0)]


def test_report_lists_stale_rows_and_is_safe():
    stored = [_row("SOLAS Ch.III Reg.20", 0), _row("SOLAS Ch.III Reg.20", 1),
              _row("SOLAS Ch.III Part B", 0, "2026-04-03"),           # renamed away
              _row("SOLAS Ch.III Reg.20", 2, "2026-04-13")]           # stale tail
    chunks = [_chunk("SOLAS Ch.III Reg.20", 0), _chunk("SOLAS Ch.III Reg.20", 1)]
    report = asyncio.run(prune.build_report(_Pool(stored), "solas", chunks))
    assert report.produced == 2 and report.stored == 4 and report.safe
    assert sorted((r["section_number"], r["chunk_index"]) for r in report.stale) == [
        ("SOLAS Ch.III Part B", 0), ("SOLAS Ch.III Reg.20", 2)]
    assert "2 stored rows not produced" in report.summary_lines()[0]


def test_prune_is_refused_when_a_produced_key_is_not_stored():
    # e.g. update mode skipped a chunk whose text moved to a new key
    stored = [_row("A", 0), _row("OLD", 0)]
    report = asyncio.run(prune.build_report(_Pool(stored), "s", [_chunk("A", 0), _chunk("NEW", 0)]))
    assert not report.safe and report.missing == [("NEW", 0)]
    with pytest.raises(prune.PruneRefused, match="not stored"):
        asyncio.run(prune.apply_prune(_Pool(stored), report))


def test_prune_is_refused_on_duplicate_keys_or_an_empty_parse():
    stored = [_row("A", 0)]
    dup = asyncio.run(prune.build_report(_Pool(stored), "s", [_chunk("A", 0), _chunk("A", 0)]))
    assert "duplicate keys" in dup.refusal()
    empty = asyncio.run(prune.build_report(_Pool(stored), "s", []))
    assert "no chunks" in empty.refusal()


def test_prune_step_skips_a_run_with_chunk_errors():
    printed = []
    console = SimpleNamespace(print=lambda *a, **k: printed.append(a[0]))
    result = SimpleNamespace(errors=1, error_details=[], pruned=0)
    asyncio.run(prune.run_prune_step(_Pool([]), "s", [], "apply", result, console))
    assert "prune skipped" in printed[0] and result.pruned == 0


@pytest.mark.parametrize("section,expected", [
    ("49 CFR 176.83", True),        # carriage by vessel
    ("49 CFR 172.101", True),
    ("49 CFR 40.85", True),         # drug testing
    ("49 CFR 1572.103", True),      # TWIC
    ("49 CFR 391.41", False),       # FMCSA driver medical
    ("49 CFR 229.125", False),      # locomotive safety
    ("49 CFR 192.3", False),        # pipelines
    ("49 CFR 1244.3", False),       # STB
])
def test_cfr_49_scope(section, expected):
    assert cfr_scope.in_scope("cfr_49", section) is expected


def test_other_sources_are_unscoped():
    assert cfr_scope.in_scope("cfr_46", "46 CFR 199.180")
    assert cfr_scope.in_scope("cfr_33", "33 CFR 165.1")
    secs = [SimpleNamespace(section_number=s) for s in ("49 CFR 176.83", "49 CFR 391.41")]
    assert [s.section_number for s in cfr_scope.scope_sections("cfr_49", secs)] == ["49 CFR 176.83"]


def test_a_scoped_report_keeps_rows_of_documents_the_parse_did_not_produce():
    """2026-09-27 — nvic: OCR'd NVICs, NVIC 04-08 Ch-2 or an NVIC that left the
    USCG index are not in a --nvic run (or failed to parse); their rows stay."""
    from ingest.sources import nvic
    stored = [_row("NVIC 06-72 §4", 0), _row("NVIC 06-72 §4", 5),        # stale tail
              _row("NVIC 07-68 §1", 0), _row("NVIC 04-08 Ch-2 §1", 0), _row("odd name", 0)]
    chunks = [_chunk("NVIC 06-72 §4", 0), _chunk("NVIC 06-72 Encl.1", 0)]
    report = asyncio.run(prune.build_report(_Pool(stored), "nvic", chunks, nvic.prune_scope))
    assert [(r["section_number"], r["chunk_index"]) for r in report.stale] == [("NVIC 06-72 §4", 5)]
    assert report.kept_out_of_scope == {"NVIC 07-68": 1, "NVIC 04-08 Ch-2": 1, "odd name": 1}
    assert report.missing == [("NVIC 06-72 Encl.1", 0)]
    assert "3 rows of documents this parse did not produce kept" in report.summary_lines()[0]
    unscoped = asyncio.run(prune.build_report(_Pool(stored), "nvic", chunks))
    assert len(unscoped.stale) == 4


def test_report_counts_produced_keys_stored_with_other_text():
    stored = [dict(_row("A", 0), content_hash="h1"), dict(_row("A", 1), content_hash="old")]
    chunks = [SimpleNamespace(section_number="A", chunk_index=0, content_hash="h1"),
              SimpleNamespace(section_number="A", chunk_index=1, content_hash="h2")]
    report = asyncio.run(prune.build_report(_Pool(stored), "s", chunks))
    assert report.changed == 1 and "1 stored with other text" in report.summary_lines()[0]


def test_manual_rows_are_never_stale():
    stored = [_row("IMDG 3.2 UN 3480 (manual)", 0, "2026-05-01"), _row("IMDG 3.2", 0), _row("OLD", 0)]
    report = asyncio.run(prune.build_report(_Pool(stored), "imdg", [_chunk("IMDG 3.2", 0)]))
    assert [r["section_number"] for r in report.stale] == ["OLD"]
    assert report.kept_manual == 1 and "1 manual rows kept" in report.summary_lines()[0]


def test_imo_code_configs_resolve_to_the_rows_source():
    """2026-09-26 — the CLI used f"imo_{code}" as the pipeline source; for four
    codes that is not where the adapter writes, so bookkeeping saw no rows."""
    from ingest import cli
    from ingest.sources import imo_codes
    for key, cfg in cli._PDF_SOURCE_CONFIG.items():
        if "imo_code" in cfg:
            assert imo_codes._CODE_TO_SOURCE.get(cfg["imo_code"], key) == key, key
