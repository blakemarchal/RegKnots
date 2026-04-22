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
# stcw_supplement, ism, erg) require local PDF / pre-extracted text files
# that must be placed manually — they are MANUAL INGEST ONLY and
# intentionally left out of the scheduled task. When a fresh PDF is
# dropped on the server and the admin runs
#   `uv run python -m ingest.cli --source <name> --update`
# the notify hook fires alerts to opted-in users if content actually
# changed. The SOLAS/STCW supplement DETECTION is covered separately by
# `check_solas_supplements`, which emails an alert when new MSC
# references appear so a human can review + ingest manually.
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


# ── ERG release monitor ────────────────────────────────────────────────────
#
# The Emergency Response Guidebook is republished every ~4 years by US DOT
# PHMSA (current: ERG 2024, prior: ERG 2020, ERG 2016). Because it's a PDF
# we have to ingest manually, we want an early warning when a new edition
# is announced so we can swap the PDF on the server and run a manual
# `uv run python -m ingest.cli --source erg --update`.
#
# The task below scrapes the PHMSA ERG landing page monthly and compares
# any edition year it finds against the most recent ERG record's
# `up_to_date_as_of` in our DB. If a newer year is mentioned on PHMSA,
# hello@regknots.com gets a heads-up email with the detected year and
# source URL so an admin can manually procure the new PDF and re-ingest.

_ERG_SOURCES = [
    {
        "name": "PHMSA ERG landing page",
        "url": "https://www.phmsa.dot.gov/hazmat/erg/erg",
    },
    {
        "name": "PHMSA Emergency Response Guidebook",
        "url": "https://www.phmsa.dot.gov/hazmat/outreach-training/emergency-response-guidebook-erg",
    },
]

# Matches four-digit years reasonably constrained to ERG range (ERG 20XX).
# Captures just the year digits so we can compare numerically.
_ERG_YEAR_RE = re.compile(r"(?:ERG|Emergency Response Guidebook)[^0-9]{0,40}(20\d{2})", re.IGNORECASE)


@celery.task(name="app.tasks.check_erg_updates")
def check_erg_updates():
    """Check PHMSA for a new ERG edition and alert hello@regknots.com if found."""
    _run_async(_check_erg_updates_async())


async def _check_erg_updates_async():
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    try:
        # Figure out the newest ERG edition year we already have ingested.
        # We use the max year across `up_to_date_as_of` and `source_version`
        # so either dating convention catches the current edition.
        row = await conn.fetchrow(
            """
            SELECT
                MAX(EXTRACT(YEAR FROM up_to_date_as_of)::int) AS ud_year,
                MAX(source_version) AS sv
            FROM regulations
            WHERE source = 'erg'
            """
        )
        db_year: int | None = row["ud_year"] if row else None
        if row and row["sv"]:
            # Extract any 20XX year mentioned in source_version (e.g. "ERG 2024")
            m = re.search(r"20\d{2}", row["sv"])
            if m:
                sv_year = int(m.group(0))
                db_year = max(db_year or 0, sv_year)

        if not db_year:
            logger.warning("ERG monitor: no ERG records in DB — skipping check")
            return

        # Scrape PHMSA pages looking for a newer edition year.
        found_years: set[int] = set()
        scrape_hits: list[tuple[str, str, int]] = []  # (source_name, source_url, year)

        for source in _ERG_SOURCES:
            try:
                resp = requests.get(
                    source["url"],
                    timeout=30,
                    headers={"User-Agent": "RegKnot ERG Monitor/1.0"},
                )
                resp.raise_for_status()
                for m in _ERG_YEAR_RE.finditer(resp.text):
                    year = int(m.group(1))
                    if 2000 <= year <= 2099:
                        found_years.add(year)
                        if year > db_year:
                            scrape_hits.append((source["name"], source["url"], year))
            except Exception as exc:
                logger.warning("ERG monitor: failed to scrape %s: %s", source["name"], exc)

        max_found = max(found_years) if found_years else 0
        logger.info(
            "ERG monitor: db_year=%s scrape_max=%s all_found=%s",
            db_year, max_found, sorted(found_years),
        )

        if not scrape_hits:
            return

        # Alert — deduplicate by year + source
        _send_erg_release_alert(db_year, scrape_hits)

    finally:
        await conn.close()


def _send_erg_release_alert(db_year: int, hits: list[tuple[str, str, int]]):
    """Send heads-up email when PHMSA appears to list a newer ERG edition."""
    try:
        import resend
        from app.config import settings
        resend.api_key = settings.resend_api_key

        # Dedupe by (source, year); keep unique entries
        seen: set[tuple[str, int]] = set()
        unique_hits: list[tuple[str, str, int]] = []
        for name, url, year in hits:
            key = (name, year)
            if key in seen:
                continue
            seen.add(key)
            unique_hits.append((name, url, year))

        items_html = "".join(
            f"<li><strong>{year}</strong> — <a href='{url}'>{name}</a></li>"
            for name, url, year in unique_hits
        )
        newest = max(y for _, _, y in unique_hits)

        resend.Emails.send({
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": f"Possible new ERG edition detected ({newest}) — RegKnot",
            "html": (
                f"<h2>Possible new ERG edition detected</h2>"
                f"<p>The PHMSA ERG pages now mention a year ({newest}) newer than "
                f"what's ingested in the RegKnot database (currently: {db_year}).</p>"
                f"<p>Detected references:</p>"
                f"<ul>{items_html}</ul>"
                f"<p><strong>Action required:</strong> If a new ERG edition is "
                f"actually out, download the PDF from PHMSA, place it in "
                f"<code>data/raw/erg/</code>, update the adapter if needed, and "
                f"run <code>uv run python -m ingest.cli --source erg --update</code>. "
                f"Opted-in users will receive immediate alerts when content changes.</p>"
                f"<p>If the year is a false positive (e.g. a historical reference "
                f"on the page), no action is needed — the monitor will keep checking.</p>"
            ),
        })
        logger.info("Sent ERG release alert: db_year=%s newest_found=%s", db_year, newest)
    except Exception as exc:
        logger.error("Failed to send ERG release alert email: %s", exc)


# ── NMC document monitor (ADMIN-ONLY, weekly) ───────────────────────────
#
# The USCG National Maritime Center publishes policy letters, memos, and
# credentialing guidance at dco.uscg.mil/nmc/. This task scrapes the 3
# NMC index pages weekly and emails a single admin digest to
# blakemarchal@gmail.com whenever genuinely new PDFs appear.
#
# Sprint D1 refactor (2026-04-22):
#   - State moved from the user-facing `notifications` table to a
#     dedicated `nmc_monitor_seen_urls` table. Cold-start bursts can no
#     longer cascade into user-visible banners.
#   - Task never inserts into `notifications`. Ever.
#   - Single digest email per run instead of per-PDF notifications.
#   - Dedupes findings against the ingested `nmc_policy` / `nmc_checklist`
#     corpus so the digest doesn't re-surface docs RegKnot already knows.
#
# Admin-only by design: we advertise "up to date" without needing to
# prove it via user-visible banners. The digest is for Blake's ingest
# decisions; users never see this signal.
#
# Schedule: weekly on Wednesdays at 12:00 UTC (see celery_beat.py).

_NMC_SOURCES = [
    {
        "name": "NMC Announcements",
        "url": "https://www.dco.uscg.mil/nmc/announcements/",
    },
    {
        "name": "NMC Policy & Regulations",
        "url": "https://www.dco.uscg.mil/nmc/policy_regulations/",
    },
    {
        "name": "NMC Medical/Physical Guidelines",
        "url": "https://www.dco.uscg.mil/nmc/medical/",
    },
]

# Matches links to PDFs on the NMC site
_NMC_PDF_RE = re.compile(
    r'href=["\']([^"\']*?/Portals/9/NMC/[^"\']*?\.pdf)["\']',
    re.IGNORECASE,
)

# Admin recipient for the weekly NMC digest. Hardcoded per standing
# rule: Owner is blakemarchal@gmail.com; Karynn is admin but not Owner
# and explicitly does NOT want these ops signals.
_NMC_DIGEST_RECIPIENT = "blakemarchal@gmail.com"


def _normalize_nmc_url(pdf_path: str) -> str:
    """Resolve relative NMC PDF URLs to absolute form."""
    if pdf_path.startswith("/"):
        return f"https://www.dco.uscg.mil{pdf_path}"
    if not pdf_path.startswith("http"):
        return f"https://www.dco.uscg.mil/{pdf_path}"
    return pdf_path


def _prettify_nmc_filename(pdf_url: str) -> str:
    """Extract a human-readable filename from an NMC PDF URL."""
    filename = pdf_url.rsplit("/", 1)[-1].replace("%20", " ").replace("_", " ")
    if filename.lower().endswith(".pdf"):
        filename = filename[:-4]
    return filename


def _filename_stem_tokens(filename: str) -> set[str]:
    """Lowercase alphanumeric tokens from a filename stem for corpus dedup."""
    return {t for t in re.split(r"[^a-z0-9]+", filename.lower()) if len(t) >= 3}


@celery.task(name="app.tasks.check_nmc_updates")
def check_nmc_updates():
    """Weekly NMC scraper. Admin-only digest email; no user notifications."""
    _run_async(_check_nmc_updates_async())


async def _check_nmc_updates_async():
    import asyncpg
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    try:
        # Seen-URL state lives in its own table (not notifications).
        seen_rows = await conn.fetch("SELECT url FROM nmc_monitor_seen_urls")
        seen_urls: set[str] = {r["url"] for r in seen_rows}

        # Filename-token sets for every already-ingested NMC doc, used to
        # skip URLs whose filename clearly matches corpus content.
        ingested_rows = await conn.fetch(
            """
            SELECT DISTINCT COALESCE(source_version, section_number) AS ident
            FROM regulations
            WHERE source IN ('nmc_policy', 'nmc_checklist')
              AND COALESCE(source_version, section_number) IS NOT NULL
            """
        )
        ingested_token_sets: list[set[str]] = [
            _filename_stem_tokens(r["ident"]) for r in ingested_rows
        ]
        ingested_token_sets = [s for s in ingested_token_sets if s]

        new_findings: list[dict] = []
        already_ingested: list[dict] = []
        total_urls_scanned = 0

        for source in _NMC_SOURCES:
            try:
                resp = requests.get(
                    source["url"],
                    timeout=30,
                    headers={"User-Agent": "RegKnot NMC Monitor/1.0"},
                )
                resp.raise_for_status()

                for match in _NMC_PDF_RE.finditer(resp.text):
                    pdf_url = _normalize_nmc_url(match.group(1))
                    total_urls_scanned += 1

                    if pdf_url in seen_urls:
                        continue

                    filename = _prettify_nmc_filename(pdf_url)
                    finding = {
                        "url": pdf_url,
                        "filename": filename,
                        "source_name": source["name"],
                        "source_url": source["url"],
                    }

                    # Dedupe against ingested corpus — if the filename tokens
                    # substantially match an already-ingested doc identifier,
                    # classify as already-known rather than truly new.
                    finding_tokens = _filename_stem_tokens(filename)
                    is_in_corpus = finding_tokens and any(
                        len(finding_tokens & s) >= max(2, len(finding_tokens) // 2)
                        for s in ingested_token_sets
                    )

                    if is_in_corpus:
                        already_ingested.append(finding)
                    else:
                        new_findings.append(finding)

                    seen_urls.add(pdf_url)  # prevent cross-page duplicates

            except Exception as exc:
                logger.warning(
                    "NMC monitor: failed to scrape %s: %s", source["name"], exc
                )

        # Persist EVERY new URL (both buckets) to seen-URLs table so we
        # don't re-process them next week — including the in-corpus ones.
        all_new = new_findings + already_ingested
        if all_new:
            await conn.executemany(
                """
                INSERT INTO nmc_monitor_seen_urls (url, filename, source_page)
                VALUES ($1, $2, $3)
                ON CONFLICT (url) DO NOTHING
                """,
                [(d["url"], d["filename"], d["source_name"]) for d in all_new],
            )

        logger.info(
            "NMC monitor: scanned=%d seen=%d truly_new=%d already_in_corpus=%d",
            total_urls_scanned,
            len(seen_urls) - len(all_new),
            len(new_findings),
            len(already_ingested),
        )

        # Only email the admin if there are truly new findings worth
        # acting on. Skip already-ingested dedupes from the email (they
        # are logged for audit but not actionable).
        if new_findings:
            _send_nmc_admin_digest(new_findings, already_ingested_count=len(already_ingested))
        else:
            logger.info("NMC monitor: no new documents this week — skipping digest email")

    finally:
        await conn.close()


def _send_nmc_admin_digest(new_findings: list[dict], *, already_ingested_count: int = 0):
    """Send the weekly NMC admin digest to the Owner.

    Admin-only — never sent to end users. One email per run, summarizing
    all genuinely-new NMC documents that warrant ingest consideration.
    """
    try:
        import resend
        from app.config import settings
        resend.api_key = settings.resend_api_key

        items_html = "".join(
            f"<li><a href='{f['url']}'>{f['filename']}</a> "
            f"<em>(via {f['source_name']})</em></li>"
            for f in new_findings
        )

        corpus_note = ""
        if already_ingested_count:
            corpus_note = (
                f"<p><em>({already_ingested_count} additional URL(s) matched "
                f"already-ingested corpus content and were auto-skipped.)</em></p>"
            )

        resend.Emails.send({
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": [_NMC_DIGEST_RECIPIENT],
            "subject": f"RegKnot NMC digest — {len(new_findings)} new doc(s) to review",
            "html": (
                f"<h2>Weekly NMC document digest</h2>"
                f"<p><strong>{len(new_findings)}</strong> new document(s) appeared "
                f"on the USCG NMC site since last week's check. Review for ingest:</p>"
                f"<ul>{items_html}</ul>"
                f"{corpus_note}"
                f"<p>If a document is relevant to credentialing policy, medical "
                f"certificate guidance, or MMC processing updates, download the "
                f"PDF and ingest via "
                f"<code>uv run python -m ingest.cli --source nmc_policy --update</code> "
                f"(or <code>nmc_checklist</code> for form-instruction documents).</p>"
                f"<p>This digest is admin-only and tracked in "
                f"<code>nmc_monitor_seen_urls</code>. The monitor will not "
                f"re-surface any URL listed here in future runs.</p>"
            ),
        })
        logger.info(
            "Sent NMC admin digest to %s (%d new)",
            _NMC_DIGEST_RECIPIENT,
            len(new_findings),
        )
    except Exception as exc:
        logger.error("Failed to send NMC admin digest: %s", exc)
