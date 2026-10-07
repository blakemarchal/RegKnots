"""Shared Anthropic call helpers (2026-09-22 LLM surface audit — U2, U3, U5).

Every model call in `rag/` and `apps/api` reads its response through these,
so that three properties hold everywhere instead of in whichever module
remembered them:

  * Answer text is read by block TYPE, never by position. Opus 5.5 (and any
    thinking-enabled model) opens every response with a `thinking` block, so
    `response.content[0].text` raises AttributeError — the bug that silently
    disabled regeneration until 2026-09-22.
  * A safety-classifier refusal (HTTP 200, `stop_reason="refusal"`, no usable
    text; Sonnet 5.5 and Opus 5.5 run cyber/bio/reasoning_extraction and
    other classifiers) is logged and surfaced as "no result", not as an empty
    answer or a JSON parse error. Sonnet 5.5 calls also carry the server-side
    fallback, which re-runs a declined request on a substitute model.
  * JSON comes from structured outputs (`output_config.format`): the API
    guarantees the shape, replacing the six copy-pasted "strip the code
    fence, regex for {...}" parsers. Truncation (`stop_reason="max_tokens"`)
    can still cut a JSON body short — callers that salvaged partial JSON
    before keep doing so on `JsonResult.text`.

Schemas are plain dicts built with the small constructors below. Structured
outputs require `additionalProperties: false` on every object and do not
support numeric/string-length constraints, so none are used here —
callers keep their existing clamping/coercion of values.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Model choice for the small helper calls ──────────────────────────────────

# 2026-09-28 — one place for the small model behind the router, distill,
# rewrite, rerank, hedge judge, citation check, hedge audit, conversation
# titles, the support bot and the fast study guide. 2026-10-07 — Haiku 5.5
# (claude-haiku-5-5; accepts effort and structured outputs per /v1/models).
# SIDECAR_MODEL=claude-haiku-4-5-20251001 in the env rolls back without a
# deploy. apps/api/app/routers/chat.py maps any claude-haiku-* ID to "haiku".
SIDECAR_MODEL: str = os.environ.get("SIDECAR_MODEL") or "claude-haiku-5-5"

# Room for thinking on a short call to a model that thinks by default.
_THINKING_HEADROOM = 2048


def small_call_kwargs(model: str, max_tokens: int) -> dict:
    """`max_tokens` (and effort) for a short call on `model`.

    Haiku 4.5 doesn't think unless asked and rejects `effort`, so it keeps the
    caller's cap. The 5.x models think by default (Opus 5.5 always), and
    thinking counts toward max_tokens: on the router's 10-token cap, any
    thinking on Sonnet left the off-topic confirmation with no text. Those get
    thinking headroom and effort `low`. A newer small model that rejects
    `effort` fails loudly on the first call instead of returning empty answers.
    """
    if model.startswith("claude-haiku-4-5"):
        return {"max_tokens": max_tokens}
    return {"max_tokens": max(max_tokens, _THINKING_HEADROOM), "output_config": {"effort": "low"}}


# ── Refusal fallback (Sonnet 5.5) ────────────────────────────────────────────

# 2026-09-28 — Sonnet 5.5 can decline in five safety categories (cyber, bio,
# frontier_llm, reasoning_extraction, general_harms), and hazmat, IMDG and
# 33 CFR 101 cyber questions sit near some of them. With the server-side
# fallback, a declined request is re-run on a substitute model inside the
# same call instead of coming back empty. Claude API only: the Batches API
# rejects the parameter, so the enricher's batch path sends none.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def takes_server_fallback(model: Optional[str]) -> bool:
    return bool(model) and model.startswith("claude-sonnet-5-5")


async def messages_create(client: Any, **kwargs: Any) -> Any:
    """`client.messages.create(**kwargs)`, with the server-side refusal
    fallback on models that take it."""
    if not takes_server_fallback(kwargs.get("model")):
        return await client.messages.create(**kwargs)
    betas = [*kwargs.pop("betas", []), FALLBACK_BETA]
    response = await client.beta.messages.create(betas=betas, fallbacks="default", **kwargs)
    iterations = getattr(getattr(response, "usage", None), "iterations", None) or []
    if any(getattr(i, "type", None) == "fallback_message" for i in iterations):
        logger.info(
            "%s declined; served by %s (stop_reason=%s)",
            kwargs.get("model"), getattr(response, "model", None), stop_reason(response),
        )
    return response


# ── Response reading ─────────────────────────────────────────────────────────

def text_of(response: Any) -> str:
    """Join the text blocks of a Messages API response, by block type."""
    content = getattr(response, "content", None) or []
    return "".join(
        getattr(b, "text", "") or "" for b in content
        if getattr(b, "type", None) == "text"
    )


def stop_reason(response: Any) -> Optional[str]:
    return getattr(response, "stop_reason", None)


def is_refusal(response: Any) -> bool:
    return stop_reason(response) == "refusal"


def log_if_abnormal(response: Any, label: str) -> None:
    """Log refusals and truncation — neither raises, so both are otherwise silent."""
    sr = stop_reason(response)
    if sr == "refusal":
        logger.warning(
            "%s: model refused (stop_details=%s)",
            label, getattr(response, "stop_details", None),
        )
    elif sr == "max_tokens":
        logger.warning("%s: hit max_tokens — output truncated", label)


# ── Prompt caching (U3) ──────────────────────────────────────────────────────

def cached_system(prompt: str) -> list[dict]:
    """A `system` value whose (static) text is marked for prompt caching.

    Only worth it for a large prompt that is byte-identical across requests —
    the chat synthesis prompt (~10K tokens, identical for every user with the
    same precision/lead-with-answer flags; all per-user context is injected
    into the user turn). Cache reads bill at 0.1x input (0.05x on Opus 5.5);
    the first write in each 5-minute window costs 1.25x.
    """
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


# ── Native PDF input (U7) ────────────────────────────────────────────────────

def pdf_document_block(pdf_bytes: bytes, *, max_pages: int) -> dict:
    """A base64 `document` content block for a PDF, trimmed to its first
    `max_pages` pages.

    Replaces rasterizing PDFs to PNG before vision: the API reads the text
    layer AND each page image, so a text PDF (a clean COI export) no longer
    loses its text to OCR-from-pixels. But a native PDF bills every page
    (measured 2026-09-22: ~50K input tokens for a 61 KB, many-page NVIC), so
    callers keep the page cap their PNG path had. If pypdf cannot read the
    file (encrypted, malformed) the original bytes are sent unchanged —
    callers already cap uploads at 10 MB, inside the API's 32 MB limit.
    """
    import base64
    import io

    data = pdf_bytes
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) > max_pages:
            writer = PdfWriter()
            for page in reader.pages[:max_pages]:
                writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            data = buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — fall back to the untrimmed file
        logger.warning("pdf_document_block: could not trim PDF (%s) — sending as-is", exc)
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


# ── JSON schema constructors (structured outputs) ────────────────────────────

STR: dict = {"type": "string"}
INT: dict = {"type": "integer"}
NUM: dict = {"type": "number"}
BOOL: dict = {"type": "boolean"}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def enum(*values: Any) -> dict:
    return {"enum": list(values)}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(properties: dict, *, required: Optional[list[str]] = None) -> dict:
    """Strict object: `additionalProperties: false`; every property required
    unless `required` names a subset."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def json_output_config(schema: dict, **extra: Any) -> dict:
    """`output_config` value carrying a JSON-schema format (merge `effort` etc. via extra)."""
    return {"format": {"type": "json_schema", "schema": schema}, **extra}


# ── Structured-output call ───────────────────────────────────────────────────

@dataclass
class JsonResult:
    data: Optional[dict]        # parsed object, or None on refusal / unparseable output
    text: str                   # raw text (for salvage parsers and debug logging)
    stop_reason: Optional[str]
    response: Any


def parse_json_text(text: str) -> Optional[dict]:
    """Parse a structured-output body. No fence-stripping or regex: with
    `output_config.format` the text IS the JSON, or it is truncated/refused."""
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def create_json(
    client: Any,
    *,
    schema: dict,
    label: str,
    output_config: Optional[dict] = None,
    **create_kwargs: Any,
) -> JsonResult:
    """`client.messages.create(...)` constrained to `schema`.

    API errors propagate unchanged — every caller already has its own
    failure path around the call. A refusal or unparseable body returns
    `JsonResult(data=None, ...)` and is logged under `label`. Sonnet 5.5
    calls go through the server-side refusal fallback (`messages_create`).
    """
    cfg = dict(output_config or {})
    cfg["format"] = {"type": "json_schema", "schema": schema}
    response = await messages_create(client, output_config=cfg, **create_kwargs)
    text = text_of(response)
    sr = stop_reason(response)
    if sr == "refusal":
        log_if_abnormal(response, label)
        return JsonResult(None, text, sr, response)
    data = parse_json_text(text)
    if data is None:
        logger.warning(
            "%s: structured output did not parse (stop_reason=%s): %s",
            label, sr, text[:200],
        )
    elif sr == "max_tokens":
        log_if_abnormal(response, label)
    return JsonResult(data, text, sr, response)
