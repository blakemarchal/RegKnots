"""
OpenAI fallback for when the Anthropic API is unavailable or Claude refuses.

Translates the Claude message format to OpenAI's chat completions format
and normalizes the response back to the same shape the rest of the engine
already expects. The system prompt, message history, and post-processing
(citation verification, vessel updates, etc.) are identical from the
caller's perspective — only the actual model invocation differs.

2026-10-16 — GPT-4o leaves the OpenAI API on 2027-01-14 (OpenAI deprecation
notice of 2026-10-14). The model is now a setting: env OPENAI_FALLBACK_MODEL
(default below) and OPENAI_FALLBACK_EFFORT. The GPT-5/6 models are reasoning
models: they take max_completion_tokens (reasoning counts toward it) and
reasoning_effort, and refuse temperature unless effort is "none". Claude
image blocks are translated to OpenAI image_url parts; before, an image
question that fell back sent Anthropic blocks to OpenAI and failed.
"""

import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL") or "gpt-6-luna"
FALLBACK_EFFORT = os.environ.get("OPENAI_FALLBACK_EFFORT") or "low"
_MAX_TOKENS = 2048
# Room for reasoning on top of the answer's own token budget.
_REASONING_HEADROOM = 8192

# Exposed so callers can log / persist a stable identifier when the fallback
# fires. The "fallback:" prefix makes it trivially distinguishable from
# normal Claude model IDs in logs and the admin dashboard.
FALLBACK_MODEL_ID = f"fallback:{FALLBACK_MODEL}"


def _legacy(model: str) -> bool:
    """GPT-4o / GPT-4.1: max_tokens, no reasoning effort."""
    return model.startswith(("gpt-4o", "gpt-4.1", "gpt-4-"))


def _system_text(system_prompt) -> str:
    """The system prompt as text: a string, or Anthropic system blocks
    (rag.llm.cached_system) joined."""
    if isinstance(system_prompt, str):
        return system_prompt
    return "\n\n".join(b.get("text", "") for b in system_prompt or [] if isinstance(b, dict))


def _content(content):
    """One message's content in OpenAI's format. Text blocks become text
    parts, base64 image blocks become data-URL image parts; anything else
    (none today) is dropped. All-text content collapses to a string."""
    if isinstance(content, str):
        return content
    parts: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image" and (block.get("source") or {}).get("type") == "base64":
            src = block["source"]
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{src.get('media_type', 'image/jpeg')};base64,{src.get('data', '')}"}})
    if all(p["type"] == "text" for p in parts):
        return "\n\n".join(p["text"] for p in parts)
    return parts


def to_openai_messages(system_prompt, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": _system_text(system_prompt)}]
    for m in messages:
        out.append({"role": m["role"], "content": _content(m.get("content"))})
    return out


def request_kwargs(model: str, effort: str, max_tokens: int) -> dict:
    if _legacy(model):
        return {"max_tokens": max_tokens}
    headroom = 0 if effort == "none" else _REASONING_HEADROOM
    return {"max_completion_tokens": max_tokens + headroom, "reasoning_effort": effort}


async def fallback_chat(
    system_prompt,
    messages: list[dict],
    max_tokens: int = _MAX_TOKENS,
    openai_api_key: str = "",
    model: str | None = None,
    effort: str | None = None,
) -> dict:
    """Call the OpenAI fallback model with the same prompt structure as Claude.

    Args:
        system_prompt:    The system prompt: a string, or Anthropic system blocks.
        messages:         List of {"role": "user"|"assistant", "content": ...}
                          dicts — the same list we would have sent to Claude
                          (string or Anthropic content blocks).
        max_tokens:       Max answer tokens (reasoning headroom is added).
        openai_api_key:   OpenAI API key.
        model, effort:    Override FALLBACK_MODEL / FALLBACK_EFFORT (evals).

    Returns:
        Dict with keys: answer (str), input_tokens (int), output_tokens (int),
        model (str — "fallback:<model>").

    Raises:
        Any OpenAI API exception. Callers should treat these as a total
        failure — there is no further fallback beyond this point.
    """
    model = model or FALLBACK_MODEL
    effort = effort or FALLBACK_EFFORT
    client = AsyncOpenAI(api_key=openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=to_openai_messages(system_prompt, messages),
            **request_kwargs(model, effort, max_tokens),
        )

        choice = response.choices[0]
        answer = choice.message.content or ""
        if getattr(choice, "finish_reason", None) not in (None, "stop"):
            logger.warning("OpenAI fallback %s finished with %s", model, choice.finish_reason)

        return {
            "answer": answer,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
            "model": f"fallback:{model}",
        }
    finally:
        await client.close()
