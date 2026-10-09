"""2026-10-08 — ingest the official documents the phase-2 web research finds (app/web_ingest.py)."""
import asyncio

from app import web_ingest as WI


def test_which_domains_are_ingested():
    assert WI.ingest_decision("https://wwwcdn.imo.org/x/MSC.576(110).pdf") is None
    assert WI.ingest_decision("https://www.dco.uscg.mil/Portals/9/NVIC/2016/NVIC_03-16.pdf") is None
    assert WI.ingest_decision("https://www.gov.uk/government/publications/mgn-123") is None
    assert WI.ingest_decision("https://ww2.eagle.org/rules.pdf") is None                       # class society
    assert "CFR" in WI.ingest_decision("https://www.ecfr.gov/current/title-46/part-142")     # already in the library
    assert "commentary" in WI.ingest_decision("https://www.ukpandi.com/news/pilot-ladders")   # used, not ingested
    assert WI.ingest_decision("https://notagov.example.com/doc") is not None


def test_jurisdictions_by_domain():
    assert WI.jurisdictions_for("https://www.dco.uscg.mil/x") == ["us"]
    assert WI.jurisdictions_for("https://www.federalregister.gov/d/2025-00708") == ["us"]
    assert WI.jurisdictions_for("https://www.gov.uk/x") == ["uk"]
    assert WI.jurisdictions_for("https://www.amsa.gov.au/x") == ["au"]
    assert WI.jurisdictions_for("https://www.register-iri.com/x") == ["mh"]
    assert WI.jurisdictions_for("https://wwwcdn.imo.org/x") == ["intl"]


def test_pick_source_needs_an_official_verified_source():
    blog = {"url": "https://ukpandi.com/a", "verified": True}
    unverified = {"url": "https://www.uscg.mil/b", "verified": False}
    good = {"url": "https://www.uscg.mil/c", "verified": True}
    assert WI.pick_source([blog, unverified, good])[0] is good
    src, why = WI.pick_source([blog, unverified])
    assert src is None and "not verified" in why


def test_html_to_text_keeps_the_main_content():
    page = ("<html><head><style>.x{}</style><script>var a=1</script></head><body><nav>Home | About</nav>"
            "<main><h1>Pilot ladders</h1><p>" + "Steps must be 25 mm thick. " * 100 + "</p></main>"
            "<footer>Contact us</footer></body></html>")
    text = WI.html_to_text(page)
    assert text.startswith("Pilot ladders") and "var a" not in text and "Home | About" not in text
    assert "Contact us" not in text


class Pool:
    def __init__(self, existing=None):
        self.existing, self.inserted = existing, []

    async def fetchval(self, sql, *args):
        return self.existing if "source_version = $1" in sql else None

    async def executemany(self, sql, rows):
        self.inserted = rows


GAP = {"id": "g1", "sources": [{"url": "https://www.dco.uscg.mil/nvic.pdf", "title": "NVIC 03-16", "publisher": "USCG",
                                "domain": "dco.uscg.mil", "quote": "Towing officers must complete the TOAR",
                                "verified": True}]}


def test_ingest_gap_writes_chunks(monkeypatch):
    async def pages(url):
        return ["Towing officers must complete the TOAR. " * 80, "Second page text. " * 80]

    async def embed(texts, key):
        return [[0.0] * 3 for _ in texts]
    monkeypatch.setattr(WI, "fetch_pages", pages)
    monkeypatch.setattr(WI, "embed_texts", embed)
    pool = Pool()
    status, note, section, url = asyncio.run(WI.ingest_gap(pool, dict(GAP), "key"))
    assert status == "ingested" and section == "USCG: NVIC 03-16" and url.endswith("nvic.pdf")
    row = pool.inserted[0]
    assert row[0].endswith("nvic.pdf") and row[2] == "USCG: NVIC 03-16" and row[9] == ["us"]
    assert row[4].startswith("[USCG: NVIC 03-16] NVIC 03-16")


def test_ingest_gap_refusals(monkeypatch):
    assert asyncio.run(WI.ingest_gap(Pool(existing="USCG: NVIC 03-16"), dict(GAP), "k"))[0:2] == \
        ("ingested", "already in the library")

    async def short(url):
        return ["too short"]
    monkeypatch.setattr(WI, "fetch_pages", short)
    assert asyncio.run(WI.ingest_gap(Pool(), dict(GAP), "k"))[0] == "ingest_skipped"

    async def other(url):
        return ["Different text entirely. " * 200]
    monkeypatch.setattr(WI, "fetch_pages", other)
    status, note, *_ = asyncio.run(WI.ingest_gap(Pool(), dict(GAP), "k"))
    assert status == "ingest_skipped" and "quote" in note
