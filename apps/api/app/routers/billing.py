"""Billing endpoints: checkout, webhook, subscription status."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.plans import MATE_MESSAGE_CAP, message_cap_for_tier
from app.stripe_service import create_billing_portal_session, create_checkout_session, handle_webhook_event

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    # Sprint D6.3 — accepted plan keys: mate_monthly, mate_annual,
    # mate_promo, captain_monthly, captain_annual, captain_promo. Legacy
    # values "monthly"/"annual" still accepted (mapped to Captain).
    plan: str = "captain_monthly"
    # Charity attribution — set when the user came in via a charity
    # landing page (e.g., /womenoffshore). Persisted on the user record
    # so the admin charity accounting view can attribute their MRR.
    referral_source: str | None = None


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
    plan = body.plan if body else "captain_monthly"
    referral_source = body.referral_source if body else None
    pool = await get_pool()
    try:
        url = await create_checkout_session(
            user.user_id, user.email, pool,
            plan=plan, referral_source=referral_source,
        )
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
    # Sprint D6.2 — Mate tier message-cap visibility. These fields are
    # populated for every user but only meaningful when tier=='mate':
    #   - monthly_message_cap: 100 for mate, null for captain/legacy pro
    #   - monthly_messages_used: count this cycle (always 0 for captain)
    #   - monthly_messages_remaining: null for captain (unlimited)
    #   - cycle_resets_at: ISO time when the current 30-day cycle rolls over
    monthly_message_cap: int | None
    monthly_messages_used: int
    monthly_messages_remaining: int | None
    cycle_resets_at: str | None
    # Sprint D6.3b — charity-partner referral for lifetime-promo pricing.
    # If set (e.g. 'womenoffshore'), upgrade flows should surface promo
    # price IDs rather than standard prices. Null means standard pricing.
    referral_source: str | None


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
               monthly_message_count, message_cycle_started_at,
               cancel_at_period_end, current_period_end, billing_interval,
               stripe_subscription_id, referral_source,
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
    monthly_count = row["monthly_message_count"]
    cycle_start = row["message_cycle_started_at"]
    trial_active = tier == "free" and trial_ends_at is not None and trial_ends_at > now
    is_privileged = bool(row["is_admin"]) or bool(row["is_internal"])

    # Compute cycle reset — Mate users see this roll over every 30 days.
    # If the cycle has already expired, the UI should show "resets now" /
    # count of 0 rather than a stale in-past timestamp.
    cycle_resets_at = cycle_start + timedelta(days=30) if cycle_start else None
    if cycle_resets_at is not None and cycle_resets_at <= now:
        # Cycle will reset on the next message — expose the fresh counter.
        monthly_count = 0
        cycle_resets_at = now + timedelta(days=30)

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

    # Mate-specific cap visibility. Captain and legacy pro stay unlimited.
    if is_privileged:
        monthly_message_cap: int | None = None
        monthly_messages_remaining: int | None = None
    else:
        monthly_message_cap = message_cap_for_tier(tier)
        if monthly_message_cap is not None:
            monthly_messages_remaining = max(0, monthly_message_cap - monthly_count)
            # If Mate user has already hit the cap, also set needs_subscription
            # so the frontend knows to surface an upgrade prompt even though
            # the user is already paying.
            if monthly_messages_remaining == 0 and not needs_subscription:
                needs_subscription = True
        else:
            monthly_messages_remaining = None

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
        monthly_message_cap=monthly_message_cap,
        monthly_messages_used=monthly_count if monthly_message_cap is not None else 0,
        monthly_messages_remaining=monthly_messages_remaining,
        cycle_resets_at=cycle_resets_at.isoformat() if cycle_resets_at else None,
        referral_source=row["referral_source"],
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
