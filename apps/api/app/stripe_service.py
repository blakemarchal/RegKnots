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
    """Create a Stripe Billing Portal session and return the URL."""
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

    etype = event["type"]
    data = event["data"]["object"]
    logger.info("Stripe webhook received: type=%s", etype)
    print(f"[STRIPE WEBHOOK] type={etype}", flush=True)

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
        print(f"[STRIPE WEBHOOK] ignoring event type={etype}", flush=True)


async def _on_checkout_completed(session: dict, pool) -> None:
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    logger.info("Checkout completed: customer_id=%s subscription_id=%s", customer_id, subscription_id)
    print(f"[STRIPE CHECKOUT] customer_id={customer_id} subscription_id={subscription_id}", flush=True)
    if not customer_id or not subscription_id:
        logger.warning("Checkout missing customer_id or subscription_id, skipping")
        print("[STRIPE CHECKOUT] missing customer_id or subscription_id, skipping", flush=True)
        return

    # Idempotency: skip if already processed
    existing = await pool.fetchrow(
        "SELECT stripe_subscription_id FROM users WHERE stripe_customer_id = $1",
        customer_id,
    )
    if existing and existing["stripe_subscription_id"] == subscription_id:
        logger.info("Skipping duplicate checkout.session.completed for customer %s", customer_id)
        print(f"[STRIPE CHECKOUT] duplicate, skipping customer={customer_id}", flush=True)
        return

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
        print(f"[STRIPE CHECKOUT] activated pro for customer={customer_id} email={row['email']}", flush=True)
    else:
        logger.warning("Checkout UPDATE matched no user for customer %s", customer_id)
        print(f"[STRIPE CHECKOUT] UPDATE matched NO user for customer={customer_id}", flush=True)

    # Send subscription confirmed email (non-blocking)
    if row:
        try:
            from app.email import send_subscription_confirmed_email
            await send_subscription_confirmed_email(row["email"], row["full_name"] or "")
        except Exception as exc:
            logger.error("Failed to send subscription confirmed email: %s", exc)


async def _on_subscription_change(subscription: dict, pool) -> None:
    sub_id = subscription.get("id")
    customer_id = subscription.get("customer")
    status = subscription.get("status")  # active, past_due, canceled, unpaid
    logger.info("Subscription change: sub_id=%s customer_id=%s status=%s", sub_id, customer_id, status)
    print(f"[STRIPE SUB] sub_id={sub_id} customer_id={customer_id} status={status}", flush=True)

    status_map = {
        "active": ("pro", "active"),
        "past_due": ("pro", "past_due"),
        "canceled": ("free", "canceled"),
        "unpaid": ("free", "inactive"),
    }
    tier, sub_status = status_map.get(status, ("free", "inactive"))

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
    print(f"[STRIPE SUB] UPDATE by sub_id result: {result}", flush=True)

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
        print(f"[STRIPE SUB] UPDATE by customer_id fallback result: {result}", flush=True)

    # Send subscription confirmed email on activation
    if tier == "pro" and sub_status == "active":
        row = await pool.fetchrow(
            "SELECT email, full_name FROM users WHERE stripe_subscription_id = $1",
            sub_id,
        )
        if row:
            try:
                from app.email import send_subscription_confirmed_email
                await send_subscription_confirmed_email(row["email"], row["full_name"] or "")
            except Exception as exc:
                logger.error("Failed to send subscription confirmed email: %s", exc)
