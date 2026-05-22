"""
Headless-browser harness for SPA-rendered sources.

Sprint D6.97 (2026-05-22) — for sources where the rules portal is a
JavaScript SPA (DNV's rules.dnv.com is 739 bytes of React shell;
Malta is Cloudflare-protected with similar render-side gating;
deeper BV NRs aren't link-discoverable from static HTML), httpx
alone can't see the actual content. This module provides a
Playwright-backed Chromium launcher that runs ONLY during an active
ingest and is torn down on exit.

RAM contract (per the 2026-05-22 Blake constraint):
  - Chromium binary lives on disk (~200 MB at ~/.cache/ms-playwright/
    chromium-XXXX/). Zero RAM cost when not in use.
  - On launch: ~300-500 MB resident.
  - The context manager guarantees cleanup on normal exit AND on
    exception. The browser process is killed when the async-with
    block leaves.
  - When the ingest unit deactivates (systemd-run --collect), all
    process memory is released. Idle cost = 0.

Standard usage pattern (per the DNV adapter):

    async with headless_browser() as ctx:
        pdfs = await capture_pdf_urls(
            ctx,
            "https://rules.dnv.com/document/<id>",
        )
    # browser is gone here; pdfs is a list[str]
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)


_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def headless_browser(
    *,
    user_agent: str | None = None,
    timeout_ms: int = 30_000,
    viewport: tuple[int, int] = (1366, 900),
) -> AsyncIterator["BrowserContext"]:  # noqa: F821 — Playwright type imported below
    """Launch a headless Chromium, yield a BrowserContext, tear down on exit.

    The browser process exists ONLY for the duration of the async-with
    block. No persistent state, no shared instance, no idle RAM cost.

    Args:
      user_agent: Override the default UA string. Default is a stock
        Chrome-on-Windows fingerprint that matches what httpx-based
        adapters send (keeps server-side analytics consistent).
      timeout_ms: Per-page navigation timeout in milliseconds.
      viewport: (width, height) of the simulated browser window. Some
        SPAs render different content for mobile vs desktop viewports.

    Yields:
      A Playwright BrowserContext. Callers spawn pages with
      `ctx.new_page()` and close them explicitly. The context is
      closed by the harness on exit.
    """
    # Late import so the playwright dependency isn't loaded for
    # adapters that don't need it (most of them).
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                # Standard "play nice in container" flags. Without
                # --no-sandbox Chromium refuses to launch as root on
                # most Linux containers; --disable-dev-shm-usage avoids
                # /dev/shm exhaustion on small VPSes.
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # Modest stealth: don't advertise that we're Playwright
                # via the navigator.webdriver property + automation
                # control banner. More aggressive stealth (worker-thread
                # tweaks, removing the chrome.runtime.webdriver hook)
                # is available via playwright-stealth but adds another
                # dependency — keep it minimal until we hit a source
                # that actually fingerprints us.
                "--disable-blink-features=AutomationControlled",
            ],
        )
        try:
            ctx = await browser.new_context(
                user_agent=user_agent or _DEFAULT_UA,
                viewport={"width": viewport[0], "height": viewport[1]},
            )
            ctx.set_default_timeout(timeout_ms)
            try:
                yield ctx
            finally:
                await ctx.close()
        finally:
            await browser.close()


async def capture_pdf_urls(
    ctx,
    url: str,
    *,
    wait_for_selector: str | None = None,
    settle_ms: int = 1500,
    network_capture: bool = True,
    pdf_url_re: re.Pattern | None = None,
) -> list[str]:
    """Navigate to URL, wait for it to settle, return PDF URLs found
    in the rendered DOM AND optionally in captured network traffic.

    The two extraction paths catch different things:
      - DOM grep finds <a href> targets and inline state that the SPA
        has rendered into the visible page.
      - Network capture catches XHR responses where PDFs are linked
        inside JSON payloads (common for tree-style document portals).

    Returns a deduplicated, sorted list of fully-qualified PDF URLs.
    """
    page = await ctx.new_page()
    pdfs_seen: set[str] = set()

    if network_capture:
        def _on_response(resp):
            try:
                u = resp.url
                if u.lower().split("?", 1)[0].endswith(".pdf"):
                    pdfs_seen.add(u)
            except Exception:
                pass
        page.on("response", _on_response)

    try:
        await page.goto(url, wait_until="networkidle")
        if wait_for_selector:
            await page.wait_for_selector(wait_for_selector, timeout=15_000)
        if settle_ms > 0:
            await page.wait_for_timeout(settle_ms)
        # Grep the rendered HTML for any PDF URLs not seen via network
        # (e.g., links the SPA placed in the DOM but didn't fetch).
        html = await page.content()
        regex = pdf_url_re or re.compile(
            r'https?://[^\s"\'<>]+?\.pdf', re.IGNORECASE,
        )
        pdfs_seen.update(regex.findall(html))
    finally:
        await page.close()

    return sorted(pdfs_seen)


async def capture_api_responses(
    ctx,
    url: str,
    *,
    wait_for_selector: str | None = None,
    settle_ms: int = 2000,
    filter_re: re.Pattern | None = None,
) -> list[dict]:
    """Navigate to URL and capture every non-asset network response.

    Used for reverse-engineering SPAs: visit a page, observe which
    backend endpoints the React app hits, then build an adapter that
    calls those endpoints directly with httpx (cheaper than running
    Chromium per ingest).

    Returns a list of {url, status, content_type, response_text}
    dicts. Static assets (css/js/woff/images) are excluded by
    default. Pass filter_re to further narrow.
    """
    page = await ctx.new_page()
    captured: list[dict] = []
    asset_re = re.compile(
        r"\.(css|js|mjs|woff2?|ttf|svg|png|jpg|jpeg|gif|ico|webp)(\?|$)",
        re.IGNORECASE,
    )

    async def _record(resp):
        try:
            u = resp.url
            if asset_re.search(u):
                return
            if filter_re and not filter_re.search(u):
                return
            ct = resp.headers.get("content-type", "")
            body = ""
            # Only read the body for textual / JSON responses, and cap
            # at 200 KB to avoid memory bloat on big payloads.
            if "json" in ct.lower() or "text" in ct.lower():
                try:
                    raw = await resp.body()
                    body = raw[:200_000].decode("utf-8", errors="replace")
                except Exception:
                    body = ""
            captured.append({
                "url":          u,
                "status":       resp.status,
                "content_type": ct,
                "body":         body,
            })
        except Exception as exc:
            logger.debug("capture_api_responses: %s", exc)

    # Playwright Python's event listeners accept async functions
    # directly — the framework schedules them on the event loop.
    page.on("response", _record)

    try:
        await page.goto(url, wait_until="networkidle")
        if wait_for_selector:
            await page.wait_for_selector(wait_for_selector, timeout=15_000)
        if settle_ms > 0:
            await page.wait_for_timeout(settle_ms)
    finally:
        await page.close()

    return captured
