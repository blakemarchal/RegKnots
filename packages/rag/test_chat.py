"""
Standalone RAG chat smoke test.

Usage:
    uv run python test_chat.py
"""

import asyncio
import uuid
from pathlib import Path

import asyncpg
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

import os  # noqa: E402

QUERY = "What are the lifeboat inspection requirements for a cargo vessel on an international route?"


async def main() -> None:
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    database_url = os.environ.get("REGKNOTS_DATABASE_URL", "")

    missing = [k for k, v in [
        ("OPENAI_API_KEY", openai_api_key),
        ("ANTHROPIC_API_KEY", anthropic_api_key),
        ("REGKNOTS_DATABASE_URL", database_url),
    ] if not v]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        return

    # Import here so load_dotenv runs first
    from rag.engine import chat
    from rag.router import route_query

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    anthropic_client = AsyncAnthropic(api_key=anthropic_api_key)

    try:
        # Show router decision separately for diagnostics
        from rag.router import route_query as _route
        route = await _route(QUERY, anthropic_client)
        print(f"\nQuery: {QUERY!r}")
        print(f"\nRouter decision: score={route.score}, model={route.model}")

        # Run retriever to show chunk count
        from rag.retriever import retrieve as _retrieve
        chunks = await _retrieve(
            query=QUERY,
            pool=pool,
            openai_api_key=openai_api_key,
            limit=8,
        )
        print(f"Chunks retrieved: {len(chunks)}")

        # Full engine run
        response = await chat(
            query=QUERY,
            conversation_history=[],
            vessel_profile=None,
            pool=pool,
            anthropic_client=anthropic_client,
            openai_api_key=openai_api_key,
            conversation_id=uuid.uuid4(),
        )
    finally:
        await pool.close()
        await anthropic_client.close()

    def _p(text: str) -> None:
        """Print with non-encodable chars replaced rather than crashing."""
        import sys
        sys.stdout.buffer.write((text + "\n").encode(sys.stdout.encoding, errors="replace"))

    _p(f"\n{'=' * 70}")
    _p("ANSWER")
    _p("=" * 70)
    _p(response.answer)

    _p(f"\n{'=' * 70}")
    _p(f"CITED REGULATIONS ({len(response.cited_regulations)})")
    _p("=" * 70)
    for reg in response.cited_regulations:
        _p(f"  [{reg.source}] {reg.section_number} -- {reg.section_title}")

    _p(f"\nTokens: {response.input_tokens} in / {response.output_tokens} out")


if __name__ == "__main__":
    asyncio.run(main())
