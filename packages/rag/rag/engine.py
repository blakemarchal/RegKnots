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
import time
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
from rag.followup import compose_followup_query, detect_followup
from rag.hedge import detect_hedge
from rag.query_distill import LENGTH_THRESHOLD_CHARS
from rag.models import ChatMessage, ChatResponse, CitedRegulation
from rag.prompts import (
    NAVIGATION_AID_REMINDER,
    SYSTEM_PROMPT,
    assemble_system_prompt,
)
from rag.retriever import retrieve, retrieve_enhanced
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
# Sprint D6.75 — Karynn report: complex Opus answers were truncating
# mid-word. Diagnostic confirmed three of her hazmat-fire responses
# were cut off at 1,300-1,400 output tokens, hitting the 2,048 cap
# before Opus could finish a multi-section ERG analysis. Bumped to
# 8,192 — gives Opus headroom for thorough cross-regulation answers
# while still bounding Anthropic API cost (~$0.60 worst case per
# Opus response, ~$0.12 worst case per Sonnet response). Real
# average output is much smaller; we only pay for what's generated.
_MAX_TOKENS = 8192

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

# Sprint D6.18 — UK MCA notices. The citation form the LLM emits should
# match the canonical section_number stored in the regulations table.
# Examples (all matched):
#   "MGN 71"                      → "MGN 71"
#   "MGN 71 (M+F)"                → "MGN 71 (M+F)"
#   "MGN 50 (M)"                  → "MGN 50 (M)"
#   "MSN 1676"                    → "MSN 1676"
#   "MSN 1676 Amendment 4"        → "MSN 1676 Amendment 4"
#   "(MSN 1790)"                  → "MSN 1790"
# Groups: (1) kind (MGN/MSN), (2) number, (3) suffix or None,
#         (4) amendment number or None.
_MCA_RE = re.compile(
    r"\(?(MGN|MSN)\s+(\d{1,4})"
    r"(?:\s*\(([MF](?:\+[MF])?)\))?"
    r"(?:\s+Amendment\s+(\d+))?"
    r"\)?",
    re.IGNORECASE,
)

_VESSEL_UPDATE_RE = re.compile(
    r"\[VESSEL_UPDATE\]\s*\n(.*?)\n\[/VESSEL_UPDATE\]",
    re.DOTALL,
)

# Sprint D6.16 — UN-number grounding verifier (Fix 5).
# Pairs with the retriever's bare-number bypass and the prompt's UN-NUMBER
# GROUNDING RULE. Catches the residual case where the LLM mentions a UN
# number that was NOT in any retrieved chunk and ALSO didn't apply the
# prompt-defined hedge — i.e., a confident hallucination from training-data
# memory that slipped past both retrieval and the system prompt.
_UN_IN_ANSWER_RE = re.compile(r"\b(UN|NA)[\s\-]?(\d{4})\b", re.IGNORECASE)
# Hedge phrases the system prompt instructs the model to use when it can't
# verify a UN-number. Matches the verbatim hedge plus reasonable variants
# the model may produce ("could not verify", "not in retrieved context").
_UN_HEDGE_PHRASE_RE = re.compile(
    r"did not retrieve|not in the retrieved|cannot verify|could not verify|"
    r"do not have (?:a |the )?verified entry|no verified entry",
    re.IGNORECASE,
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
            # CFR sections come in three shapes:
            #   1. Part only: "46 CFR 142"          — corpus has "46 CFR 142.X" rows
            #   2. Section with dot-subsection:
            #      "46 CFR 142.227"                 — corpus has the exact row
            #      OR sometimes parent of dot-sub-paragraphs ".227.X"
            #   3. Subpart with hyphen-subsection:
            #      "46 CFR 14.05"                   — corpus has "46 CFR 14.05-X" rows
            #      "46 CFR 14.05-1"                 — corpus has the exact row
            #
            # The 2026-05-09 audit shipped (1) and (2 exact). The 2026-05-09
            # PM eval surfaced (3) — model wrote "46 CFR 14.05" / "33 CFR 1.07"
            # but corpus indexes only "46 CFR 14.05-1" / "33 CFR 1.07-10" leaves.
            # Multiple candidate patterns now cover all three shapes — verifier
            # succeeds if ANY matches. False-positive risk is bounded because
            # each pattern is a strict prefix + boundary character.
            cands: list[tuple[str, str]] = []
            if "." not in section:
                # Part-only: "46 CFR 142" → match any "46 CFR 142.X" row
                cands.append((f"cfr_{title}", f"{display}.%"))
            else:
                # Section / subpart with dot. Try exact, dot-subparagraph,
                # AND hyphen-subsection (covers Subpart-style "14.05" → "14.05-1").
                cands.append((f"cfr_{title}", display))
                cands.append((f"cfr_{title}", f"{display}.%"))
                cands.append((f"cfr_{title}", f"{display}-%"))
            found[display] = _TextCitation(
                display=display,
                candidates=cands,
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

    # ── MSC resolutions (ambiguous across all IMO code sources) ────────────
    # IMO Maritime Safety Committee resolutions appear as section_number
    # suffixes across many sources, not just SOLAS / STCW supplements.
    # The 2026-05-08 audit found 6 of 12 eval F's were citations like
    # "MSC.370(93)" rejected because the verifier only checked
    # solas_supplement + stcw_supplement, while the corpus indexes the
    # resolution under "IMO IGC Code MSC.370(93)" (source: imo_igc),
    # "IMO HSC Code MSC.97(73)" (source: imo_hsc), etc. Listing every
    # IMO-family source explicitly keeps the per-source verification
    # path (the query plan stays cheap — each candidate becomes its
    # own EXISTS check).
    _MSC_SOURCE_FAMILY = (
        "solas_supplement",
        "stcw_supplement",
        "marpol_supplement",
        "ism_supplement",
        "imo_igc",
        "imo_hsc",
        "imo_ibc",
        "fss",
        "lsa",
    )
    for m in _MSC_RE.finditer(answer):
        msc_key = f"MSC.{m.group(1)}({m.group(2)})"
        if msc_key not in found:
            # Substring match (`%key%`) not end-anchored (`%key`). The
            # 2026-05-09 chapter-granularity work for IMO IGC/HSC made
            # section_numbers like "IMO IGC Code MSC.370(93) Ch.4", so
            # an end-anchored pattern stops matching after re-ingest.
            found[msc_key] = _TextCitation(
                display=msc_key,
                candidates=[(src, f"%{msc_key}%") for src in _MSC_SOURCE_FAMILY],
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
    # Models sometimes write NVIC numbers with a single-digit month
    # ("NVIC 1-86") while the corpus stores them zero-padded ("NVIC 01-86").
    # The 2026-05-09 eval V1/S-012 hit this. We try both forms in the
    # candidates list — the verifier succeeds if either matches.
    for m in _NVIC_RE.finditer(answer):
        num = m.group(1)
        sec = m.group(2)
        display = f"NVIC {num}"
        if sec:
            display += f" §{sec}"
        if display not in found:
            # Build canonical zero-padded variant if the model used 1-digit month
            month, year = num.split("-", 1)
            padded = f"{int(month):02d}-{year}" if len(month) == 1 else num
            cands = [("nvic", f"NVIC {num}%")]
            if padded != num:
                cands.append(("nvic", f"NVIC {padded}%"))
            found[display] = _TextCitation(
                display=display,
                candidates=cands,
            )

    # ── STCW Regulation ────────────────────────────────────────────────────
    for m in _STCW_REG_RE.finditer(answer):
        ch = m.group(1).upper()
        n = m.group(2)
        display = f"STCW Reg.{ch}/{n}"
        if display not in found:
            # Parent-range matching for sub-paragraph cites: "STCW Reg.I/9.5"
            # in the corpus is stored at "STCW Ch.I Reg.I/9" (sub-paragraph
            # 9.5 is content INSIDE that section, not a row of its own).
            # Same shape as the CFR parent-range fix (2026-05-09 sprint).
            # When n has a `.<digit>` suffix, strip it and match the parent.
            parent = n.split(".", 1)[0]
            if parent != n:
                # Try parent first; if no match the original LIKE will be tried below.
                candidates = [
                    ("stcw", f"STCW Ch.{ch} Reg.{ch}/{parent}%"),
                ]
            else:
                candidates = [("stcw", f"STCW Ch.{ch} Reg.{ch}/{n}%")]
            found[display] = _TextCitation(
                display=display,
                candidates=candidates,
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
    # Same parent-range matching as STCW — when the model writes a
    # sub-paragraph ("ISM 8.7"), the corpus indexes only the parent
    # clause ("ISM 8"). Strip dotted sub-paragraphs before LIKE-match.
    # The 2026-05-09 eval V1/S-020 (CO2 lockout) hit this.
    for m in _ISM_RE.finditer(answer):
        num = m.group(1)
        display = f"ISM {num}"
        if display not in found:
            parent = num.split(".", 1)[0]
            pattern = f"ISM {parent}%" if parent != num else f"ISM {num}%"
            found[display] = _TextCitation(
                display=display,
                candidates=[("ism", pattern)],
            )

    # ── UK MCA notices (MGN / MSN) — Sprint D6.18 ─────────────────────────
    # Verification uses LIKE patterns because the canonical
    # section_number ("MGN 71 (M+F)") is what's in the DB but the LLM
    # may cite without the suffix ("MGN 71") or with an Amendment tag.
    # The LIKE wildcards on either side accept any of those forms.
    for m in _MCA_RE.finditer(answer):
        kind = m.group(1).upper()        # MGN or MSN
        num = m.group(2)
        suffix = m.group(3)              # M / F / M+F or None
        amendment = m.group(4)           # "4" or None
        # Canonical display matches the LLM-emitted form.
        display = f"{kind} {num}"
        if suffix:
            display += f" ({suffix.upper()})"
        if amendment:
            display += f" Amendment {amendment}"
        if display not in found:
            source_code = f"mca_{kind.lower()}"
            # LIKE pattern: "MGN 71%" matches with or without suffix /
            # amendment in the stored section_number.
            found[display] = _TextCitation(
                display=display,
                candidates=[(source_code, f"{kind} {num}%")],
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


# ── Sprint post-D6.83 audit (2026-05-09) — Layer C UX inversion ──────────
#
# Inverts the surfaces when retrieval confidently failed AND web fallback
# confidently succeeded. Today's flow on a hard miss is:
#
#   - Main answer (synthesizer's confused attempt with hedge phrases like
#     "the retrieved context does not specify…")
#   - Side panel: "External reference — please verify" with the actually-
#     correct content the web fallback found
#
# That UX puts the wrong answer in the primary slot. The user has to
# notice the side panel and read it to get the right information.
# Inverted flow when conditions are met:
#
#   - Lead with the web fallback's content as a brief, framed answer
#   - Original synthesizer hedge moves to a "What I tried in our corpus"
#     disclosure footer
#   - web_fallback_card stays attached to the response — frontend can
#     render thumbs feedback + source link as before
#
# Eligibility: judge said complete_miss AND web_fallback returned with
# confidence ≥ 3. (Confidence 1-5 scale; ≥3 = decent enough that the
# inversion is more honest than the confused main answer.)
#
# Tracked in roadmap as "Layer C — UX inversion when retrieval miss is
# hard." Closes a chunk of the 35.7%/7d bad-answer rate by converting
# "user gets two contradicting answers" into "user gets one accurate
# answer with explicit honesty about the corpus gap."


# Layer C minimum eligibility threshold. confidence is on the 1-5 scale
# the synthesis LLM emits in citation_oracle / web fallback. 3 = decent.
_LAYER_C_MIN_CONFIDENCE = 3

# Verdicts that qualify as "retrieval failed hard enough that we should
# lead with the web answer." complete_miss is the unambiguous case.
# partial_miss is borderline — the corpus had SOME relevant content but
# the model still hedged hard. We include partial_miss when the web
# answer's confidence is ≥4 (very strong); otherwise the partial corpus
# context might be more useful than the web fallback.
_LAYER_C_TRIGGER_VERDICTS = {"complete_miss"}


def _should_apply_layer_c(
    judge_verdict: str | None,
    web_fallback_card: "WebFallbackCard | None",
) -> bool:
    """True when the eligibility conditions for Layer C inversion are met."""
    if web_fallback_card is None:
        return False
    if web_fallback_card.confidence < _LAYER_C_MIN_CONFIDENCE:
        return False
    if judge_verdict in _LAYER_C_TRIGGER_VERDICTS:
        return True
    # partial_miss with very strong web fallback (4-5) also qualifies.
    if judge_verdict == "partial_miss" and web_fallback_card.confidence >= 4:
        return True
    return False


def _apply_layer_c_inversion(
    original_answer: str,
    web_fallback_card: "WebFallbackCard",
) -> str:
    """Rewrite the answer to lead with the web fallback's content.

    The original synthesizer hedge is preserved as a small "What I tried
    in our corpus" footer so the user still sees the audit trail. The
    web answer becomes the primary content with explicit framing about
    the source.

    Format:

        I couldn't find this in our regulations corpus directly, but
        {domain} addresses it as follows:

        {summary}

        {quote_if_present}

        Source: {source_url}

        ---
        Note: the regulations corpus didn't contain a complete answer to
        this question. The above is from a trusted maritime source —
        verify against the linked source before relying on it for
        compliance-critical decisions.
    """
    parts: list[str] = []
    parts.append(
        f"I couldn't find this in our regulations corpus directly, but "
        f"**{web_fallback_card.source_domain}** addresses it as follows:"
    )
    parts.append("")
    parts.append(web_fallback_card.summary.strip())

    quote = (web_fallback_card.quote or "").strip()
    if quote:
        parts.append("")
        parts.append(f"> {quote}")

    parts.append("")
    parts.append(f"Source: {web_fallback_card.source_url}")
    parts.append("")
    parts.append("---")
    parts.append(
        "*Note: the regulations corpus didn't contain a complete answer to "
        "this question. The above is from a trusted maritime source — "
        "verify against the linked source before relying on it for "
        "compliance-critical decisions.*"
    )
    return "\n".join(parts)


def _verify_un_claims(answer: str, chunks: list[dict]) -> list[str]:
    """Sprint D6.16 — return UN numbers mentioned in `answer` that are not
    grounded in any retrieved chunk and are not hedged via the prompt-defined
    "did not retrieve" phrasing.

    A UN number is "grounded" if any retrieved chunk's full_text contains
    EITHER:
      * compact form  — "UN2734" / "UN-2734" / "UN 2734" (CFR storage style)
      * line-anchored — "2734" at the start of a line, optionally indented
        (IMDG / ERG tabular row storage style)

    We deliberately do NOT count bare 4-digit substrings appearing mid-line,
    since dates ("2024"), section numbers, paragraph references, etc. would
    produce false positives that mask real hallucinations.

    A UN number that is mentioned but ungrounded is acceptable iff the answer
    contains a hedge phrase (see `_UN_HEDGE_PHRASE_RE`) within 250 characters
    of the mention — that's the prompt-instructed escape hatch.

    Returns the list of UN numbers (e.g. ["2734", "1547"]) that should trigger
    a regeneration. Empty list means everything checked out.
    """
    if not answer:
        return []

    # Collect numbers as they appear in the answer along with their position.
    answer_mentions: list[tuple[str, int]] = []
    seen: set[str] = set()
    for m in _UN_IN_ANSWER_RE.finditer(answer):
        number = m.group(2)
        if number not in seen:
            seen.add(number)
            answer_mentions.append((number, m.start()))
    if not answer_mentions:
        return []

    hedge_positions = [m.start() for m in _UN_HEDGE_PHRASE_RE.finditer(answer)]

    ungrounded: list[str] = []
    for number, pos in answer_mentions:
        compact_re = re.compile(
            rf"\b(?:UN|NA)[\s\-]?{re.escape(number)}\b",
            re.IGNORECASE,
        )
        line_anchored_re = re.compile(rf"(?m)^\s*{re.escape(number)}\b")

        grounded = False
        for chunk in chunks:
            text = chunk.get("full_text") or ""
            if compact_re.search(text) or line_anchored_re.search(text):
                grounded = True
                break

        if grounded:
            continue

        # Ungrounded — but maybe the answer hedged. Accept any hedge phrase
        # within 250 chars of the UN-number mention as compliance with the
        # prompt-defined fallback.
        hedged = any(abs(pos - hp) <= 250 for hp in hedge_positions)
        if not hedged:
            ungrounded.append(number)

    return ungrounded


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
    conversation_title: str | None = None,
    fingerprint_summary: str | None = None,
    user_role: str | None = None,
    user_jurisdiction_focus: str | None = None,
    user_verbosity: str | None = None,
) -> list[dict]:
    """Construct the Claude API message list for a chat turn.

    Handles history truncation, vessel profile block construction, credential
    context injection, document extraction inclusion, and the final user
    message with retrieval context.

    Sprint D6.29/D6.30/D6.31 — `conversation_title`, `fingerprint_summary`,
    `user_role`, and `user_jurisdiction_focus` carry the layered soft
    jurisdictional priors documented in the SOFT JURISDICTIONAL CONTEXT
    section of the system prompt. All four are optional; the prompt rules
    only apply blocks that are populated.
    """
    history = conversation_history[-_MAX_HISTORY:]
    messages = [{"role": msg.role, "content": msg.content} for msg in history]
    messages = _trim_history_by_tokens(messages)

    vessel_block = ""
    if vessel_profile:
        lines = [f"- Name: {vessel_profile.get('vessel_name', 'Unknown')}"]
        if vessel_profile.get("vessel_type"):
            lines.append(f"- Type: {vessel_profile['vessel_type']}")
        # Sprint D6.17 — Flag state is the primary jurisdictional signal.
        # Always render it (even when "Unknown") so the LLM can apply the
        # AUTHORITY AND APPLICABILITY rules in the system prompt: U.S.-flag
        # vessels get CFR-led answers; non-U.S. flags get SOLAS-led answers
        # with CFR demoted; "Unknown" triggers a clarifying question.
        # Previously this field was loaded into the DB but never reached the
        # prompt — Rashad's Channel ferry got a 46 CFR-led answer because of
        # this gap.
        if vessel_profile.get("flag_state"):
            lines.append(f"- Flag state: {vessel_profile['flag_state']}")
        # Sprint D6.94 — class society. When set, AUTHORITY AND
        # APPLICABILITY routes class-society rules (ABS MVR / LR-RU-001 /
        # LR-CO-001 / DNV / etc.) by this value. An ABS-classed vessel's
        # binding construction + survey standard is ABS rules, not LR's
        # or DNV's; the synthesizer treats other societies as cross-
        # reference only.
        if vessel_profile.get("classification_society"):
            lines.append(
                f"- Class society: {vessel_profile['classification_society']}"
            )
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

    # Sprint D6.29 — soft jurisdictional context block. Each of the four
    # signals below is independent; render only those that are populated.
    # The system prompt's SOFT JURISDICTIONAL CONTEXT section describes how
    # to apply them with the priority order (current-query keywords beat
    # vessel profile beats chat title beats history beats fingerprint).
    soft_context_lines: list[str] = []
    if conversation_title:
        soft_context_lines.append(f"- Chat title: {conversation_title}")
    if user_role:
        soft_context_lines.append(f"- User role: {user_role}")
    if user_jurisdiction_focus:
        soft_context_lines.append(f"- User jurisdiction focus: {user_jurisdiction_focus}")
    if fingerprint_summary:
        soft_context_lines.append(f"- {fingerprint_summary}")
    soft_context_block = ""
    if soft_context_lines:
        soft_context_block = (
            "Soft jurisdictional context (use as priors when ambiguous; never override "
            "explicit current-query keywords or vessel profile):\n"
            + "\n".join(soft_context_lines) + "\n\n"
        )
        logger.info(
            "Including soft jurisdictional context: %d signals", len(soft_context_lines)
        )

    # Sprint D6.33/D6.34 — response style preference. Per-message override
    # ("verbosity" in the chat request body) is layered on top of the
    # user's persistent preference (users.verbosity_preference) by the
    # router; by the time we get here, user_verbosity is the effective
    # value to apply for this turn.
    verbosity_block = ""
    if user_verbosity == "brief":
        verbosity_block = (
            "Response style for THIS answer: BRIEF.\n"
            "- Aim for 2-3 focused paragraphs total.\n"
            "- Lead with the single most important citation.\n"
            "- Skip applicability tables and exhaustive subchapter breakdowns.\n"
            "- End with one short sentence offering to expand if the user wants more depth.\n\n"
        )
    elif user_verbosity == "detailed":
        verbosity_block = (
            "Response style for THIS answer: DETAILED.\n"
            "- The user values depth over brevity.\n"
            "- Provide thorough, sectioned answers with applicability tables when relevant.\n"
            "- Cover edge cases and cross-vessel-type variations.\n"
            "- Cite multiple sources where they reinforce or qualify each other.\n\n"
        )
    # "standard" or None → no verbosity block, system prompt's defaults apply.

    user_content = (
        f"{NAVIGATION_AID_REMINDER}\n\n"
        f"{vessel_block}"
        f"{credential_block}"
        f"{soft_context_block}"
        f"{verbosity_block}"
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
    ungrounded_un_numbers: list[str] | None = None,
) -> tuple[str, int, int] | None:
    """Call Claude (or the GPT-4o fallback) again with a corrective instruction.

    Returns (answer, input_tokens, output_tokens) or None if regeneration fails.
    Routes to whichever backend produced the original answer — if the first
    response came from the GPT-4o fallback, the regeneration goes there too.

    `ungrounded_un_numbers` carries Sprint D6.16 UN-grounding violations —
    UN numbers the model claimed an identity for without a supporting chunk.
    """
    instruction_parts: list[str] = []
    if unverified:
        instruction_parts.append(
            "Your previous answer referenced the following regulation sections that do not exist "
            "in our verified database:\n"
            + "\n".join(f"- {s}" for s in unverified)
        )
    if ungrounded_un_numbers:
        instruction_parts.append(
            "Your previous answer also stated facts about the following UN numbers WITHOUT "
            "any supporting chunk in the retrieved context:\n"
            + "\n".join(f"- UN {n}" for n in ungrounded_un_numbers)
            + "\n\nFor each UN number above, the verified context does NOT contain its proper "
            "shipping name, hazard class, packing group, or ERG Guide. Do NOT restate any "
            "attribute of these UN numbers from training-data memory. Instead, for each one, "
            "write the verbatim hedge from the system prompt's UN-NUMBER GROUNDING RULE."
        )
    corrective_instruction = (
        "\n\n".join(instruction_parts)
        + "\n\nRewrite your answer using ONLY the regulation context provided below. "
        "Do not reference any regulations or UN-number identities that are not explicitly "
        "present in the provided context. If you cannot fully answer the question with the "
        "verified context alone, say so honestly.\n\n"
        f"Verified regulation context:\n{context_str}\n\n"
        f"Original question: {query}"
    )
    messages = [{"role": "user", "content": corrective_instruction}]

    # If the original call used the GPT-4o fallback, regenerate via the same path.
    if model_used == FALLBACK_MODEL_ID:
        try:
            result = await fallback_chat(
                system_prompt=effective_system_prompt,
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
            system=effective_system_prompt,
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
                system=effective_system_prompt,
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
    chunks: list[dict] | None = None,
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

    # Sprint D6.16 Fix 5 — UN-claim grounding check. Catches the case where
    # the model produced a confident UN-number identity (e.g. "UN 2734 =
    # Aniline") without any retrieved chunk supporting it. Treats this like
    # an unverified citation: triggers the same regeneration path, with a
    # corrective instruction that lists the offending UN numbers.
    ungrounded_un = _verify_un_claims(answer, chunks or [])

    if not all_unverified and not ungrounded_un:
        return answer, verified_cited, [], vessel_update, 0, 0, False

    # DEFENSIVE LOG — WARNING level so it survives any future INFO-level
    # filtering and is unmissable in production when regeneration kicks in.
    # If this line isn't in the logs for a citation-error conversation,
    # either the code isn't actually deployed or control flow never reached
    # here. Either way it's the first thing to check next time.
    logger.warning(
        "REGEN: Entering regeneration — %d unverified citation(s): %s; "
        "%d ungrounded UN claim(s): %s",
        len(all_unverified),
        all_unverified,
        len(ungrounded_un),
        ungrounded_un,
    )

    # Log the ORIGINAL answer's bad citations for forensics, regardless of
    # whether regeneration ultimately succeeds. message_content is truncated
    # inside _log_citation_errors. Ungrounded UN-numbers are recorded in the
    # same table with a "UN <NUMBER> (ungrounded)" tag so existing dashboards
    # surface them alongside citation errors without a schema change.
    citation_log_entries = list(all_unverified) + [
        f"UN {n} (ungrounded)" for n in ungrounded_un
    ]
    if citation_log_entries:
        await _log_citation_errors(
            unverified=citation_log_entries,
            conversation_id=conversation_id,
            answer=answer,
            model_used=model_used,
            pool=pool,
        )

    logger.info(
        "Regenerating answer due to %d unverified citation(s) + %d ungrounded UN claim(s)",
        len(all_unverified),
        len(ungrounded_un),
    )
    regen = await _regenerate_answer(
        query=query,
        context_str=context_str,
        unverified=all_unverified,
        model_used=model_used,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
        ungrounded_un_numbers=ungrounded_un,
    )

    if regen is None:
        # Regeneration unavailable — fall back to the legacy strip + disclaim path.
        logger.warning("Regeneration failed; falling back to strip + disclaim")
        if all_unverified:
            answer = _strip_unverified_citations(answer, all_unverified)
        answer = answer + _UNVERIFIED_DISCLAIMER
        final_unverified = all_unverified + [
            f"UN {n} (ungrounded)" for n in ungrounded_un
        ]
        return answer, verified_cited, final_unverified, vessel_update, 0, 0, False

    new_answer, regen_in, regen_out = regen
    # Pull any (unlikely) VESSEL_UPDATE block from the regenerated answer; only
    # adopt it if the original turn didn't already produce one.
    new_answer, new_vessel_update = _extract_vessel_update(new_answer)
    if new_vessel_update and not vessel_update:
        vessel_update = new_vessel_update

    # Second pass: re-verify on the regenerated answer. Context cited list is
    # unchanged so its verification status carries over. Re-run UN-claim check
    # too — if the regen still hallucinates a UN identity, we want to know.
    new_text_citations = _extract_all_text_citations(new_answer)
    unverified_from_text_2 = await _verify_text_citations(new_text_citations, pool)
    all_unverified_2 = list(
        dict.fromkeys(unverified_from_context + unverified_from_text_2)
    )
    ungrounded_un_2 = _verify_un_claims(new_answer, chunks or [])

    if not all_unverified_2 and not ungrounded_un_2:
        logger.info("Regeneration complete — clean on second pass")
        return new_answer, verified_cited, [], vessel_update, regen_in, regen_out, True

    # Second attempt still has issues. Strip citation references and bail —
    # no recursive regeneration. UN-grounding violations are surfaced through
    # the unverified list (tagged form) but not stripped from text, since the
    # answer may still be useful with a disclaimer.
    logger.warning(
        "Regeneration complete — %d unverified citation(s) + %d ungrounded UN(s) remain: cites=%s un=%s",
        len(all_unverified_2),
        len(ungrounded_un_2),
        all_unverified_2,
        ungrounded_un_2,
    )
    if all_unverified_2:
        new_answer = _strip_unverified_citations(new_answer, all_unverified_2)
    new_answer = new_answer + _UNVERIFIED_DISCLAIMER
    final_unverified = all_unverified_2 + [
        f"UN {n} (ungrounded)" for n in ungrounded_un_2
    ]
    return (
        new_answer,
        verified_cited,
        final_unverified,
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
    conversation_title: str | None = None,
    fingerprint_summary: str | None = None,
    user_role: str | None = None,
    user_jurisdiction_focus: str | None = None,
    user_verbosity: str | None = None,
    user_id: UUID | None = None,
    subscription_tier: str | None = None,
    xai_api_key: str = "",
    web_fallback_enabled: bool = True,
    web_fallback_cosine_threshold: float = 0.5,
    web_fallback_daily_cap: int = 10,
    web_fallback_cascade_enabled: bool = True,
    hedge_judge_enabled: bool = True,
    query_rewrite_enabled: bool = False,
    reranker_enabled: bool = False,
    # Sprint D6.70 — Layer-2 citation-oracle intervention. Runs after the
    # judge confirms a miss but BEFORE the existing web fallback. If the
    # oracle locates the controlling citation in our corpus, we surface a
    # 'verified' tier card and skip the web fallback. Any failure path
    # falls through silently to the existing web fallback (additive-only
    # contract — never worse than today's behavior).
    citation_oracle_enabled: bool = True,
    # Sprint D6.71 — Hybrid BM25 + dense retrieval. Default OFF.
    # When True, retrieve_hybrid() runs in place of retrieve() inside
    # retrieve_enhanced(). All other layers (rewrite, rerank, title
    # boost, identifier/keyword merge, vessel filter) are unchanged.
    # Behavior with the flag OFF is bit-for-bit identical to today.
    hybrid_retrieval_enabled: bool = False,
    hybrid_rrf_k: int = 60,
    # Sprint D6.84 — confidence tier router. "off" | "shadow" | "live".
    # 'off' skips the router entirely (zero cost). 'shadow' computes the
    # decision and writes to tier_router_shadow_log without changing the
    # rendered answer. 'live' renders the router's decision and surfaces
    # tier_metadata to the frontend. See packages/rag/rag/tier_router.py.
    confidence_tiers_mode: str = "off",
    # Sprint D6.86 — run hedge judge on every cited answer (not just
    # when the regex matched). Captures partial-miss signal on softer
    # hedge prose like "does not specify". Web fallback firing is
    # NOT affected; this is purely data-collection for the tier router.
    judge_on_cited_enabled: bool = True,
    # Sprint D6.86 — instruct the synthesizer to lead with the practical
    # conclusion before vessel/regulatory framing. Helps mariners who
    # skim first paragraphs (Blake's gasket observation).
    lead_with_answer_enabled: bool = True,
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

    # Sprint D6.86 — assemble the synthesis system prompt once per
    # request. The lead-with-answer block is conditionally appended
    # based on the flag; defaults to on. Toggle off via env
    # LEAD_WITH_ANSWER_ENABLED=false if any regression appears.
    effective_system_prompt = assemble_system_prompt(
        lead_with_answer=lead_with_answer_enabled,
    )

    # D6.58 — off-topic gate. If the router classified the query as
    # off-topic (score=0), short-circuit before any retrieval / fallback
    # / ensemble fires. Apply daily-cap rate limiting and trigger admin
    # alerts on repeat abuse. See _handle_off_topic for the full policy.
    if route.is_off_topic:
        return await _handle_off_topic(
            pool=pool,
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
        )

    # Sprint D6.4 — conversational follow-up retrieval. If the new query
    # looks like a clarification or pushback ("So you can't tell me...",
    # "What about X?", "Are you sure?"), retrieve against the combined
    # prior-question + current-query so the embedding stays anchored to
    # the topic instead of drifting toward meta-discussion content.
    # Also escalate synthesis to Opus on the followup turn — these are
    # the moments where reasoning quality matters most.
    followup_match = detect_followup(query)
    retrieval_query = query
    if followup_match:
        prior_user_msg = next(
            (m.content for m in reversed(conversation_history) if m.role == "user"),
            None,
        )
        retrieval_query = compose_followup_query(prior_user_msg, query)
        logger.info(
            "Followup detected (pattern=%r); routing to %s with combined retrieval query",
            followup_match, REGENERATION_MODEL,
        )
    elif (
        len(conversation_history) == 0
        and len(query) > LENGTH_THRESHOLD_CHARS
    ):
        # Sprint D6.51 — verbose first-turn query distillation. Pre-
        # rewrite the query to its core regulatory question before
        # embedding, so retrieval can find the rule the user is
        # actually asking about. The original query still goes to the
        # generation prompt — only the embedding-input is distilled.
        # See packages/rag/rag/query_distill.py.
        from rag.query_distill import distill_query
        distilled = await distill_query(
            query=query,
            anthropic_client=anthropic_client,
            pool=pool,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if distilled:
            retrieval_query = distilled
            logger.info(
                "Distilled verbose first-turn query "
                "(orig=%dch, distilled=%dch): %r",
                len(query), len(distilled), distilled[:100],
            )

    # 2. Retrieve (D6.66 — multi-query rewrite + reranker + title-boost
    # via retrieve_enhanced when flags enabled; identical to retrieve()
    # when both off, so behavior is preserved on flag rollback).
    chunks = await retrieve_enhanced(
        query=retrieval_query,
        pool=pool,
        openai_api_key=openai_api_key,
        anthropic_client=anthropic_client,
        vessel_profile=vessel_profile,
        limit=8,
        query_rewrite_enabled=query_rewrite_enabled,
        reranker_enabled=reranker_enabled,
        hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        hybrid_rrf_k=hybrid_rrf_k,
    )
    logger.info(f"Retrieved {len(chunks)} chunks")

    # 3. Build context
    context_str, cited = build_context(chunks)

    # 4. Construct messages
    messages = _build_chat_messages(
        query, conversation_history, vessel_profile, context_str, credential_context,
        conversation_title=conversation_title,
        fingerprint_summary=fingerprint_summary,
        user_role=user_role,
        user_jurisdiction_focus=user_jurisdiction_focus,
        user_verbosity=user_verbosity,
    )

    # 5. Call Claude — fall back to OpenAI GPT-4o on Anthropic API failures.
    # Followup turns escalate to Opus regardless of route score (Sprint D6.4).
    model_used = REGENERATION_MODEL if followup_match else route.model
    try:
        response = await anthropic_client.messages.create(
            model=model_used,
            max_tokens=_MAX_TOKENS,
            system=effective_system_prompt,
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
            system_prompt=effective_system_prompt,
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
        chunks=chunks,
    )
    input_tokens += regen_in
    output_tokens += regen_out

    # Sprint D2-LOG: if the final answer hedges on retrieval, log the miss
    # to `retrieval_misses` for offline analysis. Fire-and-forget — DB
    # errors never fail the chat response.
    #
    # D6.60 — when hedge_judge_enabled, the regex match is just the
    # cheap pre-filter. We run a Haiku judge (~$0.004) on
    # (question, answer, retrieved chunks) to decide whether this is
    # a complete_miss, partial_miss, precision_callout, or false_hedge.
    # Only complete_miss + partial_miss fire the ensemble; precision
    # callouts and false hedges suppress.
    hedge_phrase = detect_hedge(cleaned_answer)
    regex_matched = hedge_phrase is not None
    web_fallback_card = None
    judge_verdict: str | None = None
    judge_reasoning: str | None = None
    judge_missing_topic: str | None = None
    chunks_truncated_for_judge = False

    # Sprint D6.86 — judge fires on EITHER (a) regex matched, OR (b)
    # judge_on_cited_enabled AND ≥1 verified citation. Path (b) catches
    # partial-misses on softer hedge prose ("does not specify..."). Web
    # fallback firing is still gated on regex match below (Phase 1
    # preserves legacy UX; Phase 2 may unlock fallback for cited
    # partial_miss).
    should_run_judge = hedge_judge_enabled and (
        regex_matched
        or (judge_on_cited_enabled and len(verified_cited) >= 1)
    )

    if should_run_judge:
        from rag.hedge_judge import judge_hedge
        # Sprint D6.92 — tell the judge which mode it's in so it can
        # apply the right decision rubric. The pre-D6.92 prompt assumed
        # every call was regex-triggered and biased toward finding a
        # hedge; that mis-rated three cited-confident answers as
        # complete_miss in May 2026. The new prompt switches rubric
        # based on this parameter.
        judge_mode = "regex_triggered" if regex_matched else "precautionary"
        try:
            verdict = await judge_hedge(
                question=query,
                answer=cleaned_answer,
                chunks=chunks,
                citations=[
                    {"source": c.source, "section_number": c.section_number,
                     "section_title": c.section_title}
                    for c in verified_cited
                ],
                anthropic_client=anthropic_client,
                mode=judge_mode,
            )
            judge_verdict = verdict.verdict
            judge_reasoning = verdict.reasoning or None
            judge_missing_topic = verdict.missing_topic
            chunks_truncated_for_judge = verdict.chunks_truncated
        except Exception as exc:
            logger.warning(
                "hedge_judge unexpected failure: %s: %s",
                type(exc).__name__, str(exc)[:200],
            )
            # Fail-safe default ONLY on the regex-matched path
            # (preserves legacy fire-the-ensemble behavior on judge
            # errors). For judge-on-cited invocations with no regex
            # match, leave verdict=None so we don't false-fire web
            # fallback or false-demote a Tier 1 answer.
            if regex_matched:
                judge_verdict = "complete_miss"
    elif regex_matched and not hedge_judge_enabled:
        # Judge disabled but regex matched: behave like the legacy
        # regex-only path (every regex hit fires fallback).
        judge_verdict = "complete_miss"

    if regex_matched:
        # Log to retrieval_misses on the regex-matched path only.
        # retrieval_misses semantics are "regex matched, here's what
        # happened next" — D6.86 judge-on-cited invocations skip the
        # log to avoid polluting the existing analytics surface.
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
                judge_verdict=judge_verdict,
                judge_reasoning=judge_reasoning,
                judge_missing_topic=judge_missing_topic,
                chunks_truncated_for_judge=chunks_truncated_for_judge,
            )
        except Exception as exc:
            logger.warning(
                "retrieval_miss log failed (non-fatal): %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )

        # Fire fallback only on miss verdicts AND only on the regex-
        # matched path (D6.86 Phase 1 — see comment above). Tier 2
        # ships in Phase 2 to handle the cited-partial-miss case.
        should_fire_fallback = judge_verdict in ("complete_miss", "partial_miss")
        if web_fallback_enabled and should_fire_fallback:
            top_cosine = (
                chunks[0].get("similarity", 0.0) if chunks else 0.0
            )
            # partial_miss → swap query to the focused missing topic so
            # the ensemble searches for the gap, not the whole question.
            override_query: str | None = None
            if judge_verdict == "partial_miss" and judge_missing_topic:
                override_query = judge_missing_topic
                logger.info(
                    "hedge_judge partial_miss: overriding ensemble query "
                    "from %r to %r", query[:80], override_query,
                )

            # Sprint D6.70 — Layer-2 citation-oracle intervention. Try
            # the web-routing → corpus-answering split BEFORE falling
            # back to the existing web ensemble. On any failure the
            # function returns None and we fall through to the
            # existing _dispatch_web_fallback below.
            if citation_oracle_enabled:
                try:
                    web_fallback_card = await _try_citation_oracle_intervention(
                        query=query,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        pool=pool,
                        anthropic_client=anthropic_client,
                        top_cosine=top_cosine,
                    )
                except Exception as exc:
                    logger.warning(
                        "citation_oracle intervention failed (non-fatal): %s: %s",
                        type(exc).__name__, str(exc)[:200],
                    )
                    web_fallback_card = None

            if web_fallback_card is None:
                try:
                    web_fallback_card = await _dispatch_web_fallback(
                        query=query,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        subscription_tier=subscription_tier,
                        pool=pool,
                        anthropic_client=anthropic_client,
                        openai_api_key=openai_api_key,
                        xai_api_key=xai_api_key,
                        top_cosine=top_cosine,
                        cosine_threshold=web_fallback_cosine_threshold,
                        daily_cap=web_fallback_daily_cap,
                        cascade_enabled=web_fallback_cascade_enabled,
                        override_query=override_query,
                        judge_verdict=judge_verdict,
                        judge_missing_topic=judge_missing_topic,
                    )
                except Exception as exc:
                    logger.warning(
                        "web fallback failed (non-fatal): %s: %s",
                        type(exc).__name__,
                        str(exc)[:200],
                    )
        elif not should_fire_fallback:
            logger.info(
                "hedge_judge suppressed fallback: verdict=%s reasoning=%r",
                judge_verdict, (judge_reasoning or "")[:200],
            )

        # 4. Sprint D6.58 Slice 2 hedge classifier — fires on every
        # hedge regardless of judge verdict. Different from the judge:
        # the classifier categorizes corpus failures (VOCAB / INTENT /
        # RANKING / etc.) for sprint planning, the judge decides
        # real-time fire/skip. Both pieces of data are useful.
        try:
            await _classify_and_persist_hedge(
                pool=pool,
                conversation_id=conversation_id,
                user_id=user_id,
                query=query,
                vessel_profile=vessel_profile,
                retrieved=chunks,
                hedge_text=cleaned_answer,
                anthropic_client=anthropic_client,
                web_fallback_card=web_fallback_card,
            )
        except Exception as exc:
            logger.warning(
                "hedge audit failed (non-fatal): %s: %s",
                type(exc).__name__, str(exc)[:200],
            )

    # Layer C — UX inversion when retrieval failed hard and web fallback
    # got a confident answer. Rewrites cleaned_answer to lead with the
    # web content rather than the synthesizer's hedged miss + side panel.
    # See _apply_layer_c_inversion for the framing format and rationale.
    layer_c_fired = False
    if _should_apply_layer_c(judge_verdict, web_fallback_card):
        logger.info(
            "Layer C: inverting answer surface (verdict=%s web_confidence=%d)",
            judge_verdict, web_fallback_card.confidence,
        )
        cleaned_answer = _apply_layer_c_inversion(cleaned_answer, web_fallback_card)
        layer_c_fired = True

    # Sprint D6.84 — confidence tier router. Wraps everything in
    # try/except internally; on any failure, returns the original answer
    # and None metadata so today's behavior is preserved exactly.
    tier_metadata = None
    if confidence_tiers_mode in ("shadow", "live"):
        cleaned_answer, tier_metadata = await _run_tier_router_and_log(
            pool=pool,
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
            mode=confidence_tiers_mode,
            cleaned_answer_pre_tier=cleaned_answer,
            layer_c_fired=layer_c_fired,
            judge_verdict=judge_verdict,
            judge_reasoning=judge_reasoning,
            web_fallback_card=web_fallback_card,
            verified_citations_count=len(verified_cited),
            anthropic_client=anthropic_client,
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
        web_fallback=web_fallback_card,
        tier_metadata=tier_metadata,
    )


async def _try_citation_oracle_intervention(
    *,
    query: str,
    conversation_id: UUID,
    user_id: "UUID | None",
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    top_cosine: float,
) -> "WebFallbackCard | None":
    """Sprint D6.70 — Layer-2 retrieval intervention.

    Splits the routing problem from the answering problem:
      1. Web identifies the citation (Haiku + web_search → e.g., "46 CFR 138.305").
      2. We look up that section in OUR corpus.
      3. Sonnet synthesizes a verbatim-quote-anchored answer using
         only that corpus chunk.
      4. Surface as a 'verified' tier card — strictly higher trust
         than today's 'reference' web-fallback yellow card because
         the source IS our verified corpus, not external content.

    Returns None on any failure path. Caller MUST treat None as
    "fall through to existing _dispatch_web_fallback" — never as
    a final negative answer. This is the additive-only contract.

    Failure paths (all degrade gracefully):
      - oracle returned no citation       → None
      - citation not parseable            → None
      - citation not in our corpus        → None (try alt_citations first)
      - synthesis Sonnet call failed      → None
      - synthesized answer hedged itself  → None (let web fallback try)
    """
    from rag.citation_oracle import find_citation_hint
    from rag.retriever import fetch_chunks_by_citation
    from rag.models import WebFallbackCard

    # Step 1 — ask the web what citation answers this.
    hint = await find_citation_hint(query=query, anthropic_client=anthropic_client)
    if not hint.has_citation:
        logger.info("citation_oracle: no citation hint, deferring to web fallback")
        return None

    # Step 2 — try to resolve the citation in OUR corpus. Walk the
    # primary citation first; if not found, try alternates in order.
    corpus_chunks: list[dict] = []
    matched_citation: str | None = None
    for citation in [hint.primary_citation, *hint.alt_citations]:
        if not citation:
            continue
        try:
            corpus_chunks = await fetch_chunks_by_citation(
                pool=pool, citation=citation, limit=6,
            )
        except Exception as exc:
            logger.warning(
                "citation_oracle: fetch_chunks_by_citation(%r) failed: %s",
                citation, exc,
            )
            continue
        if corpus_chunks:
            matched_citation = citation
            break

    if not corpus_chunks or not matched_citation:
        logger.info(
            "citation_oracle: hint=%r not in corpus; alt=%s also not found",
            hint.primary_citation, hint.alt_citations,
        )
        return None

    # Step 3 — synthesize a focused answer from the corpus chunks.
    # Single Sonnet call with a constrained prompt: read these chunks,
    # quote verbatim, return JSON with the same shape as
    # web_fallback's FallbackResult so the persistence layer below
    # treats it identically.
    chunks_block = "\n\n".join(
        f"[{i + 1}] {c.get('section_number')} — {c.get('section_title') or ''}\n"
        f"{(c.get('full_text') or c.get('text') or '')[:2000]}"
        for i, c in enumerate(corpus_chunks[:5])
    )
    user_payload = (
        f"USER QUESTION:\n{query[:1500]}\n\n"
        f"CORPUS PASSAGES (matched citation: {matched_citation}):\n{chunks_block}\n\n"
        f"Produce the JSON. Quote verbatim from the matched citation."
    )
    synthesis_prompt = (
        "You are RegKnots' citation-oracle answerer. The user's question hedged on initial corpus "
        "retrieval. A separate web search has identified the controlling section, and we've pulled "
        "the verbatim text from our verified corpus. Your job is to answer the question using ONLY "
        "the supplied corpus passages, anchored on a verbatim quote from the matched section.\n\n"
        "Output JSON only — no prose, no markdown fences:\n\n"
        "{\n"
        '  "confidence": 1-5 (5 = certain, 1 = guessing),\n'
        '  "answer":     "direct answer to the user\'s question, anchored on the quote",\n'
        '  "summary":    "≤200 words plain-English explanation",\n'
        '  "quote":      "verbatim string from the corpus passage",\n'
        '  "section":    "the matched section number"\n'
        "}\n\n"
        "Hard rules: quote MUST be verbatim from a corpus passage above; do not invent. If the "
        "passages don't actually answer the question, return confidence ≤ 2."
    )
    try:
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=synthesis_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", None) == "text"
        )
    except Exception as exc:
        logger.warning(
            "citation_oracle synthesis failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return None

    # Parse synthesized JSON (re-use the tolerant parser pattern).
    import json as _json
    import re as _re
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = _re.sub(r"\s*```$", "", cleaned)
    parsed = None
    try:
        parsed = _json.loads(cleaned)
    except _json.JSONDecodeError:
        m = _re.search(r"\{.*\}", cleaned, flags=_re.DOTALL)
        if m:
            try:
                parsed = _json.loads(m.group(0))
            except _json.JSONDecodeError:
                parsed = None
    if parsed is None:
        logger.warning(
            "citation_oracle synthesis returned no JSON: %s", text[:200],
        )
        return None

    confidence = int(parsed.get("confidence") or 0)
    quote = (parsed.get("quote") or "").strip()
    answer_text = (parsed.get("answer") or "").strip()
    summary = (parsed.get("summary") or "").strip()
    section = (parsed.get("section") or matched_citation).strip()

    # Verify the quote is actually present in one of the corpus chunks.
    # If it's not — Sonnet drifted off-source — refuse to surface.
    quote_verified = False
    if quote:
        for c in corpus_chunks:
            corpus_text = (c.get("full_text") or c.get("text") or "").lower()
            if quote.lower() in corpus_text:
                quote_verified = True
                break

    # Confidence floor: don't surface if the synthesis itself wasn't
    # confident or the quote didn't verify against corpus.
    if confidence < 3 or not quote_verified:
        logger.info(
            "citation_oracle: synthesis confidence=%d quote_verified=%s — not surfacing",
            confidence, quote_verified,
        )
        return None

    # Step 4 — persist + return as a 'verified' tier card. Persisted
    # exactly like a web_fallback row so the audit page shows it
    # alongside other fallback events; source_domain marks it as
    # corpus-backed for differentiation.
    fallback_id: str | None = None
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO web_fallback_responses
              (is_calibration, is_ensemble, user_id, chat_message_id, query,
               web_query_used,
               confidence, source_url, source_domain, quote_text,
               quote_verified, surfaced, surface_tier,
               surface_blocked_reason, answer_text, latency_ms,
               retrieval_top1_cosine)
            VALUES (FALSE, FALSE, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15)
            RETURNING id
            """,
            user_id, conversation_id, query,
            f"oracle:{matched_citation}",
            confidence,
            None,                                   # no external source_url
            "regknots-corpus",                      # distinctive marker
            quote,
            True,                                   # quote_verified above
            True,                                   # surfaced
            "verified",                             # tier — corpus-backed
            None,
            answer_text or summary,
            0,                                      # latency tracking TBD
            top_cosine,
        )
        if row is not None:
            fallback_id = str(row["id"])
    except Exception as exc:
        logger.warning("citation_oracle persist failed (non-fatal): %s", exc)

    logger.info(
        "citation_oracle SUCCESS: %r → corpus[%s] quote_verified=%s confidence=%d",
        query[:80], section, quote_verified, confidence,
    )

    return WebFallbackCard(
        fallback_id=fallback_id or "",
        source_url="",                              # corpus-backed; no URL
        source_domain="regknots-corpus",
        quote=quote,
        summary=summary or answer_text,
        confidence=confidence,
        surface_tier="verified",
    )


async def _dispatch_web_fallback(
    *,
    query: str,
    conversation_id: UUID,
    user_id: UUID | None,
    subscription_tier: str | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    xai_api_key: str,
    top_cosine: float,
    cosine_threshold: float,
    daily_cap: int,
    cascade_enabled: bool = True,
    override_query: str | None = None,
    judge_verdict: str | None = None,
    judge_missing_topic: str | None = None,
) -> "WebFallbackCard | None":
    """Tier-aware fallback dispatcher (D6.58 Slice 3).

    Decision tree:
      1. If user has Big-3 ensemble cap remaining for their tier
         AND xAI key is configured AND user_id is known →
         fire ensemble (parallel Claude+GPT+Grok web search +
         synthesis). Surfaces as 'verified' / 'consensus' /
         'reference' / 'blocked' per the synthesizer's verdict.
      2. Else → fall back to single-LLM (Slice 1) path. Surfaces as
         'verified' / 'reference' / 'blocked'.

    The ensemble strictly subsumes the single-LLM path — Claude with
    web search is one of its three providers — so we never fire both.
    """
    # Anonymous users → single-LLM path only (no ensemble for unauth).
    # User with empty xAI key → single-LLM (xAI couldn't fire anyway).
    if user_id is None or not xai_api_key:
        return await _try_web_fallback(
            query=query, conversation_id=conversation_id, user_id=user_id,
            pool=pool, anthropic_client=anthropic_client,
            top_cosine=top_cosine, cosine_threshold=cosine_threshold,
            daily_cap=daily_cap,
            override_query=override_query,
            judge_verdict=judge_verdict,
            judge_missing_topic=judge_missing_topic,
        )

    # Per-tier ensemble cap check.
    from rag.ensemble_fallback import is_under_ensemble_cap
    try:
        allowed, used, cap = await is_under_ensemble_cap(
            pool=pool, user_id=user_id,
            subscription_tier=subscription_tier or "free",
        )
    except Exception as exc:
        logger.warning("ensemble cap check failed: %s — falling back", exc)
        allowed = False
        used = 0
        cap = 0

    if not allowed:
        logger.info(
            "ensemble cap reached for user %s tier=%s (used %d/%d) — single-LLM fallback",
            user_id, subscription_tier, used, cap,
        )
        return await _try_web_fallback(
            query=query, conversation_id=conversation_id, user_id=user_id,
            pool=pool, anthropic_client=anthropic_client,
            top_cosine=top_cosine, cosine_threshold=cosine_threshold,
            daily_cap=daily_cap,
            override_query=override_query,
            judge_verdict=judge_verdict,
            judge_missing_topic=judge_missing_topic,
        )

    # Big-3 ensemble path.
    return await _try_ensemble_fallback(
        query=query, conversation_id=conversation_id, user_id=user_id,
        pool=pool, anthropic_client=anthropic_client,
        openai_api_key=openai_api_key, xai_api_key=xai_api_key,
        top_cosine=top_cosine,
        cascade_enabled=cascade_enabled,
        override_query=override_query,
        judge_verdict=judge_verdict,
        judge_missing_topic=judge_missing_topic,
    )


async def _try_ensemble_fallback(
    *,
    query: str,
    conversation_id: UUID,
    user_id: UUID,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    xai_api_key: str,
    top_cosine: float,
    cascade_enabled: bool = True,
    override_query: str | None = None,
    judge_verdict: str | None = None,
    judge_missing_topic: str | None = None,
) -> "WebFallbackCard | None":
    """Run the Big-3 ensemble + persist + return a card if surfaced.

    Logs to web_fallback_responses with is_ensemble=TRUE so per-tier
    cap accounting works on subsequent calls. Caller already verified
    the user is under cap.

    When cascade_enabled is True (D6.59 default), uses the cost-aware
    cascading orchestrator that probes Claude alone first and only fans
    out to GPT + Grok when needed. When False, uses the legacy always-
    parallel D6.58 Slice-3 orchestrator. The two share the same DB
    persistence shape so flipping the flag has no schema impact.

    D6.60 — when judge_verdict is 'partial_miss', override_query is the
    focused topic the judge identified as missing. We send THAT to the
    LLMs but persist the user's original query in `query` (preserving
    audit linkage to the actual chat turn) and the override in
    `web_query_used`.
    """
    from rag.ensemble_fallback import (
        attempt_cascade_ensemble,
        attempt_ensemble_fallback,
    )
    from rag.models import WebFallbackCard

    # Use override_query for the actual LLM calls; keep `query` as the
    # canonical user-facing question for persistence + audit.
    llm_query = override_query or query

    if cascade_enabled:
        result = await attempt_cascade_ensemble(
            query=llm_query,
            anthropic_client=anthropic_client,
            openai_api_key=openai_api_key,
            xai_api_key=xai_api_key,
        )
    else:
        result = await attempt_ensemble_fallback(
            query=llm_query,
            anthropic_client=anthropic_client,
            openai_api_key=openai_api_key,
            xai_api_key=xai_api_key,
        )

    fallback_id: str | None = None
    try:
        import json as _json
        row = await pool.fetchrow(
            """
            INSERT INTO web_fallback_responses
              (is_calibration, is_ensemble, user_id, chat_message_id, query,
               web_query_used,
               confidence, source_url, source_domain, quote_text,
               quote_verified, surfaced, surface_tier, surface_blocked_reason,
               answer_text, latency_ms, retrieval_top1_cosine,
               ensemble_providers, ensemble_agreement_count, provider_errors,
               judge_verdict, judge_missing_topic)
            VALUES (FALSE, TRUE, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16::text[], $17, $18::jsonb,
                    $19, $20)
            RETURNING id
            """,
            user_id, conversation_id, query,
            override_query,
            result.best_confidence, result.best_source_url,
            result.best_source_domain, result.best_quote,
            result.best_quote_verified, result.surfaced,
            result.surface_tier, result.surface_blocked_reason,
            result.best_answer, result.latency_ms, top_cosine,
            result.providers_succeeded or [],
            result.agreement_count,
            _json.dumps(result.provider_errors or {}),
            judge_verdict, judge_missing_topic,
        )
        if row is not None:
            fallback_id = str(row["id"])
    except Exception as exc:
        logger.warning("ensemble persist failed (non-fatal): %s", exc)

    if not result.surfaced:
        return None

    return WebFallbackCard(
        fallback_id=fallback_id or "",
        source_url=result.best_source_url or "",
        source_domain=result.best_source_domain or "",
        quote=result.best_quote or "",
        summary=result.best_summary or result.best_answer or "",
        confidence=result.best_confidence or 0,
        surface_tier=result.surface_tier,
    )


async def _try_web_fallback(
    *,
    query: str,
    conversation_id: UUID,
    user_id: UUID | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    top_cosine: float,
    cosine_threshold: float,
    daily_cap: int,
    override_query: str | None = None,
    judge_verdict: str | None = None,
    judge_missing_topic: str | None = None,
) -> "WebFallbackCard | None":
    """Run one fallback attempt for a hedged answer. Returns a populated
    card iff all gates pass. Persists every attempt to
    web_fallback_responses regardless of outcome.

    D6.58 force-fire-on-hedge revision:
      The caller only invokes this function when the model already
      hedged (engine.py: `if hedge_phrase is not None`). The hedge IS
      the authoritative signal that retrieval missed — the model has
      seen the chunks and decided they don't answer. Cosine is a
      noisy proxy for that decision (high cosine on adjacent topics
      is a common failure mode — Brandon's rescue-boat-drill query,
      Karynn's engine-room-signal-column query both had top_cosine
      ≥ 0.6 on irrelevant chunks).
      So we no longer pre-gate on cosine. We always TRY a fallback
      when the model hedged. top_cosine is still recorded on the
      attempt row for analysis. Cost is bounded by per-user daily
      cap below + per-tier monthly caps (Slice 3).
    """
    from rag.web_fallback import attempt_web_fallback
    from rag.models import WebFallbackCard

    # Gate: per-user daily cap (soft block — silently skip rather than
    # error). Only count surfaced fallbacks toward the cap so users who
    # ask many corpus-gap questions in a row don't get capped on
    # blocked-but-attempted ones.
    if user_id is not None and daily_cap > 0:
        try:
            count_today = await pool.fetchval(
                "SELECT COUNT(*) FROM web_fallback_responses "
                "WHERE user_id = $1 AND surfaced = TRUE "
                "AND is_calibration = FALSE "
                "AND created_at > NOW() - INTERVAL '24 hours'",
                user_id,
            )
            if (count_today or 0) >= daily_cap:
                logger.info(
                    "web_fallback daily cap reached for user %s "
                    "(%d/%d)", user_id, count_today, daily_cap,
                )
                return None
        except Exception as exc:
            logger.warning("web_fallback cap check failed: %s", exc)

    # D6.60 — partial_miss verdict overrides the LLM-side query but
    # leaves user-facing query intact for audit + persistence.
    llm_query = override_query or query
    result = await attempt_web_fallback(
        query=llm_query, anthropic_client=anthropic_client,
    )

    # Persist (fire-and-forget — DB errors don't suppress the card if
    # we managed to assemble one). top_cosine + surface_tier recorded
    # on the attempt row so the admin tools see the full state.
    fallback_id: str | None = None
    try:
        # web_query_used: prefer override_query (D6.60 partial_miss
        # focused topic) over what attempt_web_fallback returned. The
        # latter is just an internal fallback-side reformulation; the
        # former is the judge's verdict on what's actually missing.
        web_query_for_audit = override_query or result.web_query_used
        row = await pool.fetchrow(
            "INSERT INTO web_fallback_responses "
            "  (is_calibration, is_ensemble, user_id, chat_message_id, query, "
            "   web_query_used, top_urls, confidence, source_url, "
            "   source_domain, quote_text, quote_verified, surfaced, "
            "   surface_tier, surface_blocked_reason, answer_text, "
            "   latency_ms, retrieval_top1_cosine, "
            "   judge_verdict, judge_missing_topic) "
            "VALUES (FALSE, FALSE, $1, $2, $3, $4, $5::text[], $6, $7, $8, "
            "        $9, $10, $11, $12, $13, $14, $15, $16, $17, $18) "
            "RETURNING id",
            user_id, conversation_id, query, web_query_for_audit,
            result.top_urls or [], result.confidence,
            result.source_url, result.source_domain, result.quote_text,
            result.quote_verified, result.surfaced,
            result.surface_tier,
            result.surface_blocked_reason, result.answer_text,
            result.latency_ms,
            top_cosine,
            judge_verdict, judge_missing_topic,
        )
        if row is not None:
            fallback_id = str(row["id"])
    except Exception as exc:
        logger.warning("web_fallback persist failed (non-fatal): %s", exc)

    if not result.surfaced:
        return None

    # All gates passed (verified or reference tier) — assemble the
    # yellow-card payload for the UI. Tier propagates so the renderer
    # picks the right badge + language.
    return WebFallbackCard(
        fallback_id=fallback_id or "",
        source_url=result.source_url or "",
        source_domain=result.source_domain or "",
        quote=result.quote_text or "",
        summary=result.answer_text or "",
        confidence=result.confidence or 0,
        surface_tier=result.surface_tier,
    )


# ── Off-topic gate (D6.58 prelude) ────────────────────────────────────────


_OFF_TOPIC_DAILY_FLAG_THRESHOLD = 10  # admin sees flag at this count
_OFF_TOPIC_DAILY_CAP            = 25  # 26th query returns rate-limit message
_OFF_TOPIC_ABUSE_DAY_THRESHOLD  = 3   # cap-days/30 that trigger admin email

_OFF_TOPIC_REFUSAL = (
    "I'm focused on maritime compliance — vessel operations, CFR Titles 33/46/49, "
    "SOLAS, STCW, IMDG, ISM, port-state regulations, your boat's certifications, "
    "and the workflows around them. Ask me about anything in that domain and "
    "I'll cite chapter and verse.\n\n"
    "I won't help with general topics like cooking, entertainment, programming, "
    "or casual chat — there are better tools for those."
)

_OFF_TOPIC_RATE_LIMITED = (
    "You've hit today's limit for off-topic questions (25 in 24 hours). "
    "I'll be available for off-topic questions again tomorrow.\n\n"
    "Maritime compliance questions still work — ask me about vessel "
    "regulations, certifications, or operations and I'll respond as usual."
)


async def _count_off_topic_today(pool, user_id) -> int:
    """How many off-topic queries this user has already logged today (UTC)."""
    if user_id is None:
        return 0
    return int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM off_topic_queries "
            "WHERE user_id = $1 "
            "  AND created_at > date_trunc('day', NOW() AT TIME ZONE 'UTC')",
            user_id,
        )
        or 0
    )


async def _count_capped_days_last_30(pool, user_id) -> int:
    """Distinct days in the last 30 where this user hit the daily cap."""
    if user_id is None:
        return 0
    return int(
        await pool.fetchval(
            """
            SELECT COUNT(*) FROM (
                SELECT date_trunc('day', created_at AT TIME ZONE 'UTC') AS d
                FROM off_topic_queries
                WHERE user_id = $1
                  AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY 1
                HAVING COUNT(*) >= $2
            ) capped_days
            """,
            user_id, _OFF_TOPIC_DAILY_CAP,
        )
        or 0
    )


async def _log_off_topic_query(
    *, pool, user_id, conversation_id, query: str,
) -> None:
    """Insert one row into off_topic_queries. Best-effort."""
    try:
        await pool.execute(
            "INSERT INTO off_topic_queries "
            "  (user_id, conversation_id, query) "
            "VALUES ($1, $2, $3)",
            user_id, conversation_id, query[:2000],
        )
    except Exception as exc:
        logger.warning("off_topic_queries insert failed: %s", exc)


async def _maybe_send_abuse_alert(
    *, pool, user_id, today_count: int,
) -> None:
    """If the user just crossed their 3rd cap-day in 30 days, email Owner.

    Only fires when this is the FIRST query in this session that put them
    at-or-over the cap (today_count == _OFF_TOPIC_DAILY_CAP exactly).
    Prevents resending on every query past the cap.
    """
    if today_count != _OFF_TOPIC_DAILY_CAP:
        return
    capped_days = await _count_capped_days_last_30(pool, user_id)
    if capped_days < _OFF_TOPIC_ABUSE_DAY_THRESHOLD:
        return
    try:
        user_row = await pool.fetchrow(
            "SELECT email, full_name FROM users WHERE id = $1", user_id,
        )
        if user_row is None:
            return
        from app.email import send_off_topic_abuse_alert
        await send_off_topic_abuse_alert(
            user_email=user_row["email"],
            user_full_name=user_row["full_name"] or "",
            capped_days=capped_days,
        )
    except Exception as exc:
        logger.warning("off_topic abuse alert email failed: %s", exc)


async def _handle_off_topic(
    *,
    pool,
    user_id,
    conversation_id,
    query: str,
) -> "ChatResponse":
    """Non-streaming off-topic short-circuit. Returns a polite refusal
    or rate-limit message and persists the event.
    """
    today_count = await _count_off_topic_today(pool, user_id)

    if today_count >= _OFF_TOPIC_DAILY_CAP:
        # Already capped today — reply with rate-limit, do not log
        # (cap is hit, no need to keep ratcheting; user_id is on the
        # record from the cap-hit event).
        return ChatResponse(
            answer=_OFF_TOPIC_RATE_LIMITED,
            conversation_id=conversation_id,
            cited_regulations=[],
            model_used="claude-haiku-4-5-20251001",
            input_tokens=0,
            output_tokens=0,
        )

    # Log this off-topic query.
    await _log_off_topic_query(
        pool=pool, user_id=user_id,
        conversation_id=conversation_id, query=query,
    )
    new_today = today_count + 1
    await _maybe_send_abuse_alert(
        pool=pool, user_id=user_id, today_count=new_today,
    )

    return ChatResponse(
        answer=_OFF_TOPIC_REFUSAL,
        conversation_id=conversation_id,
        cited_regulations=[],
        model_used="claude-haiku-4-5-20251001",
        input_tokens=0,
        output_tokens=0,
    )


async def _handle_off_topic_stream(
    *,
    pool,
    user_id,
    conversation_id,
    query: str,
):
    """Streaming variant of the off-topic short-circuit. Emits a single
    `done` event with the same payload shape as a normal chat reply.
    """
    today_count = await _count_off_topic_today(pool, user_id)

    if today_count >= _OFF_TOPIC_DAILY_CAP:
        answer = _OFF_TOPIC_RATE_LIMITED
    else:
        await _log_off_topic_query(
            pool=pool, user_id=user_id,
            conversation_id=conversation_id, query=query,
        )
        await _maybe_send_abuse_alert(
            pool=pool, user_id=user_id, today_count=today_count + 1,
        )
        answer = _OFF_TOPIC_REFUSAL

    yield {
        "event": "done",
        "data": {
            "answer": answer,
            "cited_regulations": [],
            "conversation_id": str(conversation_id),
            "model_used": "claude-haiku-4-5-20251001",
            "input_tokens": 0,
            "output_tokens": 0,
            "unverified_citations": [],
            "vessel_update": None,
            "regenerated": False,
        },
    }


async def _classify_and_persist_hedge(
    *,
    pool,
    conversation_id,
    user_id,
    query: str,
    vessel_profile,
    retrieved: list,
    hedge_text: str,
    anthropic_client,
    web_fallback_card,
) -> None:
    """Run the Haiku hedge classifier and persist to hedge_audits.

    Fire-and-forget — caller swallows all exceptions. The classifier
    is single-shot, ~$0.001 per call, ~1s latency. We always run it
    after the user has already received their response, so this never
    affects perceived latency. Sprint D6.58 Slice 2.
    """
    from rag.hedge_audit import classify_hedge, persist_hedge_audit

    web_fallback_id = (
        web_fallback_card.fallback_id if web_fallback_card else None
    )
    web_surface_tier = (
        web_fallback_card.surface_tier if web_fallback_card else None
    )

    # D6.58 Slice 3 — give the classifier ensemble context so it can
    # recommend more pointed actions (e.g. "ensemble surfaced
    # dnv.com — ingest DNV section X").
    ensemble_context = None
    if web_fallback_card and web_surface_tier in ("consensus", "verified"):
        ensemble_context = {
            "tier": web_surface_tier,
            "source_domain": web_fallback_card.source_domain,
        }

    outcome = await classify_hedge(
        query=query,
        retrieved=retrieved or [],
        hedge_text=hedge_text,
        vessel_profile=vessel_profile,
        anthropic_client=anthropic_client,
        ensemble_context=ensemble_context,
    )
    if outcome is None:
        return

    await persist_hedge_audit(
        pool=pool,
        conversation_id=conversation_id,
        user_id=user_id,
        query=query,
        retrieved=retrieved or [],
        web_fallback_id=web_fallback_id,
        web_surface_tier=web_surface_tier,
        outcome=outcome,
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
    judge_verdict: str | None = None,
    judge_reasoning: str | None = None,
    judge_missing_topic: str | None = None,
    chunks_truncated_for_judge: bool = False,
) -> None:
    """Insert a row into retrieval_misses for later analysis.

    Called when `detect_hedge(answer)` matched. Captures the full retrieval
    context (top-K chunks) plus what the model actually cited, so we can
    later see whether the miss was "nothing relevant retrieved" vs "right
    content retrieved but model still hedged" vs "retrieval gap under
    specific vessel/no-vessel configurations."
    """
    import json as _json
    from decimal import Decimal as _Decimal

    def _json_default(o):
        # Sprint D6.3c bugfix — vessel_profile may contain Decimal values
        # (e.g. gross_tonnage from numeric(12,2) columns). json.dumps
        # rejects Decimal by default which silently dropped every
        # retrieval_miss for users with vessel profiles.
        if isinstance(o, _Decimal):
            return float(o)
        raise TypeError(f"unserializable for retrieval_misses log: {type(o)}")

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
            retrieved_chunks, cited_regulations, answer_preview,
            judge_verdict, judge_reasoning, judge_missing_topic,
            chunks_truncated_for_judge
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10::jsonb,
                $11::jsonb, $12, $13, $14, $15, $16)
        """,
        user_id,
        conversation_id,
        query,
        vessel_profile is not None,
        _json.dumps(vessel_profile, default=_json_default) if vessel_profile is not None else None,
        hedge_phrase,
        model_used,
        input_tokens,
        output_tokens,
        _json.dumps(retrieved_payload, default=_json_default),
        _json.dumps(cited_payload, default=_json_default),
        answer[:2000],
        judge_verdict,
        judge_reasoning,
        judge_missing_topic,
        chunks_truncated_for_judge,
    )


async def _run_tier_router_and_log(
    *,
    pool: asyncpg.Pool,
    conversation_id: UUID,
    user_id: "UUID | None",
    query: str,
    mode: str,
    cleaned_answer_pre_tier: str,
    layer_c_fired: bool,
    judge_verdict: str | None,
    # Sprint D6.92 — capture the judge's reasoning so post-hoc audits
    # can inspect WHY a verdict landed (e.g. distinguish a real corpus
    # gap from a mis-rated cited answer).
    judge_reasoning: str | None,
    web_fallback_card: "WebFallbackCard | None",
    verified_citations_count: int,
    anthropic_client: AsyncAnthropic,
) -> tuple[str, "TierMetadata | None"]:
    """Sprint D6.84 — run the confidence tier router and log to
    tier_router_shadow_log. Returns (final_answer, tier_metadata).

      mode='shadow' — render today's behavior; metadata is None;
                      shadow log captures what tier router would have done.
      mode='live'   — render the tier router's decision; metadata is
                      populated for the frontend; shadow log captures
                      both.

    Wraps every external call (LLM, DB) in try/except. On any internal
    failure, returns (cleaned_answer_pre_tier, None) so the caller falls
    through to today's behavior.
    """
    from rag.tier_router import route_tier
    from rag.models import TierMetadata

    started = time.monotonic()
    try:
        decision = await route_tier(
            query=query,
            cleaned_answer=cleaned_answer_pre_tier,
            verified_citations_count=verified_citations_count,
            judge_verdict=judge_verdict,
            web_fallback_card=web_fallback_card,
            anthropic_client=anthropic_client,
        )
    except Exception as exc:
        logger.warning(
            "tier_router unexpected failure (falling through): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return (cleaned_answer_pre_tier, None)

    total_latency_ms = int((time.monotonic() - started) * 1000)

    final_answer = cleaned_answer_pre_tier
    if mode == "live" and decision.rendered_answer is not None:
        final_answer = decision.rendered_answer

    tier_metadata = None
    if mode == "live":
        tier_metadata = TierMetadata(
            tier=decision.tier,
            label=decision.label,
            reason=decision.reason or "",
            classifier_verdict=decision.classifier_verdict,
            self_consistency_pass=decision.self_consistency_pass,
            web_confidence=decision.web_confidence,
        )

    # The "would the surface differ" signal admin filters on. True when
    # the router computed an answer override that differs from current.
    shadow_would_differ = (
        decision.rendered_answer is not None
        and decision.rendered_answer != cleaned_answer_pre_tier
    )

    try:
        await pool.execute(
            """
            INSERT INTO tier_router_shadow_log (
                conversation_id, user_id, query, mode,
                current_answer, current_judge_verdict, current_judge_reasoning,
                current_layer_c_fired,
                current_verified_citations_count, current_web_confidence,
                shadow_tier, shadow_label, shadow_answer, shadow_reason,
                shadow_classifier_verdict, shadow_classifier_reasoning,
                shadow_self_consistency_pass,
                shadow_classifier_latency_ms, shadow_self_consistency_latency_ms,
                shadow_total_latency_ms, shadow_error, differs
            )
            VALUES ($1, $2, $3, $4,
                    $5, $6, $7, $8,
                    $9, $10,
                    $11, $12, $13, $14,
                    $15, $16, $17,
                    $18, $19, $20, $21, $22)
            """,
            conversation_id,
            user_id,
            query[:2000],
            mode,
            cleaned_answer_pre_tier[:8000],
            judge_verdict,
            (judge_reasoning or "")[:2000] if judge_reasoning else None,
            layer_c_fired,
            verified_citations_count,
            web_fallback_card.confidence if web_fallback_card else None,
            decision.tier,
            decision.label,
            (decision.rendered_answer or cleaned_answer_pre_tier)[:8000],
            (decision.reason or "")[:2000],
            decision.classifier_verdict,
            (decision.classifier_reasoning or "")[:1000] if decision.classifier_reasoning else None,
            decision.self_consistency_pass,
            decision.classifier_latency_ms,
            decision.self_consistency_latency_ms,
            total_latency_ms,
            decision.error,
            shadow_would_differ,
        )
    except Exception as exc:
        logger.warning(
            "tier_router shadow log insert failed (non-fatal): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )

    return (final_answer, tier_metadata)


async def chat_with_progress(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    conversation_id: UUID,
    credential_context: str | None = None,
    conversation_title: str | None = None,
    fingerprint_summary: str | None = None,
    user_role: str | None = None,
    user_jurisdiction_focus: str | None = None,
    user_verbosity: str | None = None,
    user_id: UUID | None = None,
    subscription_tier: str | None = None,
    xai_api_key: str = "",
    web_fallback_enabled: bool = True,
    web_fallback_cosine_threshold: float = 0.7,
    web_fallback_daily_cap: int = 10,
    web_fallback_cascade_enabled: bool = True,
    hedge_judge_enabled: bool = True,
    query_rewrite_enabled: bool = False,
    reranker_enabled: bool = False,
    # Sprint D6.70 — Layer-2 citation-oracle intervention. See chat()
    # docstring for full contract. Defaults to True; flip via config to
    # disable instantly without redeploy.
    citation_oracle_enabled: bool = True,
    # Sprint D6.71 — Hybrid BM25 + dense retrieval. Default OFF.
    # See chat() docstring.
    hybrid_retrieval_enabled: bool = False,
    hybrid_rrf_k: int = 60,
    # Sprint D6.84 — confidence tier router mode. See chat() docstring.
    confidence_tiers_mode: str = "off",
    # Sprint D6.86 — see chat() docstring.
    judge_on_cited_enabled: bool = True,
    lead_with_answer_enabled: bool = True,
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

    # Sprint D6.86 — assemble synthesis system prompt with optional
    # lead-with-answer block. See chat() for rationale.
    effective_system_prompt = assemble_system_prompt(
        lead_with_answer=lead_with_answer_enabled,
    )

    # D6.58 — off-topic short-circuit (streaming path). Same gate as
    # the non-streaming chat() function. Skip retrieval/fallback/
    # ensemble entirely and emit a polite refusal as a single done
    # event.
    if route.is_off_topic:
        async for event in _handle_off_topic_stream(
            pool=pool,
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
        ):
            yield event
        return

    # Sprint D6.4 — same followup detection + escalation as chat().
    followup_match = detect_followup(query)
    retrieval_query = query
    if followup_match:
        prior_user_msg = next(
            (m.content for m in reversed(conversation_history) if m.role == "user"),
            None,
        )
        retrieval_query = compose_followup_query(prior_user_msg, query)
        logger.info(
            "Followup detected (pattern=%r); routing to %s with combined retrieval query",
            followup_match, REGENERATION_MODEL,
        )
    elif (
        len(conversation_history) == 0
        and len(query) > LENGTH_THRESHOLD_CHARS
    ):
        # Sprint D6.51 — verbose first-turn query distillation. See
        # query_distill.py for rationale. Streaming users get a status
        # event so the brief Haiku call is visible during the retrieval
        # pause.
        yield {"event": "status", "data": "Refining your question…"}
        from rag.query_distill import distill_query
        distilled = await distill_query(
            query=query,
            anthropic_client=anthropic_client,
            pool=pool,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if distilled:
            retrieval_query = distilled
            logger.info(
                "Distilled verbose first-turn query "
                "(orig=%dch, distilled=%dch): %r",
                len(query), len(distilled), distilled[:100],
            )

    # Stage 2: Retrieve (D6.66 — same enhanced path as the non-stream
    # chat handler; flags piped through from the chat router).
    source_labels = _describe_sources(query)
    yield {"event": "status", "data": f"Searching {source_labels}…"}
    chunks = await retrieve_enhanced(
        query=retrieval_query,
        pool=pool,
        openai_api_key=openai_api_key,
        anthropic_client=anthropic_client,
        vessel_profile=vessel_profile,
        limit=8,
        query_rewrite_enabled=query_rewrite_enabled,
        reranker_enabled=reranker_enabled,
        hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        hybrid_rrf_k=hybrid_rrf_k,
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
    messages = _build_chat_messages(
        query, conversation_history, vessel_profile, context_str, credential_context,
        conversation_title=conversation_title,
        fingerprint_summary=fingerprint_summary,
        user_role=user_role,
        user_jurisdiction_focus=user_jurisdiction_focus,
        user_verbosity=user_verbosity,
    )

    yield {"event": "status", "data": "Consulting compliance engine…"}
    # Sprint D6.4 — followup turns escalate to Opus.
    # Sprint D6.68 — answer text streams token-by-token instead of
    # holding for the full response. Each text chunk goes out as a
    # `delta` SSE event; the frontend accumulates into the assistant
    # message in real time so the user starts reading at second 1
    # rather than second 5-8.
    model_used = REGENERATION_MODEL if followup_match else route.model
    answer_chunks: list[str] = []
    input_tokens = 0
    output_tokens = 0
    streaming_failed_for_fallback = False
    try:
        async with anthropic_client.messages.stream(
            model=model_used,
            max_tokens=_MAX_TOKENS,
            system=effective_system_prompt,
            messages=messages,
        ) as stream:
            async for text_chunk in stream.text_stream:
                if not text_chunk:
                    continue
                answer_chunks.append(text_chunk)
                yield {"event": "delta", "data": text_chunk}
            final_msg = await stream.get_final_message()
        answer = "".join(answer_chunks)
        input_tokens = final_msg.usage.input_tokens
        output_tokens = final_msg.usage.output_tokens
    except _CLAUDE_FAILURE_EXCEPTIONS as exc:
        logger.warning(
            "Claude streaming failed (%s: %s), falling back to OpenAI GPT-4o",
            type(exc).__name__,
            str(exc)[:200],
        )
        streaming_failed_for_fallback = True

    if streaming_failed_for_fallback:
        # If we got partial chunks before the failure, tell the client
        # to discard and start over from the fallback. Cleanest UX is
        # a 'reset' delta so the assistant message wipes back to empty
        # before the OpenAI fallback streams its replacement.
        if answer_chunks:
            yield {"event": "delta_reset", "data": ""}
            answer_chunks = []
        # Neutral status — never surface "Claude is down" to the user.
        yield {"event": "status", "data": "Processing your question…"}
        # OpenAI fallback is currently non-streaming. Returns full text
        # in one response; we yield it as a single delta so the same
        # client-side accumulator path works.
        fallback_result = await fallback_chat(
            system_prompt=effective_system_prompt,
            messages=messages,
            max_tokens=_MAX_TOKENS,
            openai_api_key=openai_api_key,
        )
        answer = fallback_result["answer"]
        input_tokens = fallback_result["input_tokens"]
        output_tokens = fallback_result["output_tokens"]
        model_used = fallback_result["model"]
        if answer:
            yield {"event": "delta", "data": answer}
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
        chunks=chunks,
    )
    input_tokens += regen_in
    output_tokens += regen_out

    # Sprint D2-LOG (also in chat() above) — detect hedges on the final
    # answer and log the miss to retrieval_misses. This path is the one
    # real users hit via SSE streaming.
    #
    # D6.60 — Haiku judge gates the fallback decision: complete_miss /
    # partial_miss fire ensemble, precision_callout / false_hedge
    # suppress. See the chat() path above for full rationale.
    # Fire-and-forget: DB errors never fail the SSE stream.
    hedge_phrase = detect_hedge(cleaned_answer)
    regex_matched = hedge_phrase is not None
    web_fallback_card = None
    judge_verdict: str | None = None
    judge_reasoning: str | None = None
    judge_missing_topic: str | None = None
    chunks_truncated_for_judge = False

    # Sprint D6.86 — judge fires on (a) regex matched OR (b)
    # judge_on_cited_enabled AND ≥1 verified citation. See chat() for
    # the full rationale. Web fallback firing is still gated on regex
    # match below (Phase 1 preserves legacy UX).
    should_run_judge = hedge_judge_enabled and (
        regex_matched
        or (judge_on_cited_enabled and len(verified_cited) >= 1)
    )

    if should_run_judge:
        # Sprint D6.74 — emit a status BEFORE the judge call so the
        # user sees the message change between "Verifying citations…"
        # and the post-judge oracle/fallback statuses.
        yield {"event": "status", "data": "Reviewing answer quality…"}

        from rag.hedge_judge import judge_hedge
        # Sprint D6.92 — tell the judge which mode it's in so it can
        # apply the right decision rubric. The pre-D6.92 prompt assumed
        # every call was regex-triggered and biased toward finding a
        # hedge; that mis-rated three cited-confident answers as
        # complete_miss in May 2026. The new prompt switches rubric
        # based on this parameter.
        judge_mode = "regex_triggered" if regex_matched else "precautionary"
        try:
            verdict = await judge_hedge(
                question=query,
                answer=cleaned_answer,
                chunks=chunks,
                citations=[
                    {"source": c.source, "section_number": c.section_number,
                     "section_title": c.section_title}
                    for c in verified_cited
                ],
                anthropic_client=anthropic_client,
                mode=judge_mode,
            )
            judge_verdict = verdict.verdict
            judge_reasoning = verdict.reasoning or None
            judge_missing_topic = verdict.missing_topic
            chunks_truncated_for_judge = verdict.chunks_truncated
        except Exception as exc:
            logger.warning(
                "hedge_judge unexpected failure: %s: %s",
                type(exc).__name__, str(exc)[:200],
            )
            if regex_matched:
                judge_verdict = "complete_miss"
    elif regex_matched and not hedge_judge_enabled:
        judge_verdict = "complete_miss"

    if regex_matched:
        # Log to retrieval_misses on the regex-matched path only.
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
                judge_verdict=judge_verdict,
                judge_reasoning=judge_reasoning,
                judge_missing_topic=judge_missing_topic,
                chunks_truncated_for_judge=chunks_truncated_for_judge,
            )
        except Exception as exc:
            logger.warning(
                "retrieval_miss log failed (non-fatal): %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )

        # Fire fallback only on miss verdicts (regex-matched path).
        should_fire_fallback = judge_verdict in ("complete_miss", "partial_miss")
        if web_fallback_enabled and should_fire_fallback:
            top_cosine = (
                chunks[0].get("similarity", 0.0) if chunks else 0.0
            )
            override_query: str | None = None
            if judge_verdict == "partial_miss" and judge_missing_topic:
                override_query = judge_missing_topic
                logger.info(
                    "hedge_judge partial_miss (streaming): overriding ensemble "
                    "query from %r to %r", query[:80], override_query,
                )

            # Sprint D6.70 — Layer-2 citation-oracle intervention. Same
            # additive-only contract as chat(): if the oracle finds
            # the controlling citation in our corpus, we surface a
            # 'verified' tier card and skip the web ensemble. On any
            # failure path the function returns None and we fall
            # through to the existing _dispatch_web_fallback below.
            if citation_oracle_enabled:
                yield {
                    "event": "status",
                    "data": "Locating the relevant regulation…",
                }
                try:
                    web_fallback_card = await _try_citation_oracle_intervention(
                        query=query,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        pool=pool,
                        anthropic_client=anthropic_client,
                        top_cosine=top_cosine,
                    )
                except Exception as exc:
                    logger.warning(
                        "citation_oracle intervention failed (non-fatal): %s: %s",
                        type(exc).__name__, str(exc)[:200],
                    )
                    web_fallback_card = None

            if web_fallback_card is None:
                yield {
                    "event": "status",
                    "data": "Searching authoritative sources…",
                }
                try:
                    web_fallback_card = await _dispatch_web_fallback(
                        query=query,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        subscription_tier=subscription_tier,
                        pool=pool,
                        anthropic_client=anthropic_client,
                        openai_api_key=openai_api_key,
                        xai_api_key=xai_api_key,
                        top_cosine=top_cosine,
                        cosine_threshold=web_fallback_cosine_threshold,
                        daily_cap=web_fallback_daily_cap,
                        cascade_enabled=web_fallback_cascade_enabled,
                        override_query=override_query,
                        judge_verdict=judge_verdict,
                        judge_missing_topic=judge_missing_topic,
                    )
                except Exception as exc:
                    logger.warning(
                        "web fallback failed (non-fatal): %s: %s",
                        type(exc).__name__,
                        str(exc)[:200],
                    )
        elif not should_fire_fallback:
            logger.info(
                "hedge_judge suppressed fallback (streaming): verdict=%s reasoning=%r",
                judge_verdict, (judge_reasoning or "")[:200],
            )

        # 4. Hedge classifier — fires on every hedge regardless of verdict.
        try:
            await _classify_and_persist_hedge(
                pool=pool,
                conversation_id=conversation_id,
                user_id=user_id,
                query=query,
                vessel_profile=vessel_profile,
                retrieved=chunks,
                hedge_text=cleaned_answer,
                anthropic_client=anthropic_client,
                web_fallback_card=web_fallback_card,
            )
        except Exception as exc:
            logger.warning(
                "hedge audit failed (non-fatal): %s: %s",
                type(exc).__name__, str(exc)[:200],
            )

    # Layer C — UX inversion (streaming-path twin of the chat() inversion
    # above). The user already saw the original answer streamed; the
    # final done event carries the inverted answer text, which the
    # frontend uses to replace the streamed content. Same pattern as
    # citation stripping (which already rewrites cleaned_answer in-flight).
    layer_c_fired = False
    if _should_apply_layer_c(judge_verdict, web_fallback_card):
        logger.info(
            "Layer C (stream): inverting answer surface (verdict=%s web_confidence=%d)",
            judge_verdict, web_fallback_card.confidence,
        )
        cleaned_answer = _apply_layer_c_inversion(cleaned_answer, web_fallback_card)
        layer_c_fired = True

    # Sprint D6.84 — confidence tier router (streaming-path twin of the
    # chat() integration above). Same fail-safe contract: any failure
    # falls through to today's rendered answer + None metadata.
    tier_metadata = None
    if confidence_tiers_mode in ("shadow", "live"):
        cleaned_answer, tier_metadata = await _run_tier_router_and_log(
            pool=pool,
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
            mode=confidence_tiers_mode,
            cleaned_answer_pre_tier=cleaned_answer,
            layer_c_fired=layer_c_fired,
            judge_verdict=judge_verdict,
            judge_reasoning=judge_reasoning,
            web_fallback_card=web_fallback_card,
            verified_citations_count=len(verified_cited),
            anthropic_client=anthropic_client,
        )

    # Stage 6: Final event with the complete response
    done_payload = {
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
    }
    if web_fallback_card is not None:
        done_payload["web_fallback"] = {
            "fallback_id": web_fallback_card.fallback_id,
            "source_url": web_fallback_card.source_url,
            "source_domain": web_fallback_card.source_domain,
            "quote": web_fallback_card.quote,
            "summary": web_fallback_card.summary,
            "confidence": web_fallback_card.confidence,
            # D6.58 Slice 1 — propagate surface tier so the frontend
            # renders the right badge (verified vs reference).
            "surface_tier": web_fallback_card.surface_tier,
        }
    if tier_metadata is not None:
        done_payload["tier_metadata"] = {
            "tier": tier_metadata.tier,
            "label": tier_metadata.label,
            "reason": tier_metadata.reason,
            "classifier_verdict": tier_metadata.classifier_verdict,
            "self_consistency_pass": tier_metadata.self_consistency_pass,
            "web_confidence": tier_metadata.web_confidence,
        }
    yield {"event": "done", "data": done_payload}
