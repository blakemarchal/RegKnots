"""
Standalone semantic search test against the regulations table.

Usage:
    uv run python test_search.py
"""

import asyncio
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

import os  # noqa: E402 — must come after load_dotenv

QUERY = "lifeboat inspection requirements for cargo vessels"
TOP_K = 5
EMBED_MODEL = "text-embedding-3-small"


async def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    database_url = os.environ.get("REGKNOTS_DATABASE_URL", "")

    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        return
    if not database_url:
        print("ERROR: REGKNOTS_DATABASE_URL not set in .env")
        return

    # 1. Embed the query
    client = AsyncOpenAI(api_key=api_key)
    response = await client.embeddings.create(model=EMBED_MODEL, input=[QUERY])
    await client.close()

    embedding = response.data[0].embedding
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

    # 2. Vector search
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    rows = await pool.fetch(
        """
        SELECT source, section_number, section_title, full_text,
               1 - (embedding <=> $1::vector) AS similarity
        FROM regulations
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        vec_literal,
        TOP_K,
    )
    await pool.close()

    # 3. Print results
    print(f'\nQuery: "{QUERY}"\n')
    print(f"{'#':<3} {'Sim':>6}  {'Source':<8} {'Section':<22} {'Title'}")
    print("-" * 90)
    for i, row in enumerate(rows, 1):
        title = (row["section_title"] or "")[:45]
        print(f"{i:<3} {row['similarity']:>6.4f}  {row['source']:<8} {row['section_number']:<22} {title}")
        snippet = (row["full_text"] or "")[:150].replace("\n", " ")
        print(f"    {snippet}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
