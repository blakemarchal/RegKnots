"""Personalized reasoning endpoints (Sprint D6.63).

The keystone of "we reason against your actual record, they don't."
These endpoints fuse the user's stored data (credentials + sea-time +
vessels) with the corpus + Anthropic Sonnet to produce three things:

  GET /me/context
      The same compact context the chat injects, returned as JSON.
      Powers the credentials-page "what RegKnots knows about you"
      surface and acts as a debug view ("am I really sending the
      right context?").

  GET /me/renewal-readiness/{credential_id}
      Sonnet + RAG analyses ONE credential's renewal:
        - Pulls the credential + the user's other credentials
          (medical / TWIC / drug-test letters, etc.)
        - Pulls sea-time totals
        - Retrieves the controlling regulation (e.g. 46 CFR 10.227)
          from the corpus
        - Returns: structured readiness verdict + narrative + the
          specific actions remaining

  GET /me/career-progression
      Sonnet + RAG looks across the whole credential ladder relative
      to the user's current MMC and sea-time:
        - "Cap-eligible right now": upgrades you've already hit the
          floor for, just haven't applied
        - "Within reach": upgrades you're close to qualifying for,
          with the specific gap quantified
        - All anchored to actual CFR sections via citation

Both reasoning endpoints are user-triggered (button click). They
each cost ~$0.03 in Sonnet input + output tokens. We don't
auto-fire them on page load — that would scale poorly. Caching can
be added later if usage justifies it.
"""
from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from typing import Annotated, Any, Optional

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


# Model choices — Sonnet for narrative-quality reasoning, Haiku for
# context-only fetches. Keeping these explicit (vs imported from a
# central config) so per-endpoint tuning is clear in this file.
_REASONING_MODEL = "claude-sonnet-4-6"


# ── /me/context — structured user context ─────────────────────────────────


class CredentialContextDTO(BaseModel):
    id: str
    credential_type: str
    title: str
    credential_number: Optional[str]
    issuing_authority: Optional[str]
    issue_date: Optional[str]
    expiry_date: Optional[str]
    days_until_expiry: Optional[int]
    notes: Optional[str]


class SeaTimeContextDTO(BaseModel):
    total_days: int
    days_last_3_years: int
    days_last_5_years: int
    by_route_type: dict[str, int]
    by_capacity: dict[str, int]
    entry_count: int
    earliest_date: Optional[str]
    latest_date: Optional[str]


class ActiveVesselContextDTO(BaseModel):
    id: str
    name: str
    vessel_type: Optional[str]
    flag_state: Optional[str]
    gross_tonnage: Optional[float]
    subchapter: Optional[str]
    route_types: list[str]
    cargo_types: list[str]
    has_coi_extraction: bool


class UserContextDTO(BaseModel):
    user_id: str
    full_name: Optional[str]
    role: Optional[str]
    credentials: list[CredentialContextDTO]
    sea_time: Optional[SeaTimeContextDTO]
    active_vessel: Optional[ActiveVesselContextDTO]
    prompt_block: str  # the same compact text the chat sees


@router.get("/context", response_model=UserContextDTO)
async def get_user_context(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    vessel_id: Optional[str] = None,
) -> UserContextDTO:
    """Return what the chat layer sees about this user.

    UI consumers: the personalized chat starters + credential-page
    Co-Pilot widgets read this to decide what to surface. Debug
    consumers: confirm the context you THINK is being injected
    actually IS being injected.
    """
    from rag.user_context import build_user_context
    pool = await get_pool()
    ctx = await build_user_context(
        pool=pool,
        user_id=_uuid.UUID(current_user.user_id),
        active_vessel_id=vessel_id,
    )
    return UserContextDTO(
        user_id=ctx.user_id,
        full_name=ctx.full_name,
        role=ctx.role,
        credentials=[
            CredentialContextDTO(
                id=c.id, credential_type=c.credential_type, title=c.title,
                credential_number=c.credential_number,
                issuing_authority=c.issuing_authority,
                issue_date=c.issue_date, expiry_date=c.expiry_date,
                days_until_expiry=c.days_until_expiry, notes=c.notes,
            )
            for c in ctx.credentials
        ],
        sea_time=(
            SeaTimeContextDTO(
                total_days=ctx.sea_time.total_days,
                days_last_3_years=ctx.sea_time.days_last_3_years,
                days_last_5_years=ctx.sea_time.days_last_5_years,
                by_route_type=ctx.sea_time.by_route_type,
                by_capacity=ctx.sea_time.by_capacity,
                entry_count=ctx.sea_time.entry_count,
                earliest_date=ctx.sea_time.earliest_date,
                latest_date=ctx.sea_time.latest_date,
            ) if ctx.sea_time else None
        ),
        active_vessel=(
            ActiveVesselContextDTO(
                id=ctx.active_vessel.id, name=ctx.active_vessel.name,
                vessel_type=ctx.active_vessel.vessel_type,
                flag_state=ctx.active_vessel.flag_state,
                gross_tonnage=ctx.active_vessel.gross_tonnage,
                subchapter=ctx.active_vessel.subchapter,
                route_types=ctx.active_vessel.route_types,
                cargo_types=ctx.active_vessel.cargo_types,
                has_coi_extraction=ctx.active_vessel.has_coi_extraction,
            ) if ctx.active_vessel else None
        ),
        prompt_block=ctx.as_prompt_block(),
    )


# ── /me/renewal-readiness/{credential_id} ──────────────────────────────────


class RenewalRequirement(BaseModel):
    """One discrete thing the user does or doesn't have for renewal."""
    label: str          # "Medical certificate"
    status: str         # 'satisfied' | 'missing' | 'unknown' | 'expiring'
    detail: str         # narrative anchored to user's actual data


class RenewalReadinessDTO(BaseModel):
    credential_id: str
    credential_label: str
    days_until_expiry: Optional[int]
    expires_on: Optional[str]
    overall_status: str   # 'ready' | 'partial' | 'not_ready' | 'expired'
    narrative: str        # 1-3 paragraph plain-English summary
    requirements: list[RenewalRequirement]
    suggested_actions: list[str]
    citations: list[str]  # "46 CFR 10.227", "46 CFR 10.215", etc.
    model_used: str


_RENEWAL_SYSTEM_PROMPT = """You are RegKnots' Renewal Co-Pilot. The user has a maritime credential approaching renewal. Your job is to produce a personalized readiness report grounded in BOTH the user's stored data and the controlling US Coast Guard / IMO regulations.

Hard rules:
  1. Use the user's actual credentials, sea-time, and dates from the input. Don't invent values.
  2. Cite the controlling CFR / regulation section by exact number whenever you make a claim about a requirement.
  3. If a requirement's status is unclear from the data, say "unknown" — don't guess.
  4. Tone: a knowledgeable colleague, not a regulator. Plain English, no jargon dump.
  5. Suggested actions are concrete and ordered by priority. "Get a drug test letter" beats "Ensure compliance with drug testing requirements."

Output JSON ONLY (no markdown fences, no prose around it):

{
  "overall_status": "ready" | "partial" | "not_ready" | "expired",
  "narrative": "1-3 paragraph plain-English summary anchored to specific facts.",
  "requirements": [
    {
      "label": "Short name like 'Medical certificate' or 'Sea service'",
      "status": "satisfied" | "missing" | "unknown" | "expiring",
      "detail": "1-2 sentences. Anchor to data: 'Your medical cert valid through 2026-08-12, beyond the renewal target.' or 'No drug-test letter on file in the past 24 months — required by 46 CFR 16.230.'"
    }
  ],
  "suggested_actions": [
    "1-2 sentences each. Ordered by priority. Concrete next steps.",
    "..."
  ],
  "citations": ["46 CFR 10.227", "46 CFR 10.215", "46 CFR 16.230"]
}

The 'overall_status' rules:
  - 'expired'    — credential is already past expiry
  - 'not_ready'  — major gaps (sea-time short, missing required cert)
  - 'partial'    — minor gaps (one missing supporting doc, easily resolved)
  - 'ready'      — everything checks out, the user could file today
"""


@router.get("/renewal-readiness/{credential_id}", response_model=RenewalReadinessDTO)
async def get_renewal_readiness(
    credential_id: str,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> RenewalReadinessDTO:
    """Renewal Co-Pilot: assess readiness for one credential.

    Pipeline:
      1. Load credential + the user's full record (other credentials,
         sea-time, vessels)
      2. Retrieve the controlling regulation passages from the corpus
         (e.g. for an MMC: 46 CFR 10.227, 10.215, 11.x sections)
      3. Sonnet synthesizes the readiness verdict + narrative + the
         remaining actions, anchored to specific citations.
    """
    try:
        cid = _uuid.UUID(credential_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid credential id")

    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    # Fetch the credential + verify ownership in one round trip.
    cred_row = await pool.fetchrow(
        """
        SELECT id, credential_type, title, credential_number,
               issuing_authority, issue_date, expiry_date, notes
        FROM user_credentials
        WHERE id = $1 AND user_id = $2
        """,
        cid, user_uuid,
    )
    if cred_row is None:
        raise HTTPException(status_code=404, detail="credential not found")

    credential_label = cred_row["title"] or cred_row["credential_type"].upper()

    # User context — same source of truth the chat sees.
    from rag.user_context import build_user_context
    user_ctx = await build_user_context(pool=pool, user_id=user_uuid)

    # Retrieve controlling-regulation chunks from the corpus.
    # Heuristic query depends on credential_type:
    #   - mmc      → 46 CFR 10.227 (renewal), 11.x (qualification ladder)
    #   - stcw     → 46 CFR 10.215 (STCW endorsement renewal), STCW Reg I/11
    #   - medical  → 46 CFR 10.301 (medical cert renewal), NVIC 04-08
    #   - twic     → TWIC renewal (49 CFR 1572)
    cred_type = cred_row["credential_type"]
    retrieval_query = _retrieval_query_for(cred_type, credential_label)
    retrieved_chunks = await _retrieve_supporting_chunks(retrieval_query, k=8)

    # Build the user input — facts only, no synthesis.
    user_payload = _build_renewal_input(
        credential={
            "id": str(cred_row["id"]),
            "type": cred_type,
            "title": cred_row["title"],
            "number": cred_row["credential_number"],
            "authority": cred_row["issuing_authority"],
            "issue_date": cred_row["issue_date"].isoformat() if cred_row["issue_date"] else None,
            "expiry_date": cred_row["expiry_date"].isoformat() if cred_row["expiry_date"] else None,
            "notes": cred_row["notes"],
        },
        user_ctx=user_ctx,
        retrieved_chunks=retrieved_chunks,
    )

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    try:
        response = await anthropic_client.messages.create(
            model=_REASONING_MODEL,
            max_tokens=1500,
            system=_RENEWAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception as exc:
        logger.warning(
            "renewal-readiness Sonnet call failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        raise HTTPException(
            status_code=503,
            detail="Readiness analysis temporarily unavailable. Try again.",
        )

    parsed = _parse_json(text)
    if parsed is None:
        logger.warning("renewal-readiness: no JSON in response: %s", text[:200])
        raise HTTPException(
            status_code=503,
            detail="Readiness analysis returned malformed output. Try again.",
        )

    # Days until expiry computed locally to ensure consistency with user_context.
    days_left: Optional[int] = None
    expires_on: Optional[str] = None
    if cred_row["expiry_date"]:
        from datetime import date
        days_left = (cred_row["expiry_date"] - date.today()).days
        expires_on = cred_row["expiry_date"].isoformat()

    requirements_raw = parsed.get("requirements") or []
    requirements: list[RenewalRequirement] = []
    for r in requirements_raw[:12]:  # cap to keep payload sane
        if not isinstance(r, dict):
            continue
        status_str = (r.get("status") or "unknown").strip().lower()
        if status_str not in ("satisfied", "missing", "unknown", "expiring"):
            status_str = "unknown"
        requirements.append(RenewalRequirement(
            label=str(r.get("label") or "")[:80],
            status=status_str,
            detail=str(r.get("detail") or "")[:600],
        ))

    suggested_actions = [
        str(a)[:300] for a in (parsed.get("suggested_actions") or [])[:8]
    ]
    citations = [
        str(c)[:80] for c in (parsed.get("citations") or [])[:12]
    ]
    overall = (parsed.get("overall_status") or "partial").strip().lower()
    if overall not in ("ready", "partial", "not_ready", "expired"):
        overall = "partial"
    # Sanity-check overall against actual expiry — model occasionally
    # says "ready" on an already-expired credential.
    if days_left is not None and days_left < 0 and overall != "expired":
        overall = "expired"

    logger.info(
        "renewal-readiness: user=%s cred=%s status=%s reqs=%d actions=%d",
        current_user.email, cid, overall, len(requirements), len(suggested_actions),
    )

    return RenewalReadinessDTO(
        credential_id=str(cid),
        credential_label=credential_label,
        days_until_expiry=days_left,
        expires_on=expires_on,
        overall_status=overall,
        narrative=str(parsed.get("narrative") or "")[:2000],
        requirements=requirements,
        suggested_actions=suggested_actions,
        citations=citations,
        model_used=_REASONING_MODEL,
    )


# ── /me/career-progression ─────────────────────────────────────────────────


class CareerUpgrade(BaseModel):
    """One credential the user could plausibly pursue next."""
    title: str                       # "Master Near-Coastal 200 GT"
    status: str                      # 'cap_eligible' | 'within_reach' | 'requires_training'
    summary: str                     # 1-2 sentences on what it unlocks
    gap: Optional[str]               # "180 near-coastal days" — null if cap-eligible
    estimated_timeline: Optional[str] # "~8 months at current pace"
    citations: list[str]             # "46 CFR 11.422"


class CareerProgressionDTO(BaseModel):
    current_credentials: list[str]   # plain-English headlines
    cap_eligible_now: list[CareerUpgrade]
    within_reach: list[CareerUpgrade]
    narrative: str                   # plain-English overview
    citations: list[str]
    model_used: str


_CAREER_SYSTEM_PROMPT = """You are RegKnots' Career Path engine. Given a mariner's stored credentials and sea-time record, plus the controlling US Coast Guard / IMO regulations, identify the credential upgrades they're closest to qualifying for.

Hard rules:
  1. Use ONLY the user's actual data and the supplied regulation passages. Don't invent days, capacities, or routes.
  2. Cite the exact CFR section that gates each upgrade. No hand-wavy "the regs require..."
  3. Two buckets:
       - cap_eligible_now: the user has already hit the regulatory floor for this upgrade. They could apply today.
       - within_reach: 1-2 specific gaps, quantified with their current numbers vs. the requirement.
     Don't list upgrades that are far away or require completely-new credentials they don't have.
  4. Tone: a senior mariner advising a junior. Concrete and useful. No marketing language.
  5. Quantify gaps with their actual numbers. "You have 540 near-coastal days; 11.422 requires 720; you're 180 short."
  6. Estimated timeline: only when reasonable. Use "—" if you can't estimate.

Output JSON ONLY (no markdown fences, no prose around it):

{
  "current_credentials": ["plain-English summary line per held credential"],
  "cap_eligible_now": [
    {
      "title": "Specific credential name like 'Master Near-Coastal 200 GT'",
      "status": "cap_eligible",
      "summary": "1-2 sentences on what it unlocks",
      "gap": null,
      "estimated_timeline": null,
      "citations": ["46 CFR 11.422"]
    }
  ],
  "within_reach": [
    {
      "title": "...",
      "status": "within_reach" | "requires_training",
      "summary": "...",
      "gap": "180 near-coastal days",
      "estimated_timeline": "~8 months at current pace" | null,
      "citations": ["46 CFR 11.464"]
    }
  ],
  "narrative": "1-2 paragraphs of overview pulling the picture together.",
  "citations": ["all unique CFR sections referenced above"]
}

If the user has no MMC at all, both buckets should be empty and the narrative should describe the entry-level path (OS / AB / OUPV) and the documents needed to start.
"""


@router.get("/career-progression", response_model=CareerProgressionDTO)
async def get_career_progression(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CareerProgressionDTO:
    """Career Path: cap-eligible-now + within-reach upgrades."""
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    from rag.user_context import build_user_context
    user_ctx = await build_user_context(pool=pool, user_id=user_uuid)

    # Retrieve career-ladder regulation chunks. Broad query covers the
    # 11.x-series CFR (officer endorsements, ratings, OUPV, etc.) plus
    # STCW endorsements where relevant.
    retrieval_query = (
        "Merchant mariner credential officer endorsement requirements "
        "Master Mate Engineer near-coastal oceans inland sea service "
        "qualifying days 46 CFR 11"
    )
    retrieved_chunks = await _retrieve_supporting_chunks(retrieval_query, k=10)

    user_payload = _build_career_input(
        user_ctx=user_ctx, retrieved_chunks=retrieved_chunks,
    )

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    try:
        response = await anthropic_client.messages.create(
            model=_REASONING_MODEL,
            max_tokens=2000,
            system=_CAREER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception as exc:
        logger.warning(
            "career-progression Sonnet call failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        raise HTTPException(
            status_code=503,
            detail="Career analysis temporarily unavailable. Try again.",
        )

    parsed = _parse_json(text)
    if parsed is None:
        logger.warning("career-progression: no JSON in response: %s", text[:200])
        raise HTTPException(
            status_code=503,
            detail="Career analysis returned malformed output. Try again.",
        )

    def _to_upgrade(u: dict) -> Optional[CareerUpgrade]:
        if not isinstance(u, dict):
            return None
        title = str(u.get("title") or "").strip()[:120]
        if not title:
            return None
        status_str = (u.get("status") or "within_reach").strip().lower()
        if status_str not in ("cap_eligible", "within_reach", "requires_training"):
            status_str = "within_reach"
        return CareerUpgrade(
            title=title,
            status=status_str,
            summary=str(u.get("summary") or "")[:400],
            gap=str(u["gap"])[:200] if u.get("gap") else None,
            estimated_timeline=(
                str(u["estimated_timeline"])[:120]
                if u.get("estimated_timeline") else None
            ),
            citations=[str(c)[:80] for c in (u.get("citations") or [])[:6]],
        )

    cap_eligible_raw = parsed.get("cap_eligible_now") or []
    within_reach_raw = parsed.get("within_reach") or []
    cap_eligible = [
        u for u in (_to_upgrade(x) for x in cap_eligible_raw[:8])
        if u is not None
    ]
    within_reach = [
        u for u in (_to_upgrade(x) for x in within_reach_raw[:8])
        if u is not None
    ]

    current_credentials = [
        str(c)[:160] for c in (parsed.get("current_credentials") or [])[:12]
    ]
    citations = [
        str(c)[:80] for c in (parsed.get("citations") or [])[:20]
    ]

    logger.info(
        "career-progression: user=%s cap=%d reach=%d",
        current_user.email, len(cap_eligible), len(within_reach),
    )

    return CareerProgressionDTO(
        current_credentials=current_credentials,
        cap_eligible_now=cap_eligible,
        within_reach=within_reach,
        narrative=str(parsed.get("narrative") or "")[:2000],
        citations=citations,
        model_used=_REASONING_MODEL,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _retrieval_query_for(credential_type: str, label: str) -> str:
    """Pick a corpus retrieval query keyed on credential type."""
    base = label.lower() if label else credential_type
    if credential_type == "mmc":
        return (
            f"Merchant mariner credential renewal requirements active service "
            f"sea time medical certificate drug test 46 CFR 10.227 {base}"
        )
    if credential_type == "stcw":
        return (
            f"STCW endorsement renewal active service refresher training "
            f"46 CFR 10.215 STCW Regulation I/11 {base}"
        )
    if credential_type == "medical":
        return (
            f"Merchant mariner medical certificate renewal physical examination "
            f"NVIC 04-08 46 CFR 10.301 {base}"
        )
    if credential_type == "twic":
        return (
            f"Transportation Worker Identification Credential TWIC renewal "
            f"49 CFR 1572 enrollment {base}"
        )
    return f"USCG credential renewal requirements {base}"


async def _retrieve_supporting_chunks(query: str, k: int = 8) -> list[dict]:
    """Pull top-k corpus chunks for the given query.

    Wraps rag.retriever.retrieve so the reasoning endpoints use the
    same embeddings + ranking the main chat does. Returns minimal
    fields the prompt formatter consumes (source / section / text).

    Failures (DB hiccup, embedding API timeout, etc.) degrade to an
    empty list — the reasoning endpoint will still respond, just
    without retrieved citations. Better than 503-ing on every request.
    """
    try:
        from app.config import settings
        from rag.retriever import retrieve
        pool = await get_pool()
        chunks = await retrieve(
            query=query,
            pool=pool,
            openai_api_key=settings.openai_api_key,
            limit=k,
        )
    except Exception as exc:
        logger.warning(
            "_retrieve_supporting_chunks failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return []
    return chunks or []


def _build_renewal_input(
    credential: dict, user_ctx: Any, retrieved_chunks: list[dict],
) -> str:
    """Assemble the renewal-readiness user message."""
    block = user_ctx.as_prompt_block() or "(no other credentials or sea-time on file)"
    cred_block = _format_credential(credential)
    chunks_block = _format_chunks(retrieved_chunks)
    return (
        f"CREDENTIAL UNDER REVIEW:\n{cred_block}\n\n"
        f"USER'S FULL RECORD:\n{block}\n\n"
        f"CONTROLLING REGULATIONS (retrieved corpus passages):\n{chunks_block}\n\n"
        f"Produce the readiness JSON. Anchor every requirement to the user's "
        f"actual data, and cite the exact CFR section for each."
    )


def _build_career_input(user_ctx: Any, retrieved_chunks: list[dict]) -> str:
    """Assemble the career-progression user message."""
    block = user_ctx.as_prompt_block() or "(no credentials or sea-time on file)"
    chunks_block = _format_chunks(retrieved_chunks)
    return (
        f"USER'S FULL RECORD:\n{block}\n\n"
        f"REGULATION CONTEXT (retrieved corpus passages):\n{chunks_block}\n\n"
        f"Produce the career-progression JSON. Be specific about gap "
        f"quantities and cite exact CFR sections for every upgrade."
    )


def _format_credential(c: dict) -> str:
    parts = [f"- Type: {(c.get('type') or '').upper()}"]
    parts.append(f"- Title: {c.get('title') or '(untitled)'}")
    if c.get("number"):
        parts.append(f"- Number: {c['number']}")
    if c.get("authority"):
        parts.append(f"- Issuing authority: {c['authority']}")
    if c.get("issue_date"):
        parts.append(f"- Issued: {c['issue_date']}")
    if c.get("expiry_date"):
        parts.append(f"- Expires: {c['expiry_date']}")
    if c.get("notes"):
        parts.append(f"- Notes: {c['notes']}")
    return "\n".join(parts)


def _format_chunks(chunks: list[dict], per_chunk_chars: int = 1500) -> str:
    if not chunks:
        return "(no controlling-regulation passages were retrieved)"
    parts: list[str] = []
    for i, c in enumerate(chunks, 1):
        section = c.get("section_number") or "(unknown)"
        title = c.get("section_title") or ""
        text = c.get("full_text") or c.get("text") or c.get("content") or ""
        text = str(text)[:per_chunk_chars]
        parts.append(f"[{i}] {section} — {title}\n{text}")
    return "\n\n".join(parts)


def _parse_json(text: str) -> Optional[dict]:
    """Tolerantly extract the JSON object from a model response.
    Mirrors the parser pattern used in ensemble_fallback / hedge_judge.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
