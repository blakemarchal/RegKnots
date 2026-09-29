"""2026-09-29 — the admin's IMO / NMC checks run off the API's event loop.

Their scrapers call blocking requests.get (30 s timeout each); awaited on the
loop they froze every other request until the scrape finished."""
import asyncio
import importlib
import threading
import time

ADMIN = importlib.import_module("app.routers.admin")


def test_blocking_task_body_does_not_freeze_the_loop():
    done: dict[str, float] = {}
    task_thread: dict[str, int] = {}

    async def task_body():
        task_thread["id"] = threading.get_ident()
        time.sleep(0.3)  # stands in for requests.get
        done["task"] = time.monotonic()

    async def other_requests():
        for _ in range(5):
            await asyncio.sleep(0.01)
        done["others"] = time.monotonic()

    async def main():
        await asyncio.gather(ADMIN._run_task_off_loop(task_body), other_requests())

    asyncio.run(main())
    assert task_thread["id"] != threading.get_ident()
    assert done["others"] < done["task"]
