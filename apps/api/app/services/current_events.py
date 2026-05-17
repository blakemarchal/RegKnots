"""Maritime current-events tier orchestration (D6.96).

Single entrypoint for the current-events feature: ``maybe_run_current_events()``.
Owns the four moving parts so chat.py only has to call one function:

  1. Feature-flag gate (off / paid_only / live)
  2. Detector call (current_events_triggers.detect_current_events_intent)
  3. News fallback (web_fallback.attempt_news_fallback)
  4. Logging to current_events_responses

Best-effort by design. Any failure inside the orchestration is caught,
logged at WARNING, and the function returns ``(None, None)``. The chat
path never breaks from a news-fallback bug — the worst case is the
user sees today's regulatory-only answer.

Revert path:
  Set CURRENT_EVENTS_TIER=off in /opt/RegKnots/.env, restart regknots-api.
  Function short-circuits at the flag gate, returns ``(None, None)``.
  No deploy needed. ~5 seconds end-to-end.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import asyncpg
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


# Subscription tiers that count as "paid" for the paid_only feature-flag
# mode. Real tier values in the DB as of D6.96: 'free' (trial/unpaid),
# 'pro' (paying subscriber), 'cadet' (student persona — free). Only
# 'pro' counts as paid; trial users get the feature once the operator
# flips CURRENT_EVENTS_TIER=live.
_PAID_TIERS = frozenset({"pro"})


def _format_current_reading_block(news_result, briefing_date: str) -> str:
    """Render the NewsFallbackResult as a markdown block to append to
    the chat answer. Format matches the D6.96 spec: 🌐 Current Reading
    header, dated attributions, source list, stale-flag link."""
    lines: list[str] = []
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"🌐 **Current Reading** *(Briefing last updated: {briefing_date})*")
    lines.append("")
    if news_result.answer_text:
        lines.append(news_result.answer_text.strip())
        lines.append("")
    if news_result.sources:
        lines.append("**Sources:**")
        for s in news_result.sources:
            date_part = f" ({s.published_date})" if s.published_date else ""
            quote_part = f": \"{s.quote.strip()}\"" if s.quote else ""
            lines.append(f"- *{s.publication}*{date_part}{quote_part} — {s.url}")
        lines.append("")
    # Stale-window note — explicit when oldest cited source is > 90 days
    # so the user can self-assess freshness.
    if news_result.oldest_quote_date:
        try:
            from datetime import date as _date
            oldest = _date.fromisoformat(news_result.oldest_quote_date)
            age_days = (_date.today() - oldest).days
            if age_days > 180:
                lines.append(
                    f"*⚠️ This may be out of date — oldest cited source is "
                    f"{age_days} days old. Confirm against the linked source "
                    f"before relying on it for operational decisions.*"
                )
                lines.append("")
            elif age_days > 90:
                lines.append(
                    f"*As of {news_result.oldest_quote_date}, this is the most "
                    f"recent reporting from our trusted sources. Situation may "
                    f"have moved.*"
                )
                lines.append("")
        except (ValueError, TypeError):
            pass
    lines.append(
        "*Synthesized from trusted maritime news sources. Quotes are "
        "verbatim and dated; the broader situation may have moved. "
        "If this is stale, click the 'Flag as stale' button on this "
        "message so we can refresh.*"
    )
    return "\n".join(lines)


async def _log_response(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    query: str,
    markers_matched: list[str],
    surface_tier: str,
    refusal_reason: Optional[str],
    source_urls: list[str],
    source_domains: list[str],
    oldest_quote_date: Optional[str],
    newest_quote_date: Optional[str],
    answer_text: Optional[str],
    latency_ms: int,
) -> uuid.UUID:
    """Insert one row into current_events_responses and return the id.
    Caller updates chat_message_id afterward when the assistant message
    row exists. Best-effort: any DB error is logged and ``None`` is
    returned (in which case the caller skips the chat_message_id
    backfill — feature still ships, just without that log linkage)."""
    row = await pool.fetchrow(
        """
        INSERT INTO current_events_responses
            (user_id, query, markers_matched, surface_tier, refusal_reason,
             source_urls, source_domains, oldest_quote_date, newest_quote_date,
             answer_text, latency_ms)
        VALUES ($1, $2, $3::text[], $4, $5, $6::text[], $7::text[],
                $8, $9, $10, $11)
        RETURNING id
        """,
        user_id, query, markers_matched, surface_tier, refusal_reason,
        source_urls, source_domains,
        oldest_quote_date, newest_quote_date, answer_text, latency_ms,
    )
    return row["id"]


def _is_enabled_for_user(
    feature_flag: str, subscription_tier: Optional[str],
) -> bool:
    """Return True if the current-events tier should fire for this user
    given the feature flag mode and their subscription tier."""
    if feature_flag == "off":
        return False
    if feature_flag == "live":
        return True
    if feature_flag == "paid_only":
        return (subscription_tier or "").lower() in _PAID_TIERS
    # Unknown flag value → fail closed.
    logger.warning(
        "current_events: unknown CURRENT_EVENTS_TIER value %r, treating as off",
        feature_flag,
    )
    return False


async def maybe_run_current_events(
    *,
    query: str,
    user_id: uuid.UUID,
    subscription_tier: Optional[str],
    feature_flag: str,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    timeout_s: float = 20.0,
) -> tuple[Optional[str], Optional[uuid.UUID]]:
    """Run the current-events orchestration and return the block to
    append (or None) + the log row id (or None).

    Returns:
        (block_text, log_id) — block_text is markdown to append to the
        chat answer (or None if not fired / blocked / errored).
        log_id is the current_events_responses row id, used by the
        caller to backfill chat_message_id after the assistant message
        is inserted.

    Never raises — all failure modes return ``(None, None)``.
    """
    # ── Gate 0: feature flag + subscription ───────────────────────────
    if not _is_enabled_for_user(feature_flag, subscription_tier):
        return None, None

    # ── Gate 1: detector ─────────────────────────────────────────────
    try:
        from rag.current_events_triggers import detect_current_events_intent
        should_fire, markers = detect_current_events_intent(query)
    except Exception as exc:
        logger.warning(
            "current_events: detector error (non-fatal): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return None, None

    if not should_fire:
        return None, None

    # ── News fallback call ───────────────────────────────────────────
    import asyncio
    from datetime import date as _date

    try:
        from rag.web_fallback import attempt_news_fallback
        news_result = await asyncio.wait_for(
            attempt_news_fallback(
                query=query,
                markers_matched=markers,
                anthropic_client=anthropic_client,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "current_events: news fallback timed out after %ss for query=%r",
            timeout_s, query[:100],
        )
        # Log a blocked attempt so admin can see this in the audit view.
        try:
            log_id = await _log_response(
                pool, user_id=user_id, query=query,
                markers_matched=markers, surface_tier="blocked",
                refusal_reason="error",
                source_urls=[], source_domains=[],
                oldest_quote_date=None, newest_quote_date=None,
                answer_text=None, latency_ms=int(timeout_s * 1000),
            )
        except Exception:
            log_id = None
        return None, log_id
    except Exception as exc:
        logger.warning(
            "current_events: news fallback failed (non-fatal): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        try:
            log_id = await _log_response(
                pool, user_id=user_id, query=query,
                markers_matched=markers, surface_tier="blocked",
                refusal_reason="error",
                source_urls=[], source_domains=[],
                oldest_quote_date=None, newest_quote_date=None,
                answer_text=None, latency_ms=0,
            )
        except Exception:
            log_id = None
        return None, log_id

    # ── Log every outcome (surfaced or blocked) ──────────────────────
    source_urls = [s.url for s in news_result.sources]
    source_domains = [s.domain for s in news_result.sources]

    try:
        log_id = await _log_response(
            pool, user_id=user_id, query=query,
            markers_matched=markers,
            surface_tier=news_result.surface_tier,
            refusal_reason=news_result.refusal_reason,
            source_urls=source_urls, source_domains=source_domains,
            oldest_quote_date=news_result.oldest_quote_date,
            newest_quote_date=news_result.newest_quote_date,
            answer_text=news_result.answer_text,
            latency_ms=news_result.latency_ms,
        )
    except Exception as exc:
        logger.warning(
            "current_events: logging failed (non-fatal): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        log_id = None

    # ── Surface (or block) ──────────────────────────────────────────
    if news_result.surface_tier != "current_events":
        # Block — usually policy_advocacy refusal. The synthesizer's
        # refusal answer is already shaped to point the user at trusted
        # sources, so we surface it as-is.
        if news_result.refusal_reason == "policy_advocacy" and news_result.answer_text:
            return news_result.answer_text, log_id
        return None, log_id

    if not news_result.sources or not news_result.answer_text:
        return None, log_id

    # ── Format and return ───────────────────────────────────────────
    briefing_date = _date.today().isoformat()
    block = _format_current_reading_block(news_result, briefing_date)
    return block, log_id


async def backfill_chat_message_id(
    pool: asyncpg.Pool,
    log_id: uuid.UUID,
    chat_message_id: uuid.UUID,
) -> None:
    """Update the current_events_responses row to link to the assistant
    message it lives on. Called after the chat router inserts the
    assistant row. Best-effort — caller catches and ignores errors."""
    await pool.execute(
        "UPDATE current_events_responses SET chat_message_id = $1 "
        "WHERE id = $2",
        chat_message_id, log_id,
    )
