"""
Prompt context builder.

Formats retrieved chunks into a context block for the Claude prompt,
enforcing a 6,000-token limit. Chunks are consumed highest-similarity-first
(caller is responsible for ordering). Chunks that would exceed the limit are
dropped entirely — no partial truncation.

Sprint D3: each chunk is prefixed with its authority tier label (see
`packages/rag/rag/authority.py`) so the synthesizer can weight sources
correctly when they conflict. The tier label is advisory — the prompt
rules in SYSTEM_PROMPT govern how the synthesizer uses it. The main
constraint is "Tier 4 reference standards (ERG) remain authoritative
within their domain and must not be deprioritized for hazmat questions."

Returns the formatted context string and a deduplicated list of CitedRegulation
objects for response metadata.
"""

import tiktoken

from rag.authority import tier_for_source, tier_label
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
        source = chunk.get("source") or ""
        section_number = chunk.get("section_number") or ""
        section_title = chunk.get("section_title") or ""
        full_text = chunk.get("full_text") or ""
        tier = tier_for_source(source)

        block = (
            f"[SOURCE: {section_number} — {section_title}] "
            f"[{tier_label(tier)}]\n{full_text}"
        )
        block_tokens = len(_ENCODER.encode(block))

        if total_tokens + block_tokens > MAX_CONTEXT_TOKENS:
            continue  # drop — budget exhausted for this chunk

        parts.append(block)
        total_tokens += block_tokens

        if section_number not in seen_sections:
            seen_sections.add(section_number)
            cited.append(
                CitedRegulation(
                    source=source,
                    section_number=section_number,
                    section_title=section_title,
                )
            )

    return "\n\n---\n\n".join(parts), cited
