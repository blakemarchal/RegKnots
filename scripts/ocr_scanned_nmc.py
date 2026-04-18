"""One-off: OCR the 4 scanned NMC policy PDFs via Claude Vision.

The regular nmc adapter's pdfplumber pipeline returns zero text on these
four image-only policy letters. They were skipped during the initial
nmc_policy ingest. This script rasterizes each PDF page via pypdfium2,
sends the images to Claude Sonnet as a transcription task, then feeds
the resulting plain text through the SAME NMC adapter enrichment helpers
(_DOC_META, _select_aliases, _title_with_aliases) and the SAME shared
chunker / embedder / store pipeline used by the main ingest.

This preserves enrichment parity with the already-ingested nmc_policy
documents — OCR-sourced chunks are indistinguishable from pdfplumber-
sourced chunks at retrieval time.

Run on the VPS (has the Anthropic key + poppler + pypdfium2 via the
ingest venv):

    cd /opt/RegKnots/packages/ingest
    uv run python /tmp/ocr_scanned_nmc.py
"""
import asyncio
import base64
import io
import logging
import sys
from datetime import date
from pathlib import Path

import asyncpg
import pypdfium2 as pdfium
from anthropic import AsyncAnthropic
from rich.console import Console

sys.path.insert(0, "/opt/RegKnots/packages/ingest")

from ingest import store
from ingest.chunker import chunk_section
from ingest.config import settings
from ingest.embedder import EmbedderClient
from ingest.models import Section
from ingest.sources.nmc import (
    _DOC_META,
    _infer_effective_date,
    _select_aliases,
    _title_with_aliases,
    TITLE_NUMBER,
)

logger = logging.getLogger(__name__)

NMC_DIR = Path("/opt/RegKnots/data/raw/nmc")
TARGETS = [
    "04-03.pdf",
    "11-12.pdf",
    "11-15.pdf",
    "Liftboat Policy Letter_Signed 20150406.pdf",
]

# Claude Sonnet is plenty for OCR-style transcription. Opus would be overkill.
_VISION_MODEL = "claude-sonnet-4-6"
_DPI = 200  # matches the DPI used by apps/api/app/routers/documents.py Vision path

_TRANSCRIBE_PROMPT = """\
Transcribe this USCG Coast Guard policy document exactly as it appears, page by page.

Rules:
- Preserve all headings, paragraph numbering (1., a., i., etc.), and structure.
- Include signature blocks, subject lines, and reference lists.
- Do not paraphrase, summarize, or commentate. Faithful transcription only.
- Skip page numbers and running headers/footers.
- If a page has only images or is blank, write "[blank page]".
- Return plain text only — no markdown, no code fences, no explanation.
"""


def _rasterize_pdf(pdf_path: Path) -> list[bytes]:
    """Rasterize each page of the PDF to PNG bytes via pypdfium2.

    Uses pypdfium2 (already in the ingest venv) instead of pdf2image —
    same output, no extra dependency.
    """
    out: list[bytes] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        scale = _DPI / 72.0  # pdfium natural unit is 72 DPI
        for page in pdf:
            pil_image = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


async def _ocr_pdf(pdf_path: Path, client: AsyncAnthropic, console: Console) -> str:
    """Send all pages of one PDF to Claude Vision and return transcribed text."""
    page_images = _rasterize_pdf(pdf_path)
    console.print(f"    Rasterized [bold]{len(page_images)}[/bold] page(s)")

    content_blocks: list[dict] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode("ascii"),
            },
        }
        for png in page_images
    ]
    content_blocks.append({"type": "text", "text": _TRANSCRIBE_PROMPT})

    response = await client.messages.create(
        model=_VISION_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": content_blocks}],
    )

    if response.stop_reason == "max_tokens":
        console.print(
            "    [yellow]warning:[/yellow] Claude hit max_tokens — transcript may be truncated"
        )

    return response.content[0].text.strip()


async def _ingest_one(
    pdf_path: Path,
    client: AsyncAnthropic,
    embedder: EmbedderClient,
    pool: asyncpg.Pool,
    console: Console,
) -> int:
    """OCR one PDF, build an enriched Section, chunk/embed/store. Returns chunk count."""
    name = pdf_path.name
    meta = _DOC_META.get(name)
    if meta is None:
        console.print(f"  [red]{name}: no _DOC_META entry — skipping[/red]")
        return 0

    console.rule(f"[cyan]{name}")
    text = await _ocr_pdf(pdf_path, client, console)
    console.print(f"    OCR'd [bold]{len(text):,}[/bold] chars")

    if not text or text.lower().startswith("[blank"):
        console.print(f"  [yellow]{name}: OCR yielded no usable text — skipping[/yellow]")
        return 0

    aliases = _select_aliases(name, text)
    enriched_title = _title_with_aliases(meta["section_title"], aliases)
    console.print(
        f"    Aliases: {', '.join(aliases) if aliases else '(none)'}"
    )

    section = Section(
        source="nmc_policy",
        title_number=TITLE_NUMBER,
        section_number=meta["section_number"],
        section_title=enriched_title[:500],
        full_text=text,
        up_to_date_as_of=_infer_effective_date(name),
        parent_section_number=None,
    )

    chunks = chunk_section(section)
    if not chunks:
        console.print(f"  [yellow]{name}: chunker produced 0 chunks — skipping[/yellow]")
        return 0

    # Remove any prior rows for this section_number (safe re-run: the
    # 4 PDFs are not in the DB today, but if this script is re-run
    # after a previous successful pass, we want idempotency).
    await pool.execute(
        "DELETE FROM regulations WHERE source = $1 AND section_number = $2",
        "nmc_policy", meta["section_number"],
    )

    embedded = await embedder.embed_chunks(chunks)
    upserts = await store.upsert_chunks(pool, embedded)

    console.print(
        f"  [green]{name}:[/green] {len(chunks)} chunks → {upserts} upserts as "
        f"[bold]{meta['section_number']}[/bold]"
    )
    return upserts


async def main():
    logging.basicConfig(level=logging.WARNING)
    console = Console()

    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY not set in env[/red]")
        sys.exit(1)
    if not settings.openai_api_key:
        console.print("[red]OPENAI_API_KEY not set in env[/red]")
        sys.exit(1)

    missing = [t for t in TARGETS if not (NMC_DIR / t).exists()]
    if missing:
        console.print(f"[red]Missing PDFs: {missing}[/red]")
        sys.exit(1)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    embedder = EmbedderClient(api_key=settings.openai_api_key)
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)

    total = 0
    try:
        for name in TARGETS:
            try:
                total += await _ingest_one(
                    NMC_DIR / name, client, embedder, pool, console,
                )
            except Exception:
                console.print_exception()
    finally:
        await embedder.close()
        await client.close()

        # Rebuild HNSW so the newly-inserted vectors are discoverable.
        if total:
            console.print()
            console.print("[cyan]Rebuilding HNSW vector index...[/cyan]")
            async with pool.acquire() as conn:
                await conn.execute("REINDEX INDEX idx_regulations_embedding")
            console.print("[green]HNSW index rebuilt.[/green]")
        await pool.close()

    console.print()
    console.print(f"[bold green]Done[/bold green] — {total} total chunks upserted across {len(TARGETS)} documents")


if __name__ == "__main__":
    asyncio.run(main())
