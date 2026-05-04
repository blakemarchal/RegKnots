"""Stripe helpers for checkout sessions and webhook processing."""

import logging
from datetime import datetime, timezone
from uuid import UUID

import stripe

from app.config import settings
from app.plans import (
    PlanInfo,
    is_paid_tier,
    plan_info_from_price_id,
    resolve_price_for_plan,
)
from app.plans_workspace import (
    is_wheelhouse_price_id,
    resolve_wheelhouse_price_id,
    wheelhouse_interval_from_price_id,
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


# ── Workspace (Wheelhouse) checkout + portal ────────────────────────────────
#
# Sprint D6.54 — Wheelhouse billing.
#
# Each workspace gets its OWN Stripe customer (separate from the owner's
# personal customer). This keeps workspace billing tidy and makes
# ownership transfers a Stripe-side operation: the new owner takes
# control of an existing customer rather than a subscription migrating
# between customers. The owner's email is the customer email; metadata
# tracks which workspace + which user owns it.
#
# Workspace state machine:
#
#   trialing      → newly created; 30-day free trial; no Stripe
#                   relationship yet
#   active        → has paid subscription; checkout completed
#   past_due      → invoice failed; access remains for grace, Stripe
#                   handles dunning emails
#   card_pending  → trial expired without card OR owner removed card;
#                   30-day read-only grace
#   archived      → grace expired; 90-day retention before purge
#   canceled      → owner explicitly canceled; 90-day retention


async def create_workspace_checkout_session(
    workspace_id: UUID,
    owner_user_id: str,
    plan: str,  # 'monthly' | 'annual'
    pool,
) -> str:
    """Create a Stripe Checkout Session for a workspace and return the URL.

    First call creates the Stripe customer and stores it on the
    workspace row. Subsequent calls reuse it — idempotent in the sense
    that one workspace = one customer, even if the owner restarts the
    flow multiple times.
    """
    _configure()

    price_id = resolve_wheelhouse_price_id(plan)
    if not price_id:
        raise ValueError(
            f"No Stripe price configured for Wheelhouse plan {plan!r}. "
            "Verify STRIPE_PRICE_WHEELHOUSE_* env vars are set."
        )

    ws = await pool.fetchrow(
        "SELECT name, stripe_customer_id, stripe_subscription_id, status "
        "FROM workspaces WHERE id = $1",
        workspace_id,
    )
    if ws is None:
        raise ValueError("Workspace not found")
    if ws["status"] in ("archived", "canceled"):
        # Allow status='card_pending' through — that's the WHOLE point
        # of this flow; user is rescuing a workspace that hit the grace
        # period. Block only the truly-dead states.
        raise ValueError(
            f"Workspace is {ws['status']}; can't take new payment. "
            "Restore via support if recovery is intended."
        )
    if ws["stripe_subscription_id"]:
        raise ValueError(
            "Workspace already has an active subscription. Use the "
            "billing portal to manage it instead."
        )

    customer_id = ws["stripe_customer_id"]
    if not customer_id:
        # Look up owner email/name for the customer record so Stripe
        # receipts go to the right person.
        owner = await pool.fetchrow(
            "SELECT email, full_name FROM users WHERE id = $1",
            UUID(owner_user_id),
        )
        if owner is None:
            raise ValueError("Owner user not found")
        customer = stripe.Customer.create(
            email=owner["email"],
            name=owner["full_name"] or owner["email"],
            metadata={
                "workspace_id": str(workspace_id),
                "owner_user_id": owner_user_id,
                "kind": "wheelhouse",
            },
        )
        customer_id = customer.id
        await pool.execute(
            "UPDATE workspaces SET stripe_customer_id = $1 WHERE id = $2",
            customer_id, workspace_id,
        )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=(
            f"{settings.app_url}/workspaces/{workspace_id}"
            f"?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
        ),
        cancel_url=f"{settings.app_url}/workspaces/{workspace_id}",
        metadata={
            "workspace_id": str(workspace_id),
            "owner_user_id": owner_user_id,
            "plan": plan,
            "kind": "wheelhouse",
        },
        # Pass workspace_id through to the subscription itself so the
        # webhook handler can route subscription events to the right
        # workspace even on later updates (cancel, plan change).
        subscription_data={
            "metadata": {
                "workspace_id": str(workspace_id),
                "kind": "wheelhouse",
            },
        },
    )
    return session.url


async def create_workspace_billing_portal_session(
    workspace_id: UUID, pool,
) -> str:
    """Stripe Billing Portal URL for the workspace's customer.

    Owner-only (caller enforces). The portal handles cancel, update
    card, and switch monthly ↔ annual based on what's configured in
    Stripe Dashboard → Settings → Billing → Customer portal.
    """
    _configure()
    customer_id = await pool.fetchval(
        "SELECT stripe_customer_id FROM workspaces WHERE id = $1",
        workspace_id,
    )
    if not customer_id:
        raise ValueError(
            "Workspace has no Stripe customer yet. Add a payment method "
            "first."
        )

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{settings.app_url}/workspaces/{workspace_id}",
    )
    return session.url


# ── Webhook event router ───────────────────────────────────────────────────


def _is_wheelhouse_event(obj) -> bool:
    """Decide whether a Stripe object (subscription / invoice / session)
    relates to a Wheelhouse subscription.

    Two signals, in priority order:
      1. metadata.kind == 'wheelhouse' (set on subscription + checkout
         metadata at creation time) — most reliable, survives plan
         changes.
      2. The first line item's price_id matches a known Wheelhouse
         price — fallback if metadata wasn't propagated.

    Returns False on objects that have neither signal — those are
    user-tier subscriptions and route to the existing flow.
    """
    metadata = getattr(obj, "metadata", None) or {}
    if hasattr(metadata, "get"):
        if metadata.get("kind") == "wheelhouse":
            return True

    # Subscription or invoice → look at items[0].price.id
    try:
        items = getattr(obj, "items", None)
        if items and getattr(items, "data", None):
            price = getattr(items.data[0], "price", None)
            if price and is_wheelhouse_price_id(getattr(price, "id", None)):
                return True
    except Exception:
        pass

    # Invoice line items live under .lines.data, not .items.data
    try:
        lines = getattr(obj, "lines", None)
        if lines and getattr(lines, "data", None):
            price = getattr(lines.data[0], "price", None)
            if price and is_wheelhouse_price_id(getattr(price, "id", None)):
                return True
    except Exception:
        pass

    return False


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

    # D6.54 — for subscription events we need the FULL subscription
    # object (with line items + price IDs) to route to the right
    # handler. The event payload usually has it; but for robustness
    # we re-retrieve when the routing signal is missing.
    is_wheelhouse = False
    try:
        is_wheelhouse = _is_wheelhouse_event(data)
        # Subscription objects in events sometimes lack .items expansion;
        # fetch fresh if we can't decide and we have an id.
        if not is_wheelhouse and getattr(data, "object", None) == "subscription":
            sub_id = getattr(data, "id", None)
            if sub_id:
                full = stripe.Subscription.retrieve(sub_id)
                if _is_wheelhouse_event(full):
                    is_wheelhouse = True
                    data = full
    except Exception as exc:
        logger.warning("Wheelhouse routing check failed for %s: %s", etype, exc)

    if etype == "checkout.session.completed":
        # Checkout sessions carry our workspace_id metadata (set when we
        # created the session), so `_is_wheelhouse_event` reliably
        # identifies them via the `kind=wheelhouse` marker.
        if is_wheelhouse:
            await _on_workspace_checkout_completed(data, pool)
        else:
            await _on_checkout_completed(data, pool)
    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    ):
        if is_wheelhouse:
            await _on_workspace_subscription_change(data, pool)
        else:
            await _on_subscription_change(data, pool)
    elif etype == "invoice.paid":
        if is_wheelhouse:
            await _on_workspace_invoice_paid(data, pool)
        else:
            await _on_invoice_paid(data, pool)
    elif etype == "invoice.payment_failed":
        if is_wheelhouse:
            await _on_workspace_invoice_payment_failed(data, pool)
        else:
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
    """Handle invoice.paid — update current_period_end + record to ledger.

    Two responsibilities:
      1. Bump the user's current_period_end + reactivate (existing).
      2. Sprint D6.14 — insert a row into billing_events so partner-
         tithe aggregations have an authoritative per-invoice ledger.
         Skips silently if the user can't be matched (event arrived
         before checkout completed); the event will retry from Stripe.

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
            return  # Skip ledger insert — Stripe will retry the event

        # ── Sprint D6.14 — partner-tithe ledger insert ───────────────────
        # Done after the user-row update so we can safely look up the
        # user's referral_source / tier / billing_interval at the moment
        # of payment.
        await _record_billing_event(invoice, sub, subscription_id, customer_id, pool)
    except Exception as exc:
        # Log but don't raise — always return 200 to Stripe to prevent infinite retries
        logger.error("Failed to process invoice.paid: %s", exc)


async def _record_billing_event(invoice, sub, subscription_id, customer_id, pool) -> None:
    """Insert a row into billing_events for this paid invoice.

    Idempotent via UNIQUE (stripe_invoice_id) — if Stripe redelivers the
    webhook the second insert will conflict and we silently skip.
    """
    invoice_id = getattr(invoice, "id", None)
    if not invoice_id:
        logger.warning("invoice.paid without id — skipping ledger insert")
        return

    amount_paid = int(getattr(invoice, "amount_paid", 0) or 0)
    amount_total = int(getattr(invoice, "amount_due", 0) or amount_paid)
    currency = (getattr(invoice, "currency", None) or "usd").lower()

    paid_at_ts = getattr(invoice, "status_transitions", None)
    paid_at = None
    if paid_at_ts:
        paid_at_unix = getattr(paid_at_ts, "paid_at", None) or getattr(invoice, "created", None)
        if paid_at_unix:
            paid_at = datetime.fromtimestamp(paid_at_unix, tz=timezone.utc)
    if paid_at is None:
        # Fallback to invoice.created (already a unix ts)
        created = getattr(invoice, "created", None)
        if created:
            paid_at = datetime.fromtimestamp(created, tz=timezone.utc)
        else:
            paid_at = datetime.now(tz=timezone.utc)

    # Period boundaries — Stripe API places these on the subscription's
    # first item in newer API versions.
    period_start = period_end = None
    period_start_ts = getattr(invoice, "period_start", None)
    period_end_ts = getattr(invoice, "period_end", None)
    if period_start_ts:
        period_start = datetime.fromtimestamp(period_start_ts, tz=timezone.utc)
    if period_end_ts:
        period_end = datetime.fromtimestamp(period_end_ts, tz=timezone.utc)
    # Fallback to subscription items[0] if invoice didn't carry them
    if not period_start or not period_end:
        items = getattr(sub, "items", None)
        if items:
            data = getattr(items, "data", None) or []
            if data:
                item = data[0]
                if not period_start and getattr(item, "current_period_start", None):
                    period_start = datetime.fromtimestamp(item.current_period_start, tz=timezone.utc)
                if not period_end and getattr(item, "current_period_end", None):
                    period_end = datetime.fromtimestamp(item.current_period_end, tz=timezone.utc)

    # Look up user metadata (referral_source, tier, billing_interval) at
    # payment time. If the user can't be found we skip — the user-row
    # update upstream already returned without raising in that case.
    row = await pool.fetchrow(
        """
        SELECT id, referral_source, subscription_tier, billing_interval
        FROM users
        WHERE stripe_subscription_id = $1
           OR stripe_customer_id = $2
        LIMIT 1
        """,
        subscription_id,
        customer_id,
    )
    if not row:
        logger.warning(
            "billing_events: no user found for invoice %s (sub=%s cust=%s) — skipping ledger insert",
            invoice_id, subscription_id, customer_id,
        )
        return

    try:
        await pool.execute(
            """
            INSERT INTO billing_events (
                user_id, stripe_invoice_id, stripe_subscription_id, stripe_customer_id,
                amount_paid_cents, amount_total_cents, currency,
                period_start, period_end, paid_at,
                referral_source, subscription_tier, billing_interval
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7,
                $8, $9, $10,
                $11, $12, $13
            )
            ON CONFLICT (stripe_invoice_id) DO NOTHING
            """,
            row["id"],
            invoice_id,
            subscription_id,
            customer_id,
            amount_paid,
            amount_total,
            currency,
            period_start,
            period_end,
            paid_at,
            row["referral_source"],
            row["subscription_tier"],
            row["billing_interval"],
        )
        logger.info(
            "billing_events: recorded invoice %s ($%.2f %s) for user %s referral=%s",
            invoice_id, amount_paid / 100.0, currency.upper(), row["id"], row["referral_source"],
        )
    except Exception as exc:
        # Don't tank the whole webhook — the user-row update already
        # succeeded; ledger gap is recoverable via backfill.
        logger.error("billing_events: insert failed for invoice %s: %s", invoice_id, exc)


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


# ── Workspace (Wheelhouse) webhook handlers ────────────────────────────────


async def _resolve_workspace_id_for_event(obj, pool) -> UUID | None:
    """Find the workspace_id for a Stripe event object.

    Tries, in order:
      1. metadata.workspace_id (set by us at checkout creation)
      2. Lookup by stripe_subscription_id
      3. Lookup by stripe_customer_id

    Returns None if no match — handler should log and bail rather than
    raise so we always return 200 to Stripe (avoid retry storms).
    """
    metadata = getattr(obj, "metadata", None) or {}
    if hasattr(metadata, "get"):
        ws_id = metadata.get("workspace_id")
        if ws_id:
            try:
                return UUID(ws_id)
            except (ValueError, TypeError):
                pass

    sub_id = getattr(obj, "subscription", None) or getattr(obj, "id", None)
    if sub_id and isinstance(sub_id, str) and sub_id.startswith("sub_"):
        ws_id = await pool.fetchval(
            "SELECT id FROM workspaces WHERE stripe_subscription_id = $1",
            sub_id,
        )
        if ws_id:
            return ws_id

    customer_id = getattr(obj, "customer", None)
    if customer_id and isinstance(customer_id, str):
        ws_id = await pool.fetchval(
            "SELECT id FROM workspaces WHERE stripe_customer_id = $1",
            customer_id,
        )
        if ws_id:
            return ws_id

    return None


async def _on_workspace_checkout_completed(session, pool) -> None:
    """checkout.session.completed → activate the workspace.

    Stores stripe_subscription_id on the workspace row and flips
    status to 'active'. Idempotent — second delivery for the same
    subscription is a no-op.
    """
    customer_id = getattr(session, "customer", None)
    subscription_id = getattr(session, "subscription", None)
    logger.info(
        "Workspace checkout completed: customer=%s subscription=%s",
        customer_id, subscription_id,
    )
    if not customer_id or not subscription_id:
        logger.warning(
            "Workspace checkout missing customer/subscription — skipping",
        )
        return

    workspace_id = await _resolve_workspace_id_for_event(session, pool)
    if workspace_id is None:
        logger.warning(
            "Workspace checkout could not resolve workspace_id "
            "(customer=%s subscription=%s) — skipping",
            customer_id, subscription_id,
        )
        return

    # Idempotency: if this subscription is already on the workspace,
    # skip. (Stripe replays webhooks for ~3 days on success-200 fails.)
    prev_sub = await pool.fetchval(
        "SELECT stripe_subscription_id FROM workspaces WHERE id = $1",
        workspace_id,
    )
    if prev_sub == subscription_id:
        logger.info(
            "Duplicate checkout.session.completed for workspace %s — skipping",
            workspace_id,
        )
        return

    await pool.execute(
        """
        UPDATE workspaces SET
          status = 'active',
          stripe_subscription_id = $1,
          card_pending_started_at = NULL,
          updated_at = now()
        WHERE id = $2
        """,
        subscription_id, workspace_id,
    )

    # Audit log
    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events "
            "(workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, 'subscription_started', NULL, $2::jsonb)",
            workspace_id,
            json.dumps({
                "stripe_subscription_id": subscription_id,
                "stripe_customer_id": customer_id,
            }),
        )
    except Exception as exc:
        logger.warning("workspace_billing_events insert failed: %s", exc)

    # Owner email — first activation only.
    try:
        owner_email = await pool.fetchval(
            "SELECT u.email FROM workspaces w "
            "JOIN users u ON u.id = w.owner_user_id "
            "WHERE w.id = $1",
            workspace_id,
        )
        ws_name = await pool.fetchval(
            "SELECT name FROM workspaces WHERE id = $1", workspace_id,
        )
        if owner_email and ws_name:
            from app.email import send_workspace_subscription_confirmed_email
            await send_workspace_subscription_confirmed_email(
                owner_email, ws_name,
            )
    except Exception as exc:
        logger.error("workspace subscription confirmed email failed: %s", exc)


async def _on_workspace_subscription_change(subscription, pool) -> None:
    """customer.subscription.* → sync workspace status.

    Status mapping (Stripe → workspaces.status):
      active                → active
      trialing              → active (Stripe-managed trial; we don't use it
                              today but mapping is forward-compatible)
      past_due              → active (read-only enforcement is by `status`;
                              Stripe handles dunning emails)
      canceled              → canceled (90-day retention before purge)
      unpaid / incomplete   → card_pending (give the owner a grace window)
      paused / incomplete_expired → archived
    """
    sub_id = getattr(subscription, "id", None)
    customer_id = getattr(subscription, "customer", None)
    stripe_status = getattr(subscription, "status", None)
    cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)

    workspace_id = await _resolve_workspace_id_for_event(subscription, pool)
    if workspace_id is None:
        logger.warning(
            "Workspace subscription.%s could not resolve workspace "
            "(sub=%s customer=%s)",
            stripe_status, sub_id, customer_id,
        )
        return

    # Map Stripe status → workspaces.status. Note we deliberately keep
    # past_due as "active" so members aren't locked out mid-month for a
    # transient card decline. Stripe's dunning will resolve it or escalate
    # to canceled, which we DO act on.
    status_map = {
        "active": "active",
        "trialing": "active",
        "past_due": "active",
        "canceled": "canceled",
        "unpaid": "card_pending",
        "incomplete": "card_pending",
        "paused": "archived",
        "incomplete_expired": "archived",
    }
    new_status = status_map.get(stripe_status, "active")

    # Special case: cancel-at-period-end is just a flag — keep status
    # active until Stripe actually fires customer.subscription.deleted.
    # No DB change needed for that signal alone.

    set_card_pending_started = ""
    if new_status == "card_pending":
        set_card_pending_started = (
            ", card_pending_started_at = COALESCE(card_pending_started_at, now())"
        )

    await pool.execute(
        f"UPDATE workspaces SET "
        f"  status = $1, "
        f"  stripe_subscription_id = COALESCE(stripe_subscription_id, $2)"
        f"  {set_card_pending_started}, "
        f"  updated_at = now() "
        f"WHERE id = $3",
        new_status, sub_id, workspace_id,
    )
    logger.info(
        "Workspace %s: stripe_status=%s → status=%s",
        workspace_id, stripe_status, new_status,
    )

    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events "
            "(workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, $2, NULL, $3::jsonb)",
            workspace_id,
            f"sub_{stripe_status or 'unknown'}",
            json.dumps({
                "stripe_subscription_id": sub_id,
                "cancel_at_period_end": cancel_at_period_end,
                "new_status": new_status,
            }),
        )
    except Exception as exc:
        logger.warning("workspace_billing_events insert failed: %s", exc)


async def _on_workspace_invoice_paid(invoice, pool) -> None:
    """invoice.paid → confirm active status, log."""
    workspace_id = await _resolve_workspace_id_for_event(invoice, pool)
    if workspace_id is None:
        logger.warning(
            "Workspace invoice.paid could not resolve workspace (id=%s)",
            getattr(invoice, "id", None),
        )
        return

    # Recovery from past_due is handled by sub.updated; here we just
    # confirm + log for ledger.
    await pool.execute(
        "UPDATE workspaces SET status = 'active', updated_at = now() "
        "WHERE id = $1 AND status IN ('active', 'past_due', 'card_pending')",
        workspace_id,
    )
    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events "
            "(workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, 'invoice_paid', NULL, $2::jsonb)",
            workspace_id,
            json.dumps({
                "stripe_invoice_id": getattr(invoice, "id", None),
                "amount_paid_cents": getattr(invoice, "amount_paid", None),
            }),
        )
    except Exception as exc:
        logger.warning("workspace_billing_events log failed: %s", exc)


async def _on_workspace_invoice_payment_failed(invoice, pool) -> None:
    """invoice.payment_failed → log + email owner.

    We don't immediately flip status here — Stripe's dunning will
    retry the payment over ~2 weeks. If it ultimately fails, we'll
    receive customer.subscription.deleted and handle status='canceled'
    there. Status stays 'active' during dunning so members aren't
    locked out for a transient decline (matches user-tier behavior).
    """
    workspace_id = await _resolve_workspace_id_for_event(invoice, pool)
    if workspace_id is None:
        return

    try:
        owner_email = await pool.fetchval(
            "SELECT u.email FROM workspaces w "
            "JOIN users u ON u.id = w.owner_user_id WHERE w.id = $1",
            workspace_id,
        )
        ws_name = await pool.fetchval(
            "SELECT name FROM workspaces WHERE id = $1", workspace_id,
        )
        if owner_email and ws_name:
            from app.email import send_workspace_payment_failed_email
            await send_workspace_payment_failed_email(owner_email, ws_name)
    except Exception as exc:
        logger.error("workspace payment_failed email send failed: %s", exc)

    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events "
            "(workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, 'invoice_payment_failed', NULL, $2::jsonb)",
            workspace_id,
            json.dumps({"stripe_invoice_id": getattr(invoice, "id", None)}),
        )
    except Exception as exc:
        logger.warning("workspace_billing_events log failed: %s", exc)
