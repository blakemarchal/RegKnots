"""
Prompt context builder.

Formats retrieved chunks into a context block for the Claude prompt,
enforcing a 6,000-token limit. Chunks are consumed highest-similarity-first
(caller is responsible for ordering). Chunks that would exceed the limit are
dropped entirely — no partial truncation.

Returns the formatted context string and a deduplicated list of CitedRegulation
objects for response metadata.
"""

import tiktoken

from rag.models import CitedRegulation

_ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_CONTEXT_TOKENS = 6_000


def build_context(chunks: list[dict]) -> tuple[str, list[CitedRegulation]]:
    """Build Claude context string and citation list from retrieved chunks.

    Args:
        chunks: Retrieved regulation dicts (ordered best-first).

    Returns:
        Tuple of (context_str, cited_regulations).
        context_str is ready to embed directly in the user message.
    """
    parts: list[str] = []
    cited: list[CitedRegulation] = []
    seen_sections: set[str] = set()
    total_tokens = 0

    for chunk in chunks:
        section_number = chunk.get("section_number") or ""
        section_title = chunk.get("section_title") or ""
        full_text = chunk.get("full_text") or ""

        block = f"[SOURCE: {section_number} — {section_title}]\n{full_text}"
        block_tokens = len(_ENCODER.encode(block))

        if total_tokens + block_tokens > MAX_CONTEXT_TOKENS:
            continue  # drop — budget exhausted for this chunk

        parts.append(block)
        total_tokens += block_tokens

        if section_number not in seen_sections:
            seen_sections.add(section_number)
            cited.append(
                CitedRegulation(
                    source=chunk.get("source") or "",
                    section_number=section_number,
                    section_title=section_title,
                )
            )

    return "\n\n---\n\n".join(parts), cited
