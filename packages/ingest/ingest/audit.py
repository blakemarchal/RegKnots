"""
Knowledge-base audit CLI.

Compares what's actually in the `regulations` table against expected TOC
manifests, flags missing sections, truncated chunks, and embedding gaps.

Usage
-----
    uv run python -m ingest.audit --source ism
    uv run python -m ingest.audit --all
    uv run python -m ingest.audit --all --json audit_report.json

Sources that ship with a YAML manifest in `ingest/manifests/` (ism, colregs,
solas, stcw, solas_supplement, stcw_supplement) get a full structural audit:
coverage percentage, per-section status (present/missing/truncated/unembedded),
and a list of unexpected extras in the database.

Sources without a manifest (cfr_33, cfr_46, cfr_49, nvic — too large for a
static TOC) fall back to a DB-only sanity check reporting the total section
count, chunks without embeddings, and sections with suspiciously short text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ingest.config import settings
from ingest.models import PDF_SOURCES, SOURCE_TO_TITLE

logger = logging.getLogger(__name__)

# ── Source lists ─────────────────────────────────────────────────────────────

_CFR_SOURCES = list(SOURCE_TO_TITLE.keys())  # cfr_33, cfr_46, cfr_49
_ALL_SOURCES = _CFR_SOURCES + PDF_SOURCES    # + colregs, ism, nvic, solas, ...

# Sources that have a static TOC manifest file on disk.
_MANIFEST_SOURCES = {
    "ism",
    "colregs",
    "solas",
    "stcw",
    "solas_supplement",
    "stcw_supplement",
}

# Sources audited DB-only (no static manifest — too many sections).
_DB_ONLY_SOURCES = set(_CFR_SOURCES) | {"nvic"}

_MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"

# Threshold below which a DB-only source flags a section as "short"
_SHORT_SECTION_CHARS = 100


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SectionStatus:
    """Audit result for one expected section in a manifest.

    `match_type` captures how the section was resolved in the DB:
      - "exact"        : a DB row with the exact section_number exists.
      - "prefix"       : no exact row, but one or more child sections were
                         found via hierarchical prefix matching (e.g. the
                         expected "ISM 1" is satisfied by "ISM 1.1", "1.2", …).
      - "exact+prefix" : both — the parent stub row exists AND the manifest
                         also matched child subsections; stats are aggregated.
      - "missing"      : neither an exact nor a prefix match was found.

    When children are aggregated, `chunk_count` / `total_chars` sum across
    the parent (if any) plus every matched child, and `all_embedded` is true
    only when every contributing row has an embedding.
    """
    section_number: str
    expected_title: str
    min_chars: int
    status: str                     # "ok" | "missing" | "truncated" | "no_embedding"
    chunk_count: int = 0
    total_chars: int = 0
    all_embedded: bool = False
    db_title: str | None = None
    # Hierarchical match metadata (introduced for subsection aggregation)
    match_type: str = "missing"     # "exact" | "exact+prefix" | "prefix" | "missing"
    matched_children: list[str] = field(default_factory=list)
    note: str | None = None         # e.g. "via 12 subsections"


@dataclass
class SourceAudit:
    """Audit result for one source."""
    source: str
    audit_type: str                 # "manifest" | "db_only"
    total_chunks: int = 0
    distinct_sections: int = 0
    # Manifest-only fields
    manifest_title: str | None = None
    manifest_description: str | None = None
    expected_count: int = 0
    present_count: int = 0
    missing_count: int = 0
    truncated_count: int = 0
    unembedded_count: int = 0
    coverage_pct: float = 0.0
    sections: list[SectionStatus] = field(default_factory=list)
    unexpected_extras: list[str] = field(default_factory=list)
    # DB-only fields
    chunks_without_embedding: int = 0
    short_sections: list[str] = field(default_factory=list)
    # Error state
    error: str | None = None


# ── Manifest loading ─────────────────────────────────────────────────────────

def load_manifest(source: str) -> dict[str, Any] | None:
    """Load a TOC manifest YAML for the given source.

    Returns None if the manifest file does not exist.
    """
    path = _MANIFEST_DIR / f"{source}.yaml"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Manifest {path} is not a YAML mapping")
    if data.get("source") != source:
        raise ValueError(
            f"Manifest {path} declares source={data.get('source')!r}, "
            f"expected {source!r}"
        )
    return data


# ── DB queries ───────────────────────────────────────────────────────────────

_SECTION_AGG_SQL = """
    SELECT
        section_number,
        MAX(section_title)                         AS section_title,
        COUNT(*)                                   AS chunk_count,
        COALESCE(SUM(LENGTH(full_text)), 0)        AS total_chars,
        MIN(chunk_index)                           AS min_chunk,
        MAX(chunk_index)                           AS max_chunk,
        BOOL_AND(embedding IS NOT NULL)            AS all_embedded
    FROM regulations
    WHERE source = $1
    GROUP BY section_number
    ORDER BY section_number
"""

_SOURCE_TOTALS_SQL = """
    SELECT
        source,
        COUNT(*)                               AS chunks,
        COUNT(DISTINCT section_number)         AS sections,
        SUM(CASE WHEN embedding IS NULL THEN 1 ELSE 0 END) AS unembedded_chunks
    FROM regulations
    GROUP BY source
    ORDER BY source
"""


async def _fetch_section_rows(pool: asyncpg.Pool, source: str) -> list[dict[str, Any]]:
    rows = await pool.fetch(_SECTION_AGG_SQL, source)
    return [dict(r) for r in rows]


async def _fetch_source_totals(pool: asyncpg.Pool) -> dict[str, dict[str, int]]:
    rows = await pool.fetch(_SOURCE_TOTALS_SQL)
    return {
        r["source"]: {
            "chunks": int(r["chunks"] or 0),
            "sections": int(r["sections"] or 0),
            "unembedded_chunks": int(r["unembedded_chunks"] or 0),
        }
        for r in rows
    }


# ── Audit logic ──────────────────────────────────────────────────────────────

def _find_children(expected: str, db_keys: list[str]) -> list[str]:
    """Return DB section_numbers that are hierarchical children of `expected`.

    A DB section S is a child of expected E iff:
      1. S != E (the exact match is handled separately).
      2. S starts with E.
      3. The character in S immediately following E is a non-alphanumeric
         boundary (e.g. '.', ' ', '/', '-').

    The boundary check prevents false positives like:
      - "ISM 1" matching "ISM 10" / "ISM 11" (next char '0'/'1' is alnum)
      - "STCW Article I" matching "STCW Article II" (next char 'I' is alnum)

    While correctly accepting:
      - "ISM 1" → "ISM 1.1", "ISM 1.2", "ISM 1.2.1", "ISM 1.1.10" (boundary '.')
      - "STCW Ch.I" → "STCW Ch.I Reg.I/1", "STCW Ch.I Reg.I/2" (boundary ' ')
      - "STCW Code A-II" → "STCW Code A-II/1", "STCW Code A-II/4" (boundary '/')
    """
    prefix_len = len(expected)
    matches: list[str] = []
    for key in db_keys:
        if key == expected:
            continue
        if not key.startswith(expected):
            continue
        if len(key) == prefix_len:
            continue  # can't happen with the == check above, but defensive
        boundary = key[prefix_len]
        if boundary.isalnum():
            continue
        matches.append(key)
    return sorted(matches)


def _audit_with_manifest(
    source: str,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
) -> SourceAudit:
    """Compare DB rows to a manifest and build a SourceAudit.

    For each expected section we look for BOTH an exact section_number match
    and hierarchical prefix-matched children. When children are present, the
    chunk count / total chars / embedding status are aggregated across the
    parent stub plus every child row so that e.g. "ISM 1" counts as present
    once its subsections (ISM 1.1, ISM 1.2.1, …) cover it.
    """
    expected = manifest.get("expected_sections", []) or []

    # Index DB rows by section_number for O(1) lookup
    db_by_number = {r["section_number"]: r for r in rows}
    db_keys = list(db_by_number.keys())

    audit = SourceAudit(
        source=source,
        audit_type="manifest",
        total_chunks=sum(int(r["chunk_count"]) for r in rows),
        distinct_sections=len(rows),
        manifest_title=manifest.get("title"),
        manifest_description=manifest.get("description"),
        expected_count=len(expected),
    )

    # Track every DB section_number that was "consumed" by an expected
    # manifest entry (either exact or prefix match). What's left at the end
    # is reported as unexpected extras.
    consumed: set[str] = set()

    for entry in expected:
        sec_num = entry["section_number"]
        expected_title = entry.get("title", "")
        min_chars = int(entry.get("min_chars", 0))

        exact_row = db_by_number.get(sec_num)
        children_keys = _find_children(sec_num, db_keys)

        # ── No match at all → missing ───────────────────────────────────────
        if exact_row is None and not children_keys:
            audit.sections.append(SectionStatus(
                section_number=sec_num,
                expected_title=expected_title,
                min_chars=min_chars,
                status="missing",
                match_type="missing",
            ))
            audit.missing_count += 1
            continue

        # ── Collect contributing rows (stub + children) ─────────────────────
        matched_rows: list[dict[str, Any]] = []
        if exact_row is not None:
            matched_rows.append(exact_row)
            consumed.add(sec_num)
        for child_key in children_keys:
            matched_rows.append(db_by_number[child_key])
            consumed.add(child_key)

        chunk_count = sum(int(r["chunk_count"]) for r in matched_rows)
        total_chars = sum(int(r["total_chars"]) for r in matched_rows)
        all_embedded = all(bool(r["all_embedded"]) for r in matched_rows)
        db_title = (
            exact_row["section_title"] if exact_row is not None
            else matched_rows[0]["section_title"]
        )

        # ── Classify the match kind ─────────────────────────────────────────
        if exact_row is not None and children_keys:
            match_type = "exact+prefix"
        elif children_keys:
            match_type = "prefix"
        else:
            match_type = "exact"

        if children_keys:
            note = (
                f"via {len(children_keys)} subsection"
                + ("s" if len(children_keys) != 1 else "")
            )
        else:
            note = None

        # ── Status: unembedded > truncated > ok ─────────────────────────────
        if not all_embedded:
            status = "no_embedding"
            audit.unembedded_count += 1
        elif min_chars > 0 and total_chars < min_chars:
            status = "truncated"
            audit.truncated_count += 1
        else:
            status = "ok"
            audit.present_count += 1

        audit.sections.append(SectionStatus(
            section_number=sec_num,
            expected_title=expected_title,
            min_chars=min_chars,
            status=status,
            chunk_count=chunk_count,
            total_chars=total_chars,
            all_embedded=all_embedded,
            db_title=db_title,
            match_type=match_type,
            matched_children=children_keys,
            note=note,
        ))

    # Sections present in DB but not consumed by any expected entry →
    # surface as unexpected extras. Using `consumed` (rather than the raw
    # manifest key set) ensures that hierarchically-matched children don't
    # show up as extras just because they aren't named in the manifest.
    audit.unexpected_extras = sorted(
        sec_num for sec_num in db_by_number if sec_num not in consumed
    )

    if audit.expected_count:
        audit.coverage_pct = round(
            (audit.present_count / audit.expected_count) * 100.0, 1
        )

    return audit


def _audit_db_only(source: str, rows: list[dict[str, Any]]) -> SourceAudit:
    """Build a SourceAudit for a source without a static manifest."""
    audit = SourceAudit(
        source=source,
        audit_type="db_only",
        total_chunks=sum(int(r["chunk_count"]) for r in rows),
        distinct_sections=len(rows),
    )

    chunks_without_embedding = 0
    short_sections: list[str] = []
    for r in rows:
        total_chars = int(r["total_chars"])
        chunk_count = int(r["chunk_count"])
        all_embedded = bool(r["all_embedded"])
        if not all_embedded:
            # Can't know exact number without a separate query; we report
            # "≥1 chunk in this section is unembedded" by incrementing per
            # section so the totals query remains the source of truth for
            # exact chunk counts.
            chunks_without_embedding += chunk_count
        if total_chars < _SHORT_SECTION_CHARS:
            short_sections.append(r["section_number"])

    audit.chunks_without_embedding = chunks_without_embedding
    audit.short_sections = sorted(short_sections)
    return audit


async def audit_source(pool: asyncpg.Pool, source: str) -> SourceAudit:
    """Run an audit for a single source."""
    try:
        rows = await _fetch_section_rows(pool, source)
    except Exception as exc:
        return SourceAudit(source=source, audit_type="error", error=str(exc))

    if source in _MANIFEST_SOURCES:
        manifest = load_manifest(source)
        if manifest is None:
            return SourceAudit(
                source=source,
                audit_type="error",
                error=f"No manifest file found at manifests/{source}.yaml",
            )
        return _audit_with_manifest(source, manifest, rows)

    if source in _DB_ONLY_SOURCES:
        return _audit_db_only(source, rows)

    return SourceAudit(
        source=source,
        audit_type="error",
        error=f"Unknown source {source!r}",
    )


# ── Rendering ────────────────────────────────────────────────────────────────

_STATUS_ICON = {
    "ok":          ("[green]✓[/green]",        "ok"),
    "missing":     ("[red]✗[/red]",            "missing"),
    "truncated":   ("[yellow]⚠[/yellow]",     "truncated"),
    "no_embedding": ("[magenta]⚠[/magenta]",  "no embedding"),
}


def _render_manifest_audit(
    console: Console,
    audit: SourceAudit,
    verbose: bool = False,
) -> None:
    # Header panel
    header_lines = [
        f"[bold cyan]{audit.source}[/bold cyan]  —  {audit.manifest_title or ''}",
    ]
    if audit.manifest_description:
        header_lines.append(f"[dim]{audit.manifest_description}[/dim]")
    header_lines.append("")
    header_lines.append(
        f"  Expected sections : [bold]{audit.expected_count}[/bold]"
    )
    header_lines.append(
        f"  Present           : [green]{audit.present_count}[/green]"
    )
    header_lines.append(
        f"  Missing           : [red]{audit.missing_count}[/red]"
    )
    header_lines.append(
        f"  Truncated         : [yellow]{audit.truncated_count}[/yellow]"
    )
    header_lines.append(
        f"  Unembedded        : [magenta]{audit.unembedded_count}[/magenta]"
    )
    header_lines.append(
        f"  DB total chunks   : {audit.total_chunks:,}"
    )
    header_lines.append(
        f"  DB distinct secs  : {audit.distinct_sections:,}"
    )
    cov = audit.coverage_pct
    cov_color = "green" if cov >= 90 else ("yellow" if cov >= 70 else "red")
    header_lines.append(
        f"  Coverage          : [bold {cov_color}]{cov:.1f}%[/bold {cov_color}]"
    )

    console.print(Panel("\n".join(header_lines), expand=False, border_style="cyan"))

    # Per-section table
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("", width=2, justify="center")
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Chunks", justify="right")
    table.add_column("Chars", justify="right")
    table.add_column("Min", justify="right", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Expected Title", style="dim")

    for sec in audit.sections:
        icon, status_text = _STATUS_ICON.get(
            sec.status, ("?", sec.status)
        )
        status_colored = {
            "ok":           "[green]ok[/green]",
            "missing":      "[red]MISSING[/red]",
            "truncated":    "[yellow]truncated[/yellow]",
            "no_embedding": "[magenta]no embedding[/magenta]",
        }.get(sec.status, sec.status)

        # Append the hierarchical-match note so the reader can see at a
        # glance that a section is satisfied via its children, e.g.
        # "ok (via 12 subsections)".
        if sec.note:
            status_colored += f" [dim]({sec.note})[/dim]"

        table.add_row(
            icon,
            sec.section_number,
            f"{sec.chunk_count:,}" if sec.chunk_count else "-",
            f"{sec.total_chars:,}" if sec.total_chars else "-",
            f"{sec.min_chars:,}" if sec.min_chars else "-",
            status_colored,
            (sec.expected_title[:60] + "…")
            if len(sec.expected_title) > 61
            else sec.expected_title,
        )
    console.print(table)

    # Hierarchical match details (verbose only) — list the actual child
    # section_numbers that satisfied each prefix match so the reader can
    # verify the aggregation is picking up the right subsections.
    if verbose:
        prefix_entries = [s for s in audit.sections if s.matched_children]
        if prefix_entries:
            console.print()
            console.print(
                "[dim]Hierarchical matches "
                f"({len(prefix_entries)} sections covered via subsections):[/dim]"
            )
            for sec in prefix_entries:
                console.print(
                    f"  [cyan]{sec.section_number}[/cyan] "
                    f"[dim]→ {len(sec.matched_children)} children "
                    f"({sec.total_chars:,} chars total)[/dim]"
                )
                preview = sec.matched_children[:10]
                for child in preview:
                    console.print(f"      [dim]· {child}[/dim]")
                if len(sec.matched_children) > 10:
                    console.print(
                        f"      [dim]… and "
                        f"{len(sec.matched_children) - 10} more[/dim]"
                    )

    # Unexpected extras
    if audit.unexpected_extras:
        console.print()
        console.print(
            f"[dim]Unexpected extras in DB "
            f"(present but not in manifest): {len(audit.unexpected_extras)}[/dim]"
        )
        # Show up to 12 to keep the report readable
        preview = audit.unexpected_extras[:12]
        for sec in preview:
            console.print(f"    [dim]· {sec}[/dim]")
        if len(audit.unexpected_extras) > 12:
            console.print(
                f"    [dim]… and {len(audit.unexpected_extras) - 12} more[/dim]"
            )
    console.print()


def _render_db_only_audit(console: Console, audit: SourceAudit) -> None:
    lines = [
        f"[bold cyan]{audit.source}[/bold cyan]  —  DB-only audit (no static manifest)",
        "",
        f"  DB total chunks          : {audit.total_chunks:,}",
        f"  DB distinct sections     : {audit.distinct_sections:,}",
        f"  Chunks without embedding : "
        + (
            f"[red]{audit.chunks_without_embedding:,}[/red]"
            if audit.chunks_without_embedding
            else "[green]0[/green]"
        ),
        f"  Sections < {_SHORT_SECTION_CHARS} chars      : "
        + (
            f"[yellow]{len(audit.short_sections)}[/yellow]"
            if audit.short_sections
            else "[green]0[/green]"
        ),
    ]
    console.print(Panel("\n".join(lines), expand=False, border_style="cyan"))

    if audit.short_sections:
        console.print(
            f"[dim]Short sections (< {_SHORT_SECTION_CHARS} chars):[/dim]"
        )
        preview = audit.short_sections[:15]
        for sec in preview:
            console.print(f"    [dim]· {sec}[/dim]")
        if len(audit.short_sections) > 15:
            console.print(
                f"    [dim]… and {len(audit.short_sections) - 15} more[/dim]"
            )
    console.print()


def _render_error(console: Console, audit: SourceAudit) -> None:
    console.print(
        Panel(
            f"[red]{audit.source}[/red]\n\n{audit.error}",
            expand=False,
            border_style="red",
        )
    )
    console.print()


def render_reports(
    console: Console,
    audits: list[SourceAudit],
    verbose: bool = False,
) -> None:
    """Print the full audit report to the console.

    When `verbose` is true, manifest audits also list the individual
    child section_numbers that satisfied each hierarchical prefix match.
    """
    console.rule("[bold]Knowledge-Base Audit")
    console.print()

    for audit in audits:
        if audit.audit_type == "manifest":
            _render_manifest_audit(console, audit, verbose=verbose)
        elif audit.audit_type == "db_only":
            _render_db_only_audit(console, audit)
        else:
            _render_error(console, audit)

    # Final summary table
    console.rule("[bold]Summary")
    summary = Table(show_header=True, header_style="bold", show_lines=False)
    summary.add_column("Source", style="cyan")
    summary.add_column("Type")
    summary.add_column("Chunks", justify="right")
    summary.add_column("Sections", justify="right")
    summary.add_column("Expected", justify="right")
    summary.add_column("Missing", justify="right")
    summary.add_column("Truncated", justify="right")
    summary.add_column("Coverage", justify="right")

    for audit in audits:
        if audit.audit_type == "manifest":
            cov = audit.coverage_pct
            cov_color = "green" if cov >= 90 else ("yellow" if cov >= 70 else "red")
            summary.add_row(
                audit.source,
                "manifest",
                f"{audit.total_chunks:,}",
                f"{audit.distinct_sections:,}",
                f"{audit.expected_count}",
                f"[red]{audit.missing_count}[/red]" if audit.missing_count else "0",
                (
                    f"[yellow]{audit.truncated_count}[/yellow]"
                    if audit.truncated_count else "0"
                ),
                f"[{cov_color}]{cov:.1f}%[/{cov_color}]",
            )
        elif audit.audit_type == "db_only":
            unembedded = audit.chunks_without_embedding
            shorts = len(audit.short_sections)
            summary.add_row(
                audit.source,
                "db-only",
                f"{audit.total_chunks:,}",
                f"{audit.distinct_sections:,}",
                "-",
                (
                    f"[red]{unembedded} unembedded[/red]"
                    if unembedded else "0"
                ),
                f"[yellow]{shorts} short[/yellow]" if shorts else "0",
                "-",
            )
        else:
            summary.add_row(
                audit.source,
                "[red]error[/red]",
                "-", "-", "-", "-", "-", "-",
            )
    console.print(summary)


# ── JSON serialisation ───────────────────────────────────────────────────────

def _audit_to_json(audit: SourceAudit) -> dict[str, Any]:
    data = asdict(audit)
    # Dataclasses asdict preserves nested dataclasses as dicts — good as-is.
    return data


def build_json_report(audits: list[SourceAudit]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "ingest.audit",
        "sources": {a.source: _audit_to_json(a) for a in audits},
    }


# ── CLI entry point ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.audit",
        description=(
            "Audit the regulations database against TOC manifests. "
            "Reports coverage, missing sections, truncated chunks, "
            "and embedding gaps."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m ingest.audit --source ism
  uv run python -m ingest.audit --all
  uv run python -m ingest.audit --all --json /tmp/kb_audit.json
        """,
    )
    source_grp = parser.add_mutually_exclusive_group(required=True)
    source_grp.add_argument(
        "--source",
        choices=_ALL_SOURCES,
        metavar="SOURCE",
        help=f"Audit a single source ({', '.join(_ALL_SOURCES)})",
    )
    source_grp.add_argument(
        "--all",
        action="store_true",
        help="Audit every known source",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Also write a structured JSON report to PATH",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args()
    if args.verbose:
        logging.getLogger("ingest").setLevel(logging.DEBUG)

    sources = _ALL_SOURCES if args.all else [args.source]

    exit_code = asyncio.run(_run(
        sources, json_path=args.json, verbose=args.verbose,
    ))
    sys.exit(exit_code)


async def _run(
    sources: list[str],
    json_path: str | None,
    verbose: bool = False,
) -> int:
    console = Console()

    # asyncpg requires plain postgresql:// — strip the SQLAlchemy dialect prefix
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    except Exception as exc:
        console.print(f"[red]Failed to connect to database:[/red] {exc}")
        return 2

    try:
        audits: list[SourceAudit] = []
        for source in sources:
            audit = await audit_source(pool, source)
            audits.append(audit)
    finally:
        await pool.close()

    render_reports(console, audits, verbose=verbose)

    if json_path:
        report = build_json_report(audits)
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        console.print(f"\n[green]Wrote JSON report to {out}[/green]")

    # Exit code reflects severity: any missing manifest section → 1
    any_missing = any(
        a.audit_type == "manifest" and a.missing_count > 0 for a in audits
    )
    any_error = any(a.audit_type == "error" for a in audits)
    if any_error:
        return 2
    if any_missing:
        return 1
    return 0


if __name__ == "__main__":
    main()
