"""
Manual regulation section add / replace CLI.

For use when the automated ingest pipeline missed a section (OCR gaps,
copyright issues, or a section only available as a scanned page). Takes
raw text, cleans it, chunks it with the same tiktoken chunker the main
pipeline uses, embeds it via text-embedding-3-small, and upserts it into
the `regulations` table.

Existing chunks for the given (source, section_number) are deleted first
so replacing a truncated section cleans up stale chunk rows.

Usage
-----
    # From a text file
    uv run python -m ingest.manual_add \\
        --source ism \\
        --section-number "ISM 13" \\
        --section-title "Certification and Periodical Verification" \\
        --text-file data/raw/ism/section_13.txt

    # From inline text (short sections)
    uv run python -m ingest.manual_add \\
        --source ism \\
        --section-number "ISM Part B" \\
        --section-title "Part B — Certification and Verification" \\
        --text "Placeholder header for Part B"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import date
from pathlib import Path

import asyncpg
from rich.console import Console

from ingest import store
from ingest.chunker import chunk_section
from ingest.config import settings
from ingest.embedder import EmbedderClient
from ingest.models import PDF_SOURCES, SOURCE_TO_TITLE, Section

logger = logging.getLogger(__name__)

_ALL_SOURCES = list(SOURCE_TO_TITLE.keys()) + PDF_SOURCES


# ── Text cleaning ────────────────────────────────────────────────────────────

# Image/figure placeholders commonly left by PDF-to-text tools
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)
# Repeated dashes used as visual separators
_DASH_LINE = re.compile(r"^[\-\u2013\u2014]{4,}\s*$", re.MULTILINE)
# IMO eBook delivery watermark lines
_WATERMARK_LINE = re.compile(
    r"^.*(?:Delivered by|Base to:).*$", re.MULTILINE,
)
# Short alphanumeric order/license number lines
_ORDER_NUMBER_LINE = re.compile(
    r"^\s*(?:[A-Z0-9]{5,10}|[A-Z]{1,3}:[A-Z]\s*[A-Z]?)\s*$", re.MULTILINE,
)


def clean_text(text: str) -> str:
    """Remove common PDF/OCR artefacts from raw section text.

    Mirrors the cleaning patterns used by existing source adapters
    (solas.py, stcw.py, solas_supplement.py) so manually-added content
    matches the automated pipeline's quality.
    """
    # 1. Strip null bytes (PostgreSQL rejects U+0000)
    text = text.replace("\x00", "")
    # 2. Drop figure/image placeholders
    text = _IMAGE_PLACEHOLDER.sub("", text)
    # 3. Drop dash separator lines
    text = _DASH_LINE.sub("", text)
    # 4. Drop IMO eBook watermarks and order numbers
    text = _WATERMARK_LINE.sub("", text)
    text = _ORDER_NUMBER_LINE.sub("", text)
    # 5. Normalise bare page number lines
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.MULTILINE)
    # 6. Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Title number inference ───────────────────────────────────────────────────

def _infer_title_number(source: str) -> int:
    """Map a source tag to its CFR title number (0 for non-CFR sources)."""
    return SOURCE_TO_TITLE.get(source, 0)


# ── DB operations ────────────────────────────────────────────────────────────

async def _delete_existing_section(
    pool: asyncpg.Pool,
    source: str,
    section_number: str,
) -> int:
    """Remove any existing chunks for this (source, section_number).

    Returns the number of rows deleted. This prevents stale chunks from
    lingering when the replacement has fewer chunks than the original.
    """
    result = await pool.execute(
        "DELETE FROM regulations WHERE source = $1 AND section_number = $2",
        source,
        section_number,
    )
    # asyncpg returns the command tag like "DELETE 5"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


# ── Manual add core ──────────────────────────────────────────────────────────

async def manual_add(
    source: str,
    section_number: str,
    section_title: str,
    raw_text: str,
    parent_section_number: str | None,
    up_to_date_as_of: date,
    title_number: int,
    console: Console,
) -> int:
    """Clean → chunk → embed → upsert a single section.

    Returns a non-zero exit code on failure.
    """
    if not settings.openai_api_key:
        console.print(
            "[bold red]Error:[/bold red] OPENAI_API_KEY not set in .env"
        )
        return 1

    # 1. Clean
    cleaned = clean_text(raw_text)
    if not cleaned:
        console.print(
            "[red]Cleaned text is empty — nothing to ingest.[/red]"
        )
        return 1
    char_count = len(cleaned)
    console.print(
        f"  [cyan]Cleaned text:[/cyan] {char_count:,} chars"
    )

    # 2. Build a Section and chunk it
    section = Section(
        source=source,
        title_number=title_number,
        section_number=section_number,
        section_title=section_title,
        full_text=cleaned,
        up_to_date_as_of=up_to_date_as_of,
        parent_section_number=parent_section_number,
    )

    chunks = chunk_section(section)
    if not chunks:
        console.print(
            "[red]Chunker produced 0 chunks — refusing to write empty section.[/red]"
        )
        return 1
    console.print(
        f"  [cyan]Chunks:[/cyan] {len(chunks)} "
        f"(token counts: "
        + ", ".join(str(c.token_count) for c in chunks[:6])
        + ("…" if len(chunks) > 6 else "")
        + ")"
    )

    # 3. Embed
    embedder = EmbedderClient(api_key=settings.openai_api_key)
    try:
        embedded = await embedder.embed_chunks(chunks)
    finally:
        await embedder.close()
    console.print(
        f"  [cyan]Embeddings:[/cyan] {len(embedded)} vectors generated"
    )

    # 4. Delete any existing chunks for this section, then upsert
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        deleted = await _delete_existing_section(pool, source, section_number)
        if deleted:
            console.print(
                f"  [yellow]Removed {deleted} existing chunk(s) for this section[/yellow]"
            )
        upserts = await store.upsert_chunks(pool, embedded)
    finally:
        await pool.close()

    console.print(
        f"[green]OK[/green] Added {upserts} chunk(s) "
        f"for [bold]{source}[/bold] / [bold]{section_number}[/bold] "
        f"({char_count:,} chars, {len(chunks)} chunks)"
    )
    return 0


# ── CLI entry point ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.manual_add",
        description=(
            "Manually add or replace a single regulation section. Cleans "
            "the text, chunks it with the shared tiktoken chunker, embeds "
            "it via OpenAI text-embedding-3-small, and upserts into the "
            "regulations table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m ingest.manual_add \\
      --source ism --section-number "ISM 13" \\
      --section-title "Certification and Periodical Verification" \\
      --text-file data/raw/ism/section_13.txt

  uv run python -m ingest.manual_add \\
      --source ism --section-number "ISM Part B" \\
      --section-title "Part B — Certification and Verification" \\
      --text "Placeholder header for Part B"
        """,
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=_ALL_SOURCES,
        metavar="SOURCE",
        help=f"Source tag: {', '.join(_ALL_SOURCES)}",
    )
    parser.add_argument(
        "--section-number",
        required=True,
        metavar="NUMBER",
        help="Canonical section_number (e.g. 'ISM 13')",
    )
    parser.add_argument(
        "--section-title",
        required=True,
        metavar="TITLE",
        help="Human-readable section title",
    )

    text_grp = parser.add_mutually_exclusive_group(required=True)
    text_grp.add_argument(
        "--text-file",
        metavar="PATH",
        type=Path,
        help="Path to a UTF-8 text file containing the section content",
    )
    text_grp.add_argument(
        "--text",
        metavar="STRING",
        help="Inline text content (for short sections)",
    )

    parser.add_argument(
        "--parent",
        metavar="PARENT",
        default=None,
        help="Optional parent_section_number (e.g. 'ISM Part B')",
    )
    parser.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        default=None,
        help="Optional up_to_date_as_of date; defaults to today",
    )
    parser.add_argument(
        "--title-number",
        type=int,
        default=None,
        help="Override title_number; defaults to 33/46/49 for CFR, 0 otherwise",
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

    console = Console()

    # Load text
    if args.text_file:
        if not args.text_file.exists():
            console.print(
                f"[red]--text-file not found: {args.text_file}[/red]"
            )
            sys.exit(1)
        raw_text = args.text_file.read_text(encoding="utf-8", errors="replace")
    else:
        raw_text = args.text

    # Resolve up_to_date_as_of
    if args.as_of:
        try:
            up_to_date_as_of = date.fromisoformat(args.as_of)
        except ValueError:
            console.print(
                f"[red]--as-of must be YYYY-MM-DD, got {args.as_of!r}[/red]"
            )
            sys.exit(1)
    else:
        up_to_date_as_of = date.today()

    title_number = (
        args.title_number
        if args.title_number is not None
        else _infer_title_number(args.source)
    )

    console.rule("[bold]Manual regulation add")
    console.print(f"  Source           : [cyan]{args.source}[/cyan]")
    console.print(f"  Section number   : [cyan]{args.section_number}[/cyan]")
    console.print(f"  Section title    : {args.section_title}")
    console.print(f"  Parent           : {args.parent or '-'}")
    console.print(f"  Title number     : {title_number}")
    console.print(f"  As of            : {up_to_date_as_of}")
    console.print(f"  Raw text length  : {len(raw_text):,} chars")
    console.print()

    rc = asyncio.run(manual_add(
        source=args.source,
        section_number=args.section_number,
        section_title=args.section_title,
        raw_text=raw_text,
        parent_section_number=args.parent,
        up_to_date_as_of=up_to_date_as_of,
        title_number=title_number,
        console=console,
    ))

    if rc == 0:
        # Re-run the audit for just this source so the user immediately
        # sees whether the section is now present in the DB. The audit
        # module handles its own DB connection, so we just invoke it.
        try:
            from ingest.audit import audit_source, render_reports

            async def _reaudit() -> None:
                dsn = settings.database_url.replace(
                    "postgresql+asyncpg://", "postgresql://"
                )
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
                try:
                    audit = await audit_source(pool, args.source)
                finally:
                    await pool.close()
                render_reports(console, [audit])

            console.print()
            console.rule("[bold]Post-add audit")
            asyncio.run(_reaudit())
        except Exception as exc:
            logger.warning("Post-add audit failed: %s", exc)

    sys.exit(rc)


if __name__ == "__main__":
    main()
