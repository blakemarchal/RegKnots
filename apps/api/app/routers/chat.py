"""
POST /chat — authenticated RAG chat endpoint.

Flow:
  1. Validate auth (Bearer JWT)
  2. Load vessel profile from DB if vessel_id provided
  3. Load last 10 messages from conversation if conversation_id provided
  4. Create new conversation record if none provided
  5. Call engine.chat()
  6. Persist user message + assistant response to messages table
  7. Return ChatResponse

POST /chat/stream — same flow, but emits SSE progress events while
the RAG pipeline runs and a final `done` event with the complete answer.
Auth/billing/rate-limit checks all run BEFORE the stream starts and surface
as normal HTTP error responses.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

import asyncpg
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool, get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Maps full Anthropic model IDs to the short aliases stored in the DB.
# The "fallback:gpt-4o" entry shows up as a distinct bucket in the admin
# dashboard's model-usage view when Claude is unavailable and the engine
# swaps over to OpenAI GPT-4o.
_MODEL_ALIAS: dict[str, str] = {
    "claude-haiku-4-5-20251001": "haiku",
    "claude-sonnet-4-6": "sonnet",
    # Sprint D6.73 — Sprint D4 upgraded the Opus version from 4-6 to 4-7
    # in router.MODEL_MAP, but this alias map was missed. Result: every
    # Opus answer was persisted with model_used = NULL because dict.get
    # returned None. Both keys retained so historic stale data with
    # the old version string still maps correctly during any backfill.
    "claude-opus-4-7": "opus",
    "claude-opus-4-6": "opus",
    "fallback:gpt-4o": "fallback_gpt4o",
}

# Regulation sources we don't currently cover. Used by missing-source detection.
_MISSING_SOURCES: dict[str, str] = {
    "marpol": "MARPOL (Marine Pollution)",
    "mlc": "MLC (Maritime Labour Convention)",
    "imdg": "IMDG Code (Dangerous Goods)",
    "imsbc": "IMSBC Code (Solid Bulk Cargoes)",
    "igc": "IGC Code (Gas Carriers)",
    "ibc": "IBC Code (Chemical Carriers)",
    "css": "CSS Code (Safe Stowage)",
    "grain": "International Grain Code",
    "bnwas": "BNWAS Regulations",
    "ballast": "BWM Convention (Ballast Water)",
    "polar code": "Polar Code",
    "llmc": "LLMC (Limitation of Liability)",
}

_MISSING_NOTE = (
    "\n\n*This regulation source is not yet in the RegKnot database. "
    "Our team has been notified and will consider adding it. "
    "In the meantime, consult the authoritative source directly.*"
)


async def _run_chat_preflight(
    body: "ChatRequestBody",
    current_user: CurrentUser,
    pool: asyncpg.Pool,
) -> tuple[dict | None, uuid.UUID, list, bool]:
    """Run all auth/billing/rate-limit checks and load vessel + conversation state.

    Raises HTTPException for any failure (401/402/403/404/429), so callers
    can rely on normal FastAPI HTTP error handling.

    Returns:
        (vessel_profile, conversation_id, history, is_new_conversation)
    """
    from rag.models import ChatMessage

    # ── Rate limit: 10 messages per minute per user ──────────────────────────
    try:
        redis = await get_redis()
        rate_key = f"ratelimit:chat:{current_user.user_id}"
        count = await redis.incr(rate_key)
        if count == 1:
            await redis.expire(rate_key, 60)
        if count > 10:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many messages — please wait a moment before sending another.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # If Redis is down, don't block chat

    # ── Email verification gate (soft — 5 messages before required) ─────────
    if not current_user.email_verified:
        verify_row = await pool.fetchrow(
            "SELECT message_count, email_verified FROM users WHERE id = $1",
            uuid.UUID(current_user.user_id),
        )
        if verify_row and not verify_row["email_verified"] and verify_row["message_count"] >= 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email to continue using RegKnot. Check your inbox for a verification link.",
            )

    # ── Pilot mode gate ────────────────────────────────────────────────────
    from app.config import settings as _cfg
    sub_row = await pool.fetchrow(
        """
        SELECT subscription_tier, trial_ends_at, message_count,
               monthly_message_count, message_cycle_started_at, created_at
        FROM users WHERE id = $1
        """,
        uuid.UUID(current_user.user_id),
    )
    if sub_row and _cfg.pilot_mode and sub_row["subscription_tier"] == "free":
        account_age_days = (datetime.now(timezone.utc) - sub_row["created_at"]).days
        if account_age_days > 14:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The RegKnot pilot program has ended. Thank you for your feedback! Stay tuned for our official launch at regknots.com.",
            )

    # ── Subscription gate ────────────────────────────────────────────────────
    # Admins and internal users always get unlimited access.
    _is_privileged = current_user.is_admin or getattr(current_user, "is_internal", False)

    # D6.55 — Workspace chats are billed at the WORKSPACE level (the
    # owner's card, the workspace's status). Personal trial/cap gates
    # don't apply when the user is chatting inside a workspace they
    # belong to. The workspace membership + status check further down
    # (line ~310) will 403 invalid workspace_ids before any RAG runs,
    # so we can safely skip the personal gates here based on the body
    # signal alone.
    is_workspace_chat = body.workspace_id is not None

    if (
        not is_workspace_chat
        and sub_row and sub_row["subscription_tier"] == "free"
        and not _is_privileged
    ):
        trial_expired = sub_row["trial_ends_at"] < datetime.now(timezone.utc)
        over_limit = sub_row["message_count"] >= 50
        if trial_expired or over_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Trial expired or message limit reached. Subscribe to continue.",
            )

    # ── Mate tier monthly cap gate (Sprint D6.2) ───────────────────────────
    # Mate plan caps at 100 messages per rolling 30-day cycle. Captain and
    # privileged users bypass. Pre-check saves the expensive RAG call when
    # the user is already capped. Race with concurrent requests is bounded
    # to at most one extra message past the cap (the atomic increment step
    # gates subsequent calls).
    # D6.55 — same workspace bypass applies; workspace bills the owner.
    if (
        not is_workspace_chat
        and sub_row and sub_row["subscription_tier"] == "mate"
        and not _is_privileged
    ):
        from app.plans import MATE_MESSAGE_CAP as _MATE_CAP
        cycle_start = sub_row["message_cycle_started_at"]
        cycle_age = datetime.now(timezone.utc) - cycle_start if cycle_start else None
        cycle_still_current = cycle_age is not None and cycle_age.days < 30
        used_this_cycle = sub_row["monthly_message_count"]
        if cycle_still_current and used_this_cycle >= _MATE_CAP:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Mate plan monthly cap reached ({_MATE_CAP} messages). "
                    "Upgrade to Captain for unlimited messages."
                ),
            )

    # 1. Load vessel profile (including enriched fields)
    vessel_profile: dict | None = None
    if body.vessel_id:
        row = await pool.fetchrow(
            """
            SELECT name, vessel_type, flag_state, route_types, cargo_types, gross_tonnage,
                   subchapter, inspection_certificate_type, manning_requirement,
                   key_equipment, route_limitations, additional_details
            FROM vessels
            WHERE id = $1 AND user_id = $2
            """,
            body.vessel_id,
            uuid.UUID(current_user.user_id),
        )
        if row:
            raw_profile = {
                "vessel_name": row["name"],
                "vessel_type": row["vessel_type"],
                "flag_state": row["flag_state"],
                "route_types": list(row["route_types"] or []),
                "cargo_types": list(row["cargo_types"] or []),
                "gross_tonnage": row["gross_tonnage"],
                "subchapter": row["subchapter"],
                "inspection_certificate_type": row["inspection_certificate_type"],
                "manning_requirement": row["manning_requirement"],
                "key_equipment": list(row["key_equipment"] or []) if row["key_equipment"] else None,
                "route_limitations": row["route_limitations"],
                "additional_details": (
                    json.loads(row["additional_details"])
                    if isinstance(row["additional_details"], str)
                    else row["additional_details"]
                ) if row["additional_details"] else None,
            }
            # Remove None/empty values so the prompt isn't cluttered
            vessel_profile = {
                k: v for k, v in raw_profile.items()
                if v is not None and v != {} and v != []
            }
            logger.info(
                "Vessel profile loaded user=%s vessel=%s fields=%s",
                current_user.user_id,
                row["name"],
                list(vessel_profile.keys()),
            )
        else:
            logger.warning(
                "Vessel not found vessel_id=%s user=%s",
                body.vessel_id,
                current_user.user_id,
            )

    # 1b. Load confirmed document data for this vessel
    if body.vessel_id and vessel_profile:
        doc_rows = await pool.fetch(
            """SELECT document_type, extracted_data FROM vessel_documents
               WHERE vessel_id = $1 AND extraction_status = 'confirmed'
               ORDER BY created_at DESC LIMIT 3""",
            body.vessel_id,
        )
        if doc_rows:
            doc_data_list: list[dict] = []
            for dr in doc_rows:
                raw_ed = dr["extracted_data"]
                if isinstance(raw_ed, str):
                    ed = json.loads(raw_ed)
                elif raw_ed:
                    ed = dict(raw_ed)
                else:
                    ed = {}
                if ed:
                    doc_data_list.append({"type": dr["document_type"], "data": ed})
            if doc_data_list:
                vessel_profile["_confirmed_documents"] = doc_data_list
                logger.info(
                    "Loaded %d confirmed document(s) for vessel %s",
                    len(doc_data_list), body.vessel_id,
                )

    # 1c. Load user credentials + sea-time for context injection (D6.63).
    # Replaces the older credential-only loader: build_user_context now
    # returns a single block covering the full mariner record so the
    # chat can reason against the user's qualifications, expirations,
    # and sea-time aggregations in one breath. The block is empty
    # (and skipped from the prompt) when the user has no data.
    credential_context: str | None = None
    try:
        from rag.user_context import build_user_context
        user_ctx = await build_user_context(
            pool=pool,
            user_id=uuid.UUID(current_user.user_id),
            active_vessel_id=body.vessel_id,
        )
        block = user_ctx.as_prompt_block()
        if block:
            credential_context = block
            logger.info(
                "user_context: %d credentials, sea_time=%s, vessel=%s",
                len(user_ctx.credentials),
                user_ctx.sea_time is not None,
                user_ctx.active_vessel.name if user_ctx.active_vessel else None,
            )
    except Exception as exc:
        # Never let a context-injection failure block the chat itself.
        logger.warning(
            "user_context build failed (chat continues without it): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )

    # 2. Resolve conversation — load history or create new record
    conversation_id = body.conversation_id
    is_new_conversation = conversation_id is None
    history: list[ChatMessage] = []

    # Sprint D6.49 — workspace-scoped chat. If body.workspace_id is set,
    # the user MUST already be a member of that workspace. Validate up
    # front; on success, conversations created in this turn carry the
    # workspace_id for shared visibility. If body.workspace_id is None
    # (default for all users without an active workspace context), the
    # conversation behaves as personal-tier chat — no workspace columns
    # touched, no behavioral change vs. pre-D6.49.
    workspace_id = body.workspace_id
    if workspace_id is not None:
        member_role = await pool.fetchval(
            "SELECT role FROM workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            workspace_id, uuid.UUID(current_user.user_id),
        )
        if member_role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of that workspace.",
            )
        # Block writes during card_pending grace state.
        ws_status = await pool.fetchval(
            "SELECT status FROM workspaces WHERE id = $1", workspace_id,
        )
        if ws_status in ("card_pending", "archived", "canceled"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This workspace is read-only "
                    f"(status: {ws_status}). New chats are paused until "
                    "the Owner adds a payment card."
                ),
            )

        # D6.55 — vessel scope must match workspace scope. If a vessel is
        # specified, it must belong to THIS workspace. Personal vessels
        # cannot be used in workspace chat — they belong to a different
        # boat context. If no vessel is specified, auto-select the
        # workspace's first vessel (auto-created at workspace setup).
        if body.vessel_id is not None:
            v_workspace = await pool.fetchval(
                "SELECT workspace_id FROM vessels WHERE id = $1",
                body.vessel_id,
            )
            if v_workspace != workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "That vessel does not belong to this workspace. "
                        "Workspace chats can only use the workspace's "
                        "vessel."
                    ),
                )
        else:
            # Auto-select workspace's primary vessel.
            ws_vessel_id = await pool.fetchval(
                "SELECT id FROM vessels WHERE workspace_id = $1 "
                "ORDER BY created_at ASC LIMIT 1",
                workspace_id,
            )
            if ws_vessel_id is not None:
                # Mutate the body's vessel_id; downstream uses body.vessel_id
                # for the conversation INSERT and for ChatMessage history.
                body.vessel_id = ws_vessel_id

    elif body.vessel_id is not None:
        # D6.55 — personal chat with a vessel: it must be the caller's
        # personal vessel (workspace_id IS NULL, user_id = caller).
        # Workspace vessels can only be used inside their workspace.
        v_row = await pool.fetchrow(
            "SELECT user_id, workspace_id FROM vessels WHERE id = $1",
            body.vessel_id,
        )
        if (
            v_row is None
            or v_row["workspace_id"] is not None
            or v_row["user_id"] != uuid.UUID(current_user.user_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "That vessel is not available for personal chat. "
                    "Workspace vessels can only be used inside their "
                    "workspace."
                ),
            )

    conversation_title: str | None = None  # Sprint D6.29 — soft jurisdictional anchor
    if conversation_id is not None:
        # Conversation lookup: load by id, then check the caller has
        # permission. Personal conversations require user_id match.
        # Workspace conversations require the caller to be a workspace
        # member (regardless of who originally created the chat).
        conv_row = await pool.fetchrow(
            "SELECT id, vessel_id, title, user_id, workspace_id "
            "FROM conversations WHERE id = $1",
            conversation_id,
        )
        if not conv_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        owner_user_id = conv_row["user_id"]
        conv_workspace_id = conv_row["workspace_id"]
        is_personal = conv_workspace_id is None

        if is_personal:
            # Personal conversation — only the owner can resume it.
            if str(owner_user_id) != current_user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )
        else:
            # Workspace conversation — any member of the workspace can
            # resume it. (Validated above when workspace_id present in
            # body, but we re-check here for cases where the client
            # supplied conversation_id without workspace_id.)
            member_role = await pool.fetchval(
                "SELECT role FROM workspace_members "
                "WHERE workspace_id = $1 AND user_id = $2",
                conv_workspace_id, uuid.UUID(current_user.user_id),
            )
            if member_role is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )
            # Pin workspace_id from the loaded conv so downstream
            # logic uses the correct value even if the client omitted it.
            workspace_id = conv_workspace_id

        conversation_title = conv_row.get("title")

        # Update conversation if vessel changed mid-conversation
        current_vessel_id = conv_row["vessel_id"]
        requested_vessel_id = body.vessel_id
        if current_vessel_id != requested_vessel_id:
            await pool.execute(
                "UPDATE conversations SET vessel_id = $1 WHERE id = $2",
                requested_vessel_id, conversation_id,
            )
            logger.info(
                "Vessel changed mid-conversation: %s -> %s",
                current_vessel_id, requested_vessel_id,
            )

        rows = await pool.fetch(
            """
            SELECT role, content FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            conversation_id,
        )
        history = [ChatMessage(role=r["role"], content=r["content"]) for r in reversed(rows)]
    else:
        # New conversation. workspace_id is NULL when the client didn't
        # opt into a workspace context — preserves legacy behavior bit-
        # identical for personal-tier users.
        conversation_id = await pool.fetchval(
            """
            INSERT INTO conversations (user_id, vessel_id, workspace_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            uuid.UUID(current_user.user_id),
            body.vessel_id,
            workspace_id,
        )

    # Sprint D6.30 — soft jurisdictional fingerprint from prior queries.
    # Computed unconditionally; returns None for new or mixed-interest users
    # in which case the prompt block is skipped.
    from rag.jurisdiction_priors import fingerprint_for_user
    fingerprint = await fingerprint_for_user(pool, uuid.UUID(current_user.user_id))

    # Sprint D6.31 — explicit user persona + jurisdiction_focus, declared
    # in onboarding or account settings. Both nullable; the engine skips
    # the prompt line for any field that's None.
    # Sprint D6.33 — verbosity_preference fetched in same row.
    profile_row = await pool.fetchrow(
        "SELECT persona, jurisdiction_focus, verbosity_preference FROM users WHERE id = $1",
        uuid.UUID(current_user.user_id),
    )
    user_persona = profile_row["persona"] if profile_row else None
    user_jurisdiction_focus = profile_row["jurisdiction_focus"] if profile_row else None
    # Per-message override (D6.34) trumps the persistent preference. Only
    # apply the override if the body carries a known value; otherwise fall
    # through to the user's saved default.
    verbosity_override = getattr(body, "verbosity", None)
    if verbosity_override in {"brief", "standard", "detailed"}:
        user_verbosity = verbosity_override
    else:
        user_verbosity = profile_row["verbosity_preference"] if profile_row else None

    # Sprint D6.85 Fix B — persist the user message NOW, before chat()
    # runs. The historic flow inserted both user + assistant in
    # _persist_chat_outcome, which only runs after chat() completes —
    # any SSE cancellation or pipeline crash silently discarded both.
    # Karynn lost two follow-up questions to this on 2026-05-10.
    #
    # Inserting here (after history load, before the chat call)
    # guarantees that the user's question is preserved regardless of
    # what happens next. If chat() succeeds, _persist_chat_outcome
    # only inserts the assistant message; if chat() fails or the
    # client disconnects, the user message still exists and the user
    # can retry. Failure to insert is non-fatal — we'd rather degrade
    # to today's behavior than block the chat.
    try:
        await pool.execute(
            """
            INSERT INTO messages (conversation_id, role, content, cited_regulation_ids)
            VALUES ($1, 'user', $2, '{}')
            """,
            conversation_id,
            body.query,
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist user message upfront (chat continues, may lose this message on cancellation): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )

    return (
        vessel_profile, conversation_id, history, is_new_conversation,
        credential_context, conversation_title, fingerprint,
        user_persona, user_jurisdiction_focus, user_verbosity,
    )


# Sprint D6.85 — persist tasks scheduled here are tracked in this set so
# they don't get garbage-collected mid-flight. asyncio.create_task only
# holds a weak reference to the task; if no other strong ref exists, the
# task can be GC'd before it completes. We add to this set on schedule
# and remove on completion via a done callback.
_PENDING_PERSIST_TASKS: "set[asyncio.Task]" = set()

# Hard upper bound on how long the background persist is allowed to run.
# Past this, we log + drop the task. 30s is generous for two INSERTs +
# a few small UPDATEs; if persistence is taking longer than that, the
# DB is in trouble and a stuck task is worse than a dropped one.
_PERSIST_TIMEOUT_SECONDS = 30.0


def _schedule_persist(
    persist_coro,
    *,
    description: str,
) -> None:
    """Fire-and-forget the persist coro on the event loop with a 30s
    hard cap. Failures are logged, never raised.

    Why this exists (Sprint D6.85 Fix A): historically, persist was
    awaited inline inside the SSE generator. When the client
    disconnected (iOS backgrounding, navigation), Starlette cancelled
    the generator before the await completed and the row was lost.
    Karynn lost two follow-up questions to this on 2026-05-10.

    Running the persist as a top-level task on the loop decouples it
    from the request handler's lifecycle. The task continues even
    after the SSE has closed.

    Tasks are tracked in _PENDING_PERSIST_TASKS so they aren't GC'd
    mid-flight and so we have an observable handle for shutdown
    hygiene (not exposed yet — placeholder).
    """
    async def _wrapped():
        try:
            await asyncio.wait_for(persist_coro, timeout=_PERSIST_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error(
                "background persist timed out after %.0fs (%s) — data may be lost",
                _PERSIST_TIMEOUT_SECONDS, description,
            )
        except asyncio.CancelledError:
            # Loop is shutting down — let the cancellation propagate.
            logger.warning("background persist cancelled (%s)", description)
            raise
        except Exception:
            logger.exception("background persist failed (%s)", description)

    task = asyncio.create_task(_wrapped())
    _PENDING_PERSIST_TASKS.add(task)
    task.add_done_callback(_PENDING_PERSIST_TASKS.discard)


async def _persist_chat_outcome(
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    user_query: str,
    answer: str,
    model_used: str,
    input_tokens: int,
    output_tokens: int,
    cited_section_numbers: list[str],
    vessel_id: uuid.UUID | None,
    vessel_update: dict | None,
    is_new_conversation: bool,
    tier_metadata_json: str | None = None,
) -> None:
    """Persist the assistant side of a completed chat turn.

    Sprint D6.85 — the user message is now persisted UPFRONT by
    _run_chat_preflight. This function only inserts the assistant
    message + vessel update + billing increment. The `user_query`
    argument is retained for log context (title generation, missing-
    regulation detection) but is NOT re-inserted to avoid duplicates.

    Sprint D6.84 — when CONFIDENCE_TIERS_MODE=live and the chat()
    response carries TierMetadata, the JSON-encoded payload is stored
    on the assistant message so a conversation reload reproduces the
    chip. None for shadow / off modes.
    """
    # Resolve cited regulation UUIDs for FK storage
    cited_ids: list[uuid.UUID] = []
    if cited_section_numbers:
        id_rows = await pool.fetch(
            """
            SELECT DISTINCT ON (section_number) id
            FROM regulations
            WHERE section_number = ANY($1)
            """,
            cited_section_numbers,
        )
        cited_ids = [r["id"] for r in id_rows]

    model_alias = _MODEL_ALIAS.get(model_used)
    total_tokens = input_tokens + output_tokens

    await pool.execute(
        """
        INSERT INTO messages
            (conversation_id, role, content, model_used, tokens_used, cited_regulation_ids,
             tier_metadata)
        VALUES ($1, 'assistant', $2, $3, $4, $5, $6::jsonb)
        """,
        conversation_id,
        answer,
        model_alias,
        total_tokens,
        cited_ids,
        tier_metadata_json,
    )

    # Apply vessel profile updates from chat response
    if vessel_update and vessel_id:
        try:
            await _apply_vessel_update(pool, vessel_id, vessel_update)
        except Exception:
            logger.exception("Failed to apply vessel update for vessel %s", vessel_id)

    # Increment message counts for billing + Mate cap tracking.
    # Sprint D6.1 — lifetime `message_count` continues to gate the 50-message
    # free trial cap (unchanged). `monthly_message_count` is the per-cycle
    # counter for Mate 100-msg/month enforcement; it resets to 1 (this
    # message) when the current cycle is ≥30 days old.
    # Logic runs in a single atomic UPDATE so concurrent messages can't
    # double-count or race across the reset boundary.
    await pool.execute(
        """
        UPDATE users
        SET message_count = message_count + 1,
            monthly_message_count = CASE
                WHEN NOW() - message_cycle_started_at >= INTERVAL '30 days' THEN 1
                ELSE monthly_message_count + 1
            END,
            message_cycle_started_at = CASE
                WHEN NOW() - message_cycle_started_at >= INTERVAL '30 days' THEN NOW()
                ELSE message_cycle_started_at
            END
        WHERE id = $1
        """,
        user_id,
    )

    # Fire background title generation for brand-new conversations
    if is_new_conversation:
        asyncio.create_task(
            _generate_title(
                conversation_id=conversation_id,
                query=user_query,
                anthropic_client=anthropic_client,
                pool=pool,
            )
        )

    # Detect queries about regulation sources we don't cover and notify admins.
    asyncio.create_task(
        _check_missing_regulation_request(
            pool=pool,
            user_query=user_query,
            answer=answer,
            cited_count=len(cited_section_numbers),
        )
    )


@router.post("", status_code=status.HTTP_200_OK)
async def chat_endpoint(
    body: "ChatRequestBody",
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
):
    from rag.engine import chat
    from rag.models import ChatResponse
    from app.config import settings

    (
        vessel_profile, conversation_id, history, is_new_conversation,
        credential_context, conversation_title, fingerprint,
        user_persona, user_jurisdiction_focus, user_verbosity,
    ) = await _run_chat_preflight(body, current_user, pool)

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    openai_api_key: str = request.app.state.openai_api_key

    response: ChatResponse = await chat(
        query=body.query,
        conversation_history=history,
        vessel_profile=vessel_profile,
        pool=pool,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
        conversation_id=conversation_id,
        credential_context=credential_context,
        conversation_title=conversation_title,
        fingerprint_summary=fingerprint,
        user_role=user_persona,
        user_jurisdiction_focus=user_jurisdiction_focus,
        user_verbosity=user_verbosity,
        user_id=uuid.UUID(current_user.user_id),
        # D6.58 Slice 3 — ensemble cap is gated by user tier.
        subscription_tier=current_user.tier,
        xai_api_key=settings.xai_api_key,
        web_fallback_enabled=settings.web_fallback_enabled,
        web_fallback_cosine_threshold=settings.web_fallback_cosine_threshold,
        web_fallback_daily_cap=settings.web_fallback_daily_cap,
        web_fallback_cascade_enabled=settings.web_fallback_cascade_enabled,
        hedge_judge_enabled=settings.hedge_judge_enabled,
        query_rewrite_enabled=settings.query_rewrite_enabled,
        reranker_enabled=settings.reranker_enabled,
        # D6.70 Sprint 8 — Layer-2 citation oracle intervention.
        citation_oracle_enabled=settings.citation_oracle_enabled,
        # D6.71 Sprint 7 — Hybrid BM25 + dense retrieval (default OFF).
        hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled,
        hybrid_rrf_k=settings.hybrid_rrf_k,
        # D6.84 Sprint A — confidence tier router. off / shadow / live.
        confidence_tiers_mode=settings.confidence_tiers_mode,
        # D6.86 Phase 1 — judge fires on every cited answer + lead-
        # with-answer synthesis prompt. Both flags default on; toggle
        # via env if regressions appear.
        judge_on_cited_enabled=settings.judge_on_cited_enabled,
        lead_with_answer_enabled=settings.lead_with_answer_enabled,
    )

    # D6.84 — encode the TierMetadata Pydantic to JSON for the JSONB
    # column. None when CONFIDENCE_TIERS_MODE != live.
    tier_metadata_json = (
        response.tier_metadata.model_dump_json() if response.tier_metadata else None
    )
    # D6.85 Fix A — schedule persist as a background task. Survives
    # request cancellation; 30s hard cap. Failures are logged, never
    # raised. User message is already persisted by preflight (Fix B),
    # so a persist failure here only loses the assistant reply.
    _schedule_persist(
        _persist_chat_outcome(
            pool=pool,
            anthropic_client=anthropic_client,
            conversation_id=conversation_id,
            user_id=uuid.UUID(current_user.user_id),
            user_query=body.query,
            answer=response.answer,
            model_used=response.model_used,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cited_section_numbers=[c.section_number for c in response.cited_regulations],
            vessel_id=body.vessel_id,
            vessel_update=response.vessel_update,
            is_new_conversation=is_new_conversation,
            tier_metadata_json=tier_metadata_json,
        ),
        description=f"chat_endpoint conv={conversation_id}",
    )

    return response


@router.post("/stream")
async def chat_stream_endpoint(
    body: "ChatRequestBody",
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
):
    """SSE streaming variant of /chat.

    Auth/billing/rate-limit checks run synchronously before the stream is
    opened so they surface as normal HTTP errors. Once the stream begins, the
    server emits `status` events at each pipeline stage and finishes with a
    single `done` event carrying the full ChatResponse payload.

    Sprint D6.89 — engine task isolation. The engine (chat_with_progress)
    now runs in a TOP-LEVEL asyncio task, decoupled from the SSE
    generator's lifecycle. The SSE generator just observes events
    via an asyncio.Queue and forwards to the client. When the client
    disconnects, the SSE generator dies but the engine task continues
    independently to completion AND handles its own persistence.

    Why this matters: prior to D6.89, persist was only scheduled when
    the engine reached the "done" event. If a client disconnected
    after the engine emitted "Verifying citations..." but before it
    reached "done" (e.g., during a 30-60s web fallback ensemble
    dispatch), the engine task was cancelled along with the SSE
    generator and the answer was lost. Karynn lost two questions to
    this pattern on 2026-05-11 (conv 69ad63be) — the engine ran for
    62-122 seconds, hit citation verification, SSE dropped, engine
    cancelled, persist never fired. With the decoupled engine task,
    the engine runs to completion regardless of client state.
    """
    from rag.engine import chat_with_progress
    from app.config import settings

    (
        vessel_profile, conversation_id, history, is_new_conversation,
        credential_context, conversation_title, fingerprint,
        user_persona, user_jurisdiction_focus, user_verbosity,
    ) = await _run_chat_preflight(body, current_user, pool)

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    openai_api_key: str = request.app.state.openai_api_key
    user_uuid = uuid.UUID(current_user.user_id)

    # Queue of engine events. The engine task puts events on the
    # queue as they're generated; the SSE consumer pulls them off
    # and yields to the client. None sentinel signals "engine done".
    event_queue: asyncio.Queue = asyncio.Queue()

    async def _engine_runner():
        """Run chat_with_progress to completion and persist on done.

        This task is INDEPENDENT of the SSE generator's lifecycle —
        if the client disconnects, this task continues running until
        chat_with_progress finishes its pipeline. The persist happens
        inline at the end (no _schedule_persist needed; this task
        IS the background task).

        On any exception path (engine error, persist failure), the
        sentinel is still put on the queue so the SSE consumer
        terminates cleanly.
        """
        final_data: dict | None = None
        try:
            async for event in chat_with_progress(
                query=body.query,
                conversation_history=history,
                vessel_profile=vessel_profile,
                pool=pool,
                anthropic_client=anthropic_client,
                openai_api_key=openai_api_key,
                conversation_id=conversation_id,
                credential_context=credential_context,
                conversation_title=conversation_title,
                fingerprint_summary=fingerprint,
                user_role=user_persona,
                user_jurisdiction_focus=user_jurisdiction_focus,
                user_verbosity=user_verbosity,
                user_id=user_uuid,
                subscription_tier=current_user.tier,
                xai_api_key=settings.xai_api_key,
                web_fallback_enabled=settings.web_fallback_enabled,
                web_fallback_cosine_threshold=settings.web_fallback_cosine_threshold,
                web_fallback_daily_cap=settings.web_fallback_daily_cap,
                web_fallback_cascade_enabled=settings.web_fallback_cascade_enabled,
                hedge_judge_enabled=settings.hedge_judge_enabled,
                query_rewrite_enabled=settings.query_rewrite_enabled,
                reranker_enabled=settings.reranker_enabled,
                citation_oracle_enabled=settings.citation_oracle_enabled,
                hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled,
                hybrid_rrf_k=settings.hybrid_rrf_k,
                confidence_tiers_mode=settings.confidence_tiers_mode,
                judge_on_cited_enabled=settings.judge_on_cited_enabled,
                lead_with_answer_enabled=settings.lead_with_answer_enabled,
            ):
                if event["event"] == "done":
                    # Capture done payload for the persist step below.
                    event["data"] = _enrich_missing_source_note(body.query, event["data"])
                    final_data = event["data"]
                event_queue.put_nowait(event)
        except asyncio.CancelledError:
            # Engine task itself cancelled (only happens on app
            # shutdown — the SSE generator's cancellation does NOT
            # propagate here because this is a top-level task).
            logger.warning(
                "engine task cancelled (conv=%s) — likely app shutdown",
                conversation_id,
            )
            raise
        except Exception:
            logger.exception(
                "engine runner failed (conv=%s)", conversation_id,
            )
        finally:
            # Persist BEFORE the sentinel so the SSE consumer
            # doesn't try to consume more events while we're writing.
            # The user message is already in DB (preflight Fix B);
            # this writes the assistant message + vessel updates.
            if final_data is not None:
                try:
                    tier_md = final_data.get("tier_metadata")
                    tier_metadata_json = (
                        json.dumps(tier_md) if tier_md else None
                    )
                    await asyncio.wait_for(
                        _persist_chat_outcome(
                            pool=pool,
                            anthropic_client=anthropic_client,
                            conversation_id=conversation_id,
                            user_id=user_uuid,
                            user_query=body.query,
                            answer=final_data["answer"],
                            model_used=final_data["model_used"],
                            input_tokens=final_data["input_tokens"],
                            output_tokens=final_data["output_tokens"],
                            cited_section_numbers=[
                                c["section_number"]
                                for c in final_data["cited_regulations"]
                            ],
                            vessel_id=body.vessel_id,
                            vessel_update=final_data.get("vessel_update"),
                            is_new_conversation=is_new_conversation,
                            tier_metadata_json=tier_metadata_json,
                        ),
                        timeout=_PERSIST_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "engine-task persist timed out (conv=%s)",
                        conversation_id,
                    )
                except Exception:
                    logger.exception(
                        "engine-task persist failed (conv=%s)",
                        conversation_id,
                    )
            try:
                event_queue.put_nowait(None)
            except Exception:
                pass

    # Spawn the engine as a top-level task. asyncio.create_task creates
    # a task on the event loop that is NOT a child of the current
    # task. When the current task (the request handler / SSE generator)
    # is cancelled, this task continues running.
    engine_task = asyncio.create_task(_engine_runner())
    # Track for shutdown hygiene (same set used by _schedule_persist).
    _PENDING_PERSIST_TASKS.add(engine_task)
    engine_task.add_done_callback(_PENDING_PERSIST_TASKS.discard)

    async def event_generator():
        # Sprint D6.23d — emit a `started` event up front carrying
        # the conversation_id, so the client can persist a "pending
        # question" marker keyed by conversation_id BEFORE the slow
        # generation runs.
        yield (
            "event: started\n"
            f"data: {json.dumps({'conversation_id': str(conversation_id)})}\n\n"
        )
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    # Engine task signaled completion.
                    break
                event_type = event["event"]
                payload = event["data"]
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            # Client disconnected. The engine task continues
            # INDEPENDENTLY — do not cancel it. It will finish its
            # pipeline (including web fallback / tier router) and
            # persist the assistant message even though we'll
            # never deliver it to this client. Next page load by
            # the same user will see the message in conversation
            # history.
            logger.info(
                "SSE consumer cancelled by client disconnect (conv=%s); "
                "engine task continues independently",
                conversation_id,
            )
            raise
        except Exception:
            logger.exception(
                "SSE consumer error during stream (conv=%s)",
                conversation_id,
            )
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': 'An error occurred processing your request.'})}\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _apply_vessel_update(pool: asyncpg.Pool, vessel_id: uuid.UUID, update: dict) -> None:
    """Apply progressive profile updates extracted from a chat response to a vessel."""
    sets: list[str] = []
    params: list = []
    idx = 1

    field_mapping = {
        "subchapter": "subchapter",
        "inspection_certificate_type": "inspection_certificate_type",
        "manning_requirement": "manning_requirement",
        "route_limitations": "route_limitations",
        # Sprint D6.17 — flag_state persists from VESSEL_UPDATE so the
        # next conversation turn loads it into the prompt without the
        # user having to re-edit the vessel record.
        "flag_state": "flag_state",
        # Sprint D6.17b — gross_tonnage persists when the agent asks
        # the user to confirm an implausible tonnage value (the
        # TONNAGE PLAUSIBILITY CHECK in the system prompt).
        "gross_tonnage": "gross_tonnage",
    }

    for update_key, db_column in field_mapping.items():
        if update_key not in update:
            continue
        value = update[update_key]
        # Sprint D6.17b — gross_tonnage is NUMERIC(12,2); the LLM may
        # emit it as "35290", "35,290", or even "35290 GT". Strip
        # punctuation/units and coerce; on parse failure, drop the
        # field rather than corrupt the existing value.
        if update_key == "gross_tonnage":
            try:
                cleaned = re.sub(r"[^0-9.\-]", "", str(value))
                if not cleaned:
                    raise ValueError(f"empty after cleaning: {value!r}")
                value = float(cleaned)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "VESSEL_UPDATE gross_tonnage skipped (unparseable %r): %s",
                    update[update_key], exc,
                )
                continue
        sets.append(f"{db_column} = ${idx}")
        params.append(value)
        idx += 1

    if "key_equipment" in update:
        sets.append(f"key_equipment = ${idx}")
        params.append(update["key_equipment"])
        idx += 1

    # Store any extra fields in the JSONB column
    known_keys = set(field_mapping.keys()) | {"key_equipment"}
    additional = {k: v for k, v in update.items() if k not in known_keys}
    if additional:
        sets.append(f"additional_details = COALESCE(additional_details, '{{}}'::jsonb) || ${idx}::jsonb")
        params.append(json.dumps(additional))
        idx += 1

    if sets:
        sets.append("profile_enriched_at = NOW()")
        params.append(vessel_id)
        query = f"UPDATE vessels SET {', '.join(sets)} WHERE id = ${idx}"
        await pool.execute(query, *params)
        logger.info("Updated vessel profile %s with: %s", vessel_id, list(update.keys()))


def _enrich_missing_source_note(query: str, payload: dict) -> dict:
    """Append a note to the answer if the query targets a regulation source we don't cover."""
    if not isinstance(payload, dict):
        return payload
    cited = payload.get("cited_regulations", [])
    if cited:
        return payload  # Got results — not a missing source issue

    query_lower = query.lower()
    for keyword in _MISSING_SOURCES:
        if keyword in query_lower:
            payload = dict(payload)
            payload["answer"] = payload.get("answer", "") + _MISSING_NOTE
            return payload
    return payload


# ── Missing regulation detection ─────────────────────────────────────────────


async def _check_missing_regulation_request(
    pool: asyncpg.Pool,
    user_query: str,
    answer: str,
    cited_count: int,
) -> None:
    """Detect queries about unsupported regulation sources and notify admins.

    Only fires when:
    1. The query mentions a known missing source keyword, AND
    2. The response produced zero citations (indicating no retrieval match)

    Silently logs and never raises — this is a background best-effort notification.
    """
    if cited_count > 0:
        return  # Got results — not a missing source issue

    query_lower = user_query.lower()
    detected: list[str] = []
    for keyword, label in _MISSING_SOURCES.items():
        if keyword in query_lower:
            detected.append(label)

    if not detected:
        return

    labels = ", ".join(detected)
    logger.info("Missing regulation source detected: %s (query: %s)", labels, user_query[:100])

    try:
        # Insert a support-style notification for admin visibility
        await pool.execute(
            """
            INSERT INTO notifications
                (title, body, notification_type, source, is_active)
            VALUES ($1, $2, 'regulation_request', 'system', true)
            """,
            f"Regulation source requested: {labels}",
            f"A user asked about {labels} which is not in the RegKnot database. Query: \"{user_query[:200]}\"",
        )
    except Exception:
        logger.debug("Could not insert regulation request notification", exc_info=True)

    try:
        # Email admin
        import resend
        from app.config import settings
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": "RegKnot <hello@mail.regknots.com>",
            "to": ["hello@regknots.com"],
            "subject": f"Regulation source requested: {labels}",
            "html": (
                f"<h2>Regulation Source Request</h2>"
                f"<p>A user asked about <strong>{labels}</strong> which is not "
                f"currently in the RegKnot database.</p>"
                f"<p><strong>User query:</strong> {user_query[:500]}</p>"
                f"<p>Consider adding this source to the ingest pipeline.</p>"
            ),
        })
    except Exception:
        logger.debug("Could not send regulation request email", exc_info=True)


async def _generate_title(
    conversation_id: uuid.UUID,
    query: str,
    anthropic_client: AsyncAnthropic,
    pool: asyncpg.Pool,
) -> None:
    """Generate a 4-6 word title for a new conversation using Haiku. Non-blocking."""
    try:
        msg = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=24,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate a 4-6 word title for a maritime compliance conversation "
                        f"that starts with this question: {query!r}\n"
                        "Respond with only the title, no punctuation, no quotes."
                    ),
                }
            ],
        )
        title = msg.content[0].text.strip()[:120] if msg.content else None
        if title:
            await pool.execute(
                "UPDATE conversations SET title = $1 WHERE id = $2 AND title IS NULL",
                title,
                conversation_id,
            )
    except Exception:
        pass  # Never affect the chat response


# ── Request body defined here to avoid circular import with rag.models ───────

from pydantic import BaseModel  # noqa: E402


class ChatRequestBody(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    vessel_id: uuid.UUID | None = None
    # Sprint D6.34 — per-message verbosity override. One of:
    #   "brief"     — concise; lead citation + offer to expand
    #   "standard"  — current behavior (no special instruction)
    #   "detailed"  — sectioned, thorough, applicability tables
    # Overrides users.verbosity_preference for this turn only.
    verbosity: str | None = None
    # Sprint D6.49 — workspace-scoped chat. NULL/absent = personal chat
    # (legacy behavior, untouched). When set, the conversation is
    # bound to the workspace and visible to all workspace members. The
    # user must already be a member of the workspace; the preflight
    # validates this and raises 403 if not.
    workspace_id: uuid.UUID | None = None


class ChatCancelBody(BaseModel):
    """Sprint D6.85 Fix C — Stop button payload.

    Submitted from the client when the user aborts a generation
    mid-stream. We persist whatever partial content was rendered to
    the user (so they don't lose what they saw) and mark the assistant
    message as cancelled so the UI can render it distinctly.

    Defined here (post-BaseModel-import) for the same circular-import
    reason ChatRequestBody is — the rag.models module imports symbols
    that would otherwise create a cycle through pydantic.
    """
    conversation_id: uuid.UUID
    partial_content: str = ""  # client-side accumulated delta text


@router.post("/cancel", status_code=status.HTTP_200_OK)
async def chat_cancel_endpoint(
    body: "ChatCancelBody",
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    """Sprint D6.85 Fix C — record a user-initiated cancellation.

    Inserts an assistant message containing whatever partial content
    the client had rendered, marked with cancelled=true. The user's
    question is already in the DB (persisted upfront by preflight),
    so the conversation reads cleanly:

        user:      "what are CFR fire extinguisher inspection rules?"
        assistant: "[partial content...]  [user stopped generation]"

    Fail-safe: if the conversation isn't owned by the caller, returns
    404 (matches conversation-not-found behavior elsewhere). On any
    persist failure, returns 500 — but the user already aborted their
    SSE, so the client should treat 500 as informational.
    """
    conv_row = await pool.fetchrow(
        "SELECT user_id, workspace_id FROM conversations WHERE id = $1",
        body.conversation_id,
    )
    if not conv_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Personal conv: only the owner can cancel. Workspace conv: any member.
    if conv_row["workspace_id"] is None:
        if str(conv_row["user_id"]) != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    else:
        member_role = await pool.fetchval(
            "SELECT role FROM workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            conv_row["workspace_id"], uuid.UUID(current_user.user_id),
        )
        if member_role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    partial = (body.partial_content or "").strip()
    # Always append a stopped marker so the UI can render it visually
    # even if the partial text was empty (e.g., user clicked Stop
    # before any text streamed).
    stopped_marker = "\n\n_[Stopped by user]_" if partial else "_[Stopped by user before generation produced text]_"
    final_content = partial + stopped_marker

    try:
        await pool.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, cited_regulation_ids, cancelled)
            VALUES ($1, 'assistant', $2, '{}', TRUE)
            """,
            body.conversation_id,
            final_content[:8000],  # safety cap
        )
    except Exception:
        logger.exception("Failed to persist cancelled chat outcome")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record cancellation",
        )

    return {"ok": True}
