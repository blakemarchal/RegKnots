"""Federal Register API discovery utility — NOT an ingest adapter.

Enumerates USCG publications announced in the Federal Register so the
RegKnot corpus can be cross-referenced for missing documents. Used by:

  - One-off gap reports (this sprint, packages/ingest/scripts/...)
  - Future Sprint D observability (daily cross-reference of new FR
    publications against ingested rows)

The Federal Register API is public, no auth, ~60 req/min rate limit.
The pdf_url field on USCG documents reliably resolves to govinfo.gov,
which is NOT behind Akamai's WAF — direct fetch is feasible. Documents
posted on dco.uscg.mil only are absent from FR (e.g. NVICs published as
guidance rather than rulemaking are NOT in FR — this is the known
discovery weakness).

CLI:
    uv run python -m ingest.sources.federal_register_discovery \\
        --category nvic \\
        --output data/reports/fr_discovery_nvic.csv

    Categories: nvic | nmc | msib
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_API_BASE = "https://www.federalregister.gov/api/v1/documents.json"
_PER_PAGE = 100   # API maximum
_AGENCY_SLUG = "coast-guard"
_USER_AGENT = "RegKnot-FR-Discovery/1.0 (+https://regknots.com)"
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 4
_BASE_BACKOFF = 2.0


# ── Search definitions per category ──────────────────────────────────────────
#
# Each category is a list of search terms; results are deduplicated by
# document_number across the union. Phrases beat single tokens for precision
# but recall both are needed to catch FR's loose indexing.

_CATEGORY_TERMS: dict[str, list[str]] = {
    "nvic": [
        "Navigation and Vessel Inspection Circular",
        "NVIC",
    ],
    "nmc": [
        "NMC Policy Letter",
        "CG-MMC Policy Letter",
        "CG-CVC Policy Letter",
        "CG-OES Policy Letter",
        "Merchant Mariner Credential",
        "policy letter",
    ],
    "msib": [
        "Marine Safety Information Bulletin",
        "MSIB",
    ],
}


# ── Document-number inference ────────────────────────────────────────────────
#
# FR titles often embed the canonical USCG document number. Examples:
#   "Navigation and Vessel Inspection Circular (NVIC) 04-08, Change 2"
#       → NVIC 04-08 Ch-2
#   "CG-MMC Policy Letter 01-18; Harmonization …"
#       → CG-MMC PL 01-18
#   "Marine Safety Information Bulletin 04-22"
#       → MSIB 04-22
# The patterns below cover the most common forms; any missed match
# falls through to None and the gap-analyst can spot-check.

# Match either "NVIC" or "Navigation and Vessel Inspection Circular" anywhere
# in the title, optionally followed by "No.", followed by a 1-2 digit / 2 digit
# number. Examples this catches:
#   "NVIC 04-08"                                  → NVIC 04-08
#   "NVIC No. 02-16"                              → NVIC 02-16
#   "Navigation and Vessel Inspection Circular 2-10"  → NVIC 2-10
#   "(NVIC) 11-93 CH-3"                           → NVIC 11-93 Ch-3
#   "Change 2 to NVIC 02-18"                      → NVIC 02-18
_NVIC_PAT = re.compile(
    r"(?:NVIC|Navigation\s+and\s+Vessel\s+Inspection\s+Circular)"
    r"\s*(?:\([^)]*\))?"           # optional "(NVIC)" parenthetical
    r"\s*(?:No\.?|#)?\s*"          # optional "No.", "No", "#"
    r"(\d{1,2}-\d{2})"             # the actual number
    r"(?:[\s,]*(?:Change|Ch[.-]?)\s*[-\s]*(\d+))?",  # optional Ch-N
    re.IGNORECASE,
)
_NMC_PAT = re.compile(
    r"\b(CG-MMC|CG-CVC|CG-OES|NMC)\s*(?:Policy\s+Letter\s*(?:No\.\s*)?)?(\d{1,2}-\d{2})",
    re.IGNORECASE,
)
_MSIB_PAT = re.compile(
    r"(?:Marine\s+Safety\s+Information\s+Bulletin|MSIB)"
    r"\s*(?:\([^)]*\))?"
    r"\s*(?:No\.?|#)?\s*"
    r"(\d{1,3}[-/]\d{2,4})",
    re.IGNORECASE,
)


def _infer_document_number(category: str, title: str) -> str | None:
    """Best-effort extraction of canonical doc number from title."""
    if category == "nvic":
        m = _NVIC_PAT.search(title)
        if m:
            base = f"NVIC {m.group(1)}"
            if m.group(2):
                base += f" Ch-{m.group(2)}"
            return base
    elif category == "nmc":
        m = _NMC_PAT.search(title)
        if m:
            office = m.group(1).upper()
            if office == "NMC":
                return f"NMC PL {m.group(2)}"
            return f"{office} PL {m.group(2)}"
    elif category == "msib":
        m = _MSIB_PAT.search(title)
        if m:
            return f"MSIB {m.group(1)}"
    return None


def _pdf_host(pdf_url: str | None) -> str:
    """Return the bare hostname of a pdf_url, or 'none' if absent."""
    if not pdf_url:
        return "none"
    try:
        return urllib.parse.urlparse(pdf_url).hostname or "unknown"
    except Exception:
        return "unknown"


# ── HTTP fetch with retry ────────────────────────────────────────────────────


def _fetch_json(url: str) -> dict:
    """GET a JSON URL with exponential-backoff retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                if resp.status == 429:
                    sleep_for = _BASE_BACKOFF * (2 ** attempt)
                    logger.warning("FR rate-limit 429 — sleeping %.1fs", sleep_for)
                    time.sleep(sleep_for)
                    continue
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            sleep_for = _BASE_BACKOFF * (2 ** attempt)
            logger.warning("FR request failed (%s) — retry in %.1fs", exc, sleep_for)
            time.sleep(sleep_for)
    raise RuntimeError(f"FR request failed after {_MAX_RETRIES} retries: {last_exc}")


# ── Pagination ──────────────────────────────────────────────────────────────


def _iter_documents_for_term(term: str) -> Iterator[dict]:
    """Yield every document in the result set for one search term, paginated."""
    params = {
        "conditions[agencies][]": _AGENCY_SLUG,
        "conditions[term]": term,
        "per_page": str(_PER_PAGE),
        # Order by oldest first so an interruption can be resumed if needed.
        "order": "oldest",
    }
    url: str | None = f"{_API_BASE}?{urllib.parse.urlencode(params, doseq=True)}"
    page = 0
    while url:
        page += 1
        data = _fetch_json(url)
        results = data.get("results") or []
        logger.info(
            "term=%r page=%d results=%d total=%s",
            term, page, len(results), data.get("count"),
        )
        for doc in results:
            yield doc
        url = data.get("next_page_url")
        # Polite pacing — well under the documented rate limit.
        if url:
            time.sleep(0.5)


# ── Collection record ───────────────────────────────────────────────────────


@dataclass
class FRDoc:
    fr_doc_number: str
    title: str
    publication_date: str
    pdf_url: str
    html_url: str
    inferred_document_number: str | None
    pdf_host: str
    type: str
    matched_term: str


def collect_category(category: str) -> list[FRDoc]:
    """Run all term queries for a category and return deduplicated FRDoc list."""
    if category not in _CATEGORY_TERMS:
        raise ValueError(f"unknown category: {category}")

    seen: dict[str, FRDoc] = {}
    for term in _CATEGORY_TERMS[category]:
        logger.info("=== category=%s term=%r ===", category, term)
        for doc in _iter_documents_for_term(term):
            key = doc.get("document_number") or doc.get("html_url") or doc.get("title")
            if not key or key in seen:
                continue
            title = doc.get("title", "")
            pdf_url = doc.get("pdf_url") or ""
            seen[key] = FRDoc(
                fr_doc_number=doc.get("document_number") or "",
                title=title,
                publication_date=doc.get("publication_date") or "",
                pdf_url=pdf_url,
                html_url=doc.get("html_url") or "",
                inferred_document_number=_infer_document_number(category, title),
                pdf_host=_pdf_host(pdf_url),
                type=doc.get("type") or "",
                matched_term=term,
            )
    docs = sorted(seen.values(), key=lambda d: d.publication_date)
    logger.info("category=%s — %d unique documents", category, len(docs))
    return docs


# ── CSV writer ──────────────────────────────────────────────────────────────


def write_csv(docs: list[FRDoc], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(docs[0]).keys()) if docs else [
            "fr_doc_number", "title", "publication_date", "pdf_url", "html_url",
            "inferred_document_number", "pdf_host", "type", "matched_term",
        ])
        writer.writeheader()
        for d in docs:
            writer.writerow(asdict(d))


# ── CLI entry point ─────────────────────────────────────────────────────────


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Federal Register USCG publication discovery (gap-report input).",
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=sorted(_CATEGORY_TERMS.keys()),
        help="Which category to enumerate.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output CSV path.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    docs = collect_category(args.category)
    if not docs:
        logger.warning("no documents collected for category=%s", args.category)
    write_csv(docs, args.output)
    print(f"OK — {len(docs)} {args.category} documents → {args.output}")


if __name__ == "__main__":
    _main()
