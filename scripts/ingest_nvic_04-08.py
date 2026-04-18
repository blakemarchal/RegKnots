"""One-off: ingest NVIC 04-08 Ch-2 using existing ingest scaffolding.

Uses the NVIC adapter's _parse_nvic_pdf() + the shared run_pdf_pipeline(),
identical code path to the batched weekly scrape. Bypasses discovery only,
because the USCG NVIC index page never indexed this document — Akamai WAF
blocks direct PDF downloads from the VPS, and a manual seamenschurch.org
mirror copy was scp'd into data/raw/nvic/.

Run on the VPS after the PDF is in place:
    cd /opt/RegKnots/packages/ingest
    uv run python /tmp/ingest_nvic_04-08.py
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

import asyncpg
from rich.console import Console

sys.path.insert(0, "/opt/RegKnots/packages/ingest")

from ingest.config import settings
from ingest.pdf_pipeline import run_pdf_pipeline
from ingest.sources.nvic import _parse_nvic_pdf, NvicMeta

PDF_PATH = Path("/opt/RegKnots/data/raw/nvic/NVIC 04-08 Ch-2.pdf")

META = NvicMeta(
    number="04-08 Ch-2",
    title="Medical and Physical Evaluation Guidelines for Merchant Mariner Credentials",
    effective_date=date(2016, 4, 25),
    pdf_url="https://www.dco.uscg.mil/Portals/9/DCO%20Documents/5p/5ps/NVIC/2008/NVIC%2004-08%20Ch-2.pdf",
)


def section_loader():
    return _parse_nvic_pdf(PDF_PATH, META)


async def main():
    console = Console()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        result = await run_pdf_pipeline(
            source="nvic",
            mode="fresh",
            section_loader=section_loader,
            source_date=META.effective_date,
            pool=pool,
            cfg=settings,
            console=console,
            enrich=False,
        )
        console.print(
            f"[green]Done[/green]: {result.upserts} chunks upserted "
            f"({result.sections_found} sections, "
            f"{result.embeddings_generated} embeddings, "
            f"{result.errors} errors)"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
