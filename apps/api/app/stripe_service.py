"""Stripe helpers for checkout sessions and webhook processing."""

import logging

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
    ):
        await _on_subscription_change(data, pool)
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
    status = subscription.status  # active, past_due, canceled, unpaid
    cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
    logger.info(
        "Subscription change: sub_id=%s customer_id=%s status=%s cancel_at_period_end=%s",
        sub_id, customer_id, status, cancel_at_period_end,
    )

    # Detect cancellation pending (user cancelled but still has access until period end)
    if status == "active" and cancel_at_period_end:
        tier, sub_status = "pro", "canceling"
    else:
        status_map = {
            "active": ("pro", "active"),
            "past_due": ("pro", "past_due"),
            "canceled": ("free", "canceled"),
            "unpaid": ("free", "inactive"),
        }
        tier, sub_status = status_map.get(status, ("free", "inactive"))

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
            stripe_subscription_id = $3
        WHERE stripe_subscription_id = $3
        """,
        tier,
        sub_status,
        sub_id,
    )
    logger.info("Sub change UPDATE by subscription_id: %s", result)

    if result == "UPDATE 0" and customer_id:
        # Fallback: lookup by customer_id (handles subscription.created where sub_id not yet stored)
        result = await pool.execute(
            """
            UPDATE users
            SET subscription_tier = $1,
                subscription_status = $2,
                stripe_subscription_id = $3
            WHERE stripe_customer_id = $4
            """,
            tier,
            sub_status,
            sub_id,
            customer_id,
        )
        logger.info("Sub change UPDATE by customer_id fallback: %s", result)

    # Fetch user for email notifications
    row = await pool.fetchrow(
        "SELECT email, full_name FROM users WHERE stripe_subscription_id = $1",
        sub_id,
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
