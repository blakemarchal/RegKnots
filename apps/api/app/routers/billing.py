"""Billing endpoints: checkout, webhook, subscription status."""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.stripe_service import create_billing_portal_session, create_checkout_session, handle_webhook_event

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str = "monthly"


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    body: CheckoutRequest | None = None,
) -> CheckoutResponse:
    from app.config import settings as _settings
    if not _settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment system not configured",
        )
    plan = body.plan if body else "monthly"
    pool = await get_pool()
    try:
        url = await create_checkout_session(user.user_id, user.email, pool, plan=plan)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return CheckoutResponse(checkout_url=url)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="stripe-signature"),
) -> dict:
    payload = await request.body()
    pool = await get_pool()
    try:
        await handle_webhook_event(payload, stripe_signature, pool)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok"}


class BillingStatus(BaseModel):
    tier: str
    subscription_status: str
    trial_ends_at: str | None
    trial_active: bool
    message_count: int
    messages_remaining: int | None
    needs_subscription: bool
    cancel_at_period_end: bool
    current_period_end: str | None
    billing_interval: str | None  # "month" or "year"
    price_amount: int | None  # cents, e.g. 3900
    unlimited: bool = False      # True for admin/internal accounts (bypass all limits)


_FREE_MESSAGE_LIMIT = 50


@router.get("/status", response_model=BillingStatus)
async def billing_status(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> BillingStatus:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT subscription_tier, subscription_status,
               trial_ends_at, message_count,
               cancel_at_period_end, current_period_end, billing_interval,
               stripe_subscription_id,
               is_admin, is_internal
        FROM users WHERE id = $1
        """,
        uuid.UUID(user.user_id),
    )

    now = datetime.now(timezone.utc)
    tier = row["subscription_tier"]
    sub_status = row["subscription_status"]
    trial_ends_at = row["trial_ends_at"]
    message_count = row["message_count"]
    trial_active = tier == "free" and trial_ends_at is not None and trial_ends_at > now
    is_privileged = bool(row["is_admin"]) or bool(row["is_internal"])

    if is_privileged:
        # Admin / internal accounts bypass the subscription gate entirely.
        # See chat.py for the matching enforcement bypass.
        needs_subscription = False
        messages_remaining = None
    elif tier != "free":
        needs_subscription = False
        messages_remaining = None
    elif trial_active:
        needs_subscription = message_count >= _FREE_MESSAGE_LIMIT
        messages_remaining = max(0, _FREE_MESSAGE_LIMIT - message_count)
    else:
        needs_subscription = True
        messages_remaining = 0

    # Paused = full lockout — but still let privileged users through.
    if sub_status == "paused" and not is_privileged:
        needs_subscription = True
        messages_remaining = 0

    # Fetch live price from Stripe if user has a subscription
    price_amount = None
    if tier != "free" and row["stripe_subscription_id"]:
        try:
            import stripe as _stripe
            from app.config import settings as _s
            _stripe.api_key = _s.stripe_secret_key
            sub = _stripe.Subscription.retrieve(row["stripe_subscription_id"])
            if sub.items.data:
                price_amount = sub.items.data[0].price.unit_amount
        except Exception:
            pass

    return BillingStatus(
        tier=tier,
        subscription_status=sub_status,
        trial_ends_at=trial_ends_at.isoformat() if trial_ends_at else None,
        trial_active=trial_active,
        message_count=message_count,
        messages_remaining=messages_remaining,
        needs_subscription=needs_subscription,
        cancel_at_period_end=row["cancel_at_period_end"],
        current_period_end=row["current_period_end"].isoformat() if row["current_period_end"] else None,
        billing_interval=row["billing_interval"],
        price_amount=price_amount,
        unlimited=is_privileged,
    )


class PortalResponse(BaseModel):
    portal_url: str


@router.post("/portal", response_model=PortalResponse)
async def billing_portal(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortalResponse:
    pool = await get_pool()
    try:
        url = await create_billing_portal_session(user.user_id, pool)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found. Subscribe first to manage billing.",
        )
    return PortalResponse(portal_url=url)
