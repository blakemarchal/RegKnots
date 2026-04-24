"""Stripe helpers for checkout sessions and webhook processing."""

import logging
from datetime import datetime, timezone

import stripe

from app.config import settings
from app.plans import (
    PlanInfo,
    is_paid_tier,
    plan_info_from_price_id,
    resolve_price_for_plan,
)

logger = logging.getLogger(__name__)


def _configure() -> None:
    stripe.api_key = settings.stripe_secret_key


def _get_current_period_end_ts(subscription) -> int | None:
    """Resolve current_period_end across Stripe API versions.

    API <2025-03-31: present on the subscription object directly.
    API ≥2025-03-31: moved onto each subscription item; we read the first item.
    """
    ts = getattr(subscription, "current_period_end", None)
    if ts:
        return ts
    try:
        items = getattr(subscription, "items", None)
        if items and items.data:
            return getattr(items.data[0], "current_period_end", None)
    except Exception:
        pass
    return None


# Sprint D6.1 — accepted `plan` parameter values for create_checkout_session.
# Legacy "monthly"/"annual" route to Captain tier for backward compat with
# any pre-D6.1 frontend code paths still in flight.
_PLAN_TO_LOOKUP: dict[str, tuple[str, str, bool]] = {
    "mate_monthly":    ("mate", "month", False),
    "mate_annual":     ("mate", "year",  False),
    "mate_promo":      ("mate", "month", True),
    "captain_monthly": ("captain", "month", False),
    "captain_annual":  ("captain", "year",  False),
    "captain_promo":   ("captain", "month", True),
    # Legacy shims
    "monthly":         ("captain", "month", False),
    "annual":          ("captain", "year",  False),
}


async def create_checkout_session(
    user_id: str,
    email: str,
    pool,
    *,
    plan: str = "captain_monthly",
    referral_source: str | None = None,
) -> str:
    """Create a Stripe Checkout Session and return the URL.

    If the user has no stripe_customer_id yet, one is created and stored.

    Args:
        plan: One of the keys in _PLAN_TO_LOOKUP. Legacy "monthly"/"annual"
            values map to Captain tier for backward compat.
        referral_source: Attribution key from charity landing pages
            (e.g., "womenoffshore"). Stored on the user record so the
            admin charity accounting view can track contributions owed.
    """
    _configure()

    row = await pool.fetchrow(
        "SELECT stripe_customer_id, subscription_tier, subscription_status FROM users WHERE id = $1",
        __import__("uuid").UUID(user_id),
    )
    if (
        row
        and is_paid_tier(row["subscription_tier"])
        and row["subscription_status"] == "active"
    ):
        raise ValueError("User already has an active subscription")

    customer_id = row["stripe_customer_id"] if row else None

    if not customer_id:
        customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
        customer_id = customer.id
        await pool.execute(
            "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
            customer_id,
            __import__("uuid").UUID(user_id),
        )

    # Resolve plan string → Stripe price ID via the single mapping in plans.py.
    lookup = _PLAN_TO_LOOKUP.get(plan)
    if not lookup:
        raise ValueError(f"Unknown plan: {plan!r}")
    tier, interval, promo = lookup
    price_id = resolve_price_for_plan(tier, interval, promo=promo)
    if not price_id:
        raise ValueError(
            f"No Stripe price_id configured for plan {plan!r} "
            f"(tier={tier} interval={interval} promo={promo}). "
            "Verify the corresponding STRIPE_PRICE_* env var is set."
        )

    # Persist referral source on the user row BEFORE checkout so it's
    # available even if the user abandons checkout mid-flow.
    if referral_source:
        await pool.execute(
            "UPDATE users SET referral_source = COALESCE(referral_source, $1) WHERE id = $2",
            referral_source,
            __import__("uuid").UUID(user_id),
        )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.app_url}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/pricing",
        metadata={
            "user_id": user_id,
            "plan": plan,
            "referral_source": referral_source or "",
        },
    )
    return session.url


async def create_billing_portal_session(user_id: str, pool) -> str:
    """Create a Stripe Billing Portal session and return the URL.

    TODO: Configure plan switching in the Stripe dashboard under
    Settings → Billing → Customer portal. Enable subscription updates
    with monthly ↔ annual price switching, cancellation, and invoice history.
    """
    _configure()
    row = await pool.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1",
        __import__("uuid").UUID(user_id),
    )
    customer_id = row["stripe_customer_id"] if row else None
    if not customer_id:
        raise ValueError("No Stripe customer found for this user")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{settings.app_url}/account",
    )
    return session.url


async def handle_webhook_event(payload: bytes, sig_header: str, pool) -> None:
    """Process a Stripe webhook event."""
    _configure()

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret,
    )

    # stripe-python v15+: event objects are StripeObject, not dict.
    # Use attribute access (not .get()) throughout.
    etype = event.type
    data = event.data.object
    logger.info("Stripe webhook received: type=%s", etype)

    if etype == "checkout.session.completed":
        await _on_checkout_completed(data, pool)
    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    ):
        await _on_subscription_change(data, pool)
    elif etype == "invoice.paid":
        await _on_invoice_paid(data, pool)
    elif etype == "invoice.payment_failed":
        await _on_invoice_payment_failed(data, pool)
    else:
        logger.info("Ignoring Stripe event: %s", etype)


async def _on_checkout_completed(session, pool) -> None:
    customer_id = session.customer
    subscription_id = session.subscription
    logger.info(
        "Checkout completed: customer_id=%s subscription_id=%s",
        customer_id, subscription_id,
    )
    if not customer_id or not subscription_id:
        logger.warning("Checkout missing customer_id or subscription_id, skipping")
        return

    # Resolve which tier this subscription lands in by reading the price
    # off the Stripe subscription object. Sprint D6.1 — tier is no longer
    # hardcoded to 'pro'; it's derived from the price_id via plans.py.
    plan_info: PlanInfo | None = None
    try:
        _configure()
        sub = stripe.Subscription.retrieve(subscription_id)
        price_id = sub.items.data[0].price.id if sub.items.data else None
        plan_info = plan_info_from_price_id(price_id)
    except Exception as exc:
        logger.warning(
            "Could not resolve plan_info for subscription %s: %s",
            subscription_id, exc,
        )

    tier = plan_info.tier if plan_info else "captain"  # safe default if resolution fails
    if plan_info is None:
        logger.warning(
            "Unmapped price_id on subscription %s — defaulting tier to 'captain'. "
            "Verify STRIPE_PRICE_* env vars cover every configured price.",
            subscription_id,
        )

    # Check previous state before updating
    prev = await pool.fetchrow(
        "SELECT subscription_tier, stripe_subscription_id FROM users WHERE stripe_customer_id = $1",
        customer_id,
    )
    if prev and prev["stripe_subscription_id"] == subscription_id:
        logger.info(
            "Skipping duplicate checkout.session.completed for customer %s",
            customer_id,
        )
        return

    was_already_paid = prev and is_paid_tier(prev["subscription_tier"])

    row = await pool.fetchrow(
        """
        UPDATE users
        SET subscription_tier = $1,
            subscription_status = 'active',
            stripe_subscription_id = $2
        WHERE stripe_customer_id = $3
        RETURNING email, full_name
        """,
        tier,
        subscription_id,
        customer_id,
    )
    if row:
        logger.info(
            "Activated %s subscription for customer %s (email=%s)",
            tier, customer_id, row["email"],
        )
    else:
        logger.warning("Checkout UPDATE matched no user for customer %s", customer_id)

    # Send subscription confirmed email only on first activation.
    if row and not was_already_paid:
        try:
            from app.email import send_subscription_confirmed_email
            await send_subscription_confirmed_email(row["email"], row["full_name"] or "")
        except Exception as exc:
            logger.error("Failed to send subscription confirmed email: %s", exc)


async def _on_subscription_change(subscription, pool) -> None:
    sub_id = subscription.id
    customer_id = subscription.customer
    status = subscription.status  # active, past_due, canceled, unpaid, paused, etc.
    cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
    cancel_at = getattr(subscription, "cancel_at", None)

    logger.info(
        "Subscription change: sub_id=%s customer_id=%s status=%s cancel_at_period_end=%s cancel_at=%s",
        sub_id, customer_id, status, cancel_at_period_end, cancel_at,
    )

    # Sprint D6.1 — resolve tier from the subscription's price_id rather
    # than hardcoding 'pro'. Falls back to 'captain' if price is unmapped
    # (safer than silently pinning to 'free' on a genuine unknown).
    price_id: str | None = None
    billing_interval: str | None = None
    try:
        if subscription.items and subscription.items.data:
            item = subscription.items.data[0]
            price_id = item.price.id
            billing_interval = item.price.recurring.interval  # 'month' | 'year'
    except Exception:
        pass

    plan_info = plan_info_from_price_id(price_id)
    if plan_info is None and price_id:
        logger.warning(
            "Unmapped price_id %s on subscription %s — defaulting to captain tier. "
            "Verify STRIPE_PRICE_* env vars cover every configured price.",
            price_id, sub_id,
        )
    # The tier assigned when status is active/trialing/past_due.
    resolved_paid_tier = plan_info.tier if plan_info else "captain"

    # Detect cancellation pending — two Stripe patterns:
    # 1. cancel_at_period_end=True (standard "cancel at end of billing cycle")
    # 2. cancel_at is set (scheduled cancellation date)
    if status == "active" and (cancel_at_period_end or cancel_at):
        tier, sub_status = resolved_paid_tier, "canceling"
    else:
        status_to_paid = resolved_paid_tier
        status_map = {
            "active": (status_to_paid, "active"),
            "past_due": (status_to_paid, "past_due"),
            "canceled": ("free", "canceled"),
            "unpaid": ("free", "inactive"),
            "paused": ("free", "paused"),
            "incomplete": ("free", "inactive"),
            "incomplete_expired": ("free", "inactive"),
            "trialing": (status_to_paid, "active"),
        }
        tier, sub_status = status_map.get(status, ("free", "inactive"))

    # Extract billing period end for DB persistence.
    # In Stripe API 2025-03-31+ current_period_end moved onto subscription items.
    current_period_end_ts = _get_current_period_end_ts(subscription)
    current_period_end = (
        datetime.fromtimestamp(current_period_end_ts, tz=timezone.utc)
        if current_period_end_ts else None
    )

    # Check previous state before updating
    prev = await pool.fetchrow(
        "SELECT subscription_tier, subscription_status FROM users WHERE stripe_subscription_id = $1",
        sub_id,
    )
    if not prev and customer_id:
        prev = await pool.fetchrow(
            "SELECT subscription_tier, subscription_status FROM users WHERE stripe_customer_id = $1",
            customer_id,
        )
    was_already_paid = prev and is_paid_tier(prev["subscription_tier"])
    prev_status = prev["subscription_status"] if prev else None

    # Try lookup by subscription_id first
    result = await pool.execute(
        """
        UPDATE users
        SET subscription_tier = $1,
            subscription_status = $2,
            stripe_subscription_id = $3,
            cancel_at_period_end = $4,
            current_period_end = $5,
            billing_interval = $6
        WHERE stripe_subscription_id = $3
        """,
        tier,
        sub_status,
        sub_id,
        cancel_at_period_end,
        current_period_end,
        billing_interval,
    )
    logger.info("Sub change UPDATE by subscription_id: %s", result)

    if result == "UPDATE 0" and customer_id:
        # Fallback: lookup by customer_id (handles subscription.created where sub_id not yet stored)
        result = await pool.execute(
            """
            UPDATE users
            SET subscription_tier = $1,
                subscription_status = $2,
                stripe_subscription_id = $3,
                cancel_at_period_end = $4,
                current_period_end = $5,
                billing_interval = $6
            WHERE stripe_customer_id = $7
            """,
            tier,
            sub_status,
            sub_id,
            cancel_at_period_end,
            current_period_end,
            billing_interval,
            customer_id,
        )
        logger.info("Sub change UPDATE by customer_id fallback: %s", result)

    # Fetch user for email notifications
    row = await pool.fetchrow(
        "SELECT email, full_name FROM users WHERE stripe_subscription_id = $1",
        sub_id,
    )
    if not row and customer_id:
        row = await pool.fetchrow(
            "SELECT email, full_name FROM users WHERE stripe_customer_id = $1",
            customer_id,
        )

    logger.info(
        "Cancel email check: sub_status=%s prev_status=%s row_found=%s",
        sub_status, prev_status, bool(row),
    )

    # Send cancellation email when transitioning to canceling
    if sub_status == "canceling" and prev_status != "canceling" and row:
        try:
            from app.email import send_subscription_cancelled_email
            await send_subscription_cancelled_email(row["email"], row["full_name"] or "")
            logger.info("Sent cancellation email to %s", row["email"])
        except Exception as exc:
            logger.error("Failed to send cancellation email: %s", exc)

    # Send welcome email only on first activation (not already paid).
    # Fires for any paid tier — mate, captain, or legacy pro.
    if is_paid_tier(tier) and sub_status == "active" and not was_already_paid and row:
        try:
            from app.email import send_subscription_confirmed_email
            await send_subscription_confirmed_email(row["email"], row["full_name"] or "")
            logger.info("Sent %s welcome email to %s", tier, row["email"])
        except Exception as exc:
            logger.error("Failed to send subscription confirmed email: %s", exc)

    # Send pause email when transitioning to paused
    if sub_status == "paused" and prev_status != "paused" and row:
        try:
            from app.email import send_subscription_paused_email
            await send_subscription_paused_email(row["email"], row["full_name"] or "")
            logger.info("Sent subscription paused email to %s", row["email"])
        except Exception as exc:
            logger.error("Failed to send subscription paused email: %s", exc)

    # Send resume email when coming back from paused
    if sub_status == "active" and prev_status == "paused" and row:
        try:
            from app.email import send_subscription_resumed_email
            await send_subscription_resumed_email(row["email"], row["full_name"] or "")
            logger.info("Sent subscription resumed email to %s", row["email"])
        except Exception as exc:
            logger.error("Failed to send subscription resumed email: %s", exc)


async def _on_invoice_paid(invoice, pool) -> None:
    """Handle invoice.paid — update current_period_end.

    This event can arrive BEFORE checkout.session.completed finishes,
    so we try multiple lookup strategies and never return 400 to Stripe.
    """
    try:
        customer_id = getattr(invoice, "customer", None)
        # Stripe API <2025-03-31 exposes invoice.subscription directly.
        # Newer API versions move it under invoice.parent.subscription_details.subscription.
        subscription_id = getattr(invoice, "subscription", None)
        if not subscription_id:
            parent = getattr(invoice, "parent", None)
            if parent:
                sub_details = getattr(parent, "subscription_details", None)
                if sub_details:
                    subscription_id = getattr(sub_details, "subscription", None)

        logger.info("Invoice paid: customer_id=%s subscription_id=%s", customer_id, subscription_id)

        if not subscription_id:
            logger.info("Invoice paid without subscription_id, skipping (one-time payment?)")
            return

        _configure()
        sub = stripe.Subscription.retrieve(subscription_id)
        current_period_end_ts = _get_current_period_end_ts(sub)
        current_period_end = (
            datetime.fromtimestamp(current_period_end_ts, tz=timezone.utc)
            if current_period_end_ts else None
        )

        # Try update by subscription_id first
        result = await pool.execute(
            """
            UPDATE users
            SET current_period_end = $1,
                subscription_status = 'active'
            WHERE stripe_subscription_id = $2
            """,
            current_period_end,
            subscription_id,
        )
        logger.info("Invoice paid UPDATE by subscription_id: %s", result)

        # Fallback: try by customer_id
        if result == "UPDATE 0" and customer_id:
            result = await pool.execute(
                """
                UPDATE users
                SET current_period_end = $1,
                    subscription_status = 'active'
                WHERE stripe_customer_id = $2
                """,
                current_period_end,
                customer_id,
            )
            logger.info("Invoice paid UPDATE by customer_id fallback: %s", result)

        if result == "UPDATE 0":
            logger.warning(
                "Invoice paid matched no user: customer_id=%s subscription_id=%s (may arrive before checkout completes)",
                customer_id, subscription_id,
            )
    except Exception as exc:
        # Log but don't raise — always return 200 to Stripe to prevent infinite retries
        logger.error("Failed to process invoice.paid: %s", exc)


async def _on_invoice_payment_failed(invoice, pool) -> None:
    """Handle invoice.payment_failed — set past_due, send warning email."""
    customer_id = invoice.customer
    if not customer_id:
        return

    # Sprint D6.1 — match any paying tier, not just legacy 'pro'.
    await pool.execute(
        """
        UPDATE users
        SET subscription_status = 'past_due'
        WHERE stripe_customer_id = $1
          AND subscription_tier IN ('pro', 'mate', 'captain')
        """,
        customer_id,
    )
    logger.warning("Payment failed for customer %s — set to past_due", customer_id)

    try:
        from app.email import send_payment_failed_email
        user_row = await pool.fetchrow(
            "SELECT email, full_name FROM users WHERE stripe_customer_id = $1",
            customer_id,
        )
        if user_row:
            await send_payment_failed_email(user_row["email"], user_row["full_name"] or "")
    except Exception as exc:
        logger.error("Failed to send payment failed email: %s", exc)
