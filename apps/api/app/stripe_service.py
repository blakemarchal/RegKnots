"""Stripe helpers for checkout sessions and webhook processing."""

import logging

import stripe

from app.config import settings

logger = logging.getLogger(__name__)


def _configure() -> None:
    stripe.api_key = settings.stripe_secret_key


async def create_checkout_session(
    user_id: str, email: str, pool,
) -> str:
    """Create a Stripe Checkout Session and return the URL.

    If the user has no stripe_customer_id yet, one is created and stored.
    """
    _configure()

    row = await pool.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1",
        __import__("uuid").UUID(user_id),
    )
    customer_id = row["stripe_customer_id"] if row else None

    if not customer_id:
        customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
        customer_id = customer.id
        await pool.execute(
            "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
            customer_id,
            __import__("uuid").UUID(user_id),
        )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.app_url}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/pricing",
        metadata={"user_id": user_id},
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

    if etype == "checkout.session.completed":
        await _on_checkout_completed(data, pool)
    elif etype in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        await _on_subscription_change(data, pool)
    else:
        logger.debug("Ignoring Stripe event: %s", etype)


async def _on_checkout_completed(session: dict, pool) -> None:
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    if not customer_id or not subscription_id:
        return

    await pool.execute(
        """
        UPDATE users
        SET subscription_tier = 'pro',
            subscription_status = 'active',
            stripe_subscription_id = $1
        WHERE stripe_customer_id = $2
        """,
        subscription_id,
        customer_id,
    )
    logger.info("Activated pro subscription for customer %s", customer_id)


async def _on_subscription_change(subscription: dict, pool) -> None:
    sub_id = subscription.get("id")
    status = subscription.get("status")  # active, past_due, canceled, unpaid

    status_map = {
        "active": ("pro", "active"),
        "past_due": ("pro", "past_due"),
        "canceled": ("free", "canceled"),
        "unpaid": ("free", "inactive"),
    }
    tier, sub_status = status_map.get(status, ("free", "inactive"))

    await pool.execute(
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
    logger.info("Subscription %s → tier=%s status=%s", sub_id, tier, sub_status)
