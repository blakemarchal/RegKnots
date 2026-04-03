import logging
import subprocess
from pathlib import Path

from app.worker import celery

logger = logging.getLogger(__name__)

# packages/ingest/ relative to the repo root (apps/api/../../packages/ingest)
_INGEST_DIR = Path(__file__).resolve().parents[3] / "packages" / "ingest"


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
