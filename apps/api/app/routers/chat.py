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
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

import asyncpg
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool, get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Maps full Anthropic model IDs to the short aliases stored in the DB
_MODEL_ALIAS: dict[str, str] = {
    "claude-haiku-4-5-20251001": "haiku",
    "claude-sonnet-4-6": "sonnet",
    "claude-opus-4-6": "opus",
}


@router.post("", status_code=status.HTTP_200_OK)
async def chat_endpoint(
    body: "ChatRequestBody",
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
):
    from rag.engine import chat
    from rag.models import ChatMessage, ChatResponse

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

    # ── Pilot mode gate ────────────────────────────────────────────────────
    from app.config import settings as _cfg
    sub_row = await pool.fetchrow(
        "SELECT subscription_tier, trial_ends_at, message_count, created_at FROM users WHERE id = $1",
        uuid.UUID(current_user.user_id),
    )
    if sub_row and _cfg.pilot_mode and sub_row["subscription_tier"] == "free":
        account_age_days = (datetime.now(timezone.utc) - sub_row["created_at"]).days
        if account_age_days > 14:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The RegKnots pilot program has ended. Thank you for your feedback! Stay tuned for our official launch at regknots.com.",
            )

    # ── Subscription gate ────────────────────────────────────────────────────
    if sub_row and sub_row["subscription_tier"] == "free":
        trial_expired = sub_row["trial_ends_at"] < datetime.now(timezone.utc)
        over_limit = sub_row["message_count"] >= 50
        if trial_expired or over_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Trial expired or message limit reached. Subscribe to continue.",
            )

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    openai_api_key: str = request.app.state.openai_api_key

    # 1. Load vessel profile (including enriched fields)
    vessel_profile: dict | None = None
    if body.vessel_id:
        row = await pool.fetchrow(
            """
            SELECT name, vessel_type, route_types, cargo_types, gross_tonnage,
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

    # 2. Resolve conversation — load history or create new record
    conversation_id = body.conversation_id
    is_new_conversation = conversation_id is None
    history: list[ChatMessage] = []

    if conversation_id is not None:
        # Verify ownership
        exists = await pool.fetchval(
            "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
            conversation_id,
            uuid.UUID(current_user.user_id),
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

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
        conversation_id = await pool.fetchval(
            """
            INSERT INTO conversations (user_id, vessel_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            uuid.UUID(current_user.user_id),
            body.vessel_id,
        )

    # 3. Run RAG engine
    response: ChatResponse = await chat(
        query=body.query,
        conversation_history=history,
        vessel_profile=vessel_profile,
        pool=pool,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
        conversation_id=conversation_id,
    )

    # 4. Resolve cited regulation UUIDs for FK storage
    cited_ids: list[uuid.UUID] = []
    if response.cited_regulations:
        section_numbers = [c.section_number for c in response.cited_regulations]
        id_rows = await pool.fetch(
            """
            SELECT DISTINCT ON (section_number) id
            FROM regulations
            WHERE section_number = ANY($1)
            """,
            section_numbers,
        )
        cited_ids = [r["id"] for r in id_rows]

    # 5. Persist messages
    model_alias = _MODEL_ALIAS.get(response.model_used)
    total_tokens = response.input_tokens + response.output_tokens

    await pool.execute(
        """
        INSERT INTO messages (conversation_id, role, content, cited_regulation_ids)
        VALUES ($1, 'user', $2, '{}')
        """,
        conversation_id,
        body.query,
    )
    await pool.execute(
        """
        INSERT INTO messages
            (conversation_id, role, content, model_used, tokens_used, cited_regulation_ids)
        VALUES ($1, 'assistant', $2, $3, $4, $5)
        """,
        conversation_id,
        response.answer,
        model_alias,
        total_tokens,
        cited_ids,
    )

    # 6. Apply vessel profile updates from chat response
    if response.vessel_update and body.vessel_id:
        try:
            await _apply_vessel_update(pool, body.vessel_id, response.vessel_update)
        except Exception:
            logger.exception("Failed to apply vessel update for vessel %s", body.vessel_id)

    # 7. Increment message count for billing
    await pool.execute(
        "UPDATE users SET message_count = message_count + 1 WHERE id = $1",
        uuid.UUID(current_user.user_id),
    )

    # 8. Fire background title generation for brand-new conversations
    if is_new_conversation:
        asyncio.create_task(
            _generate_title(
                conversation_id=conversation_id,
                query=body.query,
                anthropic_client=anthropic_client,
                pool=pool,
            )
        )

    return response


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
    }

    for update_key, db_column in field_mapping.items():
        if update_key in update:
            sets.append(f"{db_column} = ${idx}")
            params.append(update[update_key])
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
