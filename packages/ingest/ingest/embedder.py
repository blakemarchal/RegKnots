"""
OpenAI text-embedding-3-small batch embedder with exponential backoff.
"""

import asyncio
import logging
from collections.abc import Callable

from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError

from ingest.models import Chunk, EmbeddedChunk

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50
MAX_RETRIES = 5


class EmbedderClient:
    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key)

    async def close(self) -> None:
        await self._client.close()

    async def embed_chunks(
        self,
        chunks: list[Chunk],
        on_batch: Callable[[int, int], None] | None = None,
    ) -> list[EmbeddedChunk]:
        """Embed chunks in batches of BATCH_SIZE.

        Args:
            chunks: Chunks to embed.
            on_batch: Optional callback(completed, total) called after each batch.

        Returns:
            EmbeddedChunk list in the same order as input.
        """
        results: list[EmbeddedChunk] = []
        total = len(chunks)

        for i in range(0, total, BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            embeddings = await self._embed_with_retry(batch)

            for chunk, embedding in zip(batch, embeddings):
                results.append(
                    EmbeddedChunk(
                        source=chunk.source,
                        title_number=chunk.title_number,
                        section_number=chunk.section_number,
                        section_title=chunk.section_title,
                        chunk_index=chunk.chunk_index,
                        chunk_text=chunk.chunk_text,
                        content_hash=chunk.content_hash,
                        token_count=chunk.token_count,
                        up_to_date_as_of=chunk.up_to_date_as_of,
                        parent_section_number=chunk.parent_section_number,
                        embedding=embedding,
                    )
                )

            if on_batch is not None:
                on_batch(min(i + BATCH_SIZE, total), total)

        return results

    async def _embed_with_retry(self, batch: list[Chunk]) -> list[list[float]]:
        texts = [c.chunk_text for c in batch]

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=EMBED_MODEL,
                    input=texts,
                )
                return [item.embedding for item in response.data]

            except RateLimitError:
                wait = 5 * (2 ** attempt)  # 5, 10, 20, 40, 80 seconds
                logger.warning(
                    f"Rate limit hit, waiting {wait}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(wait)

            except (APIError, APIConnectionError) as exc:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    f"API error ({exc}), waiting {wait}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(wait)

            except Exception as exc:
                # Catch connection timeouts, httpx errors, etc.
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = 3 * (2 ** attempt)  # 3, 6, 12, 24, 48 seconds
                logger.warning(
                    f"Unexpected error ({type(exc).__name__}: {exc}), "
                    f"waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(wait)

        raise RuntimeError(f"Embedding failed after {MAX_RETRIES} attempts")
