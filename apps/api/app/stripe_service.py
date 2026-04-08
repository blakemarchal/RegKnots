"""Stripe helpers for checkout sessions and webhook processing."""

import logging
from datetime import datetime, timezone

import stripe

from app.config import settings

logger = logging.getLogger(__name__)


def _configure() -> None:
    stripe.api_key = settings.stripe_secret_key


async def create_checkout_session(
    user_id: str, email: str, pool, *, plan: str = "monthly",
) -> str:
    """Create a Stripe Checkout Session and return the URL.

    If the user has no stripe_customer_id yet, one is created and stored.
    """
    _configure()

    row = await pool.fetchrow(
        "SELECT stripe_customer_id, subscription_tier, subscription_status FROM users WHERE id = $1",
        __import__("uuid").UUID(user_id),
    )
    if row and row["subscription_tier"] == "pro" and row["subscription_status"] == "active":
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

    price_id = settings.stripe_price_id
    if plan == "annual" and settings.stripe_annual_price_id:
        price_id = settings.stripe_annual_price_id

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.app_url}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/pricing",
        metadata={"user_id": user_id},
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
    logger.info("Checkout completed: customer_id=%s subscription_id=%s", customer_id, subscription_id)
    if not customer_id or not subscription_id:
        logger.warning("Checkout missing customer_id or subscription_id, skipping")
        return

    # Check previous state before updating
    prev = await pool.fetchrow(
        "SELECT subscription_tier, stripe_subscription_id FROM users WHERE stripe_customer_id = $1",
        customer_id,
    )
    if prev and prev["stripe_subscription_id"] == subscription_id:
        logger.info("Skipping duplicate checkout.session.completed for customer %s", customer_id)
        return

    was_already_pro = prev and prev["subscription_tier"] == "pro"

    row = await pool.fetchrow(
        """
        UPDATE users
        SET subscription_tier = 'pro',
            subscription_status = 'active',
            stripe_subscription_id = $1
        WHERE stripe_customer_id = $2
        RETURNING email, full_name
        """,
        subscription_id,
        customer_id,
    )
    if row:
        logger.info("Activated pro subscription for customer %s (email=%s)", customer_id, row["email"])
    else:
        logger.warning("Checkout UPDATE matched no user for customer %s", customer_id)

    # Send subscription confirmed email only if they weren't already pro
    if row and not was_already_pro:
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

    # Detect cancellation pending — two Stripe patterns:
    # 1. cancel_at_period_end=True (standard "cancel at end of billing cycle")
    # 2. cancel_at is set (scheduled cancellation date, cancel_at_period_end may be False)
    if status == "active" and (cancel_at_period_end or cancel_at):
        tier, sub_status = "pro", "canceling"
    else:
        status_map = {
            "active": ("pro", "active"),
            "past_due": ("pro", "past_due"),
            "canceled": ("free", "canceled"),
            "unpaid": ("free", "inactive"),
            "paused": ("free", "paused"),
            "incomplete": ("free", "inactive"),
            "incomplete_expired": ("free", "inactive"),
            "trialing": ("pro", "active"),
        }
        tier, sub_status = status_map.get(status, ("free", "inactive"))

    # Extract billing details for DB persistence
    current_period_end_ts = getattr(subscription, "current_period_end", None)
    current_period_end = (
        datetime.fromtimestamp(current_period_end_ts, tz=timezone.utc)
        if current_period_end_ts else None
    )

    billing_interval = None
    try:
        if subscription.items and subscription.items.data:
            billing_interval = subscription.items.data[0].price.recurring.interval
    except Exception:
        pass

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
    was_already_pro = prev and prev["subscription_tier"] == "pro"
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

    # Send Pro welcome email only on first activation (not already pro)
    if tier == "pro" and sub_status == "active" and not was_already_pro and row:
        try:
            from app.email import send_subscription_confirmed_email
            await send_subscription_confirmed_email(row["email"], row["full_name"] or "")
            logger.info("Sent Pro welcome email to %s", row["email"])
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
        current_period_end_ts = sub.current_period_end
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

    await pool.execute(
        """
        UPDATE users
        SET subscription_status = 'past_due'
        WHERE stripe_customer_id = $1 AND subscription_tier = 'pro'
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
