"""2026-09-27 — the company-documents block never fails an answer."""
import asyncio

from rag.engine import _await_company_block


def test_block_returned_skipped_on_error_and_none_without_a_task():
    async def ok():
        return "COMPANY DOCUMENTS ..."

    async def broken():
        raise RuntimeError("db down")

    async def run(coro_fn):
        task = asyncio.create_task(coro_fn()) if coro_fn else None
        return await _await_company_block(task)

    assert asyncio.run(run(ok)) == "COMPANY DOCUMENTS ..."
    assert asyncio.run(run(broken)) is None
    assert asyncio.run(run(None)) is None
