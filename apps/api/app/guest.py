"""One free answer before signup (growth plan step 2, 2026-10-14).

A visitor without an account may ask one question from a public page (the
regulation pages, the landing page). The answer runs through the normal chat
pipeline and streams like any answer, inside a conversation owned by an
internal guest account (GUEST_EMAIL: verified, Captain tier, is_internal, so
no cap applies and admin numbers leave it out). guest_questions records the
question, so the limits can be counted, and its claim: when the visitor signs
up, auth.register moves the conversation and the vessel they picked to the
new account and skips the welcome wizard.

Off unless settings.anon_chat_enabled and a Cloudflare Turnstile secret are
both set. Limits (all in settings):
  one question per device per anon_device_window_days (a random id the
      browser keeps; HMAC-hashed here)
  anon_ip_daily_cap per IP per day (loose: a vessel's crew shares one IP)
  anon_daily_cap and anon_monthly_cap across all visitors (the spend guard,
      at most ~$0.13-0.20 an answer)
Unclaimed guest conversations are deleted after GUEST_RETENTION_DAYS.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid

import httpx
from fastapi import HTTPException, Request, status

from app.auth.schemas import CurrentUser
from app.config import settings

logger = logging.getLogger(__name__)

GUEST_EMAIL = "guest@guest.regknots.invalid"
GUEST_RETENTION_DAYS = 30
VESSEL_TYPES = (
    "Towing / Tugboat", "Containership", "Tanker", "Bulk Carrier", "OSV / Offshore Support",
    "Passenger Vessel", "Ferry", "Fish Processing", "Research Vessel", "Other",
)
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_NO_EMAIL = '{"cert_expiry_reminders": false, "reg_change_digest": false, "reg_digest_frequency": "weekly"}'


def enabled() -> bool:
    return bool(settings.anon_chat_enabled and settings.turnstile_secret_key)


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 under the server secret: comparable, not reversible."""
    return hmac.new(settings.jwt_secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def claim_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    """The visitor's IP: Caddy puts it first in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip()
    return ip or (request.client.host if request.client else "")


async def verify_turnstile(token: str, ip: str) -> bool:
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(TURNSTILE_VERIFY_URL, data={
                "secret": settings.turnstile_secret_key, "response": token, "remoteip": ip,
            })
            return bool(r.json().get("success"))
    except Exception as exc:  # noqa: BLE001 — a Cloudflare outage refuses the question, not the page
        logger.warning("turnstile verify failed: %s", exc)
        return False


async def guest_user(pool) -> CurrentUser:
    """The internal account that owns guest conversations; created on first use."""
    row = await pool.fetchrow("SELECT id FROM users WHERE email = $1", GUEST_EMAIL)
    if row is None:
        from app.auth.service import hash_password
        await pool.execute(
            """
            INSERT INTO users (email, hashed_password, full_name, role, trial_ends_at, subscription_tier,
                               subscription_status, email_verified, is_internal, notification_preferences,
                               onboarding_completed_at)
            VALUES ($1, $2, 'Guest (questions before signup)', 'other', now(), 'captain', 'active', TRUE, TRUE,
                    $3::jsonb, now())
            ON CONFLICT (email) DO NOTHING
            """,
            GUEST_EMAIL, hash_password(secrets.token_urlsafe(48)), _NO_EMAIL,
        )
        row = await pool.fetchrow("SELECT id FROM users WHERE email = $1", GUEST_EMAIL)
    return CurrentUser(user_id=str(row["id"]), email=GUEST_EMAIL, role="other", tier="captain",
                       is_admin=False, email_verified=True, full_name="Guest")


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": code, "message": message})


async def check_limits(pool, device_hash: str, ip_hash: str) -> None:
    """Raise 429 {code, message} when this visitor or the budget is out."""
    row = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE device_hash = $1
                                  AND created_at > now() - make_interval(days => $3)) AS device,
               count(*) FILTER (WHERE ip_hash = $2 AND created_at > now() - interval '1 day') AS ip,
               count(*) FILTER (WHERE created_at >= date_trunc('day', now())) AS today,
               count(*) FILTER (WHERE created_at >= date_trunc('month', now())) AS month
        FROM guest_questions
        WHERE created_at >= least(date_trunc('month', now()), now() - make_interval(days => $3))
        """,
        device_hash, ip_hash, settings.anon_device_window_days,
    )
    signup = "Create a free account to keep asking: the trial includes 50 questions."
    if row["device"] >= 1:
        raise _refuse("guest_used", f"You've used your free question. {signup}")
    if row["ip"] >= settings.anon_ip_daily_cap:
        raise _refuse("guest_ip", f"Free questions from this network are used up for today. {signup}")
    if row["today"] >= settings.anon_daily_cap or row["month"] >= settings.anon_monthly_cap:
        raise _refuse("guest_paused", f"Questions without an account are paused for now. {signup}")


async def start(pool, guest: CurrentUser, *, query: str, vessel_type: str | None, page: str | None,
                device_hash: str, ip_hash: str) -> tuple[uuid.UUID, uuid.UUID | None, str]:
    """Create the guest conversation (and vessel) and the claim. Returns
    (conversation_id, vessel_id, claim_token)."""
    token = secrets.token_urlsafe(32)
    guest_id = uuid.UUID(guest.user_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            vessel_id = None
            if vessel_type:
                vessel_id = await conn.fetchval(
                    """INSERT INTO vessels (user_id, name, vessel_type, flag_state, route_types)
                       VALUES ($1, 'My vessel', $2, 'United States', '{}') RETURNING id""",
                    guest_id, vessel_type,
                )
            conversation_id = await conn.fetchval(
                "INSERT INTO conversations (user_id, vessel_id, title) VALUES ($1, $2, $3) RETURNING id",
                guest_id, vessel_id, query.strip()[:80],
            )
            await conn.execute(
                """INSERT INTO guest_questions (device_hash, ip_hash, conversation_id, vessel_id, vessel_type,
                                                page, claim_hash)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                device_hash, ip_hash, conversation_id, vessel_id, vessel_type, (page or "")[:200] or None,
                claim_hash(token),
            )
    return conversation_id, vessel_id, token


async def claim(pool, user_id: uuid.UUID, token: str | None) -> uuid.UUID | None:
    """Move a guest conversation (and its vessel) to a new account. Returns the
    conversation id, or None when the token is unknown, claimed or expired."""
    if not token:
        return None
    guest = await pool.fetchval("SELECT id FROM users WHERE email = $1", GUEST_EMAIL)
    if guest is None:
        return None
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""SELECT id, conversation_id, vessel_id FROM guest_questions
                    WHERE claim_hash = $1 AND claimed_by IS NULL
                      AND created_at > now() - interval '{GUEST_RETENTION_DAYS} days'
                    FOR UPDATE""",
                claim_hash(token),
            )
            if row is None or row["conversation_id"] is None:
                return None
            await conn.execute("UPDATE conversations SET user_id = $1 WHERE id = $2 AND user_id = $3",
                               user_id, row["conversation_id"], guest)
            if row["vessel_id"]:
                await conn.execute("UPDATE vessels SET user_id = $1 WHERE id = $2 AND user_id = $3",
                                   user_id, row["vessel_id"], guest)
            await conn.execute(
                "UPDATE users SET onboarding_completed_at = COALESCE(onboarding_completed_at, now()) WHERE id = $1",
                user_id)
            await conn.execute("UPDATE guest_questions SET claimed_by = $1, claimed_at = now() WHERE id = $2",
                               user_id, row["id"])
    return row["conversation_id"]


async def purge_unclaimed(pool) -> int:
    """Delete unclaimed guest conversations (messages cascade) and vessels
    older than GUEST_RETENTION_DAYS."""
    guest = await pool.fetchval("SELECT id FROM users WHERE email = $1", GUEST_EMAIL)
    if guest is None:
        return 0
    rows = await pool.fetch(
        f"""SELECT conversation_id, vessel_id FROM guest_questions
            WHERE claimed_by IS NULL AND created_at < now() - interval '{GUEST_RETENTION_DAYS} days'
              AND (conversation_id IS NOT NULL OR vessel_id IS NOT NULL)""")
    conversations = [r["conversation_id"] for r in rows if r["conversation_id"]]
    vessels = [r["vessel_id"] for r in rows if r["vessel_id"]]
    if conversations:
        await pool.execute("DELETE FROM conversations WHERE id = ANY($1::uuid[]) AND user_id = $2",
                           conversations, guest)
    if vessels:
        await pool.execute("DELETE FROM vessels WHERE id = ANY($1::uuid[]) AND user_id = $2", vessels, guest)
    return len(conversations)
