"""Workspace-tier (Wheelhouse) plan metadata.

Sprint D6.54 — kept separate from `plans.py` because the user-tier
PlanInfo dataclass is heavily wired into chat-side feature gating
(message caps, tier strings) and shoehorning workspace-level pricing
into it would tangle two unrelated concerns.

Wheelhouse has one product with two billing intervals (monthly and
annual). No promo variants — margin risk on the 10-seat tier is too
high to discount.

The webhook dispatcher in stripe_service.py uses
`is_wheelhouse_price_id()` to decide whether an incoming Stripe event
should route to workspace state-machine handlers (this module) or
user-tier handlers (plans.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class WheelhouseInterval:
    """The billing interval a Wheelhouse subscription is on."""
    interval: str  # 'month' | 'year'
    price_id: str


def wheelhouse_price_ids() -> set[str]:
    """All known Wheelhouse Stripe price IDs.

    Empty set if neither monthly nor annual is configured — used by
    `is_wheelhouse_price_id()` to short-circuit when the feature isn't
    wired in this environment.
    """
    return {
        p for p in (
            settings.stripe_price_wheelhouse_monthly,
            settings.stripe_price_wheelhouse_annual,
        ) if p
    }


def is_wheelhouse_price_id(price_id: str | None) -> bool:
    """True if this Stripe price_id belongs to the Wheelhouse product.

    The webhook dispatcher uses this to decide whether to route an
    event to workspace-tier handlers (workspaces table updates) vs.
    user-tier handlers (users table updates).
    """
    if not price_id:
        return False
    return price_id in wheelhouse_price_ids()


def wheelhouse_interval_from_price_id(price_id: str | None) -> str | None:
    """Resolve a Wheelhouse price_id to its billing interval.

    Returns 'month' or 'year' for known prices, None for anything that
    isn't a Wheelhouse price (callers should branch on this rather than
    crashing — Stripe events for unrelated products may share the same
    webhook handler).
    """
    if not price_id:
        return None
    if price_id == settings.stripe_price_wheelhouse_monthly:
        return "month"
    if price_id == settings.stripe_price_wheelhouse_annual:
        return "year"
    return None


def resolve_wheelhouse_price_id(plan: str) -> str | None:
    """Reverse lookup for checkout creation.

    Accepts 'monthly' / 'annual' (frontend-friendly) and returns the
    matching Stripe price_id. None if the corresponding env var isn't
    set — callers should surface that as a clear configuration error
    rather than blanking the checkout button.
    """
    if plan == "monthly":
        return settings.stripe_price_wheelhouse_monthly or None
    if plan == "annual":
        return settings.stripe_price_wheelhouse_annual or None
    return None
