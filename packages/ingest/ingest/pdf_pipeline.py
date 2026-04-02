"""
PDF-sourced ingest pipeline.

Mirrors the structure of pipeline.py but replaces the eCFR API fetch/parse
stages (steps 1–4) with PDF-based parsing via a source adapter.

Shared stages (chunker → embedder → store) are identical to pipeline.py.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import asyncpg
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ingest import store
from ingest.chunker import chunk_section
from ingest.config import IngestSettings, settings as _default_settings
from ingest.embedder import EmbedderClient
from ingest.models import IngestResult, Section

logger = logging.getLogger(__name__)

_FAILED_DIR = Path(__file__).resolve().parents[3] / "data" / "failed"


async def run_pdf_pipeline(
    source: str,
    mode: str,                            # "fresh" | "update"
    section_loader: Callable[[], list[Section]],
    source_date,                          # date — the PDF's as-of date
    pool: asyncpg.Pool,
    cfg: IngestSettings | None = None,
    console: Console | None = None,
) -> IngestResult:
    """Run the ingest pipeline for a PDF-sourced regulation.

    Args:
        source:          Source tag, e.g. 'colregs'.
        mode:            'fresh' re-embeds everything; 'update' skips unchanged hashes.
        section_loader:  Zero-arg callable returning list[Section] (PDF → sections).
        source_date:     The effective/correction date of the PDF (used as as_of).
        pool:            asyncpg connection pool.
        cfg:             IngestSettings; defaults to module-level singleton.
        console:         Rich console; defaults to a new Console().
    """
    cfg     = cfg or _default_settings
    console = console or Console()
    result  = IngestResult(source=source)

    embedder = EmbedderClient(api_key=cfg.openai_api_key)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description:<40}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )

    try:
        with progress:
            # ── 1. Short-circuit if up-to-date (update mode only) ────────────
            if mode == "update":
                prev_as_of = await store.get_previous_as_of(pool, source)
                if prev_as_of and prev_as_of >= source_date:
                    console.print(
                        f"  [green]OK {source} is current (as of {source_date}), "
                        f"nothing to do.[/green]"
                    )
                    return result

            # ── 2. Parse sections ────────────────────────────────────────────
            parse_task = progress.add_task(f"Parsing {source}…", total=1)
            sections = section_loader()
            result.sections_found = len(sections)
            progress.update(
                parse_task,
                completed=1,
                description=f"Parsed {len(sections):,} sections",
            )

            # ── 3. Chunk ─────────────────────────────────────────────────────
            chunk_task = progress.add_task("Chunking…", total=len(sections))
            all_chunks = []
            failed_entries: list[dict] = []

            for section in sections:
                try:
                    chunks = chunk_section(section)
                    all_chunks.extend(chunks)
                except Exception as exc:
                    result.errors += 1
                    msg = f"{section.section_number}: {exc}"
                    result.error_details.append(msg)
                    failed_entries.append(
                        {"section_number": section.section_number, "error": str(exc)}
                    )
                    logger.warning("Chunk error: %s", msg)
                progress.advance(chunk_task)

            result.chunks_created = len(all_chunks)
            progress.update(
                chunk_task,
                description=f"Chunked: {len(all_chunks):,} chunks",
            )

            # ── 4. Dedup (update mode skips unchanged hashes) ────────────────
            if mode == "update":
                existing_hashes = await store.get_existing_hashes(pool, source)
                to_embed = [
                    c for c in all_chunks if c.content_hash not in existing_hashes
                ]
                result.chunks_skipped = len(all_chunks) - len(to_embed)
            else:
                to_embed = all_chunks

            # ── 5. Embed ─────────────────────────────────────────────────────
            embed_task = progress.add_task("Embedding…", total=len(to_embed))
            embedded = []

            if to_embed:
                def _on_batch(done: int, _total: int) -> None:
                    progress.update(embed_task, completed=done)

                embedded = await embedder.embed_chunks(to_embed, on_batch=_on_batch)
                result.embeddings_generated = len(embedded)

            progress.update(embed_task, completed=len(to_embed))

            # ── 6. Store ─────────────────────────────────────────────────────
            store_task = progress.add_task("Storing…", total=len(embedded))
            if embedded:
                result.upserts = await store.upsert_chunks(pool, embedded)
            progress.update(store_task, completed=len(embedded))

    finally:
        await embedder.close()

    # ── Write error log ──────────────────────────────────────────────────────
    if failed_entries:
        _FAILED_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fail_path = _FAILED_DIR / f"{source}_{ts}.jsonl"
        with open(fail_path, "w", encoding="utf-8") as fh:
            for entry in failed_entries:
                fh.write(json.dumps(entry) + "\n")
        console.print(
            f"  [yellow]WARN: {result.errors} error(s) logged to {fail_path}[/yellow]"
        )

    return result
