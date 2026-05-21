"""
Australian Maritime Safety Authority (AMSA) Marine Orders source adapter.

Sprint D6.20 — RegKnots' first non-US/non-UK national-flag corpus. AMSA
Marine Orders are Australia's primary maritime regulatory instruments,
each covering one operational topic (drills, manning, lifesaving, fire,
construction, dangerous goods, MARPOL implementation, etc.). They sit
at the same authoritative level as UK MSNs — Tier 1 (binding).

License: Creative Commons Attribution 4.0 International (CC BY 4.0),
per https://www.amsa.gov.au/copyright. Required attribution string:
"© Australian Maritime Safety Authority" with a link to the source.

Two-step retrieval:
  1. AMSA landing page (gov.au/about/regulations-and-standards/...) —
     a stub with a 250-word summary and an outbound link to the
     authoritative consolidated text on legislation.gov.au.
  2. legislation.gov.au — `/<series_id>/latest/text` returns the
     consolidated HTML body. This is the substantive regulatory text
     we want to ingest.

The adapter:
  * Knows the AMSA landing slug for each Order in the curated phase-1
    list (~25 Orders covering the Tier-1 operational surface).
  * Visits the landing page to discover the current legislation.gov.au
    series ID (resilient to series-ID changes when AMSA reissues an
    Order — we always follow the link AMSA itself publishes).
  * Fetches the `/latest/text` body, strips GOV.AU chrome, saves as
    `data/raw/amsa/mo_<number>.html`.

Section numbering convention:
  section_number = "Marine Order <N>"        e.g. "Marine Order 21"
  parent_section_number = "AMSA Marine Orders"

Phase-1 sources only the consolidated current version. Amendment
history (OPC compilation C01/C02/...) is preserved by AMSA's series
page and can be added as a phase-2 freshness signal.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from ingest.models import Section

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

SOURCE       = "amsa_mo"
TITLE_NUMBER = 0
# D6.97 AU sprint 1a (2026-05-21) — bumped from 2026-04-28 so the
# `--update` freshness gate re-processes after the DCV 500-series
# entries were added. The freshness check compares this constant
# against the DB's stored up_to_date_as_of date and skips entirely
# if equal — that's correct behavior in steady state but blocks
# adapter expansions like this one until the date moves.
SOURCE_DATE  = date(2026, 5, 21)  # adapter publication, not Order edition

_AMSA_BASE      = "https://www.amsa.gov.au"
_LEGIS_BASE     = "https://www.legislation.gov.au"
_USER_AGENT     = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
_REQUEST_DELAY = 1.5  # respectful — gov.au is on AWS, multi-request crawl
_TIMEOUT       = 60.0

# Pattern to find the legislation.gov.au series ID embedded in an AMSA
# landing page. Series IDs look like F2016L01076 / F2024C00338 — the F
# prefix + 4-digit year + letter + 5-digit sequence.
#
# D6.97 AU sprint 1a — broadened to accept legislation.gov.au's full
# path variation: Navigation-Act-era MOs link as /<id> or /Series/<id>,
# but DCV-era MOs (the 500-series) link via /Details/<id>. Pre-fix the
# regex missed Details/ entirely, causing MO 50, 501, 505 to fail
# discovery with "No legislation.gov.au series ID found" even when the
# landing page DID contain the link.
_LEGIS_SERIES_RE = re.compile(
    r"https?://(?:www\.)?legislation\.gov\.au/(?:Series/|Details/)?(F\d{4}[A-Z]\d{5})",
    re.IGNORECASE,
)

# Pattern to find the consolidated-text PDF URL on a legislation.gov.au
# /downloads page. Two URL flavours exist:
#   /<series>/2024-01-01/2024-01-01/text/original/pdf     (compiled — has amendments)
#   /<series>/asmade/2023-11-23/text/original/pdf         (as-made — no amendments)
# We anchor on `/text/original/pdf` to exclude the "/es/original/pdf"
# explanatory-statement URL that lives next to it on the same page.
_LEGIS_PDF_RE = re.compile(
    r"https?://(?:www\.)?legislation\.gov\.au/F\d{4}[A-Z]\d{5}/"
    r"[^\s\"'<>]*?/text/original/pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OrderMeta:
    number:        str          # "21", "30", "70"
    title:         str
    amsa_slug:     str          # path under /about/regulations-and-standards/
    category:      str          # for filtering / debugging

    @property
    def section_number(self) -> str:
        return f"Marine Order {self.number}"

    @property
    def parent_section_number(self) -> str:
        return "AMSA Marine Orders"

    @property
    def filename_stub(self) -> str:
        return f"mo_{self.number}"


# ── Curated phase-1 list ─────────────────────────────────────────────────────
# 25 Marine Orders covering the operational surface for Tier-1 vessel
# types (passenger, cargo, tanker, offshore, fishing). Each entry has
# the AMSA landing slug; the adapter resolves the legislation.gov.au
# URL at download time.

_CURATED_ORDERS: list[OrderMeta] = [
    OrderMeta("1",  "Administration",
              "marine-order-1-administration", "administration"),
    OrderMeta("11", "Living and working conditions on vessels",
              "marine-order-11-living-and-working-conditions-vessels", "manning"),
    OrderMeta("12", "Construction — subdivision and stability",
              "marine-order-12-construction-subdivision-and-stability-machinery-and", "construction"),
    OrderMeta("15", "Construction — fire protection, fire detection and fire extinction",
              "marine-order-15-construction-fire-protection-fire-detection-and-fire", "fire"),
    OrderMeta("21", "Safety and emergency arrangements",
              "marine-order-21-safety-and-emergency-arrangements", "drills_emergency"),
    OrderMeta("25", "Equipment — lifesaving",
              "marine-order-25-equipment-lifesaving", "lsa"),
    OrderMeta("28", "Operations standards and procedures",
              "marine-order-28-operations-standards-and-procedures", "operations"),
    OrderMeta("30", "Prevention of collisions",
              "marine-order-30-prevention-collisions", "navigation"),
    OrderMeta("31", "SOLAS and non-SOLAS certification",
              "marine-order-31-solas-and-non-solas-certification", "certification"),
    OrderMeta("32", "Cargo handling equipment",
              "marine-order-32-cargo-handling-equipment", "cargo"),
    OrderMeta("41", "Carriage of dangerous goods",
              "marine-order-41-carriage-dangerous-goods", "dangerous_goods"),
    OrderMeta("42", "Carriage, stowage and securing of cargoes and containers",
              "marine-order-42-carriage-stowage-and-securing-cargoes-and-containers", "cargo"),
    OrderMeta("43", "Cargo and cargo handling — livestock",
              "marine-order-43-cargo-and-cargo-handling-livestock", "cargo_livestock"),
    OrderMeta("47", "Offshore industry units",
              "marine-order-47-offshore-industry-units", "offshore"),
    OrderMeta("50", "Special purpose vessels",
              "marine-order-50-special-purpose-vessels", "special_purpose"),
    OrderMeta("51", "Fishing vessels",
              "marine-order-51-fishing-vessels", "fishing"),
    OrderMeta("54", "Coastal pilotage",
              "marine-order-54-coastal-pilotage", "pilotage"),
    OrderMeta("70", "Seafarer certification",
              "marine-order-70-seafarer-certification", "certification"),
    OrderMeta("71", "Masters and deck officers",
              "marine-order-71-masters-and-deck-officers", "manning"),
    OrderMeta("72", "Engineer officers",
              "marine-order-72-engineer-officers", "manning"),
    OrderMeta("73", "Ratings",
              "marine-order-73-ratings", "manning"),
    OrderMeta("74", "Masters and deck officers — yachts",
              "marine-order-74-masters-and-deck-officers-yachts", "manning_yachts"),
    OrderMeta("91", "Marine pollution prevention — oil",
              "marine-order-91-marine-pollution-prevention-oil", "marpol"),
    OrderMeta("95", "Marine pollution prevention — garbage",
              "marine-order-95-marine-pollution-prevention-garbage", "marpol"),
    OrderMeta("97", "Marine pollution prevention — air pollution",
              "marine-order-97-marine-pollution-prevention-air-pollution", "marpol"),

    # ── D6.97 AU corpus sprint (2026-05-21) — DCV 500-series ─────────────
    # The 500-series Marine Orders are AMSA's Domestic Commercial Vessel
    # operational framework, made under the Marine Safety (DCV) National
    # Law Act 2012 (vs. the Navigation Act 2012 surface covered by the
    # 1-100 series above). Added after a paying-curious AU signup hit a
    # DCV-ECDIS question and our retrieval had no DCV-specific MO to
    # surface — only the international-voyage MOs, which led the
    # synthesizer to hedge ("my knowledge base does not include AMSA
    # Marine Orders 505/506").
    #
    # Index reference: https://www.amsa.gov.au/about/regulations-and-standards/index-marine-orders
    # MO 506 is intentionally NOT in this list — it's been repealed; the
    # AMSA index page (last fetched 2026-05-21) jumps 505 → 507. Any
    # model output referring to "MO 506 (Navigation equipment)" is a
    # hallucination — DCV nav equipment requirements come from NSCV
    # Part C5B (separate corpus, separate adapter in phase 1b).
    OrderMeta("501", "Administration — national law",
              "marine-order-501-administration-national-law", "dcv_administration"),
    OrderMeta("502", "Vessel identifiers — national law",
              "marine-order-502-vessel-identifiers-national-law", "dcv_identifiers"),
    # MO 503's landing page sits at the site root (/marine-order-503-...)
    # rather than under /about/regulations-and-standards/. The leading
    # "/" tells the adapter to treat the slug as an absolute path.
    OrderMeta("503", "Certificates of survey — national law",
              "/marine-order-503-certificates-survey-national-law", "dcv_survey"),
    OrderMeta("504", "Certificates of operation — national law",
              "marine-order-504-certificates-operation", "dcv_operation"),
    OrderMeta("505", "Certificates of competency — national law",
              "marine-order-505-certificates-competency-national-law", "dcv_competency"),
    OrderMeta("507", "Load line certificates — national law",
              "marine-order-507-load-line-certificates-national-law", "dcv_load_line"),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console
) -> tuple[int, int]:
    """For each Marine Order: visit AMSA landing page → discover the
    legislation.gov.au series ID → fetch /<id>/latest/text. Save the
    HTML body to data/raw/amsa/mo_<number>.html.

    Idempotent: pre-existing .html files >5KB are kept (re-runs don't
    redownload). The intermediate landing-page response is not cached
    (it's only used to discover the series ID, which goes into index.json).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    series_map: dict[str, str] = {}     # mo_number → series ID

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_ORDERS, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                logger.debug("AMSA %s: already present, skipping", meta.section_number)
                success += 1
                continue
            try:
                console.print(
                    f"  Resolving Marine Order {meta.number} "
                    f"({i}/{len(_CURATED_ORDERS)})…"
                )
                # Step 1: AMSA landing page → series ID.
                #
                # D6.97 AU sprint 1a — most MO landing pages live under
                # /about/regulations-and-standards/<slug>, but a few
                # (notably MO 503) sit at the site root /<slug>. If the
                # configured amsa_slug starts with "/" treat it as an
                # absolute path; otherwise prepend the standard prefix.
                if meta.amsa_slug.startswith("/"):
                    landing_url = f"{_AMSA_BASE}{meta.amsa_slug}"
                else:
                    landing_url = f"{_AMSA_BASE}/about/regulations-and-standards/{meta.amsa_slug}"
                resp = client.get(landing_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                series_id = _extract_series_id(resp.text)
                if not series_id:
                    raise ValueError(
                        f"No legislation.gov.au series ID found in {landing_url}"
                    )
                series_map[meta.number] = series_id

                # Step 2: legislation.gov.au /<series>/latest/downloads → find the
                # dated PDF URL. The /text endpoint returns a JS-rendered SPA so
                # BeautifulSoup just sees navigation chrome. The /downloads page
                # is plain HTML and exposes the PDF link directly.
                time.sleep(_REQUEST_DELAY)
                downloads_url = f"{_LEGIS_BASE}/{series_id}/latest/downloads"
                resp2 = client.get(downloads_url, headers=_BROWSER_HEADERS)
                resp2.raise_for_status()
                m = _LEGIS_PDF_RE.search(resp2.text)
                if not m:
                    raise ValueError(
                        f"No PDF URL found on {downloads_url}"
                    )
                pdf_url = m.group(0)

                # Step 3: fetch the consolidated PDF
                time.sleep(_REQUEST_DELAY)
                resp3 = client.get(pdf_url, headers=_BROWSER_HEADERS)
                resp3.raise_for_status()
                if not resp3.content.startswith(b"%PDF"):
                    raise ValueError(
                        f"Response is not a PDF (got {resp3.content[:32]!r})"
                    )
                out_path.write_bytes(resp3.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning(
                    "AMSA %s: failed — %s", meta.section_number, exc,
                )
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED_ORDERS):
                time.sleep(_REQUEST_DELAY)

    # Cache the index for parse_source.
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "number":     m.number,
                    "title":      m.title,
                    "amsa_slug":  m.amsa_slug,
                    "category":   m.category,
                    "series_id":  series_map.get(m.number, ""),
                }
                for m in _CURATED_ORDERS
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded Marine Order HTML bodies into Section objects."""
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"AMSA index cache not found at {cache_path}. "
            "Run discovery first (discover_and_download)."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        meta = OrderMeta(
            number=e["number"],
            title=e["title"],
            amsa_slug=e["amsa_slug"],
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("AMSA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("AMSA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 500:
            logger.warning(
                "AMSA %s: extracted text too short (%d chars), skipping",
                meta.section_number, len(text),
            )
            continue
        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = meta.section_number,
            section_title         = meta.title,
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = meta.parent_section_number,
        ))

    logger.info(
        "AMSA: parsed %d sections from %d Order(s)", len(sections), len(entries),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    """Phase 1 returns adapter SOURCE_DATE; per-Order edition tracking
    is a phase-2 enhancement (would require parsing the compilation
    info on each legislation.gov.au series page).
    """
    return SOURCE_DATE


# ── Internal helpers ─────────────────────────────────────────────────────────

def _extract_series_id(amsa_html: str) -> str | None:
    """Find the FXXXXLXXXXX or FXXXXCXXXXX series ID in an AMSA landing page."""
    m = _LEGIS_SERIES_RE.search(amsa_html)
    return m.group(1).upper() if m else None


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract page-joined text from a consolidated Marine Order PDF.

    legislation.gov.au PDFs have a consistent header/footer (compilation
    metadata, Authorised Version notice, page numbers) — we strip those
    and let the chunker handle paragraph splitting downstream.
    """
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = _AUTHORISED_VERSION_LINE.sub("", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
_AUTHORISED_VERSION_LINE = re.compile(
    r"(?im)^.*Authorised\s+Version.*$"
)


def _write_failure(meta: OrderMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "amsa_slug":      meta.amsa_slug,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"amsa_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
