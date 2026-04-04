import asyncio
import logging
import subprocess
from pathlib import Path

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
