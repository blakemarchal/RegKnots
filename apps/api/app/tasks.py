import asyncio
import logging
import re
import subprocess
from pathlib import Path

import requests

from app.worker import celery

logger = logging.getLogger(__name__)

# packages/ingest/ relative to the repo root (apps/api/../../packages/ingest)
_INGEST_DIR = Path(__file__).resolve().parents[3] / "packages" / "ingest"


def _run_async(coro):
    """Run an async function from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task(name="app.tasks.update_regulations", bind=True, max_retries=2)
def update_regulations(self):
    """Run the ingest CLI to refresh all CFR/COLREGS/NVIC sources."""
    logger.info("Starting scheduled regulation update")
    try:
        result = subprocess.run(
            ["uv", "run", "python", "-m", "ingest.cli", "--all", "--update"],
            cwd=_INGEST_DIR,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )
        if result.returncode != 0:
            logger.error("Ingest CLI failed (rc=%d): %s", result.returncode, result.stderr)
            raise RuntimeError(f"ingest.cli exited {result.returncode}: {result.stderr[:500]}")
        logger.info("Regulation update complete: %s", result.stdout[-500:] if result.stdout else "")
    except subprocess.TimeoutExpired:
        logger.error("Regulation update timed out after 1 hour")
        raise
    except Exception as exc:
        logger.exception("Regulation update failed: %s", exc)
        raise self.retry(exc=exc, countdown=3600)


@celery.task(name="app.tasks.send_trial_expiring_reminders")
def send_trial_expiring_reminders():
    """Send reminder emails to users whose trial expires in ~3 days."""
    _run_async(_send_trial_reminders_async())


async def _send_trial_reminders_async():
    import asyncpg
    from app.config import settings
    from app.email import send_trial_expiring_email

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT id, email, full_name, message_count
            FROM users
            WHERE subscription_tier = 'free'
              AND trial_reminder_sent = FALSE
              AND trial_ends_at BETWEEN NOW() + INTERVAL '2 days' AND NOW() + INTERVAL '4 days'
            """
        )
        for row in rows:
            try:
                await send_trial_expiring_email(row["email"], row["full_name"] or "", row["message_count"])
                await conn.execute(
                    "UPDATE users SET trial_reminder_sent = TRUE WHERE id = $1",
                    row["id"],
                )
                logger.info("Sent trial expiring reminder to %s", row["email"])
            except Exception as exc:
                logger.error("Failed to send trial reminder to %s: %s", row["email"], exc)
    finally:
        await conn.close()


@celery.task(name="app.tasks.reindex_vector_embeddings", bind=True, max_retries=1)
def reindex_vector_embeddings(self):
    """Rebuild the HNSW vector index to prevent stale results after bulk inserts."""
    logger.info("Starting HNSW index rebuild")
    try:
        _run_async(_reindex_async())
        logger.info("HNSW index rebuild complete")
    except Exception as exc:
        logger.exception("HNSW index rebuild failed: %s", exc)
        raise self.retry(exc=exc, countdown=600)


async def _reindex_async():
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("REINDEX INDEX idx_regulations_embedding")
    finally:
        await conn.close()


@celery.task(name="app.tasks.check_solas_supplements")
def check_solas_supplements():
    """Check for new IMO amendments (SOLAS and STCW) from public notice sources.

    Task name retained for backward compatibility with celery beat schedule.
    """
    _run_async(_check_imo_amendments_async())


# Sources scraped for new IMO amendment references.
# Each entry lists the conventions whose references we expect on that page.
_IMO_AMENDMENT_SOURCES = [
    {
        "name": "Marshall Islands Marine Notices",
        "url": "https://www.register-iri.com/maritime/marine-notices/",
        "keywords": ["SOLAS", "STCW"],
    },
    {
        "name": "IMO Meeting Summaries",
        "url": "https://www.imo.org/en/MediaCentre/MeetingSummaries",
        "keywords": ["SOLAS", "STCW"],
    },
    {
        "name": "IMO Maritime Safety Committee",
        "url": "https://www.imo.org/en/MediaCentre/MeetingSummaries/Pages/MSC-default.aspx",
        "keywords": ["SOLAS", "STCW"],
    },
]

# Matches MSC resolution references like MSC.520(106), MSC.550(108)
_MSC_RE = re.compile(r"MSC\.\d+\(\d+\)")


def _classify_amendment(context_text: str) -> list[str]:
    """Return a list of conventions the reference appears to relate to."""
    upper = context_text.upper()
    conventions: list[str] = []
    if "SOLAS" in upper:
        conventions.append("SOLAS")
    if "STCW" in upper:
        conventions.append("STCW")
    return conventions


async def _check_imo_amendments_async():
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Get existing supplement references from the DB for both conventions.
        solas_rows = await conn.fetch(
            "SELECT DISTINCT section_number FROM regulations WHERE source = 'solas_supplement'"
        )
        stcw_rows = await conn.fetch(
            "SELECT DISTINCT section_number FROM regulations WHERE source = 'stcw_supplement'"
        )
        existing_refs: set[str] = set()
        for r in solas_rows:
            existing_refs |= set(_MSC_RE.findall(r["section_number"] or ""))
        for r in stcw_rows:
            existing_refs |= set(_MSC_RE.findall(r["section_number"] or ""))

        new_findings: list[dict] = []

        for source in _IMO_AMENDMENT_SOURCES:
            try:
                resp = requests.get(
                    source["url"],
                    timeout=30,
                    headers={"User-Agent": "RegKnots IMO Monitor/1.0"},
                )
                resp.raise_for_status()
                text = resp.text

                keywords = source.get("keywords", ["SOLAS", "STCW"])
                # Collect lines that mention any monitored convention.
                relevant_chunks = [
                    chunk for chunk in text.split("\n")
                    if any(kw.upper() in chunk.upper() for kw in keywords)
                ]
                relevant_text = " ".join(relevant_chunks)
                refs = set(_MSC_RE.findall(relevant_text))

                for ref in refs:
                    if ref in existing_refs:
                        continue
                    # Look at a wider window around each hit to classify it.
                    idx = relevant_text.find(ref)
                    window = relevant_text[max(0, idx - 200): idx + 200] if idx >= 0 else relevant_text
                    conventions = _classify_amendment(window) or ["Unknown"]
                    new_findings.append({
                        "ref": ref,
                        "source_name": source["name"],
                        "source_url": source["url"],
                        "conventions": conventions,
                    })

            except Exception as exc:
                logger.warning("Failed to scrape %s: %s", source["name"], exc)

        if new_findings:
            _send_amendment_alert(new_findings)
        else:
            logger.info("IMO amendment check: no new references found")

    finally:
        await conn.close()


def _send_amendment_alert(findings: list[dict]):
    """Send alert email about new SOLAS/STCW supplement references."""
    try:
        import resend
        from app.config import settings
        resend.api_key = settings.resend_api_key

        # Deduplicate by ref while merging sources + conventions.
        merged: dict[str, dict] = {}
        for f in findings:
            ref = f["ref"]
            if ref not in merged:
                merged[ref] = {
                    "ref": ref,
                    "sources": [],
                    "conventions": set(),
                }
            merged[ref]["sources"].append((f["source_name"], f["source_url"]))
            merged[ref]["conventions"].update(f.get("conventions", []))

        items_html = ""
        for entry in merged.values():
            conv_label = ", ".join(sorted(entry["conventions"])) or "Unknown"
            source_links = " · ".join(
                f'<a href="{url}">{name}</a>' for name, url in entry["sources"]
            )
            items_html += (
                f"<li><strong>{entry['ref']}</strong> "
                f"<em>[{conv_label}]</em> — {source_links}</li>"
            )

        conv_summary = set()
        for entry in merged.values():
            conv_summary |= entry["conventions"]
        scope = ", ".join(sorted(conv_summary)) if conv_summary else "IMO"

        resend.Emails.send({
            "from": "RegKnots <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": "New IMO amendments detected — RegKnots",
            "html": (
                f"<h2>New IMO Amendment References Detected ({scope})</h2>"
                f"<p>The following MSC resolution references were found that are not yet "
                f"in the RegKnots database. Each is tagged with the convention(s) it "
                f"appears to relate to based on surrounding context:</p>"
                f"<ul>{items_html}</ul>"
                f"<p><strong>Action required:</strong> Download and review the source PDFs, "
                f"then ingest manually into <code>solas_supplement</code> or "
                f"<code>stcw_supplement</code> as appropriate.</p>"
                f"<p>Do NOT auto-ingest — manual review is required to verify copyright "
                f"compliance and correct convention attribution.</p>"
            ),
        })
        logger.info(
            "Sent IMO amendment alert for %d unique references (%s)",
            len(merged), scope,
        )
    except Exception as exc:
        logger.error("Failed to send IMO amendment alert email: %s", exc)
