"""
RegKnot CFR ingest CLI.

Usage:
    uv run python -m ingest.cli --source cfr_33 --fresh
    uv run python -m ingest.cli --source cfr_46 --update
    uv run python -m ingest.cli --source colregs --fresh
    uv run python -m ingest.cli --source solas --dry-run
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
from ingest.notify import create_regulation_update_notification
from ingest.pdf_pipeline import run_pdf_pipeline
from ingest.pipeline import run_pipeline

_CFR_SOURCES = list(SOURCE_TO_TITLE.keys())
_SOURCES = _CFR_SOURCES + PDF_SOURCES

# Data directory for source PDFs
_DATA_RAW = Path(__file__).resolve().parents[3] / "data" / "raw"

# Maps PDF/text source tag → config dict.
#
# Single-PDF sources (e.g. colregs) use the key "pdf" pointing at one file.
# Multi-PDF sources (e.g. nvic) use the key "raw_dir" pointing at a directory;
#   they must also expose discover_and_download() and get_source_date() in
#   their adapter module.
# Text-dir sources (e.g. solas) use the key "text_dir" pointing at a directory
#   of pre-extracted .txt files plus a headers.txt index.  The adapter must
#   expose parse_source(raw_dir) and SOURCE_DATE.
_PDF_SOURCE_CONFIG: dict[str, dict] = {
    "colregs": {
        "pdf":     _DATA_RAW / "colregs_2024.pdf",
        "adapter": "ingest.sources.colregs",
    },
    "erg": {
        "pdf":     _DATA_RAW / "erg" / "ERG2024-Eng-Web-a.pdf",
        "adapter": "ingest.sources.erg",
    },
    "ism": {
        "text_dir": _DATA_RAW / "ism" / "extracted",
        "adapter":  "ingest.sources.ism",
    },
    "ism_supplement": {
        "text_dir": _DATA_RAW / "ism" / "extracted",
        "adapter":  "ingest.sources.ism_supplement",
    },
    "nvic": {
        "raw_dir": _DATA_RAW / "nvic",
        "adapter": "ingest.sources.nvic",
    },
    "solas": {
        "text_dir": _DATA_RAW / "solas",
        "adapter":  "ingest.sources.solas",
    },
    "solas_supplement": {
        "pdf":     _DATA_RAW / "solas_supplements" / "1QH110E_supplement_January2026_EBK.pdf",
        "adapter": "ingest.sources.solas_supplement",
    },
    "stcw": {
        "text_dir": _DATA_RAW / "stcw" / "extracted",
        "adapter":  "ingest.sources.stcw",
    },
    "stcw_supplement": {
        "pdf":     _DATA_RAW / "stcw_supplements" / "QQQQD938E_supplement_January2025_EBK.pdf",
        "adapter": "ingest.sources.stcw_supplement",
    },
}

_DATA_FAILED = Path(__file__).resolve().parents[3] / "data" / "failed"


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="RegKnot CFR ingest pipeline",
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
        "--dry-run",
        action="store_true",
        help=(
            "For text-dir sources (e.g. solas): print the page-range → section "
            "mapping and exit without embedding or writing to the database."
        ),
    )

    parser.add_argument(
        "--extract",
        action="store_true",
        help="For image-based sources (e.g. stcw): run Vision extraction on raw images first.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extraction of already-processed images (use with --extract).",
    )

    enrich_grp = parser.add_mutually_exclusive_group()
    enrich_grp.add_argument(
        "--enrich",
        action="store_true",
        default=False,
        help="Enrich chunks with LLM-generated search aliases before embedding.",
    )
    enrich_grp.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip alias enrichment (default).",
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
    enrich = args.enrich and not args.no_enrich

    asyncio.run(_run(
        sources, mode,
        dry_run=args.dry_run,
        extract=args.extract,
        force=args.force,
        enrich=enrich,
    ))


async def _run(
    sources: list[str],
    mode: str,
    dry_run: bool = False,
    extract: bool = False,
    force: bool = False,
    enrich: bool = False,
) -> None:
    import importlib

    console = Console()

    # ── Extract: run Vision OCR on raw images ────────────────────────────────
    if extract:
        for source in sources:
            cfg = _PDF_SOURCE_CONFIG.get(source)
            if cfg is None or "text_dir" not in cfg:
                console.print(
                    f"[yellow]--extract not supported for '{source}'[/yellow]"
                )
                sys.exit(1)
            adapter = importlib.import_module(cfg["adapter"])
            if not hasattr(adapter, "extract_images"):
                console.print(
                    f"[yellow]'{source}' does not support image extraction[/yellow]"
                )
                sys.exit(1)
            # Extract raw_dir is the PARENT of text_dir (stcw/ not stcw/extracted/)
            raw_dir = cfg["text_dir"].parent
            await adapter.extract_images(raw_dir, force=force)
            console.print(f"[green]Extraction complete for {source}.[/green]")
        if not dry_run and mode == "fresh" or mode == "update":
            pass  # continue to ingest
        elif dry_run:
            pass  # fall through to dry-run
        else:
            return  # --extract only, no ingest

    # ── Dry-run: no DB or API calls needed ────────────────────────────────────
    if dry_run:
        for source in sources:
            cfg = _PDF_SOURCE_CONFIG.get(source)
            if cfg is None:
                console.print(
                    f"[yellow]--dry-run is only supported for PDF/text sources. "
                    f"'{source}' does not support it.[/yellow]"
                )
                sys.exit(1)
            adapter = importlib.import_module(cfg["adapter"])
            if "text_dir" in cfg:
                adapter.dry_run(cfg["text_dir"])
            elif "pdf" in cfg and hasattr(adapter, "dry_run"):
                adapter.dry_run(cfg["pdf"])
            else:
                console.print(
                    f"[yellow]--dry-run is not supported for '{source}'.[/yellow]"
                )
                sys.exit(1)
        return

    if not settings.openai_api_key:
        console.print("[bold red]Error:[/bold red] OPENAI_API_KEY not set in .env")
        sys.exit(1)

    console.rule("[bold]RegKnot CFR Ingest")
    console.print(f"  Sources : {', '.join(sources)}")
    console.print(f"  Mode    : {mode}")
    # Show DB host only — never log credentials
    db_host = settings.database_url.split("@")[-1] if "@" in settings.database_url else "?"
    console.print(f"  Database: {db_host}")
    console.print()

    # asyncpg requires plain "postgresql://" — strip the SQLAlchemy dialect suffix
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)
    all_results: list[IngestResult] = []

    try:
        for source in sources:
            console.rule(f"[cyan]{source}")
            if source in PDF_SOURCES:
                result = await _run_pdf_source(source, mode, pool, console, enrich=enrich)
            else:
                result = await run_pipeline(
                    source=source,
                    mode=mode,
                    pool=pool,
                    cfg=settings,
                    console=console,
                )
            all_results.append(result)

            # Auto-notification hook: fire a regulation_update notification
            # when this source actually introduced new or modified content.
            # No-op runs (0 changes) are intentionally silent.
            if result.new_or_modified_chunks > 0:
                notif_id = await create_regulation_update_notification(pool, result)
                if notif_id:
                    console.print(
                        f"  [magenta]Notification created[/magenta] "
                        f"[dim]({notif_id[:8]}…)[/dim] — "
                        f"{result.new_or_modified_chunks} new/modified chunks"
                    )

        # Rebuild the HNSW vector index after ingest to prevent stale results
        total_upserts = sum(r.upserts for r in all_results)
        if total_upserts > 0:
            console.print()
            console.print("[cyan]Rebuilding HNSW vector index...[/cyan]")
            async with pool.acquire() as conn:
                await conn.execute("REINDEX INDEX idx_regulations_embedding")
            console.print("[green]HNSW index rebuilt successfully.[/green]")
    finally:
        await pool.close()

    _print_summary(all_results, console)


async def _run_pdf_source(
    source: str,
    mode: str,
    pool: asyncpg.Pool,
    console: Console,
    enrich: bool = False,
) -> IngestResult:
    """Dispatch a PDF/text-sourced ingest run.

    Supports three adapter patterns:
      - Single-PDF  (cfg["pdf"])      — COLREGs style; one PDF file, static SOURCE_DATE.
      - Multi-PDF   (cfg["raw_dir"])  — NVIC style; adapter handles discovery + download,
                                        exposes get_source_date(raw_dir) dynamically.
      - Text-dir    (cfg["text_dir"]) — SOLAS style; pre-extracted .txt files + headers.txt.
                                        Adapter exposes parse_source(raw_dir) and SOURCE_DATE.
    """
    import importlib

    cfg = _PDF_SOURCE_CONFIG.get(source)
    if cfg is None:
        console.print(f"[red]No PDF config found for source '{source}'[/red]")
        return IngestResult(source=source, errors=1)

    adapter = importlib.import_module(cfg["adapter"])

    # ── Text-dir path (e.g. solas) ────────────────────────────────────────────
    if "text_dir" in cfg:
        return await _run_text_source(source, mode, cfg, adapter, pool, console, enrich=enrich)

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
            enrich=enrich,
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
        enrich=enrich,
    )


async def _run_text_source(
    source: str,
    mode: str,
    cfg: dict,
    adapter,
    pool: asyncpg.Pool,
    console: Console,
    enrich: bool = False,
) -> IngestResult:
    """Ingest a pre-extracted text-dir source (e.g. SOLAS).

    The adapter must expose:
      - parse_source(raw_dir: Path) -> list[Section]
      - SOURCE_DATE: date

    The raw_dir must contain:
      - headers.txt  — page-range metadata index
      - <start>-<end>.txt files — pre-extracted text per page range
    """
    raw_dir: Path = cfg["text_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)

    # STCW and ISM use auto-detected structure from extracted .txt files (no headers.txt).
    # SOLAS uses headers.txt + range-named .txt files.
    needs_headers = source not in ("stcw", "ism", "ism_supplement")

    if needs_headers:
        headers_path = raw_dir / "headers.txt"
        if not headers_path.exists():
            console.print(
                f"[red]headers.txt not found: {headers_path}\n"
                f"Create it with lines like: '5-12: Chapter I Part A — General'[/red]"
            )
            return IngestResult(source=source, errors=1)

        txt_files = list(raw_dir.glob("[0-9]*-[0-9]*.txt"))
        if not txt_files:
            console.print(
                f"[red]No <start>-<end>.txt files found in {raw_dir}\n"
                f"Expected files named like '5-12.txt'.[/red]"
            )
            return IngestResult(source=source, errors=1)
    else:
        txt_files = [f for f in raw_dir.iterdir() if f.suffix == ".txt"]
        if not txt_files:
            console.print(
                f"[red]No .txt files found in {raw_dir}\n"
                f"Run --extract first to generate them from page images.[/red]"
            )
            return IngestResult(source=source, errors=1)

    console.print(
        f"  [cyan]Text dir:[/cyan] {raw_dir} "
        f"([bold]{len(txt_files)}[/bold] text files)"
    )

    section_loader = lambda: adapter.parse_source(raw_dir)  # noqa: E731

    return await run_pdf_pipeline(
        source=source,
        mode=mode,
        section_loader=section_loader,
        source_date=adapter.SOURCE_DATE,
        pool=pool,
        cfg=settings,
        console=console,
        enrich=enrich,
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
    table.add_column("New/Mod", justify="right")
    table.add_column("NetΔ", justify="right")
    table.add_column("Errors", justify="right")

    total_errors = 0
    for r in results:
        total_errors += r.errors
        delta_str = f"{r.net_chunk_delta:+d}" if r.net_chunk_delta else "0"
        table.add_row(
            r.source,
            f"{r.sections_found:,}",
            f"{r.chunks_created:,}",
            f"{r.chunks_skipped:,}",
            f"{r.embeddings_generated:,}",
            f"{r.upserts:,}",
            f"{r.new_or_modified_chunks:,}",
            delta_str,
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
