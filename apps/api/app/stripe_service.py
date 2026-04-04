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
    status = subscription.get("status")  # active, past_due, canceled, unpaid
    logger.info("Subscription change: sub_id=%s status=%s", sub_id, status)
    print(f"[STRIPE SUB] sub_id={sub_id} status={status}", flush=True)

    status_map = {
        "active": ("pro", "active"),
        "past_due": ("pro", "past_due"),
        "canceled": ("free", "canceled"),
        "unpaid": ("free", "inactive"),
    }
    tier, sub_status = status_map.get(status, ("free", "inactive"))

    # Idempotency: skip if DB already matches
    existing = await pool.fetchrow(
        "SELECT subscription_tier, subscription_status FROM users WHERE stripe_subscription_id = $1",
        sub_id,
    )
    if existing and existing["subscription_tier"] == tier and existing["subscription_status"] == sub_status:
        logger.info("Skipping duplicate subscription change for %s (already %s/%s)", sub_id, tier, sub_status)
        print(f"[STRIPE SUB] duplicate, skipping sub={sub_id}", flush=True)
        return
    if not existing:
        print(f"[STRIPE SUB] no user found with stripe_subscription_id={sub_id}", flush=True)

    result = await pool.execute(
        """
        UPDATE users
        SET subscription_tier = $1,
            subscription_status = $2
        WHERE stripe_subscription_id = $3
        """,
        tier,
        sub_status,
        sub_id,
    )
    logger.info("Subscription %s → tier=%s status=%s (result=%s)", sub_id, tier, sub_status, result)
    print(f"[STRIPE SUB] {sub_id} → tier={tier} status={sub_status} result={result}", flush=True)
