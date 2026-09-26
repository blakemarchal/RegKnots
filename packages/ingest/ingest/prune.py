"""Remove rows a source's current parse no longer produces (2026-09-25).

store.upsert_chunks is ON CONFLICT (source, section_number, chunk_index) DO
UPDATE, so a re-parse that renames sections or yields fewer chunks leaves the
old rows in place, and retrieval keeps serving them. SOLAS carried about 1,000
such rows from four parses (docs/sprint-audits/question-audit-2026-09-25.md
§3.5).

A prune runs only when it is provably safe:
  - the parse yields no duplicate (section_number, chunk_index) key. Two
    Section objects sharing a section_number chunk from index 0 and overwrite
    each other on upsert, so the stored rows are already a mix; that is a
    parser or source-data bug to fix first.
  - every key the parse yields is already stored. In update mode a chunk
    whose text moved to a new key is skipped as unchanged (its hash is stored
    under the old key), so the new key was never written, and pruning the
    old key would lose the text.

The rows are copied to data/pruned/<source>-<UTC stamp>.csv (embeddings
included; gzipped after the commit) inside the same transaction as the
DELETE, so a failed copy deletes nothing. Restore with COPY ... FROM ... CSV
HEADER.

Rows added by ingest/manual_add.py are produced by no parse, so they show up
as stale. Rows whose section_number contains "(manual)" (the convention the
IMDG manual additions use) are never pruned; any other manual addition must
be spotted in the report before --prune-stale / --prune is run.
"""

from __future__ import annotations

import gzip
import re
import json
import logging
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

PRUNED_DIR = Path(__file__).resolve().parents[3] / "data" / "pruned"

Key = tuple[str, int]
_KEEP = re.compile(r"\(manual\)", re.IGNORECASE)


class PruneRefused(RuntimeError):
    pass


@dataclass
class StaleReport:
    source: str
    produced: int = 0                                 # distinct keys the parse yields
    duplicates: list[Key] = field(default_factory=list)
    stored: int = 0                                   # rows stored for the source
    missing: list[Key] = field(default_factory=list)  # produced but not stored
    stale: list[dict] = field(default_factory=list)   # stored but not produced
    kept_manual: int = 0                              # stored, not produced, kept

    @property
    def safe(self) -> bool:
        return self.produced > 0 and not self.duplicates and not self.missing

    def refusal(self) -> str | None:
        if self.produced == 0:
            return "the parse produced no chunks"
        if self.duplicates:
            return (f"the parse yields {len(self.duplicates)} duplicate keys, e.g. "
                    f"{self.duplicates[:3]}; fix the parser or source data first")
        if self.missing:
            return (f"{len(self.missing)} keys the parse yields are not stored, e.g. "
                    f"{self.missing[:3]}; run an ingest (--fresh) before pruning")
        return None

    def summary_lines(self) -> list[str]:
        lines = [
            f"{self.source}: parse yields {self.produced} keys; {self.stored} rows stored; "
            f"{len(self.stale)} stored rows not produced (stale); "
            f"{len(self.missing)} produced keys missing; {len(self.duplicates)} duplicate keys"
            + (f"; {self.kept_manual} manual rows kept" if self.kept_manual else ""),
        ]
        by_created = Counter(str(r["created"]) for r in self.stale)
        for created, n in sorted(by_created.items()):
            lines.append(f"  stale rows created {created}: {n}")
        by_section = Counter(r["section_number"] for r in self.stale)
        for sec, n in by_section.most_common(15):
            lines.append(f"  {n:4d}  {sec}")
        if len(by_section) > 15:
            lines.append(f"  … {len(by_section) - 15} more sections")
        return lines


def produced_keys(chunks) -> tuple[set[Key], list[Key]]:
    """Distinct (section_number, chunk_index) keys and any yielded twice."""
    counts = Counter((c.section_number, c.chunk_index) for c in chunks)
    return set(counts), sorted(k for k, n in counts.items() if n > 1)


async def build_report(pool: asyncpg.Pool, source: str, chunks) -> StaleReport:
    keys, duplicates = produced_keys(chunks)
    rows = await pool.fetch(
        "SELECT id, section_number, chunk_index, created_at::date AS created "
        "FROM regulations WHERE source = $1",
        source,
    )
    stored = {(r["section_number"], r["chunk_index"]) for r in rows}
    not_produced = [r for r in rows if (r["section_number"], r["chunk_index"]) not in keys]
    manual = [r for r in not_produced if _KEEP.search(r["section_number"] or "")]
    return StaleReport(
        source=source,
        produced=len(keys),
        duplicates=duplicates,
        stored=len(rows),
        missing=sorted(keys - stored),
        stale=[
            {"id": str(r["id"]), "section_number": r["section_number"],
             "chunk_index": r["chunk_index"], "created": str(r["created"])}
            for r in not_produced if not _KEEP.search(r["section_number"] or "")
        ],
        kept_manual=len(manual),
    )


def write_report(report: StaleReport, out_dir: Path = PRUNED_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{report.source}-{stamp}-report.json"
    path.write_text(json.dumps({
        "source": report.source, "produced": report.produced, "stored": report.stored,
        "duplicates": report.duplicates, "missing": report.missing, "stale": report.stale,
    }, indent=1), encoding="utf-8")
    return path


async def run_prune_step(pool: asyncpg.Pool, source: str, chunks, mode: str, result, console) -> None:
    """Pipeline hook. mode "report" lists stale rows; "apply" also removes them.

    Skipped when this run had parse or chunk errors: a section that failed
    to chunk yields no keys, so its stored rows would look stale.
    """
    if result.errors:
        console.print(f"  [yellow]prune skipped: {result.errors} parse/chunk error(s) this run[/yellow]")
        return
    report = await build_report(pool, source, chunks)
    for line in report.summary_lines():
        console.print(f"  {line}")
    console.print(f"  report: {write_report(report)}")
    if mode == "report":
        return
    try:
        backup = await apply_prune(pool, report)
    except PruneRefused as exc:
        console.print(f"  [red]{exc}[/red]")
        result.errors += 1
        result.error_details.append(str(exc))
        return
    if backup is None:
        console.print("  nothing to prune")
        return
    result.pruned = len(report.stale)
    console.print(f"  [green]pruned {result.pruned} rows; copy at {backup}[/green]")


async def apply_prune(pool: asyncpg.Pool, report: StaleReport, out_dir: Path = PRUNED_DIR) -> Path | None:
    """Copy the stale rows to a CSV and delete them, in one transaction."""
    reason = report.refusal()
    if reason:
        raise PruneRefused(f"{report.source}: not pruning: {reason}")
    ids = [uuid.UUID(r["id"]) for r in report.stale]
    if not ids:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"{report.source}-{stamp}.csv"
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.copy_from_query(
                "SELECT * FROM regulations WHERE source = $1 AND id = ANY($2::uuid[])",
                report.source, ids, output=str(csv_path), format="csv", header=True,
            )
            status = await conn.execute(
                "DELETE FROM regulations WHERE source = $1 AND id = ANY($2::uuid[])",
                report.source, ids,
            )
            deleted = int(status.split()[-1])
            if deleted != len(ids):
                raise PruneRefused(
                    f"{report.source}: DELETE matched {deleted} of {len(ids)} rows; rolled back"
                )
    gz_path = csv_path.with_suffix(".csv.gz")
    with open(csv_path, "rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    csv_path.unlink()
    logger.info("pruned %d rows from %s; copy at %s", len(ids), report.source, gz_path)
    return gz_path
