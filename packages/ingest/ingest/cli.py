"""
RegKnots CFR ingest CLI.

Usage:
    uv run python -m ingest.cli --source cfr_33 --fresh
    uv run python -m ingest.cli --source cfr_46 --update
    uv run python -m ingest.cli --source colregs --fresh
    uv run python -m ingest.cli --all --update
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg
from rich.console import Console
from rich.table import Table

from ingest.config import settings
from ingest.models import IngestResult, PDF_SOURCES, SOURCE_TO_TITLE
from ingest.pdf_pipeline import run_pdf_pipeline
from ingest.pipeline import run_pipeline

_CFR_SOURCES = list(SOURCE_TO_TITLE.keys())
_SOURCES = _CFR_SOURCES + PDF_SOURCES

# Data directory for source PDFs
_DATA_RAW = Path(__file__).resolve().parents[3] / "data" / "raw"

# Maps PDF source tag → config dict.
#
# Single-PDF sources (e.g. colregs) use the key "pdf" pointing at one file.
# Multi-PDF sources (e.g. nvic) use the key "raw_dir" pointing at a directory;
# they must also expose discover_and_download() and get_source_date() in their
# adapter module.
_PDF_SOURCE_CONFIG: dict[str, dict] = {
    "colregs": {
        "pdf":     _DATA_RAW / "colregs_2024.pdf",
        "adapter": "ingest.sources.colregs",
    },
    "nvic": {
        "raw_dir": _DATA_RAW / "nvic",
        "adapter": "ingest.sources.nvic",
    },
}

_DATA_FAILED = Path(__file__).resolve().parents[3] / "data" / "failed"


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="RegKnots CFR ingest pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m ingest.cli --source cfr_33 --fresh
  uv run python -m ingest.cli --source cfr_46 --update
  uv run python -m ingest.cli --all --update
        """,
    )

    source_grp = parser.add_mutually_exclusive_group(required=True)
    source_grp.add_argument(
        "--source",
        choices=_SOURCES,
        metavar="SOURCE",
        help=f"Single source: {', '.join(_SOURCES)}",
    )
    source_grp.add_argument(
        "--all",
        action="store_true",
        help=f"Ingest all sources ({', '.join(_SOURCES)})",
    )

    mode_grp = parser.add_mutually_exclusive_group()
    mode_grp.add_argument(
        "--fresh",
        action="store_true",
        help="Full ingest — re-embed all chunks regardless of hash (default)",
    )
    mode_grp.add_argument(
        "--update",
        action="store_true",
        help="Incremental — skip sections whose content_hash is unchanged",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("ingest").setLevel(logging.DEBUG)

    sources = _SOURCES if args.all else [args.source]
    mode = "update" if args.update else "fresh"

    asyncio.run(_run(sources, mode))


async def _run(sources: list[str], mode: str) -> None:
    console = Console()

    if not settings.openai_api_key:
        console.print("[bold red]Error:[/bold red] OPENAI_API_KEY not set in .env")
        sys.exit(1)

    console.rule("[bold]RegKnots CFR Ingest")
    console.print(f"  Sources : {', '.join(sources)}")
    console.print(f"  Mode    : {mode}")
    # Show DB host only — never log credentials
    db_host = settings.database_url.split("@")[-1] if "@" in settings.database_url else "?"
    console.print(f"  Database: {db_host}")
    console.print()

    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=5)
    all_results: list[IngestResult] = []

    try:
        for source in sources:
            console.rule(f"[cyan]{source}")
            if source in PDF_SOURCES:
                result = await _run_pdf_source(source, mode, pool, console)
            else:
                result = await run_pipeline(
                    source=source,
                    mode=mode,
                    pool=pool,
                    cfg=settings,
                    console=console,
                )
            all_results.append(result)
    finally:
        await pool.close()

    _print_summary(all_results, console)


async def _run_pdf_source(
    source: str,
    mode: str,
    pool: asyncpg.Pool,
    console: Console,
) -> IngestResult:
    """Dispatch a PDF-sourced ingest run.

    Supports two adapter patterns:
      - Single-PDF  (cfg["pdf"])    — COLREGs style; one PDF file, static SOURCE_DATE.
      - Multi-PDF   (cfg["raw_dir"]) — NVIC style; adapter handles discovery + download,
                                       exposes get_source_date(raw_dir) dynamically.
    """
    import importlib

    cfg = _PDF_SOURCE_CONFIG.get(source)
    if cfg is None:
        console.print(f"[red]No PDF config found for source '{source}'[/red]")
        return IngestResult(source=source, errors=1)

    adapter = importlib.import_module(cfg["adapter"])

    # ── Multi-PDF path (e.g. nvic) ────────────────────────────────────────────
    if "raw_dir" in cfg:
        raw_dir: Path = cfg["raw_dir"]
        raw_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"  [cyan]Phase 1:[/cyan] Discovering and downloading {source.upper()} documents…")
        dl_success, dl_failures = adapter.discover_and_download(
            raw_dir, _DATA_FAILED, console
        )

        if dl_success == 0 and dl_failures == 0:
            console.print(f"  [yellow]No {source.upper()} documents found — aborting[/yellow]")
            return IngestResult(source=source, errors=1)

        source_date = adapter.get_source_date(raw_dir)
        section_loader = lambda: adapter.parse_source(raw_dir)  # noqa: E731

        result = await run_pdf_pipeline(
            source=source,
            mode=mode,
            section_loader=section_loader,
            source_date=source_date,
            pool=pool,
            cfg=settings,
            console=console,
        )
        # Surface download failures in the summary error count
        result.errors += dl_failures
        return result

    # ── Single-PDF path (e.g. colregs) ────────────────────────────────────────
    pdf_path: Path = cfg["pdf"]
    if not pdf_path.exists():
        console.print(
            f"[red]PDF not found: {pdf_path}\n"
            f"Download it first and place it at that path.[/red]"
        )
        return IngestResult(source=source, errors=1)

    section_loader = lambda: adapter.parse_source(pdf_path)  # noqa: E731

    return await run_pdf_pipeline(
        source=source,
        mode=mode,
        section_loader=section_loader,
        source_date=adapter.SOURCE_DATE,
        pool=pool,
        cfg=settings,
        console=console,
    )


def _print_summary(results: list[IngestResult], console: Console) -> None:
    console.print()
    console.rule("[bold]Summary")

    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Source")
    table.add_column("Sections", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Embeddings", justify="right")
    table.add_column("Upserts", justify="right")
    table.add_column("Changes", justify="right")
    table.add_column("Errors", justify="right")

    total_errors = 0
    for r in results:
        total_errors += r.errors
        table.add_row(
            r.source,
            f"{r.sections_found:,}",
            f"{r.chunks_created:,}",
            f"{r.chunks_skipped:,}",
            f"{r.embeddings_generated:,}",
            f"{r.upserts:,}",
            str(r.version_changes),
            f"[red]{r.errors}[/red]" if r.errors else "0",
        )

    console.print(table)
    if total_errors:
        console.print(
            f"\n[yellow]WARN: {total_errors} error(s) total - "
            f"check data/failed/ for details.[/yellow]"
        )
    else:
        console.print("\n[green]Completed with no errors.[/green]")


if __name__ == "__main__":
    main()
