import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
from pydantic import BaseModel

BASE_URL = "https://www.ecfr.gov/api"
VERSIONER = f"{BASE_URL}/versioner/v1"
RENDERER = f"{BASE_URL}/renderer/v1"

# Titles relevant to maritime regulatory compliance
MARITIME_TITLES = {
    33: "Navigation and Navigable Waters",
    46: "Shipping",
    49: "Transportation",
}

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"


class TitleInfo(BaseModel):
    number: int
    name: str
    latest_amended_on: str | None = None
    latest_issue_date: str | None = None
    up_to_date_as_of: str | None = None
    reserved: bool


class ECFRClient:
    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self._last_request: float = 0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        self._last_request = asyncio.get_event_loop().time()

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        await self._throttle()
        response = await client.get(url, timeout=60.0)
        response.raise_for_status()
        return response

    async def list_titles(self) -> list[TitleInfo]:
        async with httpx.AsyncClient() as client:
            resp = await self._get(client, f"{VERSIONER}/titles")
            data = resp.json()
            return [TitleInfo(**t) for t in data["titles"]]

    async def fetch_structure(
        self, title_number: int, as_of: date | None = None
    ) -> dict:
        as_of = as_of or date.today()
        url = f"{VERSIONER}/structure/{as_of.isoformat()}/title-{title_number}.json"
        async with httpx.AsyncClient() as client:
            resp = await self._get(client, url)
            return resp.json()

    async def fetch_full_xml(
        self, title_number: int, as_of: date | None = None
    ) -> bytes:
        """Fetch the complete CFR title as XML. Returns raw bytes for lxml.

        Uses a 10-minute timeout — Title 46 can be 50-100 MB.
        """
        as_of = as_of or date.today()
        url = f"{VERSIONER}/full/{as_of.isoformat()}/title-{title_number}.xml"
        async with httpx.AsyncClient() as client:
            await self._throttle()
            response = await client.get(url, timeout=600.0)
            response.raise_for_status()
            self._last_request = asyncio.get_event_loop().time()
            return response.content

    async def fetch_full_text(
        self, title_number: int, as_of: date | None = None
    ) -> str:
        as_of = as_of or date.today()
        url = f"{RENDERER}/content/enhanced/{as_of.isoformat()}/title-{title_number}"
        async with httpx.AsyncClient() as client:
            resp = await self._get(client, url)
            return resp.text

    async def ingest_titles(
        self, title_numbers: list[int], fetch_text: bool = False
    ) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        titles = await self.list_titles()
        titles_file = DATA_DIR / "titles.json"
        titles_file.write_text(
            json.dumps([t.model_dump() for t in titles], indent=2)
        )
        print(f"Saved {len(titles)} titles to {titles_file}")

        titles_by_number = {t.number: t for t in titles}

        for num in title_numbers:
            if num not in MARITIME_TITLES:
                print(f"Warning: Title {num} is not a known maritime title, skipping")
                continue

            title_info = titles_by_number.get(num)
            if not title_info or not title_info.up_to_date_as_of:
                print(f"Warning: No date info for Title {num}, skipping")
                continue

            as_of = date.fromisoformat(title_info.up_to_date_as_of)
            print(f"\nFetching Title {num} ({MARITIME_TITLES[num]}) as of {as_of}...")

            print(f"  Fetching structure...")
            structure = await self.fetch_structure(num, as_of=as_of)
            structure_file = DATA_DIR / f"title-{num}-structure.json"
            structure_file.write_text(json.dumps(structure, indent=2))
            print(f"  Saved structure to {structure_file}")

            if fetch_text:
                print(f"  Fetching full text (this may take a while)...")
                text = await self.fetch_full_text(num, as_of=as_of)
                text_file = DATA_DIR / f"title-{num}-full.html"
                text_file.write_text(text)
                print(f"  Saved full text to {text_file}")
