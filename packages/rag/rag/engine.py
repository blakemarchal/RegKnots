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
from anthropic import AsyncAnthropic

from rag.context import build_context
from rag.models import ChatMessage, ChatResponse, CitedRegulation
from rag.prompts import NAVIGATION_AID_REMINDER, SYSTEM_PROMPT
from rag.retriever import retrieve
from rag.router import route_query

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

# Matches both "(46 CFR 199.261)" and bare "46 CFR 199.261" — same as parseMessage.ts
_CFR_RE = re.compile(r"\(?(\d+)\s+CFR\s+([\d]+(?:\.[\d]+(?:-[\d]+)?)?)\)?")

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

    Args:
        cited_regulations: List of CitedRegulation objects to check.
        pool:              asyncpg connection pool.

    Returns:
        (verified, unverified) where verified is the subset found in the DB
        and unverified is a list of section_number strings not found.
    """
    verified: list[CitedRegulation] = []
    unverified: list[str] = []

    for reg in cited_regulations:
        exists = await pool.fetchval(
            """
            SELECT 1 FROM regulations
            WHERE source = $1 AND section_number = $2
            LIMIT 1
            """,
            reg.source,
            reg.section_number,
        )
        if exists:
            verified.append(reg)
        else:
            logger.warning(
                "Citation not found in DB — source=%r section=%r",
                reg.source,
                reg.section_number,
            )
            unverified.append(reg.section_number)

    return verified, unverified


def _extract_text_citations(answer: str) -> list[CitedRegulation]:
    """Extract CFR citations mentioned in answer text that aren't already in the
    cited_regulations list from context retrieval.

    Returns CitedRegulation stubs (section_title left blank) for DB lookup.
    """
    stubs: list[CitedRegulation] = []
    seen: set[str] = set()

    for m in _CFR_RE.finditer(answer):
        title = m.group(1)
        section = m.group(2)
        section_number = f"{title} CFR {section}"
        source = f"cfr_{title}"

        if section_number not in seen:
            seen.add(section_number)
            stubs.append(
                CitedRegulation(
                    source=source,
                    section_number=section_number,
                    section_title="",
                )
            )

    return stubs


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

    Handles both parenthesized "(46 CFR 131)" and bare "46 CFR 131" formats.
    Uses word-boundary guards so "46 CFR 131" doesn't match "46 CFR 131.45".
    """
    for section_number in unverified:
        escaped = re.escape(section_number)
        # Remove parenthesized format: "(46 CFR 131)" with optional leading space
        answer = re.sub(r"\s*\(" + escaped + r"\)", "", answer)
        # Remove bare format only when NOT followed by a dot+digit (sub-section)
        answer = re.sub(r"\b" + escaped + r"\b(?!\.\d)", "", answer)

    # Clean up artifacts: double spaces, orphaned punctuation patterns
    answer = re.sub(r"  +", " ", answer)                      # collapse double spaces
    answer = re.sub(r"\s+([,;.])", r"\1", answer)             # " ," → ","
    answer = re.sub(r"(per|under|in|by|see|of)\s*[,;.]", r"\1", answer)  # "per ," → "per"
    answer = re.sub(r"\(\s*\)", "", answer)                    # empty parens "()"
    answer = re.sub(r"  +", " ", answer)                      # final collapse

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
) -> list[dict]:
    """Construct the Claude API message list for a chat turn.

    Handles history truncation, vessel profile block construction, document
    extraction inclusion, and the final user message with retrieval context.
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

    user_content = (
        f"{NAVIGATION_AID_REMINDER}\n\n"
        f"{vessel_block}"
        f"Regulation context:\n{context_str}\n\n"
        f"Question: {query}"
    )
    messages.append({"role": "user", "content": user_content})
    return messages


async def _finalize_answer(
    answer: str,
    cited: list[CitedRegulation],
    conversation_id: UUID,
    model_used: str,
    pool: asyncpg.Pool,
) -> tuple[str, list[CitedRegulation], list[str], dict | None]:
    """Run vessel-update extraction, citation verification, and unverified-citation cleanup.

    Returns:
        (cleaned_answer, verified_cited, all_unverified, vessel_update)
    """
    # Extract vessel update block (before citation verification)
    answer, vessel_update = _extract_vessel_update(answer)

    # Verify the cited_regulations list from context retrieval.
    verified_cited, unverified_from_context = await verify_citations(cited, pool)

    # Extract additional CFR references Claude added in answer text and verify those.
    context_section_numbers = {r.section_number for r in cited}
    text_stubs = [
        stub
        for stub in _extract_text_citations(answer)
        if stub.section_number not in context_section_numbers
    ]

    if text_stubs:
        _, unverified_from_text = await verify_citations(text_stubs, pool)
    else:
        unverified_from_text = []

    # Deduplicated combined list
    all_unverified = list(
        dict.fromkeys(unverified_from_context + unverified_from_text)
    )

    # Handle unverified citations
    if all_unverified:
        # Log BEFORE stripping (so admin can see original text)
        await _log_citation_errors(
            unverified=all_unverified,
            conversation_id=conversation_id,
            answer=answer,
            model_used=model_used,
            pool=pool,
        )
        answer = _strip_unverified_citations(answer, all_unverified)
        answer = answer + _UNVERIFIED_DISCLAIMER

    return answer, verified_cited, all_unverified, vessel_update


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
    messages = _build_chat_messages(query, conversation_history, vessel_profile, context_str)

    # 5. Call Claude
    response = await anthropic_client.messages.create(
        model=route.model,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    answer = response.content[0].text

    # 6. Post-process: vessel update extraction, citation verification, cleanup
    cleaned_answer, verified_cited, all_unverified, vessel_update = await _finalize_answer(
        answer=answer,
        cited=cited,
        conversation_id=conversation_id,
        model_used=route.model,
        pool=pool,
    )

    return ChatResponse(
        answer=cleaned_answer,
        conversation_id=conversation_id,
        cited_regulations=verified_cited,
        model_used=route.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        unverified_citations=all_unverified,
        vessel_update=vessel_update,
    )


async def chat_with_progress(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    conversation_id: UUID,
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
    messages = _build_chat_messages(query, conversation_history, vessel_profile, context_str)

    yield {"event": "status", "data": "Consulting compliance engine…"}
    response = await anthropic_client.messages.create(
        model=route.model,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    answer = response.content[0].text

    # Stage 5: Post-processing
    yield {"event": "status", "data": "Verifying citations…"}
    cleaned_answer, verified_cited, all_unverified, vessel_update = await _finalize_answer(
        answer=answer,
        cited=cited,
        conversation_id=conversation_id,
        model_used=route.model,
        pool=pool,
    )

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
            "model_used": route.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "unverified_citations": all_unverified,
            "vessel_update": vessel_update,
        },
    }
