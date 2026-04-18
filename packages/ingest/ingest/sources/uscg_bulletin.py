"""
USCG GovDelivery bulletin source adapter.

Ingests USCG bulletins published at
content.govdelivery.com/accounts/USDHSCG/bulletins/<hex-id>. The
GovDelivery account is a firehose of mixed content (regulatory
bulletins, press releases, photo releases, internal admin). This
adapter applies a STRICT canonical-ID filter at ingest time — only
bulletins whose subject or leading body text contains a recognizable
maritime-regulatory identifier (MSIB, ALCOAST, NVIC mention, CG-MMC
policy letter, or a labeled NMC announcement) are accepted. Everything
else is logged and rejected.

Discovery vs. content boundary
------------------------------
Bulletin IDs are discovered via a pre-built `wayback_ids.txt` produced
by `scripts/collect_wayback_bulletin_ids.sh` (or equivalent). Wayback
is used ONLY as a URL index. All content in this adapter is fetched
**live** from content.govdelivery.com at sprint-run time. Wayback
snapshots are never read. Citations preserve the live content.govdelivery.com
URL in full.

CLI:
    uv run python -m ingest.cli --source uscg_bulletin \\
        --ids-file data/raw/uscg_bulletins/wayback_ids.txt --fresh
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import httpx

try:
    import pdfplumber
except ImportError:  # pragma: no cover — guard rails only
    pdfplumber = None  # type: ignore[assignment]

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "uscg_bulletin"
TITLE_NUMBER = 0
SOURCE_DATE = date.today()

_BULLETIN_URL = "https://content.govdelivery.com/accounts/USDHSCG/bulletins/{id}"
_USER_AGENT = "RegKnot-USCG-Bulletin-Ingest/1.0 (+https://regknots.com)"
_MAX_CONCURRENCY = 5
_FETCH_TIMEOUT = 30.0
_PDF_FETCH_TIMEOUT = 45.0


# ── HTML parsing regexes (bulletin page structure confirmed in recon) ──────

_SUBJECT_RE = re.compile(r"<h1 class=['\"]bulletin_subject['\"]>(.*?)</h1>", re.S)
_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.S | re.I)
_DATELINE_RE = re.compile(r"<span class=['\"]dateline[^'\"]*['\"]>(.*?)</span>", re.S)
_BODY_RE = re.compile(r"<div class=['\"]bulletin_body['\"][^>]*>(.*)", re.S)
_PDF_HREF_RE = re.compile(
    r'href=[\'"]'
    r'(https://content\.govdelivery\.com/attachments/[^\'"]+?\.pdf)'
    r'[\'"]',
    re.I,
)
_DCO_PDF_HREF_RE = re.compile(
    r'href=[\'"](https?://[^\'"]*dco\.uscg\.mil[^\'"]+?\.pdf)[\'"]',
    re.I,
)

# Date like "10/17/2018 11:22 AM EDT" in the dateline
_DATE_IN_DATELINE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


# ── Canonical-ID filter — STRICT ──────────────────────────────────────────
#
# Accept a bulletin iff subject OR first ~1000 chars of body match one of
# these patterns. Rejections are logged with a reason code. False
# negatives are acceptable per sprint direction — false positives are not.

_ACCEPT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("MSIB", re.compile(r"\bMSIB[\s\-]*(\d{2}-\d{2,4})\b", re.I)),
    ("ALCOAST", re.compile(r"\bALCOAST[\s\-]*(\d{3}/\d{2})\b", re.I)),
    ("NVIC_mention", re.compile(r"\bNVIC[\s\-]*(\d{2}-\d{2,4})\b", re.I)),
    ("CG_POLICY_LETTER", re.compile(
        r"\b(CG-MMC|CG-CVC|CG-OES)[\s\-]*(?:Policy\s+Letter\s+)?(\d{2}-\d{2,4})\b",
        re.I,
    )),
    ("NMC_ANNOUNCEMENT", re.compile(
        r"\bNational\s+Maritime\s+Center\s+Announcement\b", re.I,
    )),
    ("MERCHANT_MARINER_SUBJ", re.compile(
        r"\bMerchant\s+Mariner\s+(?:Credential|Medical\s+Certificate)\b", re.I,
    )),
]


@dataclass
class ParsedBulletin:
    """Raw fields extracted from one bulletin HTML page, pre-filter."""
    gd_id: str
    url: str
    subject: str
    body_text: str
    published_date: date | None
    pdf_urls: list[str]
    has_dco_pdf_link: bool  # bulletin referenced a dco.uscg.mil PDF we can't fetch


@dataclass
class AcceptedBulletin:
    """Post-filter bulletin ready for chunking."""
    gd_id: str
    url: str
    canonical_id: str       # e.g. "MSIB 01-24" or "NMC Announcement 2024-06-26"
    bulletin_type: str      # one of the _ACCEPT_PATTERNS names, or NMC_ANNOUNCEMENT_UNDATED
    subject: str
    body_text: str
    pdf_text: str           # extracted text from content.govdelivery.com PDF, if any
    published_date: date | None
    expires_date: date | None
    superseded_by: str | None
    alias_list: list[str]   # populated by enricher below


# ── HTML entity / tag cleanup ─────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    # Common HTML entities that matter for regulatory content
    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&ndash;": "-", "&mdash;": "-", "&rsquo;": "'", "&lsquo;": "'",
    }
    for k, v in replacements.items():
        txt = txt.replace(k, v)
    # Collapse whitespace
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _parse_dateline_date(dateline: str) -> date | None:
    m = _DATE_IN_DATELINE.search(dateline)
    if not m:
        return None
    mm, dd, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


# ── HTML → ParsedBulletin ────────────────────────────────────────────────


def _parse_bulletin_html(gd_id: str, html: str) -> ParsedBulletin | None:
    """Extract structured fields from a bulletin HTML page.

    Returns None if the page doesn't look like a valid bulletin (missing
    subject or body markers — usually means an error page or a redirect).
    """
    subj_m = _SUBJECT_RE.search(html)
    title_m = _TITLE_RE.search(html)
    raw_subject = subj_m.group(1) if subj_m else (title_m.group(1) if title_m else "")
    subject = _strip_tags(raw_subject)

    if not subject:
        return None

    dateline_m = _DATELINE_RE.search(html)
    dateline = _strip_tags(dateline_m.group(1)) if dateline_m else ""
    published_date = _parse_dateline_date(dateline)

    body_m = _BODY_RE.search(html)
    # Slice off the trailing closing </div> chain — the body regex is greedy
    # by design so we can trim the chain below via heuristics.
    body_html = body_m.group(1) if body_m else ""
    # Trim at the share buttons / related-bulletins div if present
    for tail_marker in (
        "<div class='share_box", "<div class='share-box",
        "<div id='gd_social_share'",
        "<div class='related_bulletins'",
        "<footer",
    ):
        idx = body_html.find(tail_marker)
        if idx != -1:
            body_html = body_html[:idx]
            break

    body_text = _strip_tags(body_html)

    # PDF attachments — content.govdelivery.com preferred, dco.uscg.mil flagged
    pdf_urls = _PDF_HREF_RE.findall(html)
    has_dco_pdf_link = bool(_DCO_PDF_HREF_RE.search(html))

    return ParsedBulletin(
        gd_id=gd_id,
        url=_BULLETIN_URL.format(id=gd_id),
        subject=subject,
        body_text=body_text,
        published_date=published_date,
        pdf_urls=pdf_urls,
        has_dco_pdf_link=has_dco_pdf_link,
    )


# ── Canonical-ID filter + classification ──────────────────────────────────


def _canonical_id_and_type(
    subject: str, body_text: str, published_date: date | None,
) -> tuple[str, str] | None:
    """Return (canonical_id, bulletin_type) if the bulletin passes the filter.

    Scans the subject first, then the first 1000 chars of body. First
    matching pattern wins. The NMC announcement fallback emits a
    date-stamped canonical ID so every accepted bulletin has a distinct
    section_number in the corpus.
    """
    haystack_subject = subject or ""
    haystack_body = (body_text or "")[:1000]

    for name, pat in _ACCEPT_PATTERNS:
        for scope_text in (haystack_subject, haystack_body):
            m = pat.search(scope_text)
            if not m:
                continue
            if name == "MSIB":
                return f"MSIB {m.group(1)}", "MSIB"
            if name == "ALCOAST":
                return f"ALCOAST {m.group(1)}", "ALCOAST"
            if name == "NVIC_mention":
                return f"NVIC {m.group(1)} (announcement)", "NVIC_mention"
            if name == "CG_POLICY_LETTER":
                office = m.group(1).upper()
                return f"{office} PL {m.group(2)}", "CG_POLICY_LETTER"
            if name == "NMC_ANNOUNCEMENT":
                stamp = published_date.isoformat() if published_date else "undated"
                return f"NMC Announcement {stamp}", "NMC_ANNOUNCEMENT"
            if name == "MERCHANT_MARINER_SUBJ":
                if scope_text is haystack_subject:
                    stamp = published_date.isoformat() if published_date else "undated"
                    return f"NMC Announcement {stamp}", "NMC_ANNOUNCEMENT"
    return None


# ── Expiration / supersession parsing ─────────────────────────────────────

_SUPERSEDE_RE = re.compile(
    r"\b(?:supersedes?|replaces?|cancels?|supplants?)\s+"
    r"(?:the\s+)?"
    r"((?:MSIB|ALCOAST|NVIC|CG-MMC|CG-CVC|CG-OES|NMC)[\s\-]*(?:Policy\s+Letter\s+)?"
    r"\d{1,3}[-/]\d{2,4})",
    re.I,
)
_EXPIRES_RE = re.compile(
    r"(?:expires?(?:\s+on)?|valid\s+(?:through|until)|effective\s+until)\s+"
    r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)

_DATE_PATTERNS = [
    ("%d %B %Y", re.compile(r"\d{1,2}\s+\w+\s+\d{4}")),
    ("%d %b %Y", re.compile(r"\d{1,2}\s+\w+\s+\d{4}")),
    ("%B %d, %Y", re.compile(r"\w+\s+\d{1,2},\s+\d{4}")),
    ("%B %d %Y", re.compile(r"\w+\s+\d{1,2}\s+\d{4}")),
    ("%m/%d/%Y", re.compile(r"\d{1,2}/\d{1,2}/\d{4}")),
]


def _try_parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt, _pat in _DATE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _extract_superseded_by(body: str) -> str | None:
    m = _SUPERSEDE_RE.search(body or "")
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _extract_expires_date(body: str) -> date | None:
    m = _EXPIRES_RE.search(body or "")
    if not m:
        return None
    return _try_parse_date(m.group(1))


# ── Alias enrichment (per-bulletin, capped at 8) ─────────────────────────

_ALIAS_BUCKETS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    (
        "port_security",
        ("port closure", "security zone", "marsec", "restricted area",
         "transportation security", "tsi"),
        ("port security", "MARSEC", "security zone", "port closure"),
    ),
    (
        "equipment_recall",
        ("recall", "defective", "safety alert", "notice to operators",
         "safety notice"),
        ("equipment recall", "safety alert", "defective equipment"),
    ),
    (
        "enforcement",
        ("enforcement priority", "port state control", "psc exam",
         "inspection campaign", "focused inspection", "concentrated inspection"),
        ("enforcement priority", "PSC campaign", "inspection focus"),
    ),
    (
        "credential_process",
        ("mmc", "medical certificate", "credential application", "backlog",
         "processing time", "application acceptance"),
        ("MMC process", "credential update", "NMC processing"),
    ),
    (
        "environmental",
        ("pollution", "spill", "marpol", "environmental",
         "hazardous material", "oil discharge"),
        ("environmental compliance", "pollution response"),
    ),
    (
        "weather_navigation",
        ("hurricane", "storm", "navigation safety", "aid to navigation",
         "notmar", "notice to mariners", "typhoon"),
        ("navigation safety", "weather advisory", "aid to navigation"),
    ),
    (
        "vessel_tanker",
        ("tanker", "tank vessel", "tank barge", "petroleum carrier"),
        ("tanker", "tank vessel"),
    ),
    (
        "vessel_towing",
        ("towing vessel", "tugboat", "tug and tow", "subchapter m"),
        ("towing vessel", "Subchapter M"),
    ),
    (
        "vessel_passenger",
        ("passenger vessel", "ferry", "small passenger", "subchapter t",
         "subchapter k"),
        ("passenger vessel", "small passenger vessel"),
    ),
    (
        "vessel_fishing",
        ("fishing vessel", "commercial fishing", "fishing industry"),
        ("fishing vessel", "commercial fishing"),
    ),
    (
        "vessel_offshore",
        ("osv", "offshore supply", "mobile offshore drilling", "modu"),
        ("OSV", "offshore supply vessel", "MODU"),
    ),
]

_MAX_ALIASES = 8


def _select_aliases(subject: str, body: str) -> list[str]:
    haystack = (subject + "\n" + body[:6000]).lower()
    seen: set[str] = set()
    picked: list[str] = []
    for _name, triggers, aliases in _ALIAS_BUCKETS:
        if not any(t in haystack for t in triggers):
            continue
        for alias in aliases:
            key = alias.lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append(alias)
            if len(picked) >= _MAX_ALIASES:
                return picked
    return picked


def _title_with_aliases(title: str, aliases: list[str]) -> str:
    if not aliases:
        return title
    low = title.lower()
    fresh = [a for a in aliases if a.lower() not in low]
    if not fresh:
        return title
    return f"{title} ({', '.join(fresh)})"


# ── HTTP + PDF fetchers ──────────────────────────────────────────────────


async def _fetch_bulletin_html(
    client: httpx.AsyncClient, gd_id: str,
) -> tuple[str | None, int | None]:
    """GET the bulletin HTML. Returns (html, status_code). One retry on non-2xx."""
    url = _BULLETIN_URL.format(id=gd_id)
    for attempt in range(2):
        try:
            resp = await client.get(url, timeout=_FETCH_TIMEOUT)
            if 200 <= resp.status_code < 300:
                return resp.text, resp.status_code
            if resp.status_code == 404:
                return None, 404
            if 500 <= resp.status_code < 600 and attempt == 0:
                await asyncio.sleep(2.0)
                continue
            return None, resp.status_code
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            if attempt == 0:
                logger.debug("retry after network error on %s: %s", gd_id, exc)
                await asyncio.sleep(2.0)
                continue
            return None, None
    return None, None


async def _fetch_pdf_text(client: httpx.AsyncClient, pdf_url: str) -> str:
    """Fetch a GovDelivery-hosted PDF and extract text via pdfplumber.

    Returns empty string on any failure — we never block the bulletin on
    PDF extraction issues.
    """
    if pdfplumber is None:
        return ""
    try:
        resp = await client.get(pdf_url, timeout=_PDF_FETCH_TIMEOUT)
        if resp.status_code != 200:
            return ""
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    pages.append(t.strip())
        return "\n\n".join(pages)
    except Exception as exc:
        logger.debug("PDF fetch/parse failed for %s: %s", pdf_url, exc)
        return ""


# ── Orchestration ────────────────────────────────────────────────────────


async def _process_one(
    client: httpx.AsyncClient,
    gd_id: str,
    stats: dict,
    rejected_fh,
) -> AcceptedBulletin | None:
    """Fetch + parse + filter + (optionally) enrich one bulletin."""
    html, status = await _fetch_bulletin_html(client, gd_id)
    if html is None:
        stats["fetch_failures"] += 1
        if status == 404:
            stats["fetch_404"] += 1
        elif status and 500 <= status < 600:
            stats["fetch_5xx"] += 1
        else:
            stats["fetch_other"] += 1
        return None
    stats["fetched"] += 1

    parsed = _parse_bulletin_html(gd_id, html)
    if parsed is None:
        rejected_fh.write(f"{gd_id}\t(parse_failed)\t(no-subject-or-body)\n")
        stats["rejected"] += 1
        stats["rejected_parse"] += 1
        return None

    verdict = _canonical_id_and_type(parsed.subject, parsed.body_text, parsed.published_date)
    if verdict is None:
        preview = parsed.body_text[:100].replace("\t", " ").replace("\n", " ")
        rejected_fh.write(
            f"{gd_id}\tno_canonical_id\t{parsed.subject[:100]}\t{preview}\n"
        )
        stats["rejected"] += 1
        stats["rejected_no_canonical_id"] += 1
        return None

    canonical_id, bulletin_type = verdict
    stats["accepted"] += 1
    stats["accepted_by_type"][bulletin_type] = stats["accepted_by_type"].get(bulletin_type, 0) + 1

    # PDF text (best-effort, only for content.govdelivery.com attachments)
    pdf_text = ""
    for pdf_url in parsed.pdf_urls[:3]:  # cap at 3 PDFs per bulletin
        text = await _fetch_pdf_text(client, pdf_url)
        if text:
            pdf_text += "\n\n" + text
            stats["pdf_text_extracted"] += 1

    # Freshness metadata — best-effort, null when absent
    superseded_by = _extract_superseded_by(parsed.body_text)
    if superseded_by:
        stats["superseded_by_count"] += 1
    expires_date = _extract_expires_date(parsed.body_text)
    if expires_date:
        stats["expires_date_count"] += 1

    aliases = _select_aliases(parsed.subject, parsed.body_text + pdf_text)

    return AcceptedBulletin(
        gd_id=gd_id,
        url=parsed.url,
        canonical_id=canonical_id,
        bulletin_type=bulletin_type,
        subject=parsed.subject,
        body_text=parsed.body_text,
        pdf_text=pdf_text.strip(),
        published_date=parsed.published_date,
        expires_date=expires_date,
        superseded_by=superseded_by,
        alias_list=aliases,
    )


async def _fetch_and_filter_all(
    ids: list[str], rejected_log_path: Path,
) -> tuple[list[AcceptedBulletin], dict]:
    """Drive the full fetch → filter pipeline with bounded concurrency."""
    stats: dict = {
        "attempted": len(ids),
        "fetched": 0,
        "fetch_failures": 0,
        "fetch_404": 0,
        "fetch_5xx": 0,
        "fetch_other": 0,
        "accepted": 0,
        "rejected": 0,
        "rejected_parse": 0,
        "rejected_no_canonical_id": 0,
        "accepted_by_type": {},
        "pdf_text_extracted": 0,
        "superseded_by_count": 0,
        "expires_date_count": 0,
    }
    accepted: list[AcceptedBulletin] = []

    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    rejected_log_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        with rejected_log_path.open("w", encoding="utf-8") as rejected_fh:
            rejected_fh.write("gd_id\treason\tsubject\tbody_preview\n")

            async def _one(gd_id: str) -> None:
                async with sem:
                    try:
                        ab = await _process_one(client, gd_id, stats, rejected_fh)
                        if ab is not None:
                            accepted.append(ab)
                    except Exception:
                        logger.exception("unhandled error on %s", gd_id)
                        stats["fetch_failures"] += 1

            tasks = [asyncio.create_task(_one(i)) for i in ids]
            # Simple progress logging every 500 done
            done = 0
            for coro in asyncio.as_completed(tasks):
                await coro
                done += 1
                if done % 500 == 0:
                    logger.info(
                        "progress: %d/%d (accepted=%d rejected=%d)",
                        done, len(ids), stats["accepted"], stats["rejected"],
                    )

    return accepted, stats


# ── Public API (called by CLI dispatch) ──────────────────────────────────


def _read_ids_file(path: Path) -> list[str]:
    ids: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not re.fullmatch(r"[0-9a-f]+", line):
                logger.warning("skipping non-hex id in ids file: %r", line)
                continue
            ids.append(line)
    return ids


def _build_sections(accepted: list[AcceptedBulletin]) -> list[Section]:
    """Convert AcceptedBulletins into Sections for the shared chunker.

    Section_numbers can collide (e.g. multiple "MSIB 01-24" bulletins or
    "NMC Announcement 2024-06-26" on the same day). Disambiguate with
    the GovDelivery hex ID suffix — preserves traceability to the live
    bulletin URL and avoids chunker / unique-index collisions.
    """
    # Count canonical_id occurrences to decide which ones need disambiguation
    from collections import Counter
    counts = Counter(a.canonical_id for a in accepted)

    sections: list[Section] = []
    for ab in accepted:
        section_number = ab.canonical_id
        if counts[ab.canonical_id] > 1:
            section_number = f"{ab.canonical_id} [{ab.gd_id}]"

        full_text = ab.body_text
        if ab.pdf_text:
            full_text = f"{ab.body_text}\n\n{ab.pdf_text}"
        # Prepend the canonical GovDelivery URL so retrieval/citation
        # always exposes a live link to the original bulletin.
        full_text = f"Source URL: {ab.url}\n\n{full_text}"

        section_title = _title_with_aliases(ab.subject, ab.alias_list)

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=section_title[:500],
            full_text=full_text,
            up_to_date_as_of=ab.published_date or date.today(),
            parent_section_number=None,
            published_date=ab.published_date,
            expires_date=ab.expires_date,
            superseded_by=ab.superseded_by,
        ))
    return sections


def parse_source(ids_file: Path) -> list[Section]:
    """Fetch, filter, enrich, and return Section objects for the CLI pipeline.

    This is the callable the shared PDF pipeline invokes. Takes the
    Wayback-derived IDs file path and drives the whole fetch loop.
    """
    ids_file = Path(ids_file)
    if not ids_file.exists():
        raise FileNotFoundError(f"ids file not found: {ids_file}")

    ids = _read_ids_file(ids_file)
    logger.info("uscg_bulletin: %d ids to process", len(ids))

    rejected_log_path = ids_file.parent / "rejected.log"
    accepted, stats = asyncio.run(_fetch_and_filter_all(ids, rejected_log_path))

    # Write stats to a sibling file so the CLI can surface them later.
    stats_path = ids_file.parent / "ingest_stats.json"
    import json
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    logger.info(
        "uscg_bulletin: fetched=%d accepted=%d rejected=%d (rejection log: %s)",
        stats["fetched"], stats["accepted"], stats["rejected"], rejected_log_path,
    )

    return _build_sections(accepted)
