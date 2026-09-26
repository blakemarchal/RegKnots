"""
LLM alias enrichment for regulation chunks.

Generates 8-12 colloquial search terms per chunk via Claude Sonnet,
prepending them as a `[Search terms: ...]` block so the embedding
model captures operational vocabulary that mariners actually use.

Results are cached by content hash so re-ingests only call the API
for genuinely modified chunks. D6.94 — API calls are now parallelized
within each batch via asyncio.gather + a semaphore (10 concurrent)
because sequential per-chunk calls put lr_rules and abs_mvr enrichment
on a 30-50 minute critical path. Cache also checkpoints per batch so a
crash mid-run doesn't lose all progress.
"""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import replace
from pathlib import Path

import tiktoken
from anthropic import AsyncAnthropic

from ingest.models import Chunk

logger = logging.getLogger(__name__)

_ENCODER = tiktoken.get_encoding("cl100k_base")
_MAX_TOKENS = 512
_MODEL = "claude-sonnet-5"
_BATCH_SIZE = 20  # chunks per API batch — kept as the per-batch
                  # window so we can checkpoint the cache between
                  # batches and recover from interruptions.
_BATCH_CONCURRENCY = 10  # D6.94 — concurrent API calls per batch.
                         # Anthropic's tier-2 limit is 1000 req/min so
                         # 10 in flight gives ~10x throughput for
                         # large sources (lr_rules / abs_mvr) without
                         # tripping rate limits.
_MAX_ALIAS_TOKENS = 60  # hard cap on alias block token count

# 2026-09-22 (U8) — Message Batches API for bulk enrichment: 50% of the
# online price and no per-minute ceiling, and enrichment has no latency
# requirement (it only runs inside an ingest). The batch PRE-FILLS the
# content-hash cache; the online loop in enrich_chunks then runs
# unchanged and covers whatever the batch did not (errored / expired /
# canceled requests), plus runs too small to be worth a batch.
# REGKNOTS_ENRICH_MODE=online restores the all-online path.
# 2026-09-26 — REGKNOTS_ENRICH_MODE=cache applies cached aliases only and
# makes no API call: a chunk with no cache entry stays un-enriched. For
# re-ingests that must not spend Anthropic credits: without --enrich, an
# enriched row (stored under its enriched hash) is overwritten with plain
# text, so a plain re-parse strips aliases from sections it doesn't change.
_BATCH_API_MIN_CHUNKS = 50
_BATCH_POLL_SECONDS = 30
_BATCH_MAX_WAIT_SECONDS = 24 * 3600  # the API's own ceiling

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

        mode = os.environ.get("REGKNOTS_ENRICH_MODE", "batch").strip().lower()
        if mode == "batch":
            await self._prefill_cache_via_batch(chunks, source)
        cache_only = mode == "cache"
        cache_misses = 0

        enriched: list[Chunk] = []
        api_calls = 0
        cache_hits = 0
        skipped_budget = 0
        skipped_errors = 0

        # D6.94 — process batches concurrently. Within each batch, fire
        # up to _BATCH_CONCURRENCY API calls in parallel via
        # asyncio.gather. Cache + budget skips remain synchronous (fast
        # local lookups, no point parallelizing).
        sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _generate_with_sem(chunk: Chunk) -> tuple[Chunk, list[str] | None, Exception | None]:
            """Call _generate_aliases under the concurrency semaphore.
            Returns (chunk, aliases, exception) — exception is None on
            success. Never raises so the gather call doesn't short-circuit."""
            async with sem:
                try:
                    aliases = await self._generate_aliases(chunk)
                    return chunk, aliases, None
                except Exception as exc:  # noqa: BLE001
                    return chunk, None, exc

        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]
            to_generate: list[Chunk] = []

            # Synchronous pre-pass: handle budget-skip + cache hits, queue
            # the rest for the parallel API generation step.
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

                if cache_only:
                    enriched.append(chunk)
                    cache_misses += 1
                    continue

                to_generate.append(chunk)

            # Parallel API generation for the to_generate slice.
            if to_generate:
                results = await asyncio.gather(
                    *(_generate_with_sem(c) for c in to_generate)
                )
                for chunk, aliases, exc in results:
                    if exc is not None:
                        logger.warning(
                            "enricher: API error for %s chunk %d: %s — using original",
                            chunk.section_number, chunk.chunk_index, exc,
                        )
                        enriched.append(chunk)
                        skipped_errors += 1
                    else:
                        self._cache[chunk.content_hash] = aliases
                        enriched.append(self._apply_aliases(chunk, aliases))
                        api_calls += 1

            # Checkpoint the cache after each batch so a crash mid-run
            # doesn't lose progress (the prior implementation only saved
            # once at the end).
            self._save_cache(source, self._cache)

        self._save_cache(source, self._cache)

        logger.info(
            "enricher: %s — %d chunks: %d API calls, %d cache hits, "
            "%d skipped (budget), %d skipped (errors), %d left plain (cache-only mode)",
            source, len(chunks), api_calls, cache_hits,
            skipped_budget, skipped_errors, cache_misses,
        )
        return enriched

    @staticmethod
    def _alias_request_params(chunk: Chunk) -> dict:
        """Messages API params for one chunk — shared by the online and batch paths."""
        return {
            "model": _MODEL,
            "max_tokens": 200,
            "system": _SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": f"Text:\n{chunk.chunk_text}",
            }],
        }

    @staticmethod
    def _parse_aliases(raw: str) -> list[str]:
        # Parse comma-separated terms, strip whitespace and empty strings
        aliases = [t.strip() for t in raw.split(",") if t.strip()]
        # Filter: skip terms longer than 50 chars (likely sentences, not terms)
        aliases = [a for a in aliases if len(a) <= 50]
        # Cap at 12 terms
        return aliases[:12]

    @staticmethod
    def _text_of(message) -> str:
        # By block type, not content[0] (2026-09-22 U2 — a thinking-enabled
        # model opens with a thinking block; a refusal has no text at all).
        return "".join(
            getattr(b, "text", "") or "" for b in (getattr(message, "content", None) or [])
            if getattr(b, "type", None) == "text"
        )

    async def _generate_aliases(self, chunk: Chunk) -> list[str]:
        """Call Sonnet to generate search aliases for a single chunk."""
        resp = await self._client.messages.create(**self._alias_request_params(chunk))
        return self._parse_aliases(self._text_of(resp))

    async def _prefill_cache_via_batch(self, chunks: list[Chunk], source: str) -> None:
        """Generate aliases for every uncached, in-budget chunk through one
        Message Batch (50% price), writing successes into the cache.

        Never raises: any failure (create, polling, results) just leaves the
        remaining chunks for the online loop. Requests are keyed by the
        chunk's content_hash (sha256 hex — 64 chars, a valid custom_id), which
        is also the cache key, so duplicate chunks are sent once.
        """
        pending: dict[str, Chunk] = {}
        for chunk in chunks:
            tokens = chunk.token_count or _count(chunk.chunk_text)
            if tokens > _MAX_TOKENS - _MAX_ALIAS_TOKENS:
                continue
            if chunk.content_hash in self._cache:
                continue
            pending.setdefault(chunk.content_hash, chunk)
        if len(pending) < _BATCH_API_MIN_CHUNKS:
            if pending:
                logger.info(
                    "enricher: %s — %d uncached chunks, below the batch threshold (%d); online",
                    source, len(pending), _BATCH_API_MIN_CHUNKS,
                )
            return

        requests = [
            {"custom_id": h, "params": self._alias_request_params(c)}
            for h, c in pending.items()
        ]
        try:
            batch = await self._client.messages.batches.create(requests=requests)
        except Exception as exc:  # noqa: BLE001
            logger.warning("enricher: batch create failed (%s) — falling back to online", exc)
            return
        logger.info(
            "enricher: %s — submitted batch %s for %d chunks (Batch API, 50%% price)",
            source, batch.id, len(requests),
        )

        waited = 0
        while getattr(batch, "processing_status", None) != "ended":
            if waited >= _BATCH_MAX_WAIT_SECONDS:
                logger.warning(
                    "enricher: batch %s not ended after %ds — online fallback for the rest",
                    batch.id, waited,
                )
                return
            await asyncio.sleep(_BATCH_POLL_SECONDS)
            waited += _BATCH_POLL_SECONDS
            try:
                batch = await self._client.messages.batches.retrieve(batch.id)
            except Exception as exc:  # noqa: BLE001 — transient; keep polling
                logger.info("enricher: batch %s poll failed (%s) — retrying", batch.id, exc)
                continue
            if waited % 300 == 0:
                counts = getattr(batch, "request_counts", None)
                logger.info(
                    "enricher: batch %s %s after %ds (%s)",
                    batch.id, batch.processing_status, waited, counts,
                )

        succeeded = not_succeeded = 0
        try:
            decoder = await self._client.messages.batches.results(batch.id)
            async for entry in decoder:
                if entry.result.type == "succeeded":
                    raw = self._text_of(entry.result.message)
                    self._cache[entry.custom_id] = self._parse_aliases(raw)
                    succeeded += 1
                else:
                    not_succeeded += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("enricher: reading batch %s results failed (%s)", batch.id, exc)
        self._save_cache(source, self._cache)
        logger.info(
            "enricher: batch %s ended — %d succeeded, %d errored/expired (those go online)",
            batch.id, succeeded, not_succeeded,
        )

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
