"""
LLM alias enrichment for regulation chunks.

Generates 8-12 colloquial search terms per chunk via Claude Sonnet,
prepending them as a `[Search terms: ...]` block so the embedding
model captures operational vocabulary that mariners actually use.

Results are cached by content hash so re-ingests only call the API
for genuinely modified chunks.
"""

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path

import tiktoken
from anthropic import AsyncAnthropic

from ingest.models import Chunk

logger = logging.getLogger(__name__)

_ENCODER = tiktoken.get_encoding("cl100k_base")
_MAX_TOKENS = 512
_MODEL = "claude-sonnet-4-20250514"
_BATCH_SIZE = 20  # chunks per API batch (sequential, not parallel)
_MAX_ALIAS_TOKENS = 60  # hard cap on alias block token count

_SYSTEM_PROMPT = """\
You are a maritime safety expert. Given a regulatory text chunk, \
list 8-12 search terms a working mariner would use to find this content.

Include:
- Common names and colloquial terms (not formal regulatory language)
- Trade names, abbreviations, and acronyms
- Shipboard slang and operational terms
- Related hazards or scenarios that would lead someone to this content

Rules:
- Do NOT repeat terms already in the text
- Do NOT invent regulation numbers or material names not mentioned in the text
- Return ONLY the terms, comma-separated, no numbering or explanation\
"""

# Sources that should NOT be enriched (already handled by other means)
_SKIP_SOURCES = frozenset({"erg"})


def _count(text: str) -> int:
    return len(_ENCODER.encode(text))


class AliasEnricher:
    """Generate search term aliases for chunks via Claude Sonnet."""

    def __init__(self, api_key: str, cache_dir: Path):
        self._client = AsyncAnthropic(api_key=api_key)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[str]] = {}
        self._source: str = ""

    async def close(self) -> None:
        await self._client.close()

    async def enrich_chunks(
        self,
        chunks: list[Chunk],
        source: str,
    ) -> list[Chunk]:
        """Enrich chunks with LLM-generated search aliases.

        Skips chunks that:
        - Are from an excluded source (e.g., ERG)
        - Are already near the MAX_TOKENS limit
        - Have cached aliases from a previous run
        - Fail API generation (graceful fallback to un-enriched)

        Returns new Chunk objects with enriched chunk_text, recomputed
        content_hash, and updated token_count.
        """
        if source in _SKIP_SOURCES:
            logger.info("enricher: skipping %s (excluded source)", source)
            return chunks

        self._source = source
        self._cache = self._load_cache(source)

        enriched: list[Chunk] = []
        api_calls = 0
        cache_hits = 0
        skipped_budget = 0
        skipped_errors = 0

        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]

            for chunk in batch:
                original_hash = chunk.content_hash
                original_tokens = chunk.token_count or _count(chunk.chunk_text)

                # Skip if no room for aliases
                if original_tokens > _MAX_TOKENS - _MAX_ALIAS_TOKENS:
                    enriched.append(chunk)
                    skipped_budget += 1
                    continue

                # Check cache
                if original_hash in self._cache:
                    aliases = self._cache[original_hash]
                    enriched.append(self._apply_aliases(chunk, aliases))
                    cache_hits += 1
                    continue

                # Generate aliases via API
                try:
                    aliases = await self._generate_aliases(chunk)
                    self._cache[original_hash] = aliases
                    enriched.append(self._apply_aliases(chunk, aliases))
                    api_calls += 1
                except Exception as exc:
                    logger.warning(
                        "enricher: API error for %s chunk %d: %s — using original",
                        chunk.section_number, chunk.chunk_index, exc,
                    )
                    enriched.append(chunk)
                    skipped_errors += 1

        self._save_cache(source, self._cache)

        logger.info(
            "enricher: %s — %d chunks: %d API calls, %d cache hits, "
            "%d skipped (budget), %d skipped (errors)",
            source, len(chunks), api_calls, cache_hits,
            skipped_budget, skipped_errors,
        )
        return enriched

    async def _generate_aliases(self, chunk: Chunk) -> list[str]:
        """Call Sonnet to generate search aliases for a single chunk."""
        resp = await self._client.messages.create(
            model=_MODEL,
            max_tokens=200,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Text:\n{chunk.chunk_text}",
            }],
        )
        raw = resp.content[0].text if resp.content else ""
        # Parse comma-separated terms, strip whitespace and empty strings
        aliases = [t.strip() for t in raw.split(",") if t.strip()]
        # Filter: skip terms longer than 50 chars (likely sentences, not terms)
        aliases = [a for a in aliases if len(a) <= 50]
        # Cap at 12 terms
        return aliases[:12]

    def _apply_aliases(self, chunk: Chunk, aliases: list[str]) -> Chunk:
        """Create a new Chunk with aliases prepended to chunk_text."""
        if not aliases:
            return chunk

        alias_block = "[Search terms: " + ", ".join(aliases) + "]"
        alias_tokens = _count(alias_block)
        chunk_tokens = chunk.token_count or _count(chunk.chunk_text)

        # Final safety check: don't exceed token budget
        if chunk_tokens + alias_tokens > _MAX_TOKENS:
            return chunk

        # Insert alias block after the header line but before content.
        # Header format: "[section_number] section_title\n\n..."
        text = chunk.chunk_text
        first_break = text.find("\n\n")
        if first_break > 0:
            enriched_text = (
                text[: first_break + 2]
                + alias_block + "\n\n"
                + text[first_break + 2 :]
            )
        else:
            enriched_text = alias_block + "\n\n" + text

        return replace(
            chunk,
            chunk_text=enriched_text,
            content_hash=hashlib.sha256(
                enriched_text.encode("utf-8")
            ).hexdigest(),
            token_count=_count(enriched_text),
        )

    def _load_cache(self, source: str) -> dict[str, list[str]]:
        """Load alias cache from disk."""
        cache_path = self._cache_dir / f"{source}.json"
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.info(
                    "enricher: loaded %d cached aliases for %s",
                    len(data), source,
                )
                return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "enricher: cache load failed for %s: %s", source, exc,
                )
        return {}

    def _save_cache(self, source: str, cache: dict) -> None:
        """Persist alias cache to disk."""
        cache_path = self._cache_dir / f"{source}.json"
        try:
            cache_path.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "enricher: saved %d cached aliases for %s",
                len(cache), source,
            )
        except OSError as exc:
            logger.warning(
                "enricher: cache save failed for %s: %s", source, exc,
            )
