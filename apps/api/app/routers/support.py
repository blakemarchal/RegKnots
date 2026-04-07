"""Support endpoints: AI chat and email escalation."""

import logging
import uuid
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool, get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])

_SUPPORT_SYSTEM_PROMPT = """\
You are RegKnot Support, a helpful assistant for the RegKnot maritime compliance platform.

You help users with:
- Account issues (login, password reset, profile updates)
- Billing questions (subscription, pricing, trial)
- How to use RegKnot features (vessel profiles, citations, certificates, chat)
- Technical issues (browser support, PWA installation, display problems)

You do NOT answer maritime regulation questions — redirect those to the main RegKnot chat.

If you cannot resolve an issue, suggest the user send an email to support@regknots.com.

Be concise, friendly, and practical. The user is likely a working mariner, not a tech expert.\
"""


# ── AI Support Chat ──────────────────────────────────────────────────────────────

class SupportMessage(BaseModel):
    role: str
    content: str


class SupportChatRequest(BaseModel):
    message: str
    history: list[SupportMessage] = []


class SupportChatResponse(BaseModel):
    response: str


@router.post("/chat", response_model=SupportChatResponse)
async def support_chat(
    body: SupportChatRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SupportChatResponse:
    # Rate limit: 5 messages/minute
    try:
        redis = await get_redis()
        rate_key = f"ratelimit:support:{user.user_id}"
        count = await redis.incr(rate_key)
        if count == 1:
            await redis.expire(rate_key, 60)
        if count > 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many support messages — please wait a moment.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis down — allow request

    client: AsyncAnthropic = request.app.state.anthropic

    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": body.message})

    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SUPPORT_SYSTEM_PROMPT,
            messages=messages,
        )
        text = resp.content[0].text if resp.content else "I'm sorry, I couldn't generate a response."
    except Exception as exc:
        logger.error("Support chat error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Support chat is temporarily unavailable.",
        )

    return SupportChatResponse(response=text)


# ── Email Escalation ─────────────────────────────────────────────────────────────

class CharitySuggestionRequest(BaseModel):
    org_name: str
    website: str = ""
    reason: str


class CharitySuggestionResponse(BaseModel):
    sent: bool


@router.post("/charity-suggestion", response_model=CharitySuggestionResponse)
async def charity_suggestion(
    body: CharitySuggestionRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CharitySuggestionResponse:
    if not body.org_name.strip() or not body.reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Organization name and reason are required.",
        )

    from app.email import send_charity_suggestion_email

    try:
        await send_charity_suggestion_email(
            user_email=user.email,
            org_name=body.org_name.strip(),
            website=body.website.strip(),
            reason=body.reason.strip(),
        )
    except Exception as exc:
        logger.error("Charity suggestion email error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send suggestion. Please try again.",
        )

    return CharitySuggestionResponse(sent=True)


# ── Email Escalation ─────────────────────────────────────────────────────────────

class SupportEmailRequest(BaseModel):
    subject: str
    message: str


class SupportEmailResponse(BaseModel):
    sent: bool


@router.post("/email", response_model=SupportEmailResponse)
async def support_email(
    body: SupportEmailRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SupportEmailResponse:
    if not body.subject.strip() or not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject and message are required.",
        )

    import resend
    from app.email import FROM_EMAIL, send_support_confirmation_email

    display_name = user.full_name or user.email

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": ["support@regknots.com"],
            "reply_to": user.email,
            "subject": f"[Support] {body.subject.strip()}",
            "html": (
                f"<p><strong>From:</strong> {user.email}</p>"
                f"<p><strong>Name:</strong> {display_name}</p>"
                f"<p><strong>Role:</strong> {user.role}</p>"
                f"<p><strong>Tier:</strong> {user.tier}</p>"
                f"<hr>"
                f"<p>{body.message.strip()}</p>"
            ),
        })
    except Exception as exc:
        logger.error("Support email error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email. Please try again or email support@regknots.com directly.",
        )

    # Send confirmation to user — non-fatal if it fails (support email already sent)
    try:
        await send_support_confirmation_email(user.email, display_name, body.subject.strip())
    except Exception as exc:
        logger.warning("Support confirmation email failed: %s", exc)

    # Persist the ticket so admins can view and reply via the dashboard.
    # Non-fatal if it fails — the support email has already gone out.
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO support_tickets (user_id, user_email, user_name, subject, message)
            VALUES ($1, $2, $3, $4, $5)
            """,
            uuid.UUID(user.user_id),
            user.email,
            display_name,
            body.subject.strip(),
            body.message.strip(),
        )
    except Exception as exc:
        logger.warning("Support ticket DB insert failed: %s", exc)

    return SupportEmailResponse(sent=True)
