"""
OpenAI GPT-4o fallback for when the Anthropic API is unavailable.

Translates the Claude message format to OpenAI's chat completions format
and normalizes the response back to the same shape the rest of the engine
already expects. The system prompt, message history, and post-processing
(citation verification, vessel updates, etc.) are identical from the
caller's perspective — only the actual model invocation differs.
"""

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_FALLBACK_MODEL = "gpt-4o"
_MAX_TOKENS = 2048

# Exposed so callers can log / persist a stable identifier when the fallback
# fires. The "fallback:" prefix makes it trivially distinguishable from
# normal Claude model IDs in logs and the admin dashboard.
FALLBACK_MODEL_ID = f"fallback:{_FALLBACK_MODEL}"


async def fallback_chat(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = _MAX_TOKENS,
    openai_api_key: str = "",
) -> dict:
    """Call OpenAI GPT-4o with the same prompt structure as Claude.

    Args:
        system_prompt:    The SYSTEM_PROMPT string used for the Claude call.
        messages:         List of {"role": "user"|"assistant", "content": "..."}
                          dicts — the same list we would have sent to Claude.
        max_tokens:       Max response tokens.
        openai_api_key:   OpenAI API key.

    Returns:
        Dict with keys: answer (str), input_tokens (int), output_tokens (int),
        model (str — always FALLBACK_MODEL_ID).

    Raises:
        Any OpenAI API exception. Callers should treat these as a total
        failure — there is no further fallback beyond this point.
    """
    client = AsyncOpenAI(api_key=openai_api_key)

    try:
        # Claude + OpenAI use the same user/assistant role names, but OpenAI
        # puts the system prompt inside the messages array with role="system"
        # rather than as a separate parameter.
        openai_messages: list[dict] = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        response = await client.chat.completions.create(
            model=_FALLBACK_MODEL,
            max_tokens=max_tokens,
            messages=openai_messages,
        )

        choice = response.choices[0]
        answer = choice.message.content or ""

        return {
            "answer": answer,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
            "model": FALLBACK_MODEL_ID,
        }
    finally:
        await client.close()
