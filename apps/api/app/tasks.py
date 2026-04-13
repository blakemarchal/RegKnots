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

# Sources that can actually run unattended (fetch from public APIs / scrapers).
# Sources NOT in this list (colregs, solas, solas_supplement, stcw,
# stcw_supplement, ism) require local PDF / pre-extracted text files that
# must be placed manually — they are MANUAL INGEST ONLY and intentionally
# left out of the scheduled task. The SOLAS/STCW supplement DETECTION is
# covered separately by `check_solas_supplements`, which emails an alert
# when new MSC references appear so a human can review + ingest manually.
_AUTOMATABLE_SOURCES: list[str] = [
    "cfr_33",
    "cfr_46",
    "cfr_49",
    "nvic",
]


def _run_async(coro):
    """Run an async function from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task(name="app.tasks.update_regulations", bind=True, max_retries=2)
def update_regulations(self):
    """Refresh every source that can run unattended.

    Runs each automatable source in its own CLI invocation so that:
      - A failure in one source doesn't abort the others.
      - The CLI's per-source auto-notification hook fires once per source
        that actually changed (instead of a single lump-sum notification).

    Sources that require local files (SOLAS, STCW, COLREGs, ISM, and the
    two supplements) are intentionally NOT run here — they're manual ingest
    only. See _AUTOMATABLE_SOURCES at module top.
    """
    logger.info(
        "Starting scheduled regulation update for %d automatable sources: %s",
        len(_AUTOMATABLE_SOURCES), ", ".join(_AUTOMATABLE_SOURCES),
    )

    failures: list[tuple[str, str]] = []
    for source in _AUTOMATABLE_SOURCES:
        logger.info("Running ingest for source=%s", source)
        try:
            result = subprocess.run(
                ["uv", "run", "python", "-m", "ingest.cli", "--source", source, "--update"],
                cwd=_INGEST_DIR,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour per source
            )
            if result.returncode != 0:
                logger.error(
                    "Ingest failed for %s (rc=%d): %s",
                    source, result.returncode, result.stderr[-500:],
                )
                failures.append((source, f"rc={result.returncode}"))
                continue
            logger.info(
                "Ingest complete for %s: %s",
                source, result.stdout[-300:] if result.stdout else "(no output)",
            )
        except subprocess.TimeoutExpired:
            logger.error("Ingest for %s timed out after 1 hour", source)
            failures.append((source, "timeout"))
        except Exception as exc:
            logger.exception("Ingest for %s raised: %s", source, exc)
            failures.append((source, str(exc)[:200]))

    if failures:
        # Retry the whole task if any source failed — the CLI is idempotent
        # so sources that already succeeded will short-circuit on the retry.
        msg = ", ".join(f"{s}: {e}" for s, e in failures)
        logger.warning("Regulation update had %d failures: %s", len(failures), msg)
        raise self.retry(exc=RuntimeError(msg), countdown=3600)

    logger.info("Scheduled regulation update complete — all sources up to date")


@celery.task(name="app.tasks.send_trial_expiring_reminders")
def send_trial_expiring_reminders():
    """Send reminder emails to users whose trial expires in ~3 days."""
    _run_async(_send_trial_reminders_async())


async def _send_trial_reminders_async():
    import asyncpg
    from app.config import settings
    from app.email import (
        RESEND_THROTTLE_SECONDS,
        send_trial_expiring_email,
        send_with_throttle,
    )

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
        total = len(rows)
        for idx, row in enumerate(rows):
            email = row["email"]
            try:
                await send_with_throttle(
                    lambda email=email, name=(row["full_name"] or ""), count=row["message_count"]:
                        send_trial_expiring_email(email, name, count),
                    label=email,
                )
                await conn.execute(
                    "UPDATE users SET trial_reminder_sent = TRUE WHERE id = $1",
                    row["id"],
                )
                logger.info("Sent trial expiring reminder to %s", email)
            except Exception as exc:
                logger.error("Failed to send trial reminder to %s: %s", email, exc)
            # Stay under Resend's 5 req/s limit even on failure.
            if idx < total - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)
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
                    headers={"User-Agent": "RegKnot IMO Monitor/1.0"},
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


@celery.task(name="app.tasks.send_credential_expiry_reminders")
def send_credential_expiry_reminders():
    """Send expiry reminder emails for credentials approaching their expiry date.

    Checks each user's notification_preferences for enabled cert_expiry_reminders
    and cert_expiry_days (90, 30, 7). Sends one email per credential per threshold
    and marks the corresponding reminder_sent flag to avoid duplicates.
    """
    _run_async(_send_credential_expiry_reminders_async())


async def _send_credential_expiry_reminders_async():
    import asyncpg
    from app.config import settings
    from app.email import (
        RESEND_THROTTLE_SECONDS,
        send_credential_expiry_email,
        send_with_throttle,
    )

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Fetch credentials with upcoming expiry for users who have reminders enabled
        rows = await conn.fetch(
            """
            SELECT
                c.id AS cred_id,
                c.title,
                c.expiry_date,
                c.reminder_sent_90,
                c.reminder_sent_30,
                c.reminder_sent_7,
                u.id AS user_id,
                u.email,
                u.full_name,
                u.notification_preferences
            FROM user_credentials c
            JOIN users u ON u.id = c.user_id
            WHERE c.expiry_date IS NOT NULL
              AND c.expiry_date <= CURRENT_DATE + INTERVAL '91 days'
            """
        )

        sent_count = 0
        for row in rows:
            prefs = row["notification_preferences"] or {}
            if isinstance(prefs, str):
                import json
                prefs = json.loads(prefs)

            if not prefs.get("cert_expiry_reminders", True):
                continue

            enabled_days = prefs.get("cert_expiry_days", [90, 30, 7])
            days_left = (row["expiry_date"] - __import__("datetime").date.today()).days

            # Determine which threshold to fire
            thresholds = [
                (90, "reminder_sent_90"),
                (30, "reminder_sent_30"),
                (7, "reminder_sent_7"),
            ]

            for threshold, flag_col in thresholds:
                if threshold not in enabled_days:
                    continue
                if row[flag_col]:
                    continue
                if days_left > threshold:
                    continue

                # Send reminder
                try:
                    await send_with_throttle(
                        lambda email=row["email"], name=(row["full_name"] or ""),
                               title=row["title"], days=days_left:
                            send_credential_expiry_email(email, name, title, days),
                        label=f"{row['email']}:{row['title']}:{threshold}d",
                    )
                    await conn.execute(
                        f"UPDATE user_credentials SET {flag_col} = TRUE WHERE id = $1",
                        row["cred_id"],
                    )
                    sent_count += 1
                    logger.info(
                        "Sent %dd credential expiry reminder to %s for '%s'",
                        threshold, row["email"], row["title"],
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to send credential expiry reminder to %s: %s",
                        row["email"], exc,
                    )

                await asyncio.sleep(RESEND_THROTTLE_SECONDS)
                break  # Only send one reminder per credential per run

        logger.info("Credential expiry reminder run complete: %d emails sent", sent_count)
    finally:
        await conn.close()


@celery.task(name="app.tasks.send_regulation_digest")
def send_regulation_digest():
    """Send weekly/biweekly regulation change digest emails to opted-in users."""
    _run_async(_send_regulation_digest_async())


async def _send_regulation_digest_async():
    import asyncpg
    import json
    from app.config import settings
    from app.email import (
        RESEND_THROTTLE_SECONDS,
        send_regulation_digest_email,
        send_with_throttle,
    )

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Get recent regulation notifications (last 14 days covers both weekly and biweekly)
        notifications = await conn.fetch(
            """
            SELECT title, body, source, created_at
            FROM notifications
            WHERE notification_type = 'regulation_update'
              AND is_active = true
              AND created_at > NOW() - INTERVAL '14 days'
            ORDER BY created_at DESC
            """
        )

        if not notifications:
            logger.info("No regulation updates in the last 14 days — skipping digest")
            return

        updates = [
            {
                "title": n["title"],
                "body": n["body"],
                "source": n["source"],
                "created_at": n["created_at"].isoformat(),
            }
            for n in notifications
        ]

        # Get users opted in to digest
        users = await conn.fetch(
            """
            SELECT id, email, full_name, notification_preferences
            FROM users
            WHERE subscription_tier != 'free'
               OR trial_ends_at > NOW()
            """
        )

        sent_count = 0
        for idx, user in enumerate(users):
            prefs = user["notification_preferences"] or {}
            if isinstance(prefs, str):
                prefs = json.loads(prefs)

            if not prefs.get("reg_change_digest", True):
                continue

            # For biweekly users, only send every other week
            freq = prefs.get("reg_digest_frequency", "weekly")
            if freq == "biweekly":
                from datetime import datetime
                week_num = datetime.utcnow().isocalendar()[1]
                if week_num % 2 != 0:
                    continue

            try:
                await send_with_throttle(
                    lambda email=user["email"], name=(user["full_name"] or ""),
                           u=updates:
                        send_regulation_digest_email(email, name, u),
                    label=f"digest:{user['email']}",
                )
                sent_count += 1
            except Exception as exc:
                logger.error("Failed to send digest to %s: %s", user["email"], exc)

            if idx < len(users) - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)

        logger.info("Regulation digest run complete: %d emails sent", sent_count)
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
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": "New IMO amendments detected — RegKnot",
            "html": (
                f"<h2>New IMO Amendment References Detected ({scope})</h2>"
                f"<p>The following MSC resolution references were found that are not yet "
                f"in the RegKnot database. Each is tagged with the convention(s) it "
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
