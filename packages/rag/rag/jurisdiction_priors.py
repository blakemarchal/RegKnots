"""Sprint D6.30 — soft jurisdictional priors derived from a user's history.

When a user's current question is jurisdictionally ambiguous AND no other
hard signal is available (vessel profile flag is absent or "Unknown",
chat title carries no jurisdiction word, no prior turn established an
anchor), we still have one more piece of context: what this user has
historically asked about.

Brandon (`2ndmate09@gmail.com`) is the motivating case — a teacher with
no vessel profile who has asked dozens of "X cfr" questions over weeks.
Every signal pointed at U.S. CFR but the system had no way to use it
because nothing tied the prior queries to the current turn.

This module computes a one-line summary of the user's last ~90 days of
queries by jurisdiction signal and feeds it into the chat prompt as a
SOFT prior. It is the weakest signal in the priority order documented in
prompts.py SOFT JURISDICTIONAL CONTEXT — current-query keywords, vessel
profile flag, chat title, and prior-turn anchors all override it. New
users (no history yet) and mixed-jurisdiction users (no clear lean) get
None back, and the prompt skips the line entirely.

Cost is one indexed query per chat() call. Sub-millisecond on prod, no
cache needed at this scale.
"""
import logging
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


# Jurisdiction signal patterns, anchored to word boundaries (PostgreSQL
# regex: \m and \M) so "msm" doesn't match "transmission" and "no" doesn't
# match every English negation. Tested against today's audit corpus —
# Brandon's queries match `us` cleanly; LaMaina's IGF queries match `imo`
# because they reference STCW; Andrew's "MAERSK HARTFORD containership"
# correctly matches none (vessel-name only).
JURISDICTION_PATTERNS = {
    "us": (
        r"\m("
        r"cfr|uscg|nvic|msib|alcoast|46 usc|33 usc|49 usc|"
        r"msm|nmc|coast guard|federal register"
        r")\M"
    ),
    "uk": (
        r"\m("
        r"mca|mgn|msn |merchant shipping notice|marine guidance note|"
        r"maritime and coastguard"
        r")\M"
    ),
    "au": r"\m(amsa|marine order)\M",
    "sg": r"\m(mpa singapore|maritime and port authority)\M",
    "hk": r"\m(hkmd|hong kong marine)\M",
    "no": r"\m(nma|sjofart|sjøfart|norwegian maritime)\M",
    "lr": r"\m(liscr|liberian registry)\M",
    "mh": r"\m(rmi|iri|marshall island)\M",
    "bs": r"\m(bma|bahamas maritime)\M",
    "imo": (
        r"\m("
        r"solas|marpol|stcw|colreg|ism code|imdg|igc|ibc|hsc|"
        r"polar code|bwm|iamsar"
        r")\M"
    ),
}


# Display labels for the prompt summary line. Keep these humane —
# the model reads these directly and the language matters.
JURISDICTION_LABEL = {
    "us": "U.S. regulations (CFR, USCG)",
    "uk": "UK regulations (MCA)",
    "au": "Australian regulations (AMSA)",
    "sg": "Singapore regulations (MPA)",
    "hk": "Hong Kong regulations (HKMD)",
    "no": "Norwegian regulations (NMA)",
    "lr": "Liberian flag regulations (LISCR)",
    "mh": "Marshall Islands flag regulations (IRI/RMI)",
    "bs": "Bahamas flag regulations (BMA)",
    "imo": "international IMO conventions (SOLAS/MARPOL/STCW etc.)",
}


# Tunables — surfaced as constants so we can adjust without touching the
# query logic. Defaults chosen for the scale we're at (small user base,
# pattern emerges quickly):
#   - 90 day lookback covers the typical session arc + holiday breaks
#   - 5 query minimum prevents spurious leans on first-day users
#   - 70% threshold means a user has to be clearly dominant in one
#     jurisdiction; mixed-interest users get neutral treatment
LOOKBACK_DAYS = 90
MIN_QUERIES = 5
DOMINANCE_THRESHOLD = 0.70


async def compute_user_fingerprint(
    pool: asyncpg.Pool,
    user_id: UUID,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict:
    """Tally jurisdiction signals across the user's recent queries.

    Returns a dict mapping jurisdiction code → count. Codes with zero
    matches are omitted, so empty dict means no signals at all (new user
    or one whose queries never name a jurisdiction).
    """
    # Build the SELECT dynamically so the patterns dict stays the single
    # source of truth. asyncpg uses $1, $2, ... so we map each pattern
    # to a numbered placeholder; user_id is $1.
    select_clauses = []
    params: list = [user_id]
    for i, (code, pattern) in enumerate(JURISDICTION_PATTERNS.items(), start=2):
        select_clauses.append(
            f"COUNT(*) FILTER (WHERE m.content ~* ${i}) AS {code}_count"
        )
        params.append(pattern)

    sql = (
        "SELECT " + ", ".join(select_clauses) + " "
        "FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = $1 "
        "  AND m.role = 'user' "
        f"  AND m.created_at > NOW() - INTERVAL '{int(lookback_days)} days'"
    )
    row = await pool.fetchrow(sql, *params)
    if not row:
        return {}
    return {
        code: row[f"{code}_count"]
        for code in JURISDICTION_PATTERNS
        if row[f"{code}_count"] > 0
    }


def fingerprint_summary(fp: dict) -> Optional[str]:
    """Render the fingerprint as a one-line prompt-ready summary.

    Returns None when there's no clear signal — empty dict (new user),
    too few queries to be meaningful, or no dominant jurisdiction. The
    caller skips the prompt block entirely in these cases.

    The phrasing is intentionally hedged ("historically", "based on
    prior queries") so the model treats this as a soft prior, not a
    hard fact. The HARD signals in the prompt (vessel profile flag,
    current-query keywords) override this.
    """
    if not fp:
        return None
    total = sum(fp.values())
    if total < MIN_QUERIES:
        return None
    top_code, top_count = max(fp.items(), key=lambda kv: kv[1])
    if top_count / total < DOMINANCE_THRESHOLD:
        return None  # mixed interests, no clear lean
    label = JURISDICTION_LABEL.get(top_code, top_code.upper())
    return (
        f"User context: based on prior queries, this user has historically "
        f"asked about {label} ({top_count} of last {total} queries). "
        f"Use as a soft prior only when the current question is otherwise "
        f"jurisdictionally ambiguous."
    )


async def fingerprint_for_user(
    pool: asyncpg.Pool, user_id: UUID
) -> Optional[str]:
    """Convenience wrapper: compute + render in one call.

    Used by the chat router. Returns None for new/mixed users (which
    means the prompt simply doesn't include the line — no error path).
    """
    try:
        fp = await compute_user_fingerprint(pool, user_id)
    except Exception:  # noqa: BLE001 — defensive; never fail chat()
        logger.exception(
            "fingerprint computation failed for user %s; treating as no signal",
            user_id,
        )
        return None
    return fingerprint_summary(fp)
