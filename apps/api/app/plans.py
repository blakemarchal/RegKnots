"""Plan tier / billing interval metadata and Stripe price ID mapping.

Sprint D6.1 — single source of truth for mapping a Stripe price_id back
to the tier, interval, and promo status of a subscription. Used by:

  * stripe_service._on_subscription_change (set user fields from webhook)
  * stripe_service.create_checkout_session (resolve a requested plan
    string like "mate_monthly" to the right Stripe price to charge)
  * billing / chat / admin routers (feature gating + attribution)

Adding a new price in the future (e.g., a new charity partner):
  1. Create the price in the Stripe dashboard
  2. Add its env var to config.Settings + .env.example
  3. Register it in _build_price_map() below
  4. Every caller routes correctly — no other changes required

Promo pricing mechanics:
  * "Promo" variants are the Mate $14.99 / Captain $29.99 monthly rates
    offered via charity landing pages (e.g., /womenoffshore). They are
    just additional Stripe prices with lower dollar amounts — no Stripe
    coupon, no discount code.
  * Message caps + feature gates are identical between promo and
    non-promo prices within the same tier. The is_promo flag is for
    attribution + admin accounting only.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

# Hard caps applied at the Mate and free-trial tiers respectively.
MATE_MESSAGE_CAP = 100
FREE_TRIAL_MESSAGE_CAP = 50


@dataclass(frozen=True)
class PlanInfo:
    """Describes a paid plan a user is subscribed to."""

    tier: str
    """'mate' | 'captain'"""

    interval: str
    """'month' | 'year' — Stripe-native naming."""

    is_promo: bool
    """True when the purchase used a promo-priced variant (charity partner pricing)."""

    monthly_message_cap: int | None
    """Per-cycle message cap. 100 for Mate, None (unlimited) for Captain."""


# Plans known to the system. Populated lazily on first lookup so config
# can be read at process start without ordering issues during import.
_PRICE_MAP_CACHE: dict[str, PlanInfo] | None = None


def _build_price_map() -> dict[str, PlanInfo]:
    entries: list[tuple[str, PlanInfo]] = [
        # Primary two-tier pricing — Sprint D6.1
        (settings.stripe_price_mate_monthly,
         PlanInfo("mate", "month", False, MATE_MESSAGE_CAP)),
        (settings.stripe_price_mate_annual,
         PlanInfo("mate", "year", False, MATE_MESSAGE_CAP)),
        (settings.stripe_price_mate_promo,
         PlanInfo("mate", "month", True, MATE_MESSAGE_CAP)),
        (settings.stripe_price_captain_monthly,
         PlanInfo("captain", "month", False, None)),
        (settings.stripe_price_captain_annual,
         PlanInfo("captain", "year", False, None)),
        (settings.stripe_price_captain_promo,
         PlanInfo("captain", "month", True, None)),
        # Legacy pre-D6.1 single-tier prices. Map to Captain so any
        # historical webhooks route to the unlimited tier rather than
        # being silently ignored. Safe because we have zero paying
        # users pre-D6.1, but future-proof if stale webhooks replay.
        (settings.stripe_price_id,
         PlanInfo("captain", "month", False, None)),
        (settings.stripe_annual_price_id,
         PlanInfo("captain", "year", False, None)),
    ]
    out: dict[str, PlanInfo] = {}
    for price_id, info in entries:
        if price_id:
            # If the same price_id maps multiple times (shouldn't happen
            # but guarded), prefer the first — which is the primary
            # D6.1 mapping, not legacy.
            out.setdefault(price_id, info)
    return out


def _get_price_map() -> dict[str, PlanInfo]:
    global _PRICE_MAP_CACHE
    if _PRICE_MAP_CACHE is None:
        _PRICE_MAP_CACHE = _build_price_map()
    return _PRICE_MAP_CACHE


def plan_info_from_price_id(price_id: str | None) -> PlanInfo | None:
    """Resolve a Stripe price_id to plan metadata; None if not configured.

    Returns None for unknown price_ids (treat as a configuration error —
    the caller should log and skip rather than crash, so an unmapped
    webhook doesn't break the whole billing flow).
    """
    if not price_id:
        return None
    return _get_price_map().get(price_id)


def resolve_price_for_plan(
    tier: str, interval: str, *, promo: bool = False,
) -> str | None:
    """Reverse lookup for checkout session creation.

    Given a requested tier + interval + promo flag, return the Stripe
    price_id to charge. None if no matching price is configured
    (caller should surface a clear error to the frontend).

    Note: this only returns D6.1 primary prices — legacy
    stripe_price_id / stripe_annual_price_id are excluded from reverse
    lookup so new checkouts always hit the new pricing.
    """
    candidates = {
        ("mate",    "month", False): settings.stripe_price_mate_monthly,
        ("mate",    "year",  False): settings.stripe_price_mate_annual,
        ("mate",    "month", True):  settings.stripe_price_mate_promo,
        ("captain", "month", False): settings.stripe_price_captain_monthly,
        ("captain", "year",  False): settings.stripe_price_captain_annual,
        ("captain", "month", True):  settings.stripe_price_captain_promo,
    }
    price_id = candidates.get((tier, interval, promo))
    return price_id or None


# ── Convenience helpers ──────────────────────────────────────────────────

def is_paid_tier(tier: str | None) -> bool:
    """True if the given tier is any paying plan (mate/captain and legacy pro)."""
    return tier in {"mate", "captain", "pro"}


def message_cap_for_tier(tier: str | None) -> int | None:
    """Return per-cycle message cap for a tier. None = unlimited.

    Used by feature-gate logic in the chat route. Free-tier users are
    gated by the 50-message trial cap handled separately; this helper
    only covers paid tiers.
    """
    if tier == "mate":
        return MATE_MESSAGE_CAP
    # captain and legacy pro are unlimited
    return None
