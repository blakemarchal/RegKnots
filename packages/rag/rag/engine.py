"""
RAG orchestrator.

Steps:
  1. Route query → model selection (Haiku classifier)
  2. Retrieve top 8 relevant chunks (with soft vessel profile re-ranking)
  3. Build formatted context + citation list
  4. Construct Claude messages (system + history + current turn)
  5. Call Claude with selected model
  6. Verify every citation in the response actually exists in the DB
  7. Strip unverified citations, append disclaimer, log to citation_errors
  8. Return ChatResponse
"""

import logging
import re
from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import tiktoken
from anthropic import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)

from rag.context import build_context
from rag.fallback import FALLBACK_MODEL_ID, fallback_chat
from rag.hedge import detect_hedge
from rag.models import ChatMessage, ChatResponse, CitedRegulation
from rag.prompts import NAVIGATION_AID_REMINDER, SYSTEM_PROMPT
from rag.retriever import retrieve
from rag.router import REGENERATION_MODEL, route_query

# Anthropic exceptions that indicate Claude itself is unavailable — these are
# the only errors we fall back on. Application-level bugs (ValueError,
# KeyError, DB errors, etc.) are intentionally NOT caught so they still fail
# loudly.
_CLAUDE_FAILURE_EXCEPTIONS = (
    APIError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Conversation history limits.
# _MAX_HISTORY is the hard cap on message count (10 user/assistant pairs).
# _MAX_HISTORY_TOKENS is a token-aware safety valve — if the selected window
# still exceeds this budget, we drop the oldest messages until it fits.
# No summarization is applied; trimming is purely FIFO.
_MAX_HISTORY = 20
_MAX_HISTORY_TOKENS = 12_000
_MAX_TOKENS = 2048

_HISTORY_ENCODER = tiktoken.get_encoding("cl100k_base")


def _trim_history_by_tokens(
    messages: list[dict],
    budget: int = _MAX_HISTORY_TOKENS,
) -> list[dict]:
    """Drop oldest messages until total token count is within budget.

    Operates on the list of Claude API message dicts (role + content). Counts
    tokens on the content string via cl100k_base as a portable proxy — exact
    Claude tokenization differs slightly but cl100k is close enough for a
    safety-valve budget check. No summarization, purely FIFO eviction.
    """
    def _count(msgs: list[dict]) -> int:
        return sum(len(_HISTORY_ENCODER.encode(m["content"])) for m in msgs)

    total = _count(messages)
    if total <= budget:
        return messages

    original_count = len(messages)
    original_tokens = total
    trimmed = list(messages)
    while trimmed and _count(trimmed) > budget:
        trimmed.pop(0)

    logger.info(
        "Trimmed conversation history: %d→%d messages, %d→%d tokens (budget=%d)",
        original_count,
        len(trimmed),
        original_tokens,
        _count(trimmed),
        budget,
    )
    return trimmed

# ── Citation extraction regexes (one per knowledge-base source) ─────────────
#
# These patterns extract citations Claude inserted into answer text so each
# reference can be verified against the regulations table. The canonical DB
# formats they map to (see packages/ingest/ingest/sources/*) are:
#
#   cfr_{N}            "46 CFR 199.261"
#   solas              "SOLAS Ch.II-2", "SOLAS Ch.II-2 Part A", "SOLAS Annex I"
#   solas_supplement   "SOLAS Supplement Jan2026 MSC.520(106)"
#   colregs            "COLREGS Rule 5" or merged "COLREGS Rules 4-10"
#   stcw               "STCW Ch.II Reg.II/1", "STCW Code A-II/1", "STCW Ch.II"
#   stcw_supplement    "STCW Supplement Jan2025 MSC.540(107)"
#   nvic               "NVIC 01-23" or "NVIC 01-23 §3"
#   ism                "ISM 1.2.3", "ISM Part A", "ISM Code"
#
# For sources whose DB granularity is coarser than Claude's citation (SOLAS
# stores at chapter/part level; COLREGs may store ranges), verification uses
# LIKE patterns or range checks — see _verify_text_citations.

# Matches both "(46 CFR 199.261)" and bare "46 CFR 199.261" — same as parseMessage.ts
_CFR_RE = re.compile(r"\(?(\d+)\s+CFR\s+([\d]+(?:\.[\d]+(?:-[\d]+)?)?)\)?")

# SOLAS chapter: "SOLAS Ch. II-2 Reg. 10", "SOLAS Chapter V, Regulation 19"
# Groups: (1) chapter (Roman, optional -N), (2) part letter (optional),
# (3) regulation number (optional — informational only, not verified against DB)
_SOLAS_CH_RE = re.compile(
    r"SOLAS\s+Ch(?:apter)?\.?\s*([IVX]+(?:-\d+)?)"
    r"(?:\s+Part\.?\s*([A-Z](?:-\d+)?))?"
    r"(?:[,\s]*Reg(?:ulation)?\.?\s*(\d+(?:\.\d+)*))?",
    re.IGNORECASE,
)

# SOLAS Annex: "SOLAS Annex I", "SOLAS Annex V"
_SOLAS_ANNEX_RE = re.compile(r"SOLAS\s+Annex\s+([IVX]+|\d+)", re.IGNORECASE)

# MSC resolution — applies to both SOLAS and STCW supplements.
# Format: "MSC.520(106)" — captured wherever it appears (inside parens or bare).
_MSC_RE = re.compile(r"MSC\.(\d+)\((\d+)\)")

# COLREGs rule — only match inside parens or with an explicit "COLREG(S)"
# prefix to avoid false positives on generic "Rule N" prose elsewhere.
_COLREGS_RE = re.compile(
    r"\(\s*(?:COLREGS?\s+)?Rule\s+(\d+)\s*\)"
    r"|COLREGS?\s+Rule\s+(\d+)",
    re.IGNORECASE,
)

# NVIC: "NVIC 01-20", optionally with "§3" section suffix.
_NVIC_RE = re.compile(
    r"NVIC\s+(\d{1,2}-\d{2})(?:\s*(?:§|Sec(?:tion)?\.?\s*)(\d+))?",
    re.IGNORECASE,
)

# STCW Regulation: "STCW Reg. II/1", "STCW Regulation II-1/1", "STCW II/1"
# Groups: (1) chapter (Roman, optional -N), (2) number
_STCW_REG_RE = re.compile(
    r"STCW\s+(?:Reg(?:ulation)?\.?\s*)?([IVX]+(?:-\d+)?)/(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# STCW Code: "STCW Code A-II/1", "STCW Code B-I/2"
_STCW_CODE_RE = re.compile(
    r"STCW\s+Code\s+([AB])-([IVX]+(?:-\d+)?)/(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# STCW Chapter standalone: "STCW Ch. II" (when there's no regulation suffix)
_STCW_CH_RE = re.compile(
    r"STCW\s+Ch(?:apter)?\.?\s*([IVX]+(?:-\d+)?)(?!\s*(?:Reg|/|Code))",
    re.IGNORECASE,
)

# ISM Code: "(ISM Code 1.2.3)", "(ISM 10.1)", "ISM Code Section 12"
_ISM_RE = re.compile(
    r"ISM(?:\s+Code)?\s+(?:Section\s+)?(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

_VESSEL_UPDATE_RE = re.compile(
    r"\[VESSEL_UPDATE\]\s*\n(.*?)\n\[/VESSEL_UPDATE\]",
    re.DOTALL,
)


def _extract_vessel_update(answer: str) -> tuple[str, dict | None]:
    """Extract and remove VESSEL_UPDATE block from answer text.

    Returns:
        (cleaned_answer, update_dict) where update_dict is None if no block found.
    """
    match = _VESSEL_UPDATE_RE.search(answer)
    if not match:
        return answer, None

    # Parse the key-value pairs
    update: dict = {}
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if not value or value.lower() in ("none", "n/a", ""):
            continue
        if key == "key_equipment":
            update[key] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "additional":
            # "additional: key: value" → store in dict
            if ":" in value:
                akey, _, aval = value.partition(":")
                update[akey.strip().lower().replace(" ", "_")] = aval.strip()
        else:
            update[key] = value

    # Remove the block from the answer
    cleaned = _VESSEL_UPDATE_RE.sub("", answer).rstrip()

    logger.info("Extracted vessel update: %s", list(update.keys()) if update else "empty")
    return cleaned, update if update else None


_UNVERIFIED_DISCLAIMER = (
    "\n\n*Note: Some referenced sections could not be verified in our current database "
    "and have been removed from this response. Please verify requirements directly on eCFR.*"
)


async def verify_citations(
    cited_regulations: list[CitedRegulation],
    pool: asyncpg.Pool,
) -> tuple[list[CitedRegulation], list[str]]:
    """Verify each cited regulation actually exists in the regulations table.

    Uses a single batched query via unnest() instead of N sequential fetches.

    Args:
        cited_regulations: List of CitedRegulation objects to check.
        pool:              asyncpg connection pool.

    Returns:
        (verified, unverified) where verified is the subset found in the DB
        and unverified is a list of section_number strings not found.
    """
    if not cited_regulations:
        return [], []

    sources = [r.source for r in cited_regulations]
    section_numbers = [r.section_number for r in cited_regulations]

    rows = await pool.fetch(
        """
        SELECT DISTINCT r.source, r.section_number
        FROM regulations r
        WHERE (r.source, r.section_number) IN (
            SELECT a, b FROM unnest($1::text[], $2::text[]) AS t(a, b)
        )
        """,
        sources,
        section_numbers,
    )
    found: set[tuple[str, str]] = {(r["source"], r["section_number"]) for r in rows}

    verified: list[CitedRegulation] = []
    unverified: list[str] = []
    for reg in cited_regulations:
        if (reg.source, reg.section_number) in found:
            verified.append(reg)
        else:
            logger.warning(
                "Citation not found in DB — source=%r section=%r",
                reg.source,
                reg.section_number,
            )
            unverified.append(reg.section_number)

    return verified, unverified


class _TextCitation:
    """Represents a citation reference extracted from answer text.

    `display` is exactly what Claude wrote (used for logging, stripping, and
    reporting in ChatResponse.unverified_citations). The `candidates` list is a
    set of (source, LIKE_pattern) pairs; verification succeeds if ANY of them
    matches a row in regulations. `colregs_rule` is set for COLREGs citations
    that also need range-membership checking (e.g. Rule 5 matching a merged
    "COLREGS Rules 4-10" row).
    """

    __slots__ = ("display", "candidates", "colregs_rule")

    def __init__(
        self,
        display: str,
        candidates: list[tuple[str, str]],
        colregs_rule: int | None = None,
    ) -> None:
        self.display = display
        self.candidates = candidates
        self.colregs_rule = colregs_rule


def _extract_all_text_citations(answer: str) -> list[_TextCitation]:
    """Extract citation references from answer text across ALL source types.

    Returns one _TextCitation per unique display string. Each entry carries
    the candidate (source, LIKE pattern) pairs used by _verify_text_citations
    to check the regulations table.
    """
    found: dict[str, _TextCitation] = {}

    # ── CFR ─────────────────────────────────────────────────────────────────
    for m in _CFR_RE.finditer(answer):
        title = m.group(1)
        section = m.group(2)
        display = f"{title} CFR {section}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[(f"cfr_{title}", display)],
            )

    # ── SOLAS chapter/part (regulation number is informational) ─────────────
    for m in _SOLAS_CH_RE.finditer(answer):
        chapter = m.group(1).upper()
        part = m.group(2)
        reg = m.group(3)
        chapter_key = f"SOLAS Ch.{chapter}"
        if part:
            chapter_key += f" Part {part.upper()}"
        display = chapter_key
        if reg:
            display += f" Reg.{reg}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("solas", f"{chapter_key}%")],
            )

    # ── SOLAS Annex ─────────────────────────────────────────────────────────
    for m in _SOLAS_ANNEX_RE.finditer(answer):
        annex = m.group(1).upper()
        display = f"SOLAS Annex {annex}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("solas", f"SOLAS Annex {annex}%")],
            )

    # ── MSC resolutions (ambiguous between SOLAS and STCW supplements) ─────
    for m in _MSC_RE.finditer(answer):
        msc_key = f"MSC.{m.group(1)}({m.group(2)})"
        if msc_key not in found:
            found[msc_key] = _TextCitation(
                display=msc_key,
                candidates=[
                    ("solas_supplement", f"%{msc_key}"),
                    ("stcw_supplement", f"%{msc_key}"),
                ],
            )

    # ── COLREGs (rules + merged-range verification) ────────────────────────
    for m in _COLREGS_RE.finditer(answer):
        rule_str = m.group(1) or m.group(2)
        rule_num = int(rule_str)
        display = f"Rule {rule_str}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("colregs", f"COLREGS Rule {rule_str}")],
                colregs_rule=rule_num,
            )

    # ── NVIC ───────────────────────────────────────────────────────────────
    for m in _NVIC_RE.finditer(answer):
        num = m.group(1)
        sec = m.group(2)
        display = f"NVIC {num}"
        if sec:
            display += f" §{sec}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("nvic", f"NVIC {num}%")],
            )

    # ── STCW Regulation ────────────────────────────────────────────────────
    for m in _STCW_REG_RE.finditer(answer):
        ch = m.group(1).upper()
        n = m.group(2)
        display = f"STCW Reg.{ch}/{n}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("stcw", f"STCW Ch.{ch} Reg.{ch}/{n}%")],
            )

    # ── STCW Code (part A or B) ─────────────────────────────────────────────
    for m in _STCW_CODE_RE.finditer(answer):
        part = m.group(1).upper()
        ch = m.group(2).upper()
        n = m.group(3)
        display = f"STCW Code {part}-{ch}/{n}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("stcw", f"STCW Code {part}-{ch}/{n}%")],
            )

    # ── STCW Chapter standalone ────────────────────────────────────────────
    for m in _STCW_CH_RE.finditer(answer):
        ch = m.group(1).upper()
        display = f"STCW Ch.{ch}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("stcw", f"STCW Ch.{ch}%")],
            )

    # ── ISM Code ───────────────────────────────────────────────────────────
    for m in _ISM_RE.finditer(answer):
        num = m.group(1)
        display = f"ISM {num}"
        if display not in found:
            found[display] = _TextCitation(
                display=display,
                candidates=[("ism", f"ISM {num}%")],
            )

    return list(found.values())


async def _verify_text_citations(
    citations: list[_TextCitation],
    pool: asyncpg.Pool,
) -> list[str]:
    """Verify each extracted text citation against the regulations table.

    Returns the list of display strings that FAILED verification. Uses one DB
    roundtrip for all LIKE candidates, plus one extra query for COLREGs range
    resolution if any COLREGs rules were extracted.
    """
    if not citations:
        return []

    # Flatten all (source, pattern) candidates into two parallel arrays and
    # remember which indices belong to which citation.
    sources: list[str] = []
    patterns: list[str] = []
    owners: list[int] = []  # parallel to sources/patterns: which citation index
    for i, cit in enumerate(citations):
        for src, pat in cit.candidates:
            sources.append(src)
            patterns.append(pat)
            owners.append(i)

    # Single batched query: each (source, pattern) row marked if ANY matching
    # regulation exists. Indices line up with the input arrays.
    rows = await pool.fetch(
        """
        SELECT t.idx
        FROM unnest($1::int[], $2::text[], $3::text[]) AS t(idx, src, pat)
        WHERE EXISTS (
            SELECT 1 FROM regulations r
            WHERE r.source = t.src AND r.section_number LIKE t.pat
            LIMIT 1
        )
        """,
        list(range(len(sources))),
        sources,
        patterns,
    )
    verified_owners: set[int] = {owners[r["idx"]] for r in rows}

    # COLREGs range check — any rule that didn't verify via LIKE might be
    # covered by a merged "COLREGS Rules A-B" row. Do one extra query to pull
    # all COLREGs section_numbers, then range-check in Python.
    colregs_pending = [
        i for i, cit in enumerate(citations)
        if cit.colregs_rule is not None and i not in verified_owners
    ]
    if colregs_pending:
        colregs_rows = await pool.fetch(
            "SELECT section_number FROM regulations WHERE source = 'colregs'"
        )
        range_re = re.compile(r"^COLREGS Rules (\d+)-(\d+)$", re.IGNORECASE)
        single_re = re.compile(r"^COLREGS Rule (\d+)$", re.IGNORECASE)
        covered: set[int] = set()
        for row in colregs_rows:
            sec = row["section_number"] or ""
            rm = range_re.match(sec)
            if rm:
                start, end = int(rm.group(1)), int(rm.group(2))
                covered.update(range(start, end + 1))
                continue
            sm = single_re.match(sec)
            if sm:
                covered.add(int(sm.group(1)))
        for i in colregs_pending:
            if citations[i].colregs_rule in covered:
                verified_owners.add(i)

    unverified_displays: list[str] = []
    for i, cit in enumerate(citations):
        if i not in verified_owners:
            logger.warning("Text citation not found in DB — display=%r", cit.display)
            unverified_displays.append(cit.display)

    return unverified_displays


async def _log_citation_errors(
    unverified: list[str],
    conversation_id: UUID,
    answer: str,
    model_used: str,
    pool: asyncpg.Pool,
) -> None:
    """Insert one row per unverified citation into citation_errors."""
    # Truncate message_content to avoid bloating the log table
    content_preview = answer[:1000] if len(answer) > 1000 else answer

    for section_number in unverified:
        await pool.execute(
            """
            INSERT INTO citation_errors
                (conversation_id, message_content, unverified_citation, model_used)
            VALUES ($1, $2, $3, $4)
            """,
            conversation_id,
            content_preview,
            section_number,
            model_used,
        )
    logger.info(
        "Logged %d citation error(s) for conversation %s",
        len(unverified),
        conversation_id,
    )


def _strip_unverified_citations(answer: str, unverified: list[str]) -> str:
    """Remove inline references to unverified citations from the answer text.

    `unverified` may contain any supported citation format (CFR, SOLAS, COLREGs,
    STCW, NVIC, ISM, MSC resolutions). For each display string we remove both
    the parenthesized and bare forms. For CFR displays we keep the original
    `(?!\\.\\d)` guard so "46 CFR 131" doesn't eat "46 CFR 131.45".
    """
    for display in unverified:
        escaped = re.escape(display)
        # Parenthesized form: "(SOLAS Ch. II-2 Reg. 10)"
        answer = re.sub(r"\s*\(" + escaped + r"\)", "", answer)
        # Bare form. CFR needs sub-section protection; everything else is safe.
        if re.match(r"^\d+\s+CFR\s", display):
            answer = re.sub(r"\b" + escaped + r"\b(?!\.\d)", "", answer)
        else:
            answer = re.sub(escaped, "", answer)

    # Clean up artifacts: double spaces, orphaned punctuation patterns.
    answer = re.sub(r"  +", " ", answer)                                 # collapse double spaces
    answer = re.sub(r"\s+([,;.])", r"\1", answer)                        # " ," → ","
    answer = re.sub(r"(per|under|in|by|see|of)\s*[,;.]", r"\1", answer)  # "per ," → "per"
    answer = re.sub(r"\(\s*\)", "", answer)                              # empty parens "()"
    answer = re.sub(r"  +", " ", answer)                                 # final collapse

    return answer.strip()


def _flatten_doc_value(v: object) -> str:
    """Recursively flatten nested dicts/lists from Claude Vision extractions."""
    if isinstance(v, dict):
        return "; ".join(
            f"{k}: {_flatten_doc_value(val)}" for k, val in v.items() if val
        )
    if isinstance(v, list):
        return ", ".join(_flatten_doc_value(i) for i in v)
    return str(v)


def _build_chat_messages(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    context_str: str,
    credential_context: str | None = None,
) -> list[dict]:
    """Construct the Claude API message list for a chat turn.

    Handles history truncation, vessel profile block construction, credential
    context injection, document extraction inclusion, and the final user
    message with retrieval context.
    """
    history = conversation_history[-_MAX_HISTORY:]
    messages = [{"role": msg.role, "content": msg.content} for msg in history]
    messages = _trim_history_by_tokens(messages)

    vessel_block = ""
    if vessel_profile:
        lines = [f"- Name: {vessel_profile.get('vessel_name', 'Unknown')}"]
        if vessel_profile.get("vessel_type"):
            lines.append(f"- Type: {vessel_profile['vessel_type']}")
        if vessel_profile.get("route_types"):
            lines.append(f"- Routes: {', '.join(vessel_profile['route_types'])}")
        if vessel_profile.get("cargo_types"):
            lines.append(f"- Cargo: {', '.join(vessel_profile['cargo_types'])}")
        if vessel_profile.get("gross_tonnage"):
            lines.append(f"- Tonnage: {vessel_profile['gross_tonnage']}")
        if vessel_profile.get("subchapter"):
            lines.append(f"- Subchapter: {vessel_profile['subchapter']}")
        if vessel_profile.get("inspection_certificate_type"):
            lines.append(f"- Inspection certificate: {vessel_profile['inspection_certificate_type']}")
        if vessel_profile.get("manning_requirement"):
            lines.append(f"- Manning: {vessel_profile['manning_requirement']}")
        if vessel_profile.get("key_equipment"):
            equip = vessel_profile["key_equipment"]
            if isinstance(equip, list):
                lines.append(f"- Key equipment: {', '.join(equip)}")
            else:
                lines.append(f"- Key equipment: {equip}")
        if vessel_profile.get("route_limitations"):
            lines.append(f"- Route limitations: {vessel_profile['route_limitations']}")
        if vessel_profile.get("additional_details"):
            for k, v in vessel_profile["additional_details"].items():
                lines.append(f"- {k.replace('_', ' ').title()}: {v}")

        doc_sections: list[str] = []
        for doc_info in vessel_profile.get("_confirmed_documents", []):
            doc_type = doc_info.get("type", "document")
            data = doc_info.get("data", {})
            if not data:
                continue
            type_labels = {
                "coi": "Certificate of Inspection",
                "safety_equipment": "Safety Equipment Certificate",
                "safety_construction": "Safety Construction Certificate",
                "safety_radio": "Safety Radio Certificate",
                "isps": "ISPS Certificate",
                "ism": "ISM Certificate",
                "other": "Vessel Document",
            }
            label = type_labels.get(doc_type, "Vessel Document")
            doc_lines = [f"\nFrom uploaded {label}:"]
            for dk, dv in data.items():
                if dv and str(dv).lower() not in ("null", "none", "n/a", ""):
                    doc_lines.append(f"- {dk.replace('_', ' ').title()}: {_flatten_doc_value(dv)}")
            if len(doc_lines) > 1:
                doc_sections.append("\n".join(doc_lines))

        vessel_block = (
            "Vessel profile:\n" + "\n".join(lines) + "\n"
            + "".join(doc_sections) + "\n"
            "Tailor your answer to this vessel's characteristics.\n\n"
        )
        logger.info("Including vessel context in prompt: %d fields", len(lines))

    credential_block = ""
    if credential_context:
        credential_block = (
            f"{credential_context}\n"
            "When relevant, tailor your answer to the user's credential situation.\n\n"
        )
        logger.info("Including credential context in prompt")

    user_content = (
        f"{NAVIGATION_AID_REMINDER}\n\n"
        f"{vessel_block}"
        f"{credential_block}"
        f"Regulation context:\n{context_str}\n\n"
        f"Question: {query}"
    )
    messages.append({"role": "user", "content": user_content})
    return messages


async def _collect_unverified(
    answer: str,
    cited: list[CitedRegulation],
    pool: asyncpg.Pool,
) -> tuple[list[CitedRegulation], list[str], list[str]]:
    """Run both citation checks against a given answer.

    Returns (verified_from_context, unverified_from_context, unverified_from_text).
    """
    verified_cited, unverified_from_context = await verify_citations(cited, pool)

    text_citations = _extract_all_text_citations(answer)
    unverified_from_text = await _verify_text_citations(text_citations, pool)

    return verified_cited, unverified_from_context, unverified_from_text


async def _regenerate_answer(
    query: str,
    context_str: str,
    unverified: list[str],
    model_used: str,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
) -> tuple[str, int, int] | None:
    """Call Claude (or the GPT-4o fallback) again with a corrective instruction.

    Returns (answer, input_tokens, output_tokens) or None if regeneration fails.
    Routes to whichever backend produced the original answer — if the first
    response came from the GPT-4o fallback, the regeneration goes there too.
    """
    corrective_instruction = (
        "Your previous answer referenced the following regulation sections that do not exist "
        "in our verified database:\n"
        + "\n".join(f"- {s}" for s in unverified)
        + "\n\nRewrite your answer using ONLY the regulation context provided below. "
        "Do not reference any regulations that are not explicitly present in the provided context. "
        "If you cannot fully answer the question with the verified context alone, say so honestly.\n\n"
        f"Verified regulation context:\n{context_str}\n\n"
        f"Original question: {query}"
    )
    messages = [{"role": "user", "content": corrective_instruction}]

    # If the original call used the GPT-4o fallback, regenerate via the same path.
    if model_used == FALLBACK_MODEL_ID:
        try:
            result = await fallback_chat(
                system_prompt=SYSTEM_PROMPT,
                messages=messages,
                max_tokens=_MAX_TOKENS,
                openai_api_key=openai_api_key,
            )
            return result["answer"], result["input_tokens"], result["output_tokens"]
        except Exception as exc:  # noqa: BLE001 — surface as regen failure
            logger.warning("Regeneration via GPT-4o failed: %s", exc)
            return None

    # Sprint D4 — regeneration pass always uses Opus 4.7 regardless of the
    # initial model. The first answer already failed verification; we spend
    # Opus only on these recoveries, not on every call. Upside: second-try
    # reasoning is materially better on conflict/applicability cases.
    regen_model = REGENERATION_MODEL
    logger.info(
        "REGEN: original=%s → regenerating with %s", model_used, regen_model,
    )
    try:
        response = await anthropic_client.messages.create(
            model=regen_model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return (
            response.content[0].text,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
    except _CLAUDE_FAILURE_EXCEPTIONS as exc:
        logger.warning(
            "Regeneration via Claude %s failed (%s: %s) — falling back to original model %s",
            regen_model,
            type(exc).__name__,
            str(exc)[:200],
            model_used,
        )
        # If Opus is transiently unavailable, fall back to the original model
        # rather than return None (which would surface to the user as a cite
        # stripped with disclaimer).
        try:
            response = await anthropic_client.messages.create(
                model=model_used,
                max_tokens=_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            return (
                response.content[0].text,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        except _CLAUDE_FAILURE_EXCEPTIONS as exc2:
            logger.warning(
                "Regeneration fallback also failed (%s: %s)",
                type(exc2).__name__,
                str(exc2)[:200],
            )
            return None


async def _finalize_answer(
    *,
    answer: str,
    cited: list[CitedRegulation],
    conversation_id: UUID,
    model_used: str,
    pool: asyncpg.Pool,
    query: str,
    context_str: str,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
) -> tuple[str, list[CitedRegulation], list[str], dict | None, int, int, bool]:
    """Vessel-update extraction, citation verification, regeneration, cleanup.

    When the first pass finds unverified citations, log them, then attempt ONE
    regeneration call with a corrective instruction. The regenerated answer is
    re-verified; if it still has unverified citations, fall back to
    strip + disclaim on that second answer. If regeneration fails outright,
    strip + disclaim on the original.

    Returns:
        (cleaned_answer, verified_cited, unverified_displays, vessel_update,
         regen_input_tokens, regen_output_tokens, regenerated)
    """
    # Extract vessel update block (before citation verification)
    answer, vessel_update = _extract_vessel_update(answer)

    # First pass: verify context citations + text citations in the original answer
    verified_cited, unverified_from_context, unverified_from_text = await _collect_unverified(
        answer, cited, pool,
    )
    all_unverified = list(
        dict.fromkeys(unverified_from_context + unverified_from_text)
    )

    if not all_unverified:
        return answer, verified_cited, [], vessel_update, 0, 0, False

    # DEFENSIVE LOG — WARNING level so it survives any future INFO-level
    # filtering and is unmissable in production when regeneration kicks in.
    # If this line isn't in the logs for a citation-error conversation,
    # either the code isn't actually deployed or control flow never reached
    # here. Either way it's the first thing to check next time.
    logger.warning(
        "REGEN: Entering regeneration — %d unverified citation(s): %s",
        len(all_unverified),
        all_unverified,
    )

    # Log the ORIGINAL answer's bad citations for forensics, regardless of
    # whether regeneration ultimately succeeds. message_content is truncated
    # inside _log_citation_errors.
    await _log_citation_errors(
        unverified=all_unverified,
        conversation_id=conversation_id,
        answer=answer,
        model_used=model_used,
        pool=pool,
    )

    logger.info(
        "Regenerating answer due to %d unverified citation(s): %s",
        len(all_unverified),
        all_unverified,
    )
    regen = await _regenerate_answer(
        query=query,
        context_str=context_str,
        unverified=all_unverified,
        model_used=model_used,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
    )

    if regen is None:
        # Regeneration unavailable — fall back to the legacy strip + disclaim path.
        logger.warning("Regeneration failed; falling back to strip + disclaim")
        answer = _strip_unverified_citations(answer, all_unverified) + _UNVERIFIED_DISCLAIMER
        return answer, verified_cited, all_unverified, vessel_update, 0, 0, False

    new_answer, regen_in, regen_out = regen
    # Pull any (unlikely) VESSEL_UPDATE block from the regenerated answer; only
    # adopt it if the original turn didn't already produce one.
    new_answer, new_vessel_update = _extract_vessel_update(new_answer)
    if new_vessel_update and not vessel_update:
        vessel_update = new_vessel_update

    # Second pass: re-verify on the regenerated answer. Context cited list is
    # unchanged so its verification status carries over.
    new_text_citations = _extract_all_text_citations(new_answer)
    unverified_from_text_2 = await _verify_text_citations(new_text_citations, pool)
    all_unverified_2 = list(
        dict.fromkeys(unverified_from_context + unverified_from_text_2)
    )

    if not all_unverified_2:
        logger.info("Regeneration complete — clean on second pass")
        return new_answer, verified_cited, [], vessel_update, regen_in, regen_out, True

    # Second attempt still has hallucinated citations. Strip + disclaim here
    # and bail — no recursive regeneration.
    logger.warning(
        "Regeneration complete — %d unverified citation(s) remain on second pass: %s",
        len(all_unverified_2),
        all_unverified_2,
    )
    new_answer = _strip_unverified_citations(new_answer, all_unverified_2) + _UNVERIFIED_DISCLAIMER
    return (
        new_answer,
        verified_cited,
        all_unverified_2,
        vessel_update,
        regen_in,
        regen_out,
        True,
    )


def _describe_sources(query: str) -> str:
    """Generate a human-readable label for the sources being searched based on query keywords."""
    q = query.lower()
    sources: list[str] = []

    # Specific regulation references
    if "cfr" in q or "code of federal" in q:
        if "33" in q:
            sources.append("33 CFR")
        elif "46" in q:
            sources.append("46 CFR")
        elif "49" in q:
            sources.append("49 CFR")
        else:
            sources.append("CFR")
    if "solas" in q:
        sources.append("SOLAS")
    if "colreg" in q or "collision" in q or "rule of the road" in q or "rules of the road" in q:
        sources.append("COLREGs")
    if "nvic" in q:
        sources.append("NVICs")
    if "stcw" in q:
        sources.append("STCW")
    if (
        "ism code" in q
        or "international safety management" in q
        or "safety management system" in q
        or "designated person" in q
        or "document of compliance" in q
        or "safety management certificate" in q
        or re.search(r"\b(?:ism|dpa|smc)\b", q)
    ):
        sources.append("ISM Code")
    if (
        "erg" in q
        or "emergency response guidebook" in q
        or "emergency response guide" in q
        or "hazmat" in q
        or "hazardous material" in q
        or "dangerous goods" in q
        or re.search(r"\b(?:UN|NA)\s*\d{4}\b", q, re.IGNORECASE)
        or re.search(r"\bguide\s*\d{3}\b", q, re.IGNORECASE)
    ):
        sources.append("ERG")

    # Topical fallback
    if not sources:
        if any(w in q for w in ["fire", "extinguish", "smoke", "flame"]):
            sources = ["fire safety regulations"]
        elif any(w in q for w in ["lifeboat", "life raft", "lifesaving", "life jacket", "immersion suit"]):
            sources = ["lifesaving equipment regulations"]
        elif any(w in q for w in ["navigation", "radar", "ais", "gps", "compass", "chart"]):
            sources = ["navigation equipment regulations"]
        elif any(w in q for w in ["inspection", "survey", "certificate", "coi"]):
            sources = ["inspection and certification regulations"]
        elif any(w in q for w in ["manning", "crew", "watchkeep", "license", "credential"]):
            sources = ["manning and credentialing regulations"]
        elif any(w in q for w in ["pollution", "discharge", "oil", "marpol", "ballast"]):
            sources = ["environmental compliance regulations"]
        else:
            sources = ["federal and international maritime regulations"]

    return ", ".join(sources)


def _summarize_found_sources(chunks: list[dict]) -> str:
    """Summarize which actual sources were found in the retrieved chunks."""
    source_map = {
        "cfr_33": "33 CFR",
        "cfr_46": "46 CFR",
        "cfr_49": "49 CFR",
        "solas": "SOLAS",
        "solas_supplement": "SOLAS",
        "colregs": "COLREGs",
        "nvic": "NVICs",
        "stcw": "STCW",
        "stcw_supplement": "STCW",
        "ism": "ISM Code",
        "erg": "ERG",
    }
    found: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        source = chunk.get("source", "")
        label = source_map.get(source, source)
        if label and label not in seen:
            seen.add(label)
            found.append(label)

    if not found:
        return ""
    if len(found) == 1:
        return found[0]
    if len(found) == 2:
        return f"{found[0]} and {found[1]}"
    return ", ".join(found[:-1]) + f", and {found[-1]}"


async def chat(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    conversation_id: UUID,
    credential_context: str | None = None,
) -> ChatResponse:
    """Run the full RAG pipeline and return a ChatResponse.

    Args:
        query:                The user's current question.
        conversation_history: Prior messages for this conversation.
        vessel_profile:       Dict with vessel_type, route_type, cargo_types — or None.
        pool:                 asyncpg connection pool.
        anthropic_client:     Shared AsyncAnthropic client (caller owns lifecycle).
        openai_api_key:       Key for OpenAI query embedding.
        conversation_id:      UUID of the conversation (new or existing).
    """
    # 1. Route
    route = await route_query(query, anthropic_client)
    logger.info(f"Routed query to {route.model} (score={route.score})")

    # 2. Retrieve
    chunks = await retrieve(
        query=query,
        pool=pool,
        openai_api_key=openai_api_key,
        vessel_profile=vessel_profile,
        limit=8,
    )
    logger.info(f"Retrieved {len(chunks)} chunks")

    # 3. Build context
    context_str, cited = build_context(chunks)

    # 4. Construct messages
    messages = _build_chat_messages(query, conversation_history, vessel_profile, context_str, credential_context)

    # 5. Call Claude — fall back to OpenAI GPT-4o on Anthropic API failures.
    model_used = route.model
    try:
        response = await anthropic_client.messages.create(
            model=route.model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
    except _CLAUDE_FAILURE_EXCEPTIONS as exc:
        logger.warning(
            "Claude API failed (%s: %s), falling back to OpenAI GPT-4o",
            type(exc).__name__,
            str(exc)[:200],
        )
        fallback_result = await fallback_chat(
            system_prompt=SYSTEM_PROMPT,
            messages=messages,
            max_tokens=_MAX_TOKENS,
            openai_api_key=openai_api_key,
        )
        answer = fallback_result["answer"]
        input_tokens = fallback_result["input_tokens"]
        output_tokens = fallback_result["output_tokens"]
        model_used = fallback_result["model"]
        logger.warning(
            "Fallback response received: %d input tokens, %d output tokens",
            input_tokens,
            output_tokens,
        )

    # 6. Post-process: vessel update extraction, citation verification,
    #    optional regeneration on citation failure, cleanup.
    (
        cleaned_answer,
        verified_cited,
        all_unverified,
        vessel_update,
        regen_in,
        regen_out,
        regenerated,
    ) = await _finalize_answer(
        answer=answer,
        cited=cited,
        conversation_id=conversation_id,
        model_used=model_used,
        pool=pool,
        query=query,
        context_str=context_str,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
    )
    input_tokens += regen_in
    output_tokens += regen_out

    # Sprint D2-LOG: if the final answer hedges on retrieval, log the miss
    # to `retrieval_misses` for offline analysis. Fire-and-forget — DB
    # errors never fail the chat response.
    hedge_phrase = detect_hedge(cleaned_answer)
    if hedge_phrase is not None:
        try:
            await _log_retrieval_miss(
                pool=pool,
                conversation_id=conversation_id,
                query=query,
                vessel_profile=vessel_profile,
                hedge_phrase=hedge_phrase,
                model_used=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                retrieved_chunks=chunks,
                cited=verified_cited,
                answer=cleaned_answer,
            )
        except Exception as exc:
            logger.warning(
                "retrieval_miss log failed (non-fatal): %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )

    return ChatResponse(
        answer=cleaned_answer,
        conversation_id=conversation_id,
        cited_regulations=verified_cited,
        model_used=model_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        unverified_citations=all_unverified,
        vessel_update=vessel_update,
        regenerated=regenerated,
    )


async def _log_retrieval_miss(
    *,
    pool: asyncpg.Pool,
    conversation_id: UUID,
    query: str,
    vessel_profile: dict | None,
    hedge_phrase: str,
    model_used: str,
    input_tokens: int,
    output_tokens: int,
    retrieved_chunks: list,
    cited: list[CitedRegulation],
    answer: str,
) -> None:
    """Insert a row into retrieval_misses for later analysis.

    Called when `detect_hedge(answer)` matched. Captures the full retrieval
    context (top-K chunks) plus what the model actually cited, so we can
    later see whether the miss was "nothing relevant retrieved" vs "right
    content retrieved but model still hedged" vs "retrieval gap under
    specific vessel/no-vessel configurations."
    """
    import json as _json

    # Resolve user_id from conversation (best-effort; DB constraint allows NULL).
    user_id = await pool.fetchval(
        "SELECT user_id FROM conversations WHERE id = $1", conversation_id,
    )

    def _chunk_get(c, key, default=None):
        # retrieve() yields dicts; be defensive in case this ever changes.
        if isinstance(c, dict):
            return c.get(key, default)
        return getattr(c, key, default)

    retrieved_payload = [
        {
            "source": _chunk_get(c, "source"),
            "section_number": _chunk_get(c, "section_number"),
            "section_title": (_chunk_get(c, "section_title") or "")[:200],
            "similarity": float(_chunk_get(c, "similarity", 0.0) or 0.0),
        }
        for c in retrieved_chunks
    ]
    cited_payload = [
        {
            "source": c.source,
            "section_number": c.section_number,
            "section_title": (c.section_title or "")[:200],
        }
        for c in cited
    ]

    await pool.execute(
        """
        INSERT INTO retrieval_misses (
            user_id, conversation_id, query,
            vessel_profile_set, vessel_profile,
            hedge_phrase_matched, model_used,
            input_tokens, output_tokens,
            retrieved_chunks, cited_regulations, answer_preview
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12)
        """,
        user_id,
        conversation_id,
        query,
        vessel_profile is not None,
        _json.dumps(vessel_profile) if vessel_profile is not None else None,
        hedge_phrase,
        model_used,
        input_tokens,
        output_tokens,
        _json.dumps(retrieved_payload),
        _json.dumps(cited_payload),
        answer[:2000],
    )


async def chat_with_progress(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    conversation_id: UUID,
    credential_context: str | None = None,
) -> AsyncIterator[dict]:
    """Same RAG pipeline as chat() but yields lightweight progress events.

    Yields dicts with shape:
        {"event": "status", "data": "<message to display>"}
        {"event": "done",   "data": {... full response payload as dict ...}}

    The done payload contains the same fields as the JSON serialization of
    ChatResponse, with conversation_id stringified for transport.
    """
    # Stage 1: Route
    yield {"event": "status", "data": "Analyzing your question…"}
    route = await route_query(query, anthropic_client)
    logger.info(f"Routed query to {route.model} (score={route.score})")

    # Stage 2: Retrieve
    source_labels = _describe_sources(query)
    yield {"event": "status", "data": f"Searching {source_labels}…"}
    chunks = await retrieve(
        query=query,
        pool=pool,
        openai_api_key=openai_api_key,
        vessel_profile=vessel_profile,
        limit=8,
    )
    logger.info(f"Retrieved {len(chunks)} chunks")

    # Stage 3: Build context
    context_str, cited = build_context(chunks)

    found_sources = _summarize_found_sources(chunks)
    if found_sources:
        yield {
            "event": "status",
            "data": f"Found {len(chunks)} relevant sections in {found_sources}",
        }
    else:
        yield {
            "event": "status",
            "data": f"Found {len(chunks)} relevant regulation sections",
        }

    # Stage 4: Construct messages and call Claude
    messages = _build_chat_messages(query, conversation_history, vessel_profile, context_str, credential_context)

    yield {"event": "status", "data": "Consulting compliance engine…"}
    model_used = route.model
    try:
        response = await anthropic_client.messages.create(
            model=route.model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
    except _CLAUDE_FAILURE_EXCEPTIONS as exc:
        logger.warning(
            "Claude API failed (%s: %s), falling back to OpenAI GPT-4o",
            type(exc).__name__,
            str(exc)[:200],
        )
        # Neutral status — never surface "Claude is down" to the user.
        yield {"event": "status", "data": "Processing your question…"}
        fallback_result = await fallback_chat(
            system_prompt=SYSTEM_PROMPT,
            messages=messages,
            max_tokens=_MAX_TOKENS,
            openai_api_key=openai_api_key,
        )
        answer = fallback_result["answer"]
        input_tokens = fallback_result["input_tokens"]
        output_tokens = fallback_result["output_tokens"]
        model_used = fallback_result["model"]
        logger.warning(
            "Fallback response received: %d input tokens, %d output tokens",
            input_tokens,
            output_tokens,
        )

    # Stage 5: Post-processing
    yield {"event": "status", "data": "Verifying citations…"}
    (
        cleaned_answer,
        verified_cited,
        all_unverified,
        vessel_update,
        regen_in,
        regen_out,
        regenerated,
    ) = await _finalize_answer(
        answer=answer,
        cited=cited,
        conversation_id=conversation_id,
        model_used=model_used,
        pool=pool,
        query=query,
        context_str=context_str,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
    )
    input_tokens += regen_in
    output_tokens += regen_out

    # Stage 6: Final event with the complete response
    yield {
        "event": "done",
        "data": {
            "answer": cleaned_answer,
            "cited_regulations": [
                {
                    "source": c.source,
                    "section_number": c.section_number,
                    "section_title": c.section_title,
                }
                for c in verified_cited
            ],
            "conversation_id": str(conversation_id),
            "model_used": model_used,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "unverified_citations": all_unverified,
            "vessel_update": vessel_update,
            "regenerated": regenerated,
        },
    }
