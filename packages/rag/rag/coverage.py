"""Coverage check (2026-10-08, answer pipeline phase 2).

Before the answer is written: does RegKnot's library text cover the question?
One small-model call with structured output returns `full`, `partial` or
`none`, and for anything short of full, the specific facts that are missing,
each with a web search query naming the likely authority. Missing items go to
rag.web_research; the rest of the pipeline is unchanged when coverage is full.

Fail-open: any error means "full" (no web step), so a coverage outage can only
cost the web step, never the answer. Spec: docs/specs/answer-pipeline-2026-10-08.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_MISSING = 2   # 2026-10-09 A/B: 3 items researched on 13 of 15 questions, +22 s
_CONTEXT_CHARS = 90_000   # the library text the answer model reads (≤ ~20K tokens)

_PROMPT = """\
You check whether a maritime compliance assistant has what it needs to answer a mariner's question.

Below are the mariner's question, their vessel, the conversation so far (if any), and the LIBRARY TEXT \
the assistant will answer from: regulation and guidance excerpts from its own library.

Decide whether the library text answers the CORE of the question for this vessel: the specific thing \
the mariner asked, not everything related to it.
- full: the library text states the rule, figure, date or document the question asks for. This is the \
usual case. Return full even if related details, background, other jurisdictions or follow-on topics \
are missing; the assistant handles those.
- partial: the library covers the topic but lacks the one specific fact the question turns on (the \
figure, interval or date asked for, the section that sets the requirement, whether an instrument is in \
force or amended, a form or document the question names).
- none: the library text does not address the question.

For partial or none, list at most 2 missing items, each a fact without which the answer to the question \
asked would be wrong or incomplete. Never list nice-to-know details. For each, write a web search query \
that names the likely authority and instrument, e.g. "USCG 46 CFR 142.240 towing vessel fixed fire \
extinguishing system" or "IMO MSC.576(110) pilot transfer performance standards entry into force".

A greeting, a thank-you, a question about RegKnot itself, or a request to rewrite or format the \
previous answer needs no library text: return full."""


@dataclass
class MissingItem:
    item: str
    search_query: str


@dataclass
class Coverage:
    status: str                       # full | partial | none
    missing: list[MissingItem] = field(default_factory=list)
    error: str | None = None


def coverage_schema() -> dict:
    from rag.llm import STR, arr, enum, obj
    return obj({
        "coverage": enum("full", "partial", "none"),
        "missing": arr(obj({"item": STR, "search_query": STR})),
    })


async def check_coverage(client, *, question: str, library_text: str, vessel_line: str = "",
                         history: str = "") -> Coverage:
    from rag.llm import SIDECAR_MODEL, create_json, small_call_kwargs
    parts = [_PROMPT, f"QUESTION: {question}"]
    if vessel_line:
        parts.append(f"VESSEL: {vessel_line}")
    if history:
        parts.append(f"CONVERSATION SO FAR:\n{history}")
    parts.append("LIBRARY TEXT:\n" + (library_text or "(none)")[:_CONTEXT_CHARS])
    try:
        res = await create_json(
            client, schema=coverage_schema(), label="coverage check", model=SIDECAR_MODEL,
            **small_call_kwargs(SIDECAR_MODEL, 600),
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
        )
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("coverage check failed: %s: %s", type(exc).__name__, str(exc)[:200])
        return Coverage("full", error=type(exc).__name__)
    data = res.data or {}
    status = data.get("coverage") if data.get("coverage") in ("full", "partial", "none") else "full"
    missing = [MissingItem(str(m.get("item", "")).strip()[:300], str(m.get("search_query", "")).strip()[:300])
               for m in (data.get("missing") or []) if m.get("item") and m.get("search_query")]
    if status == "full":
        missing = []
    elif not missing:
        status = "full"               # nothing concrete to look for
    return Coverage(status, missing[:MAX_MISSING])


def vessel_line(profile: dict | None) -> str:
    """One line for the checker: type, flag, tonnage, route, subchapter."""
    if not profile:
        return ""
    bits = [profile.get("vessel_type"), profile.get("flag_state") and f"{profile['flag_state']} flag",
            profile.get("gross_tonnage") and f"{profile['gross_tonnage']} GT",
            ", ".join(profile.get("route_types") or []) or profile.get("route_type"),
            profile.get("subchapter") and f"Subchapter {profile['subchapter']}"]
    return ", ".join(str(b) for b in bits if b)
