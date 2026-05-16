"""User-context assembly for personalized regulatory reasoning (D6.63).

The chat layer already accepts a vessel_profile and a credential_context.
Sprint D6.63 — the keystone Move A from the Sprint 3 plan — fuses
those signals into one structured context bundle and adds sea-time
totals so the chat can reason against the user's full record:

  "Am I qualified to sail Master near-coastal on a 250 GT?"
   → user has Master Inland 100 GT + 540 near-coastal days
   → 46 CFR 11.422 requires X for the upgrade
   → answer the actual question, not a generic regulation summary

The same structured data feeds the /me/context endpoint (debug + UI),
the Renewal Co-Pilot cards (D6.63 Move B), and the Career Path widget
(D6.63 Move C). All three derive from this one source of truth.

Token budget:
  - Compact prompt block aimed at ~250 input tokens nominal. Hard cap
    enforced via per-section truncation. At Anthropic input pricing
    that's ~$0.0008/chat for Sonnet — negligible vs the value.
  - Structured form has no token cap (it's JSON for the UI).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


# ── Structured result types ────────────────────────────────────────────────


@dataclass
class CredentialSummary:
    """One stored credential, normalized for prompt + UI consumption."""
    id: str
    credential_type: str        # 'mmc' | 'stcw' | 'medical' | 'twic' | 'other'
    title: str
    credential_number: Optional[str]
    issuing_authority: Optional[str]
    issue_date: Optional[str]   # ISO
    expiry_date: Optional[str]  # ISO
    days_until_expiry: Optional[int]   # negative if expired
    notes: Optional[str]


@dataclass
class SeaTimeTotals:
    """Sea-time aggregations over the windows USCG actually cares about."""
    total_days: int
    days_last_3_years: int
    days_last_5_years: int
    by_route_type: dict[str, int]
    by_capacity: dict[str, int]
    entry_count: int
    earliest_date: Optional[str]
    latest_date: Optional[str]


@dataclass
class ActiveVesselSummary:
    """Compact summary of the active vessel for prompt injection.

    Mirrors the fields the existing engine.py vessel_profile block
    surfaces, so the user_context block can subsume the vessel block
    when used together. The chat path still uses vessel_profile for
    rich rendering; this is the compact form for the structured
    /me/context endpoint.
    """
    id: str
    name: str
    vessel_type: Optional[str]
    flag_state: Optional[str]
    gross_tonnage: Optional[float]
    subchapter: Optional[str]
    route_types: list[str]
    cargo_types: list[str]
    has_coi_extraction: bool   # flag — full extraction lives in vessel_profile
    # D6.94 — class society. NULL when the vessel record has not been
    # tagged yet (user hasn't picked AND IACS auto-lookup missed). When
    # present, drives the synthesis prompt's binding-rule routing.
    classification_society: Optional[str] = None


@dataclass
class UserContext:
    """The full bundle. as_prompt_block() renders it for chat injection."""
    user_id: str
    full_name: Optional[str]
    role: Optional[str]
    credentials: list[CredentialSummary] = field(default_factory=list)
    sea_time: Optional[SeaTimeTotals] = None
    active_vessel: Optional[ActiveVesselSummary] = None

    def as_prompt_block(self, max_chars: int = 1800) -> str:
        """Render a compact text block suitable for injection into the
        chat system/user prompt. Targets ~250 tokens nominal; the
        max_chars cap is the safety belt.

        Empty when the user has no data (so we don't waste tokens on
        a useless 'USER CONTEXT: (none)' block on every chat fire).
        """
        parts: list[str] = []
        # Credentials section — highlight imminent expiries first since
        # those are the ones that change the right answer.
        cred_lines = self._credential_lines()
        if cred_lines:
            parts.append("MARINER CREDENTIALS ON FILE:")
            parts.extend(cred_lines)

        # Sea-time totals — the windows that gate USCG upgrades.
        st_lines = self._sea_time_lines()
        if st_lines:
            if parts:
                parts.append("")
            parts.append("SEA-TIME TOTALS:")
            parts.extend(st_lines)

        if not parts:
            return ""

        block = "\n".join(parts)
        if len(block) > max_chars:
            block = block[: max_chars - 20] + "\n[...truncated]"
        return block

    def _credential_lines(self) -> list[str]:
        """Format credentials, prioritizing imminent expiries."""
        if not self.credentials:
            return []
        # Sort: expired/expiring first, then no-expiry
        def _key(c: CredentialSummary) -> tuple[int, int]:
            if c.days_until_expiry is None:
                return (1, 0)  # no-expiry credentials sink to bottom
            return (0, c.days_until_expiry)
        ordered = sorted(self.credentials, key=_key)

        lines: list[str] = []
        for c in ordered:
            kind = c.credential_type.upper()
            label = c.title or kind
            number = f" (#{c.credential_number})" if c.credential_number else ""
            if c.days_until_expiry is None:
                lines.append(f"- {kind}: {label}{number} — no expiry tracked")
            elif c.days_until_expiry < 0:
                lines.append(
                    f"- {kind}: {label}{number} — EXPIRED "
                    f"{abs(c.days_until_expiry)} days ago "
                    f"(was {c.expiry_date})"
                )
            else:
                lines.append(
                    f"- {kind}: {label}{number} — expires {c.expiry_date} "
                    f"({c.days_until_expiry} days)"
                )
        return lines

    def _sea_time_lines(self) -> list[str]:
        """Format sea-time totals + breakdowns."""
        st = self.sea_time
        if st is None or st.entry_count == 0:
            return []
        lines = [
            f"- Total: {st.total_days} days across {st.entry_count} "
            f"entr{'y' if st.entry_count == 1 else 'ies'}",
            f"- Last 3 years: {st.days_last_3_years} days "
            f"(USCG active-service window for many upgrades)",
            f"- Last 5 years: {st.days_last_5_years} days",
        ]
        if st.by_route_type:
            top_routes = sorted(
                st.by_route_type.items(), key=lambda x: -x[1],
            )[:4]
            lines.append(
                "- By route: " + ", ".join(f"{k} {v}d" for k, v in top_routes)
            )
        if st.by_capacity:
            top_caps = sorted(
                st.by_capacity.items(), key=lambda x: -x[1],
            )[:4]
            lines.append(
                "- By capacity: " + ", ".join(f"{k} {v}d" for k, v in top_caps)
            )
        return lines


# ── Builder ────────────────────────────────────────────────────────────────


async def build_user_context(
    pool: asyncpg.Pool,
    user_id: str | Any,  # accepts UUID or str; coerced internally
    active_vessel_id: Optional[str | Any] = None,
) -> UserContext:
    """Assemble a UserContext for the given user.

    All queries are user-scoped + indexed; expected total < 10ms even
    for a heavy mariner (50+ credentials, 200+ sea-time entries).

    active_vessel_id, if provided, is included as a compact summary
    in the bundle. Full vessel data (with COI extraction etc.) still
    lives in the `vessel_profile` parameter that chat.py already
    constructs — this is the lightweight summary for /me/context.
    """
    import uuid as _uuid
    uid = user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))

    # User basics
    user_row = await pool.fetchrow(
        "SELECT full_name, role FROM users WHERE id = $1", uid,
    )
    full_name = user_row["full_name"] if user_row else None
    role = user_row["role"] if user_row else None

    # Credentials — fetch all, defer prioritization to as_prompt_block()
    cred_rows = await pool.fetch(
        """
        SELECT id, credential_type, title, credential_number,
               issuing_authority, issue_date, expiry_date, notes
        FROM user_credentials
        WHERE user_id = $1
        ORDER BY expiry_date ASC NULLS LAST, created_at DESC
        """,
        uid,
    )
    today = date.today()
    credentials: list[CredentialSummary] = []
    for r in cred_rows:
        exp = r["expiry_date"]
        days_left = (exp - today).days if exp else None
        credentials.append(CredentialSummary(
            id=str(r["id"]),
            credential_type=r["credential_type"],
            title=r["title"] or "",
            credential_number=r["credential_number"],
            issuing_authority=r["issuing_authority"],
            issue_date=r["issue_date"].isoformat() if r["issue_date"] else None,
            expiry_date=exp.isoformat() if exp else None,
            days_until_expiry=days_left,
            notes=r["notes"],
        ))

    # Sea-time totals — same math as /sea-time/totals so the two
    # surfaces never disagree about a mariner's qualifications.
    st_rows = await pool.fetch(
        "SELECT route_type, capacity_served, from_date, to_date, days_on_board "
        "FROM sea_time_entries WHERE user_id = $1",
        uid,
    )
    sea_time: Optional[SeaTimeTotals] = None
    if st_rows:
        cutoff_3yr = today - timedelta(days=365 * 3)
        cutoff_5yr = today - timedelta(days=365 * 5)
        total_days = days_3yr = days_5yr = 0
        by_route: dict[str, int] = {}
        by_capacity: dict[str, int] = {}
        earliest: Optional[date] = None
        latest: Optional[date] = None
        for r in st_rows:
            d = int(r["days_on_board"])
            total_days += d
            rt = r["route_type"] or "Unspecified"
            cap = r["capacity_served"] or "Unspecified"
            by_route[rt] = by_route.get(rt, 0) + d
            by_capacity[cap] = by_capacity.get(cap, 0) + d
            f = r["from_date"]
            t = r["to_date"]
            if earliest is None or f < earliest:
                earliest = f
            if latest is None or t > latest:
                latest = t
            for cutoff, key in ((cutoff_3yr, "3yr"), (cutoff_5yr, "5yr")):
                o_start = max(f, cutoff)
                o_end = min(t, today)
                if o_end >= o_start:
                    overlap = min((o_end - o_start).days + 1, d)
                    if key == "3yr":
                        days_3yr += overlap
                    else:
                        days_5yr += overlap
        sea_time = SeaTimeTotals(
            total_days=total_days,
            days_last_3_years=days_3yr,
            days_last_5_years=days_5yr,
            by_route_type=by_route,
            by_capacity=by_capacity,
            entry_count=len(st_rows),
            earliest_date=earliest.isoformat() if earliest else None,
            latest_date=latest.isoformat() if latest else None,
        )

    # Active vessel summary (lightweight — full data lives in vessel_profile)
    active_vessel: Optional[ActiveVesselSummary] = None
    if active_vessel_id:
        try:
            vid = (
                active_vessel_id if isinstance(active_vessel_id, _uuid.UUID)
                else _uuid.UUID(str(active_vessel_id))
            )
            v = await pool.fetchrow(
                """
                SELECT v.id, v.name, v.vessel_type, v.flag_state,
                       v.gross_tonnage, v.subchapter, v.route_types,
                       v.cargo_types, v.classification_society,
                       (
                         SELECT COUNT(*) > 0 FROM vessel_documents vd
                         WHERE vd.vessel_id = v.id
                           AND vd.document_type = 'coi'
                           AND vd.extraction_status IN ('extracted', 'confirmed')
                       ) AS has_coi
                FROM vessels v
                WHERE v.id = $1
                """,
                vid,
            )
            if v is not None:
                active_vessel = ActiveVesselSummary(
                    id=str(v["id"]),
                    name=v["name"],
                    vessel_type=v["vessel_type"],
                    flag_state=v["flag_state"],
                    gross_tonnage=float(v["gross_tonnage"]) if v["gross_tonnage"] is not None else None,
                    subchapter=v["subchapter"],
                    route_types=list(v["route_types"] or []),
                    cargo_types=list(v["cargo_types"] or []),
                    has_coi_extraction=bool(v["has_coi"]),
                    classification_society=v["classification_society"],
                )
        except Exception as exc:
            logger.info(
                "user_context: skipping active vessel summary: %s: %s",
                type(exc).__name__, str(exc)[:200],
            )

    return UserContext(
        user_id=str(uid),
        full_name=full_name,
        role=role,
        credentials=credentials,
        sea_time=sea_time,
        active_vessel=active_vessel,
    )
