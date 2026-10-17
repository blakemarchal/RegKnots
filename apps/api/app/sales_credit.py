"""Which salesperson an account counts toward (2026-10-17).

An admin's assignment wins (users.credited_sales_code: a code, or '' for no
one); otherwise the pilot code in the account's first-touch signup link
(signup_attribution.src = pilot-<code>, any case). Every sales query (the
salesperson's /sales pages, Admin > Sales, the commission report) reads this
one expression, so the views can't disagree.
"""
from __future__ import annotations

from app.pilots import SRC_PREFIX


def credit_code_sql(a: str = "u") -> str:
    """The code users-row `a` counts toward; NULL when it counts toward no one."""
    src = f"lower({a}.signup_attribution->>'src')"
    return (f"NULLIF(COALESCE({a}.credited_sales_code, "
            f"CASE WHEN {src} LIKE '{SRC_PREFIX}%' THEN substr({src}, {len(SRC_PREFIX) + 1}) END), '')")


# Needs the users table aliased as u.
CREDIT_CODE_SQL = credit_code_sql("u")

# Where the credit came from: 'admin' (set by hand) or 'link'.
CREDIT_SOURCE_SQL = "CASE WHEN u.credited_sales_code IS NOT NULL THEN 'admin' ELSE 'link' END"

# A fleet that pays us right now.
WORKSPACE_PAYING_SQL = "(w.stripe_subscription_id IS NOT NULL AND w.status = 'active')"

# A personal plan that pays us right now.
USER_PAYING_SQL = "(u.subscription_status = 'active' AND u.subscription_tier IN ('cadet','mate','captain','pro'))"
