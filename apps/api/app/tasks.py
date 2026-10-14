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
# 2026-09-10 audit — scheduled ingest goes through the same memory-capped
# transient unit as ad-hoc ingest (scripts/run_ingest.sh: regknots-ingest
# slice, MemoryMax=1.5G). Before this it ran as a bare `uv run` inside
# this worker's 1 GB cgroup — the OOM class the 2026-05-08 audit named.
_RUN_INGEST = Path(__file__).resolve().parents[3] / "scripts" / "run_ingest.sh"

# Sources that can actually run unattended (fetch from public APIs / scrapers).
# Sources NOT in this list (colregs, solas, solas_supplement, stcw,
# stcw_supplement, ism, erg) require local PDF / pre-extracted text files
# that must be placed manually — they are MANUAL INGEST ONLY and
# intentionally left out of the scheduled task. When a fresh PDF is
# dropped on the server and the admin runs
#   `uv run python -m ingest.cli --source <name> --update`
# the notify hook fires alerts to opted-in users if content actually
# changed. New IMO resolutions (amendments to SOLAS, MARPOL, STCW and the
# codes) come in on their own: `harvest_imo_resolutions` (2026-10-13).
_AUTOMATABLE_SOURCES: list[str] = [
    "cfr_33",
    "cfr_46",
    "cfr_49",
    # 2026-09-30 — scoped parts only (ingest/cfr_scope.py): EPA vessel
    # rules, FCC maritime radio, the right whale rule, OSHA maritime.
    "cfr_40",
    "cfr_47",
    "cfr_50",
    "cfr_29",
    "nvic",
]

# 2026-09-30 — Coast Guard listing pages that change a few times a month at
# most: safety alerts, CG-CVC letters and work instructions, TVNCOE Sub M
# FAQs, VTS manuals / waterways action plans, NMC checklists. Monthly run
# (update_uscg_guidance). Downloads only what is new or re-versioned.
_MONTHLY_SOURCES: list[str] = [
    "uscg_safety_alert",
    "uscg_cvc",
    "uscg_towing",
    "uscg_waterways",
    "nmc_checklist",
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

    failures = _run_ingest_sources(_AUTOMATABLE_SOURCES)
    if failures:
        # Retry the whole task if any source failed — the CLI is idempotent
        # so sources that already succeeded will short-circuit on the retry.
        msg = ", ".join(f"{s}: {e}" for s, e in failures)
        logger.warning("Regulation update had %d failures: %s", len(failures), msg)
        raise self.retry(exc=RuntimeError(msg), countdown=3600)

    logger.info("Scheduled regulation update complete — all sources up to date")


@celery.task(name="app.tasks.update_uscg_guidance", bind=True, max_retries=1)
def update_uscg_guidance(self):
    """Monthly refresh of the Coast Guard listing-page sources (2026-09-30).

    Same per-source CLI invocation as update_regulations; see
    _MONTHLY_SOURCES at module top.
    """
    logger.info(
        "Starting monthly USCG guidance update for %d sources: %s",
        len(_MONTHLY_SOURCES), ", ".join(_MONTHLY_SOURCES),
    )
    failures = _run_ingest_sources(_MONTHLY_SOURCES)
    _run_ocr(_OCR_SOURCES)
    if failures:
        msg = ", ".join(f"{s}: {e}" for s, e in failures)
        logger.warning("USCG guidance update had %d failures: %s", len(failures), msg)
        raise self.retry(exc=RuntimeError(msg), countdown=6 * 3600)
    logger.info("Monthly USCG guidance update complete")


# 2026-09-30 — sources whose adapters read OCR text for a scanned PDF
# (data/ocr/<source>/). A scan the runs above downloaded is read by
# tesseract here (python -m ingest.ocr) and ingested by the next scheduled
# run: Sunday for NVICs, next month for the rest. Normally a no-op in seconds.
_OCR_SOURCES: list[str] = ["nvic", "uscg_cvc", "uscg_safety_alert", "uscg_towing", "uscg_waterways"]


def _run_ocr(sources: list[str]) -> None:
    for source in sources:
        try:
            result = subprocess.run(
                [str(_RUN_INGEST), "--ocr", "--source", source],
                cwd=_INGEST_DIR, capture_output=True, text=True, timeout=3600,
            )
            if result.returncode != 0:
                logger.error("OCR failed for %s (rc=%d): %s", source, result.returncode, result.stderr[-500:])
            else:
                logger.info("OCR for %s: %s", source, (result.stdout or result.stderr)[-300:])
        except Exception as exc:  # OCR never fails the refresh
            logger.exception("OCR for %s raised: %s", source, exc)


@celery.task(name="app.tasks.update_uscg_bulletins")
def update_uscg_bulletins():
    """Daily: new bulletins from GovDelivery's USCG feed (2026-09-30).

    The feed lists the latest ~30 hours, hence daily. `--update` reads only
    feed items no earlier run decided and keeps policy / safety / credential
    bulletins (sources/uscg_bulletin.py parse_feed; no LLM calls unless
    USCG_BULLETIN_LLM=1). --no-notify: a banner a day would be noise. A
    missed day is not retried; its bulletins have left the feed.
    """
    failures = _run_ingest_sources(["uscg_bulletin"], extra_args=("--no-notify",))
    if failures:
        logger.warning("USCG bulletin feed update failed: %s", failures)


def _run_ingest_sources(sources: list[str], extra_args: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Run `--update` for each source in its own memory-capped unit.

    Returns (source, reason) for each failure; one failure never stops the
    rest.
    """
    failures: list[tuple[str, str]] = []
    for source in sources:
        logger.info("Running ingest for source=%s", source)
        try:
            # run_ingest.sh picks --pipe (not --pty) when stdout is not a
            # TTY, so stdout/stderr are still captured below and the
            # transient unit's exit code is forwarded by systemd-run --wait.
            result = subprocess.run(
                [str(_RUN_INGEST), "--source", source, "--update", *extra_args],
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
    return failures


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


# reindex_vector_embeddings removed 2026-09-10. It ran a plain (non-
# concurrent) `REINDEX INDEX idx_regulations_embedding` on the 1st of
# the month — 271 s of ACCESS EXCLUSIVE on 2026-09-01 — duplicating the
# weekly `REINDEX CONCURRENTLY` in regknots-db-maintenance.timer that
# replaced the per-ingest reindex on 2026-07-19 for exactly that reason.


# 2026-10-13 — IMO resolutions: ingest.imo_harvest reads the IMO's Index of
# IMO Resolutions, adds new MSC / MEPC / Assembly resolutions (and the codes
# they amend, when missing) to the corpus, and re-checks any whose certified
# text was pending. It replaces the old scraper, which looked for "MSC.n(m)"
# strings on three pages and had found nothing since the IMO site moved
# (the Marshall Islands page failed its TLS check every run; IMO pages 301).
# Spec: docs/specs/imo-harvester-2026-10-13.md.
_HARVEST_REPORT = Path(__file__).resolve().parents[3] / "data" / "raw" / "imo_harvest" / "report-latest.json"


@celery.task(name="app.tasks.harvest_imo_resolutions", bind=True, max_retries=1)
def harvest_imo_resolutions(self):
    """Weekly: new IMO resolutions into the corpus, then a digest email."""
    import json

    try:
        result = subprocess.run(
            [str(_RUN_INGEST), "--module", "ingest.imo_harvest"],
            cwd=_INGEST_DIR, capture_output=True, text=True, timeout=3 * 3600,
        )
    except subprocess.TimeoutExpired:
        logger.error("IMO harvest timed out after 3 hours")
        raise self.retry(exc=RuntimeError("timeout"), countdown=6 * 3600)
    tail = (result.stdout or "")[-500:] + (result.stderr or "")[-500:]
    try:
        report = json.loads(_HARVEST_REPORT.read_text(encoding="utf-8"))
    except Exception:
        report = None
    if result.returncode != 0 or report is None:
        logger.error("IMO harvest failed (rc=%d): %s", result.returncode, tail)
        _send_harvest_email(report, failed_tail=tail)
        raise self.retry(exc=RuntimeError(f"rc={result.returncode}"), countdown=6 * 3600)
    logger.info("IMO harvest: %d harvested, %d failed", len(report.get("harvested", [])),
                len(report.get("failed", [])))
    if report.get("harvested") or report.get("failed") or report.get("superseded"):
        _send_harvest_email(report)


@celery.task(name="app.tasks.check_solas_supplements")
def check_solas_supplements():
    """Old name (a Beat entry or a queued message from before 2026-10-13)."""
    harvest_imo_resolutions.delay()


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


def _send_harvest_email(report: dict | None, failed_tail: str = "") -> None:
    """The weekly IMO harvest digest, to hello@ (Blake)."""
    import html as _html
    try:
        from app.email import send_email

        def esc(s) -> str:
            return _html.escape(str(s or ""))

        if report is None:
            body = f"<p>The IMO harvest did not produce a report.</p><pre>{esc(failed_tail)}</pre>"
            subject = "IMO harvest failed — RegKnot"
        else:
            items = "".join(
                f"<li><strong>{esc(h['code'])}</strong> → {esc(h['source'])}: {esc(h['title'])}"
                f"{' — ' + esc(h['status']) if h.get('status') else ''}"
                f"{' (parent)' if h.get('reason') == 'parent' else ''}</li>"
                for h in report.get("harvested", [])
            )
            failed = "".join(f"<li>{esc(f['code'])}: {esc(f['error'])}</li>" for f in report.get("failed", []))
            superseded = "".join(
                f"<li>{esc(s['code'])} revoked by {esc(s['by'])}: {esc(s['action'])}</li>"
                for s in report.get("superseded", [])
            )
            body = (
                f"<h2>IMO resolutions added ({len(report.get('harvested', []))})</h2><ul>{items}</ul>"
                + (f"<h3>Failed</h3><ul>{failed}</ul>" if failed else "")
                + (f"<h3>Revoked by newer resolutions</h3><ul>{superseded}</ul>" if superseded else "")
                + (f"<p><strong>Error:</strong> {esc(report.get('error'))}</p>" if report.get("error") else "")
                + "<p>Full report: data/raw/imo_harvest/report-latest.json on the server.</p>"
            )
            subject = f"IMO harvest: {len(report.get('harvested', []))} resolutions added — RegKnot"
        send_email({
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": subject,
            "html": body,
        })
    except Exception as exc:
        logger.error("Failed to send IMO harvest email: %s", exc)


# ── Workspace (Wheelhouse) state-machine crons (Sprint D6.54) ────────────


@celery.task(name="app.tasks.hedge_audit_weekly_digest")
def hedge_audit_weekly_digest():
    """Email the Owner a weekly summary of open hedge audits.

    Sprint D6.58 Slice 2. Aggregates the top open audits since the
    last digest, grouped by classification, with the model's
    recommendations inline so Karynn can scan and prioritize without
    opening the admin UI.

    Recipient: blakemarchal@gmail.com per project standing rule
    (admin digests go to the Owner; Karynn gets context separately).
    """
    _run_async(_hedge_audit_weekly_digest_async())


async def _hedge_audit_weekly_digest_async():
    import asyncpg
    import resend
    from app.email import send_email
    from app.config import settings

    resend.api_key = settings.resend_api_key
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Aggregate counters
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM hedge_audits WHERE status = 'open'"
        ) or 0
        fixed_last_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM hedge_audits "
            "WHERE status = 'fixed' AND fixed_at > NOW() - INTERVAL '7 days'"
        ) or 0
        new_open_last_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM hedge_audits "
            "WHERE status = 'open' AND created_at > NOW() - INTERVAL '7 days'"
        ) or 0

        # Top 12 open audits, newest first
        rows = await conn.fetch(
            """
            SELECT id, classification, query, recommendation,
                   created_at, classifier_reasoning
            FROM hedge_audits
            WHERE status = 'open'
            ORDER BY created_at DESC
            LIMIT 12
            """
        )

        if not rows and fixed_last_7d == 0:
            logger.info("hedge audit digest: nothing to report — skipping email")
            return

        items_html = ""
        for r in rows:
            items_html += (
                f"<li style='margin-bottom:14px;'>"
                f"<strong style='color:#2dd4bf;'>[{r['classification']}]</strong> "
                f"<em style='color:#f0ece4;'>{_escape(r['query'])[:160]}</em><br>"
                f"<span style='color:#6b7594; font-size:13px;'>"
                f"→ {_escape(r['recommendation'] or 'No recommendation provided.')[:300]}"
                f"</span>"
                f"</li>"
            )

        from app.email import APP_URL
        admin_url = f"{APP_URL}/admin/hedge-audit"
        html = (
            f"<h2 style='color:#f0ece4;'>RegKnots — Weekly hedge audit</h2>"
            f"<p style='color:#6b7594;'>"
            f"<strong style='color:#f0ece4;'>{open_count}</strong> open audits "
            f"(<strong>{new_open_last_7d}</strong> new this week, "
            f"<strong>{fixed_last_7d}</strong> fixed)"
            f"</p>"
            f"<p style='color:#6b7594;'>Top open items, newest first:</p>"
            f"<ol style='color:#f0ece4; line-height:1.4;'>{items_html}</ol>"
            f"<p style='margin-top:20px;'>"
            f"<a href='{admin_url}' "
            f"style='background:#2dd4bf; color:#0a0e1a; padding:10px 20px; "
            f"border-radius:8px; text-decoration:none; font-weight:bold; "
            f"font-family:monospace;'>"
            f"Open admin queue</a></p>"
            f"<p style='color:#6b7594; font-size:12px; margin-top:24px;'>"
            f"Sprint D6.58 Slice 2 — mariner-in-the-loop feedback. "
            f"Each audit is auto-classified by Haiku and recommends a "
            f"specific next step (synonyms.py edit, ingest, retrieval tweak)."
            f"</p>"
        )

        send_email({
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": ["blakemarchal@gmail.com"],
            "subject": (
                f"RegKnot weekly hedge audit — {open_count} open "
                f"({new_open_last_7d} new, {fixed_last_7d} fixed)"
            ),
            "html": html,
        })
        logger.info(
            "Sent hedge audit digest: open=%d new=%d fixed=%d",
            open_count, new_open_last_7d, fixed_last_7d,
        )
    finally:
        await conn.close()


def _escape(s: str) -> str:
    """Minimal HTML escape for digest body."""
    if not s:
        return ""
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


@celery.task(name="app.tasks.workspace_state_transitions")
def workspace_state_transitions():
    """Daily cron: drive the workspace billing state machine forward.

    Two transitions:
      1. trialing → card_pending  (when the trial ends, no Stripe
         subscription; 2026-10-14: COALESCE(trial_ends_at, created_at +
         30 days), app/pilots.py, so a pilot's longer trial is honoured)
      2. card_pending → archived  (after 30 days from card_pending_started_at)

    Idempotent — safe to run multiple times per day; the WHERE
    conditions filter out already-transitioned rows.

    Sends one reminder email per transition. Emails are best-effort;
    a failure doesn't block the state change.
    """
    _run_async(_workspace_state_transitions_async())


async def _workspace_state_transitions_async():
    import asyncpg
    from app.config import settings
    from app.email import (
        RESEND_THROTTLE_SECONDS,
        send_with_throttle,
        send_workspace_archived_email,
        send_workspace_card_pending_reminder_email,
        send_workspace_trial_ended_email,
        send_workspace_trial_ending_email,
    )

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # Sub-task 1: trial day-25 reminder ("5 days left, add a card")
        # Fires once per workspace, tracked by trial_reminder_sent_at flag.
        # We don't add a column for this — instead use the
        # workspace_billing_events ledger to dedup. This keeps the
        # workspaces table lean.
        trial_reminder_rows = await conn.fetch(
            """
            SELECT w.id, w.name, u.email AS owner_email
            FROM workspaces w
            JOIN users u ON u.id = w.owner_user_id
            WHERE w.status = 'trialing'
              AND COALESCE(w.trial_ends_at, w.created_at + INTERVAL '30 days') < now() + INTERVAL '5 days'
              AND COALESCE(w.trial_ends_at, w.created_at + INTERVAL '30 days') > now()
              AND NOT EXISTS (
                SELECT 1 FROM workspace_billing_events
                WHERE workspace_id = w.id
                  AND event_type = 'trial_25d_reminder_sent'
              )
            """
        )
        for idx, row in enumerate(trial_reminder_rows):
            try:
                await send_with_throttle(
                    lambda email=row["owner_email"], name=row["name"]:
                        send_workspace_trial_ending_email(email, name),
                    label=f"trial-25d:{row['id']}",
                )
                await conn.execute(
                    "INSERT INTO workspace_billing_events "
                    "(workspace_id, event_type, actor_user_id, details) "
                    "VALUES ($1, 'trial_25d_reminder_sent', NULL, '{}'::jsonb)",
                    row["id"],
                )
            except Exception as exc:
                logger.error(
                    "Workspace trial 25d reminder failed for %s: %s",
                    row["id"], exc,
                )
            if idx < len(trial_reminder_rows) - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)

        # Sub-task 2: trialing → card_pending after 30 days
        expiring_trials = await conn.fetch(
            """
            UPDATE workspaces SET
              status = 'card_pending',
              card_pending_started_at = now(),
              updated_at = now()
            WHERE status = 'trialing'
              AND COALESCE(trial_ends_at, created_at + INTERVAL '30 days') < now()
              AND stripe_subscription_id IS NULL
            RETURNING id, name, owner_user_id
            """
        )
        for idx, row in enumerate(expiring_trials):
            owner_email = await conn.fetchval(
                "SELECT email FROM users WHERE id = $1", row["owner_user_id"],
            )
            try:
                if owner_email:
                    await send_with_throttle(
                        lambda email=owner_email, name=row["name"]:
                            send_workspace_trial_ended_email(email, name),
                        label=f"trial-ended:{row['id']}",
                    )
                await conn.execute(
                    "INSERT INTO workspace_billing_events "
                    "(workspace_id, event_type, actor_user_id, details) "
                    "VALUES ($1, 'trial_expired_to_card_pending', NULL, "
                    "'{}'::jsonb)",
                    row["id"],
                )
            except Exception as exc:
                logger.error(
                    "Trial-ended email failed for workspace %s: %s",
                    row["id"], exc,
                )
            if idx < len(expiring_trials) - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)

        # Sub-task 3: card_pending day-25 reminder
        card_pending_reminder_rows = await conn.fetch(
            """
            SELECT w.id, w.name, u.email AS owner_email,
                   w.card_pending_started_at
            FROM workspaces w
            JOIN users u ON u.id = w.owner_user_id
            WHERE w.status = 'card_pending'
              AND w.card_pending_started_at < now() - INTERVAL '25 days'
              AND w.card_pending_started_at > now() - INTERVAL '30 days'
              AND NOT EXISTS (
                SELECT 1 FROM workspace_billing_events
                WHERE workspace_id = w.id
                  AND event_type = 'card_pending_25d_reminder_sent'
              )
            """
        )
        for idx, row in enumerate(card_pending_reminder_rows):
            try:
                await send_with_throttle(
                    lambda email=row["owner_email"], name=row["name"]:
                        send_workspace_card_pending_reminder_email(email, name),
                    label=f"card-pending-25d:{row['id']}",
                )
                await conn.execute(
                    "INSERT INTO workspace_billing_events "
                    "(workspace_id, event_type, actor_user_id, details) "
                    "VALUES ($1, 'card_pending_25d_reminder_sent', NULL, "
                    "'{}'::jsonb)",
                    row["id"],
                )
            except Exception as exc:
                logger.error(
                    "Card-pending 25d reminder failed for %s: %s",
                    row["id"], exc,
                )
            if idx < len(card_pending_reminder_rows) - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)

        # Sub-task 4: card_pending → archived after another 30 days
        archived_rows = await conn.fetch(
            """
            UPDATE workspaces SET
              status = 'archived',
              updated_at = now()
            WHERE status = 'card_pending'
              AND card_pending_started_at < now() - INTERVAL '30 days'
            RETURNING id, name, owner_user_id
            """
        )
        for idx, row in enumerate(archived_rows):
            owner_email = await conn.fetchval(
                "SELECT email FROM users WHERE id = $1", row["owner_user_id"],
            )
            try:
                if owner_email:
                    await send_with_throttle(
                        lambda email=owner_email, name=row["name"]:
                            send_workspace_archived_email(email, name),
                        label=f"archived:{row['id']}",
                    )
                await conn.execute(
                    "INSERT INTO workspace_billing_events "
                    "(workspace_id, event_type, actor_user_id, details) "
                    "VALUES ($1, 'archived', NULL, '{}'::jsonb)",
                    row["id"],
                )
            except Exception as exc:
                logger.error(
                    "Archived email failed for workspace %s: %s",
                    row["id"], exc,
                )
            if idx < len(archived_rows) - 1:
                await asyncio.sleep(RESEND_THROTTLE_SECONDS)

        logger.info(
            "Workspace state transitions: trial-25d=%d, trial→pending=%d, "
            "card-25d=%d, pending→archived=%d",
            len(trial_reminder_rows), len(expiring_trials),
            len(card_pending_reminder_rows), len(archived_rows),
        )
    finally:
        await conn.close()


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
        from app.email import send_email
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

        send_email({
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
        from app.email import send_email
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

        send_email({
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


@celery.task(name="app.tasks.reconcile_subscriptions")
def reconcile_subscriptions():
    """2026-09-26 — daily re-sync of paid users whose billing period ended
    without a Stripe update (the webhook endpoint does not receive
    customer.subscription.deleted). See
    stripe_service.reconcile_stale_subscriptions."""
    _run_async(_reconcile_subscriptions_async())


async def _reconcile_subscriptions_async():
    import asyncpg
    from app.config import settings
    from app.stripe_service import reconcile_stale_subscriptions

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        return await reconcile_stale_subscriptions(conn)
    finally:
        await conn.close()


@celery.task(name="app.tasks.process_company_document")
def process_company_document(document_id: str):
    """2026-09-27 — extract, chunk and embed one uploaded company document
    (app/company_docs.py). Status ends as ready or failed; never raises."""
    _run_async(_process_company_document_async(document_id))


async def _process_company_document_async(document_id: str):
    import uuid

    import asyncpg
    from app import company_docs
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        await company_docs.process_document(pool, uuid.UUID(document_id), settings.openai_api_key)
    finally:
        await pool.close()


@celery.task(name="app.tasks.process_user_document", soft_time_limit=600, time_limit=660)
def process_user_document(document_id: str):
    """2026-10-05 — extract, chunk, embed and check one document a user attached
    in chat (app/user_docs.py). Status ends as ready or failed; never raises."""
    _run_async(_process_user_document_async(document_id))


async def _process_user_document_async(document_id: str):
    import uuid

    import asyncpg
    from anthropic import AsyncAnthropic
    from app import user_docs
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        await user_docs.process_document(pool, uuid.UUID(document_id), settings.openai_api_key, client)
    finally:
        await client.close()
        await pool.close()


@celery.task(name="app.tasks.refresh_seo_pages", soft_time_limit=1800, time_limit=1900)
def refresh_seo_pages():
    """2026-10-14 — keep the public regulation pages (/regs) current: hold the
    pages whose regulation text changed in the weekly update and write them
    again from the new text (app/seo_pages.py refresh, at most 50 a week)."""
    return _run_async(_refresh_seo_pages_async())


async def _refresh_seo_pages_async():
    from app import seo_pages
    conn, client = await seo_pages._connect(), seo_pages._client()
    try:
        result = await seo_pages.refresh(conn, client)
        logger.info("refresh_seo_pages: %s", result)
        return result
    finally:
        await conn.close()


@celery.task(name="app.tasks.purge_user_documents")
def purge_user_documents():
    """2026-10-05 — delete chat-attached documents past their delete_after (the
    internal check found them not maritime: 7 days after upload) and failed
    uploads older than 7 days, files included."""
    return _run_async(_purge_user_documents_async())


async def _purge_user_documents_async():
    import asyncpg
    from app import user_docs
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    try:
        removed = await user_docs.purge(pool)
        logger.info("purge_user_documents: %d removed", removed)
        # 2026-10-14 — guest questions nobody claimed (app/guest.py), same daily run
        from app import guest
        guest_removed = await guest.purge_unclaimed(pool)
        if guest_removed:
            logger.info("purge_user_documents: %d unclaimed guest conversations removed", guest_removed)
        return {"removed": removed, "guest_conversations": guest_removed}
    finally:
        await pool.close()


@celery.task(name="app.tasks.ingest_web_gaps", soft_time_limit=600, time_limit=660)
def ingest_web_gaps():
    """2026-10-08 — add the official documents the phase-2 web research found
    to the library (app/web_ingest.py): a few found corpus_gaps per run,
    within WEB_INGEST_DAILY_CAP."""
    return _run_async(_ingest_web_gaps_async())


async def _ingest_web_gaps_async():
    import asyncpg
    from app import web_ingest
    from app.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        result = await web_ingest.run(pool, settings.openai_api_key, settings.web_ingest_daily_cap)
        logger.info("ingest_web_gaps: %s", result)
        return result
    finally:
        await pool.close()
