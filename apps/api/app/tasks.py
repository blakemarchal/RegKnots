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


@celery.task(name="app.tasks.check_solas_supplements")
def check_solas_supplements():
    """Check for new SOLAS supplements from public marine notice sources."""
    _run_async(_check_solas_async())


_SOLAS_SOURCES = [
    {
        "name": "Marshall Islands Marine Notices",
        "url": "https://www.register-iri.com/maritime/marine-notices/",
    },
    {
        "name": "IMO Meeting Summaries",
        "url": "https://www.imo.org/en/MediaCentre/MeetingSummaries",
    },
]

# Matches MSC resolution references like MSC.520(106), MSC.550(108)
_MSC_RE = re.compile(r"MSC\.\d+\(\d+\)")


async def _check_solas_async():
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Get existing supplement references from DB
        rows = await conn.fetch(
            "SELECT DISTINCT section_number FROM regulations WHERE source = 'solas_supplement'"
        )
        existing_refs = {r["section_number"] for r in rows}

        new_findings = []

        for source in _SOLAS_SOURCES:
            try:
                resp = requests.get(source["url"], timeout=30, headers={
                    "User-Agent": "RegKnots SOLAS Monitor/1.0"
                })
                resp.raise_for_status()
                text = resp.text

                # Find MSC resolution references in SOLAS-related content
                solas_chunks = [
                    chunk for chunk in text.split("\n")
                    if "SOLAS" in chunk.upper() or "solas" in chunk.lower()
                ]
                solas_text = " ".join(solas_chunks)
                solas_refs = set(_MSC_RE.findall(solas_text))

                for ref in solas_refs:
                    if ref not in existing_refs:
                        new_findings.append({
                            "ref": ref,
                            "source_name": source["name"],
                            "source_url": source["url"],
                        })

            except Exception as exc:
                logger.warning("Failed to scrape %s: %s", source["name"], exc)

        if new_findings:
            _send_solas_alert(new_findings)
        else:
            logger.info("SOLAS supplement check: no new references found")

    finally:
        await conn.close()


def _send_solas_alert(findings: list[dict]):
    """Send alert email about new SOLAS supplement references."""
    try:
        import resend
        from app.config import settings
        resend.api_key = settings.resend_api_key

        items_html = ""
        for f in findings:
            items_html += (
                f"<li><strong>{f['ref']}</strong> — found on "
                f"<a href=\"{f['source_url']}\">{f['source_name']}</a></li>"
            )

        resend.Emails.send({
            "from": "RegKnots <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": "New SOLAS supplement detected",
            "html": (
                f"<h2>New SOLAS Supplement References Detected</h2>"
                f"<p>The following MSC resolution references were found that are not yet in the RegKnots database:</p>"
                f"<ul>{items_html}</ul>"
                f"<p><strong>Action required:</strong> Download and review the source PDFs, then ingest manually "
                f"if they contain new SOLAS amendments.</p>"
                f"<p>Do NOT auto-ingest — manual review is required to verify copyright compliance.</p>"
            ),
        })
        logger.info("Sent SOLAS supplement alert for %d new references", len(findings))
    except Exception as exc:
        logger.error("Failed to send SOLAS alert email: %s", exc)
