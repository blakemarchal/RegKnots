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
import os
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


# ── Filter architecture (Sprint B2 rewrite) ─────────────────────────────
#
# Two-pass classification, subject-only:
#
#   Pass 1 — deterministic regex whitelist. Direct accept.
#            section_number is parsed from the SUBJECT, never from the body.
#            This fixes the "buried reference" bug from Sprint B where an
#            ALCGENL bulletin's body-text reference to an older ALCOAST
#            number was mistaken for the bulletin's own canonical ID.
#
#   Pre-deny — cheap regex reject for obvious noise (news/photo releases,
#              rescue/search reports). Saves LLM calls + cost.
#
#   Pass 2 — LLM classifier (Claude Haiku 4.5) for anything ambiguous.
#            Subject + first 500 body chars → JSON {accept, bulletin_type,
#            confidence, reason}. Accept iff accept=true AND confidence
#            >= 0.7. Fail closed on any error (API down, malformed JSON,
#            low confidence).
#
# Pass 1 and Pre-deny run synchronously per bulletin during fetch; Pass 2
# classifications are batched at end of fetch phase to amortize Anthropic
# API latency. Prompt caching keeps the per-call cost sub-$0.001.

# ── Pass 1: deterministic subject-only matches ──────────────────────────

# MSIBs come in two flavors:
#   - Coast-Guard-HQ style: "MSIB 07-20 Ports and Facilities..."  → ID NN-NN
#   - Sector VTS style:     "MSIB Vol XXV Issue 062 Safety Advisory..." → Vol NN Issue NN
# Broad match on "MSIB" + any number-ish follow-up catches both. Canonical ID
# is extracted by _extract_msib_canonical below.
_MSIB_SUBJECT_RE = re.compile(
    r"\bMSIB\b(?![A-Za-z])",  # MSIB as a token, not part of a longer word
    re.I,
)

# NVIC, CG Policy Letter, ALCOAST, NMC Announcement, Merchant Mariner Credential
_NVIC_SUBJECT_RE = re.compile(r"\bNVIC\s+(\d{1,2}-\d{2,4})\b", re.I)
_POLICY_LETTER_SUBJECT_RE = re.compile(
    r"\b(CG-MMC|CG-CVC|CG-OES)\s+Policy\s+Letter\s+(\d{1,2}-\d{2,4})\b",
    re.I,
)
_NMC_ANNOUNCEMENT_RE = re.compile(
    r"^\s*National\s+Maritime\s+Center\s+Announcement\s*$", re.I,
)
_MMC_CERT_RE = re.compile(
    r"\bMerchant\s+Mariner\s+(?:Credential|Medical\s+Certificate)\b", re.I,
)

# ── Pre-deny: cheap reject for obvious non-regulatory subjects ──────────

_DENY_PREFIXES = [
    re.compile(r"^\s*\(?(news|photo|multimedia|video|imagery|feature|media)\s+(release|available(?:ly)?)", re.I),
    re.compile(r"^\s*(press\s+release|photo\s+release|update\s*\d*:)", re.I),
]
_DENY_PHRASES = [
    re.compile(r"\brescues?\s+\d*\s*\w*\b", re.I),
    re.compile(r"\bsuspends?\s+search\b", re.I),
    re.compile(r"\bsearch\s+for\s+missing\b", re.I),
    re.compile(r"\bsearching\s+for\s+\w+\s+(?:vessel|fisherman|diver|boater)\b", re.I),
]


# ── Ephemeral kinds (2026-09-30) ─────────────────────────────────────────
#
# Time-bound operational traffic: weekly Local Notice to Mariners notices,
# broadcast notices to mariners (BNMs) and their updates, closures and river
# stages, storm and port conditions, GPS / NANU / ice advisories. Stale by the
# time anyone asks, and all of it tagged 'us', so it crowded every U.S. query:
# 2,406 of 2,629 stored documents (corpus gap audit 2026-09-29 §3.3). Rejected
# before Pass 1 (a Sector VTS "MSIB ... High Water" is still ephemeral) and
# pruned from the corpus (prune_ephemeral). The live sources are NAVCEN's
# LNMs and the sector MSIB pages.

_EPHEMERAL: list[tuple[str, re.Pattern]] = [
    ("outlook_or_lnm", re.compile(
        r"\boutlook\b|\bdaily\b|(?:\b|\d)lnms?\b|local notices? to mariners|light list"
        r"|dispatchers? list", re.I)),
    ("broadcast_notice", re.compile(
        r"\be?bnms?\b|\bumib\b|broadcast notice|\bupdate-\d+\b|\bupdate\s+0?\d{1,2}\b"
        r"|^\s*cancell?ation\b|mariners are advised"
        r"|^\s*(?:safety|update|scheduled|summary|security|marine event)\s*/", re.I)),
    ("closure_or_river_stage", re.compile(
        r"safety zones?|security zones?|\bclosures?\b|\bclosed\b|\bcloser\b|\bre-?open|\bopen to all\b"
        r"|\brestrictions?\b|high water|low water|river stages?|\bgauge\b|\bgage\b|\bfalling\b|\brising\b"
        r"|elevated winds|high winds|restricted visibility|impaired operations|system restored"
        r"|safety measure|\bcat i{1,3}\b|\bdeviations?\b|temporary operating|revetment|dredg"
        r"|^\s*vts\b", re.I)),
    ("storm_or_port_condition", re.compile(
        r"hurricane|tropical|\bstorms?\b|port conditions?|heavy weather|\bzulu\b|\byankee\b"
        r"|x-ray|\bwhiskey\b", re.I)),
    ("navigation_warning", re.compile(
        r"\bnanu\b|\bgps\b|\bjday\b|iceberg|ice (?:conditions|report)"
        r"|space operations|navigational warning|\bnavarea\b|\bhydro(?:lant|pac)\b", re.I)),
    ("marine_event", re.compile(
        r"marine event|regatta|fireworks|air show|grand prix|harborfest|mardi gras|boat parade", re.I)),
    ("pandemic_measures", re.compile(r"covid|cor[oa]navirus", re.I)),
]

# Coast Guard internal messages (ALCOAST, ACN, ALAUX…) about units, training,
# awards and personnel. The LLM pass accepted some as "ALCOAST_OPERATIONAL";
# only those that also speak to mariners or boaters are kept.
_INTERNAL_RE = re.compile(r"^\s*(?:ALCOAST|ACN|ALAUX|ALCGENL|ALCGPSC|ALCGRSV|ALCGOFF|ALCGCIV|ALDIST)\s+\d+/\d+", re.I)
_MARINER_FACING_RE = re.compile(
    r"visual distress|\bvhf\b|\bdsc\b|\bepirb|\bpfds?\b|life ?jackets?|recreational|boating safety"
    r"|fire extinguisher|fire protection equipment|\brecall\b|merchant mariner|mariner credential"
    r"|certificate of (?:number|documentation)|\bnvic\b|\bmarpol\b|\bsolas\b|\bstcw\b|ballast water"
    r"|vessel inspection|commercial (?:fishing )?vessel|towing vessel|passenger vessel|\btwic\b|\bmarsec\b", re.I)


def ephemeral_kind(subject: str) -> str | None:
    """The ephemeral kind a bulletin subject belongs to, or None if durable."""
    s = subject or ""
    for kind, pattern in _EPHEMERAL:
        if pattern.search(s):
            return kind
    return None


def drop_reason(subject: str) -> str | None:
    """Why a bulletin is not kept: an ephemeral kind, "internal_notice", or None."""
    kind = ephemeral_kind(subject)
    if kind:
        return kind
    if _INTERNAL_RE.search(subject or "") and not _MARINER_FACING_RE.search(subject or ""):
        return "internal_notice"
    return None


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


def _extract_msib_canonical(subject: str) -> str:
    """Derive the canonical MSIB section_number from a subject line.

    Handles both formats we've seen in the wild:
      "MSIB 07-20 Ports and Facilities..."      → "MSIB 07-20"
      "MSIB Vol XXV Issue 062 Safety Advisory..." → "MSIB Vol XXV Issue 062"
      "(Correction) MSIB Vol XXIII Issue 012 ..." → "MSIB Vol XXIII Issue 012"
      "SEC VA MSIB 20-113 - HRBT Expansion..."   → "MSIB 20-113"
      "MSIB XXV Issue: 048 High Water..."        → "MSIB XXV Issue 048"
    Falls back to "MSIB" + next 40 chars if no pattern recognized.
    """
    # NN-NN(N) form (CG HQ bulletins)
    m = re.search(r"\bMSIB\s+(\d{1,3}-\d{2,4})\b", subject, re.I)
    if m:
        return f"MSIB {m.group(1)}"
    # Vol/Issue form (Sector VTS bulletins) — capture roman or arabic numerals
    m = re.search(
        r"\bMSIB\s+(?:Vol\.?\s*)?([IVXLCDM]+|\d{1,3})[\s,.]*(?:Issue[\s:.]*)?(\d{1,4})\b",
        subject, re.I,
    )
    if m:
        return f"MSIB Vol {m.group(1).upper()} Issue {m.group(2)}"
    # Bare "MSIB <something>" — grab a trailing chunk for traceability
    m = re.search(r"\bMSIB\b[\s,.\-:]*(\S.{0,39})", subject, re.I)
    if m:
        tail = re.sub(r"\s+", " ", m.group(1)).strip(" ,.-:")
        if tail:
            return f"MSIB ({tail[:50]})"
    return "MSIB (unparsed)"


def _deny_prefilter(subject: str) -> str | None:
    """Return a reason code if the subject is obvious non-regulatory noise.

    Run before the LLM classifier to save cost. Matches press/photo/video
    releases and incident-response announcements (rescues, search
    reports). Returns None if subject doesn't trigger.
    """
    s = subject or ""
    for pat in _DENY_PREFIXES:
        if pat.search(s):
            return "deny_press_release"
    for pat in _DENY_PHRASES:
        if pat.search(s):
            return "deny_rescue_search"
    return None


def _pass1_match(
    subject: str, published_date: date | None,
) -> tuple[str, str] | None:
    """Subject-only deterministic match. Returns (canonical_id, type) or None.

    Order matters: more specific patterns first so MSIB wins over a stray
    "Merchant Mariner Credential" phrase in an MSIB subject.
    """
    s = subject or ""
    if _MSIB_SUBJECT_RE.search(s):
        return _extract_msib_canonical(s), "MSIB"
    m = _NVIC_SUBJECT_RE.search(s)
    if m:
        return f"NVIC {m.group(1)} (announcement)", "NVIC_mention"
    m = _POLICY_LETTER_SUBJECT_RE.search(s)
    if m:
        return f"{m.group(1).upper()} PL {m.group(2)}", "CG_POLICY_LETTER"
    # NOTE: no blanket ALCOAST Pass 1 rule — the prior run showed this was
    # a firehose for CG-internal admin (awards, solicitations, heritage
    # months, pay policy, etc.). Let the LLM in Pass 2 decide which
    # ALCOAST bulletins carry operational-regulatory content.
    if _NMC_ANNOUNCEMENT_RE.match(s):
        stamp = published_date.isoformat() if published_date else "undated"
        return f"NMC Announcement {stamp}", "NMC_ANNOUNCEMENT"
    if _MMC_CERT_RE.search(s):
        stamp = published_date.isoformat() if published_date else "undated"
        return f"NMC Announcement {stamp}", "NMC_ANNOUNCEMENT"
    return None


# 2026-09-30 — subjects that name a maritime-regulatory instrument or topic
# are accepted without the LLM (drop_reason has already removed the
# ephemeral and internal kinds). E.g. "Amendments to STCW Basic Training
# Requirements for Personal Safety and Social Responsibilities".
_REGULATORY_SUBJECT_RE = re.compile(
    r"\bSTCW\b|merchant mariners?|mariner credential|\bMMC\b|medical certificate"
    r"|national maritime center|\bNMC\b|\bNVIC\b|policy letter|work instruction|safety alert"
    r"|marine safety information|interim rule|final rule|proposed rule|rulemaking|federal register"
    r"|subchapter [A-Z]\b|towing vessel|\b(?:33|46|49) CFR\b|\bMARSEC\b|\bTWIC\b|ballast water|\bVIDA\b"
    r"|\bMARPOL\b|\bSOLAS\b|\bISM code\b|port state control|vessel inspection|certificate of inspection"
    r"|marine casualty|drug (?:and|&) alcohol testing|\brecall\b|lithium|carbon monoxide", re.I)


def _keyword_match(subject: str, published_date: date | None, gd_id: str) -> tuple[str, str] | None:
    """A regulatory-keyword subject: (section_number, "KEYWORD_REGULATORY")."""
    if not _REGULATORY_SUBJECT_RE.search(subject or ""):
        return None
    stamp = published_date.isoformat() if published_date else "undated"
    return f"USCG REGULATORY {stamp} [{gd_id[:7]}]", "KEYWORD_REGULATORY"


# ── Pass 2: Claude Haiku LLM classifier ─────────────────────────────────

# The same small model as the app (rag.llm.SIDECAR_MODEL); ingest does not
# import rag, so it reads the same env var with the same default.
_LLM_MODEL = os.environ.get("SIDECAR_MODEL") or "claude-haiku-4-5-20251001"
_LLM_MAX_CONCURRENCY = 10
_LLM_CONFIDENCE_THRESHOLD = 0.7
_LLM_TIMEOUT = 30.0

_LLM_SYSTEM_PROMPT = """\
You classify USCG bulletins for a maritime regulatory compliance database. \
Accept if the bulletin contains:
- Operational safety advisories (port security, equipment alerts, navigation hazards)
- Regulatory enforcement priorities or inspection campaigns
- Mariner credential process changes or medical certificate updates
- References to MSIB/NVIC/Policy Letter issuances
- Marine casualty investigation findings
- Vessel inspection or PSC guidance
- Ice operations, polar code, or environmental compliance

Reject if the bulletin contains:
- Internal CG HR (awards, solicitations, surveys, performance evaluations)
- Heritage month proclamations or ceremonial announcements
- Recruitment, benefits, pay, retirement, leave policy
- News releases, photo releases, rescue reports
- Internal training or administrative notices

Return JSON only: {"accept": true|false, "bulletin_type": "MSIB|NVIC|ALCOAST_OPERATIONAL|NMC|POLICY_LETTER|OTHER_REGULATORY|ADMIN|NEWS|RECRUITMENT", "confidence": 0.0-1.0, "reason": "brief"}"""


_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "bulletin_type": {"enum": [
            "MSIB", "NVIC", "ALCOAST_OPERATIONAL", "NMC", "POLICY_LETTER",
            "OTHER_REGULATORY", "ADMIN", "NEWS", "RECRUITMENT",
        ]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["accept", "bulletin_type", "confidence", "reason"],
    "additionalProperties": False,
}


def _try_parse_llm_json(text: str) -> dict | None:
    """Parse a JSON response from Claude. Strip markdown fences defensively.

    Returns None on any parse failure — the caller treats that as a
    reject per the fail-closed rule.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json or ``` prefix and trailing ```
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.I)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        import json as _json
        data = _json.loads(text.strip())
        if not isinstance(data, dict):
            return None
        if "accept" not in data or "confidence" not in data:
            return None
        return data
    except Exception:
        return None


async def _classify_one(client, subject: str, body: str) -> dict:
    """Call Claude Haiku once, return parsed result dict or a fail-closed reject.

    Uses prompt caching on the system prompt so the stable instructions
    only count as cache-read (~10% cost) on calls after the first.
    """
    import anthropic
    try:
        resp = await client.messages.create(
            model=_LLM_MODEL,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": _LLM_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[{
                "role": "user",
                "content": (
                    f"SUBJECT: {subject[:200]}\n\n"
                    f"BODY (first 500 chars): {body[:500]}"
                ),
            }],
            timeout=_LLM_TIMEOUT,
            # 2026-09-22 (U5) — structured output: the API enforces the
            # accept/bulletin_type/confidence/reason shape. (Note: the
            # cache_control above is a no-op — this ~300-token prompt is
            # below Haiku 4.5's 4,096-token caching minimum. Harmless.)
            output_config={"format": {"type": "json_schema", "schema": _LLM_SCHEMA}},
        )
        if not resp.content:
            return {"accept": False, "reason": "llm_empty_response", "confidence": 0.0}
        text = "".join(
            getattr(b, "text", "") or "" for b in resp.content
            if getattr(b, "type", None) == "text"
        )
        parsed = _try_parse_llm_json(text)
        if parsed is None:
            return {"accept": False, "reason": "llm_malformed_json", "confidence": 0.0,
                    "raw": text[:200]}
        return parsed
    except anthropic.APIError as exc:
        return {"accept": False, "reason": f"llm_api_error: {exc}", "confidence": 0.0}
    except Exception as exc:
        return {"accept": False, "reason": f"llm_exception: {type(exc).__name__}", "confidence": 0.0}


async def _classify_batch(
    parsed_bulletins: list["ParsedBulletin"],
    anthropic_key: str,
    log_fh,
) -> dict[str, tuple[bool, str, str]]:
    """Classify every bulletin in the list via Claude Haiku, bounded concurrency.

    Returns {gd_id: (accept_bool, bulletin_type, reason)}. Every classification
    is written to log_fh (tab-separated) for audit.
    """
    import anthropic

    results: dict[str, tuple[bool, str, str]] = {}
    if not parsed_bulletins:
        return results

    client = anthropic.AsyncAnthropic(api_key=anthropic_key)
    sem = asyncio.Semaphore(_LLM_MAX_CONCURRENCY)

    async def _one(pb: "ParsedBulletin") -> None:
        async with sem:
            res = await _classify_one(client, pb.subject, pb.body_text)
            accept = (
                res.get("accept") is True
                and float(res.get("confidence") or 0) >= _LLM_CONFIDENCE_THRESHOLD
            )
            btype = res.get("bulletin_type", "UNKNOWN")
            reason = res.get("reason", "")
            results[pb.gd_id] = (accept, btype, reason)
            log_fh.write(
                f"{pb.gd_id}\t{accept}\t{res.get('confidence', 0)}\t"
                f"{btype}\t{reason[:120]}\t{pb.subject[:120]}\n"
            )

    try:
        await asyncio.gather(*[_one(pb) for pb in parsed_bulletins])
    finally:
        await client.close()

    return results


def _canonical_from_llm_accept(
    subject: str, bulletin_type: str, published_date: date | None, gd_id: str,
) -> tuple[str, str]:
    """Build section_number + bulletin_type label for an LLM-accepted bulletin.

    LLM-accepted bulletins don't have a Pass-1 canonical ID by definition.
    Use the LLM's bulletin_type as the prefix + date + gd_id suffix for
    traceability. Same-ID collisions auto-resolve via the chunker's
    section_number disambiguation in _build_sections below.
    """
    stamp = published_date.isoformat() if published_date else "undated"
    short = gd_id[:7]
    type_tag = (bulletin_type or "OTHER_REGULATORY").strip().upper()[:30]
    return f"USCG {type_tag} {stamp} [{short}]", f"LLM_{type_tag}"


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
_ALIAS_VOCAB = {a.lower() for _name, _triggers, aliases in _ALIAS_BUCKETS for a in aliases}


def strip_alias_tail(title: str) -> str:
    """A stored section_title without the "(alias, alias)" block that
    _title_with_aliases appends (its words would trip ephemeral_kind)."""
    m = re.search(r"\s*\(([^()]*)\)\s*$", title or "")
    if m:
        items = {x.strip().lower() for x in m.group(1).split(",") if x.strip()}
        if items and items <= _ALIAS_VOCAB:
            return title[:m.start()]
    return title


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


async def _fetch_and_prefilter_one(
    client: httpx.AsyncClient, gd_id: str, stats: dict, rejected_fh,
) -> tuple[ParsedBulletin | None, str | None]:
    """Phase-1-inline step: fetch, parse, apply deny-prefilter + Pass 1 match.

    Returns (parsed_bulletin_or_None, pass1_verdict_or_None):
      - (None, None) — fetch/parse failed (logged already)
      - (parsed, None) — needs Pass 2 LLM classification
      - (parsed, canonical_id|type) — accepted by Pass 1 (stored as tuple string)

    We never send a deny-prefiltered bulletin to the LLM — that's the cost-saving win.
    """
    html, status = await _fetch_bulletin_html(client, gd_id)
    if html is None:
        stats["fetch_failures"] += 1
        if status == 404:
            stats["fetch_404"] += 1
        elif status and 500 <= status < 600:
            stats["fetch_5xx"] += 1
        else:
            stats["fetch_other"] += 1
        return None, None
    stats["fetched"] += 1

    parsed = _parse_bulletin_html(gd_id, html)
    if parsed is None:
        rejected_fh.write(f"{gd_id}\tparse_failed\t(no-subject-or-body)\t\n")
        stats["rejected"] += 1
        stats["rejected_parse"] += 1
        return None, None

    verdict, detail = subject_verdict(parsed.subject, parsed.published_date, gd_id)
    if verdict == "drop":
        rejected_fh.write(f"{gd_id}\tdrop_{detail}\t{parsed.subject[:100]}\t\n")
        stats["rejected"] += 1
        stats["rejected_dropped"] = stats.get("rejected_dropped", 0) + 1
        return None, None
    if verdict == "accept":
        canonical_id, bulletin_type = detail
        stats["accepted"] += 1
        stats["accepted_pass1"] += 1
        stats["accepted_by_type"][bulletin_type] = stats["accepted_by_type"].get(bulletin_type, 0) + 1
        # Return verdict encoded as "pass1|canonical_id|type"
        return parsed, f"pass1|{canonical_id}|{bulletin_type}"
    if verdict == "deny":
        preview = parsed.body_text[:100].replace("\t", " ").replace("\n", " ")
        rejected_fh.write(f"{gd_id}\t{detail}\t{parsed.subject[:100]}\t{preview}\n")
        stats["rejected"] += 1
        stats["rejected_predeny"] += 1
        return None, None

    # Candidate for Pass 2 LLM classification
    return parsed, None


def subject_verdict(subject: str, published_date: date | None, gd_id: str):
    """Decide a bulletin from its subject alone (2026-09-30).

    ("drop", kind)          ephemeral or internal (drop_reason); checked first,
                            since a Sector VTS "MSIB ... High Water" matches Pass 1
    ("accept", (id, type))  Pass 1, or a regulatory keyword that is not a
                            press or rescue release
    ("deny", reason)        press / photo release, rescue or search report
    ("ambiguous", None)     left to the LLM pass, when it runs
    """
    reason = drop_reason(subject)
    if reason is not None:
        return "drop", reason
    p1 = _pass1_match(subject, published_date)
    if p1 is not None:
        return "accept", p1
    deny = _deny_prefilter(subject)
    if deny is not None:
        return "deny", deny
    kw = _keyword_match(subject, published_date, gd_id)
    if kw is not None:
        return "accept", kw
    return "ambiguous", None


def _build_accepted_from_parsed(
    pb: ParsedBulletin,
    canonical_id: str,
    bulletin_type: str,
    pdf_text: str,
    stats: dict,
) -> AcceptedBulletin:
    """Finish building an AcceptedBulletin once fetch + filter decided to accept."""
    superseded_by = _extract_superseded_by(pb.body_text)
    if superseded_by:
        stats["superseded_by_count"] += 1
    expires_date = _extract_expires_date(pb.body_text)
    if expires_date:
        stats["expires_date_count"] += 1

    aliases = _select_aliases(pb.subject, pb.body_text + pdf_text)

    return AcceptedBulletin(
        gd_id=pb.gd_id,
        url=pb.url,
        canonical_id=canonical_id,
        bulletin_type=bulletin_type,
        subject=pb.subject,
        body_text=pb.body_text,
        pdf_text=pdf_text.strip(),
        published_date=pb.published_date,
        expires_date=expires_date,
        superseded_by=superseded_by,
        alias_list=aliases,
    )


async def _fetch_pdfs_for_accepted(
    client: httpx.AsyncClient, parsed: ParsedBulletin, stats: dict,
) -> str:
    pdf_text = ""
    for pdf_url in parsed.pdf_urls[:3]:
        text = await _fetch_pdf_text(client, pdf_url)
        if text:
            pdf_text += "\n\n" + text
            stats["pdf_text_extracted"] += 1
    return pdf_text.strip()


async def _fetch_and_filter_all(
    ids: list[str],
    rejected_log_path: Path,
    llm_log_path: Path,
    anthropic_key: str | None,
) -> tuple[list[AcceptedBulletin], dict]:
    """Two-phase pipeline:

    Phase A — fetch + parse + prefilter (Pass 1 + deny). Parallel, 5 concurrent.
              Accepts per Pass 1 stay in `pass1_accepts`. Ambiguous bulletins
              (not deterministically matched, not pre-denied) go to
              `llm_candidates` for Phase B.

    Phase B — batch LLM classification on all `llm_candidates`. 10 concurrent.
              Every classification logged to `llm_log_path`.

    Phase C — for every accepted bulletin (from Pass 1 or Pass 2), fetch any
              attached PDF text and build the final AcceptedBulletin.
    """
    stats: dict = {
        "attempted": len(ids),
        "fetched": 0,
        "fetch_failures": 0,
        "fetch_404": 0,
        "fetch_5xx": 0,
        "fetch_other": 0,
        "accepted": 0,
        "accepted_pass1": 0,
        "accepted_pass2_llm": 0,
        "rejected": 0,
        "rejected_parse": 0,
        "rejected_predeny": 0,
        "rejected_llm_lowconf": 0,
        "rejected_llm_error": 0,
        "accepted_by_type": {},
        "pdf_text_extracted": 0,
        "superseded_by_count": 0,
        "expires_date_count": 0,
    }
    rejected_log_path.parent.mkdir(parents=True, exist_ok=True)
    llm_log_path.parent.mkdir(parents=True, exist_ok=True)

    # Phase A state
    pass1_accepts: dict[str, tuple[ParsedBulletin, str, str]] = {}  # gd_id -> (parsed, canonical, type)
    llm_candidates: list[ParsedBulletin] = []

    sem_fetch = asyncio.Semaphore(_MAX_CONCURRENCY)

    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        with rejected_log_path.open("w", encoding="utf-8") as rejected_fh:
            rejected_fh.write("gd_id\treason\tsubject\tbody_preview\n")

            async def _phase_a_one(gd_id: str) -> None:
                async with sem_fetch:
                    try:
                        parsed, verdict = await _fetch_and_prefilter_one(
                            client, gd_id, stats, rejected_fh,
                        )
                    except Exception:
                        logger.exception("unhandled error on %s", gd_id)
                        stats["fetch_failures"] += 1
                        return
                    if parsed is None:
                        return
                    if verdict is not None:
                        # Pass 1 accepted
                        _tag, canonical_id, btype = verdict.split("|", 2)
                        pass1_accepts[gd_id] = (parsed, canonical_id, btype)
                    else:
                        llm_candidates.append(parsed)

            # ── Phase A: fetch + prefilter ────────────────────────────────
            logger.info("Phase A: fetching %d bulletins…", len(ids))
            tasks = [asyncio.create_task(_phase_a_one(i)) for i in ids]
            done = 0
            for coro in asyncio.as_completed(tasks):
                await coro
                done += 1
                if done % 500 == 0:
                    logger.info(
                        "  A-progress: %d/%d (pass1=%d llm_candidates=%d rejected=%d)",
                        done, len(ids), stats["accepted_pass1"],
                        len(llm_candidates), stats["rejected"],
                    )

            logger.info(
                "Phase A complete: %d fetched, %d pass1-accepted, %d llm-candidates, %d pre-rejected",
                stats["fetched"], stats["accepted_pass1"], len(llm_candidates),
                stats["rejected"],
            )

            # ── Phase B: LLM classification ───────────────────────────────
            llm_results: dict[str, tuple[bool, str, str]] = {}
            if llm_candidates and anthropic_key:
                logger.info("Phase B: LLM-classifying %d candidates…", len(llm_candidates))
                with llm_log_path.open("w", encoding="utf-8") as llm_log_fh:
                    llm_log_fh.write("gd_id\taccept\tconfidence\tbulletin_type\treason\tsubject\n")
                    llm_results = await _classify_batch(
                        llm_candidates, anthropic_key, llm_log_fh,
                    )
                for pb in llm_candidates:
                    res = llm_results.get(pb.gd_id)
                    if res is None:
                        # Fail-closed on missing result
                        stats["rejected"] += 1
                        stats["rejected_llm_error"] += 1
                        rejected_fh.write(f"{pb.gd_id}\tllm_missing\t{pb.subject[:100]}\t\n")
                        continue
                    accept, btype, reason = res
                    if not accept:
                        stats["rejected"] += 1
                        if reason.startswith("llm_"):
                            stats["rejected_llm_error"] += 1
                        else:
                            stats["rejected_llm_lowconf"] += 1
                        rejected_fh.write(
                            f"{pb.gd_id}\tllm_reject:{btype}\t{pb.subject[:100]}\t{reason[:100]}\n"
                        )
                        continue
                    # Accepted by Pass 2
                    stats["accepted"] += 1
                    stats["accepted_pass2_llm"] += 1
                    canonical, type_tag = _canonical_from_llm_accept(
                        pb.subject, btype, pb.published_date, pb.gd_id,
                    )
                    stats["accepted_by_type"][type_tag] = stats["accepted_by_type"].get(type_tag, 0) + 1
                    pass1_accepts[pb.gd_id] = (pb, canonical, type_tag)
            elif llm_candidates and not anthropic_key:
                # Fail-closed: no key means all candidates are rejected.
                logger.warning(
                    "Phase B skipped: ANTHROPIC_API_KEY not set. %d candidates auto-rejected.",
                    len(llm_candidates),
                )
                for pb in llm_candidates:
                    stats["rejected"] += 1
                    stats["rejected_llm_error"] += 1
                    rejected_fh.write(
                        f"{pb.gd_id}\tllm_no_key\t{pb.subject[:100]}\t\n"
                    )

            # ── Phase C: PDF fetch + build AcceptedBulletin ───────────────
            logger.info("Phase C: fetching PDFs + building %d accepted records…", len(pass1_accepts))
            accepted: list[AcceptedBulletin] = []
            sem_pdf = asyncio.Semaphore(_MAX_CONCURRENCY)

            async def _phase_c_one(gd_id: str, parsed: ParsedBulletin,
                                    canonical_id: str, btype: str) -> None:
                async with sem_pdf:
                    try:
                        pdf_text = await _fetch_pdfs_for_accepted(client, parsed, stats)
                        ab = _build_accepted_from_parsed(
                            parsed, canonical_id, btype, pdf_text, stats,
                        )
                        accepted.append(ab)
                    except Exception:
                        logger.exception("phase C error on %s", gd_id)

            c_tasks = [
                asyncio.create_task(_phase_c_one(gd_id, parsed, cid, btype))
                for gd_id, (parsed, cid, btype) in pass1_accepts.items()
            ]
            done = 0
            for coro in asyncio.as_completed(c_tasks):
                await coro
                done += 1
                if done % 200 == 0:
                    logger.info("  C-progress: %d/%d", done, len(c_tasks))

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
    """Fetch, filter (two-pass), enrich, and return Section objects.

    Run inside a dedicated worker thread because the CLI dispatch already
    owns an asyncio event loop and we can't call ``asyncio.run`` from a
    running loop. The anthropic key is pulled from ``ingest.config.settings``
    at call time so the adapter stays config-free otherwise.
    """
    ids_file = Path(ids_file)
    if not ids_file.exists():
        raise FileNotFoundError(f"ids file not found: {ids_file}")

    ids = _read_ids_file(ids_file)
    logger.info("uscg_bulletin: %d ids to process", len(ids))

    rejected_log_path = ids_file.parent / "rejected.log"
    llm_log_path = ids_file.parent / "llm_classifications.log"

    # Pull the key at call time — avoids making the module import-time
    # dependent on the ingest.config settings.
    from ingest.config import settings as _ingest_settings
    anthropic_key = _ingest_settings.anthropic_api_key or None

    import concurrent.futures

    def _run_in_thread():
        return asyncio.run(
            _fetch_and_filter_all(ids, rejected_log_path, llm_log_path, anthropic_key),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        accepted, stats = pool.submit(_run_in_thread).result()

    # Write stats to a sibling file so the CLI can surface them later.
    stats_path = ids_file.parent / "ingest_stats.json"
    import json
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    logger.info(
        "uscg_bulletin: fetched=%d accepted=%d rejected=%d (rejection log: %s)",
        stats["fetched"], stats["accepted"], stats["rejected"], rejected_log_path,
    )

    return _build_sections(accepted)


# ── Feed discovery (2026-09-30) ──────────────────────────────────────────
#
# The ids file came from a one-off Wayback crawl (April 2026), so discovery
# stopped at its newest bulletin (2026-02-03). GovDelivery's public RSS feed
# lists the account's latest 100 bulletins, about 30 hours of traffic, so
# app.tasks.update_uscg_bulletins polls it daily (the CLI's --update). Each
# new bulletin is decided from its subject (subject_verdict) and only the
# accepted ones are fetched. Ambiguous ones are listed in feed_review.tsv;
# the LLM pass classifies them only when USCG_BULLETIN_LLM=1. (Until 2026-08
# the weekly refresh re-fetched the whole ids file and sent about 6,000
# subjects a week to the LLM, most of them broadcast notices.)

FEED_URL = "https://public.govdelivery.com/accounts/USDHSCG/feed.rss"
FEED_SEEN = "feed_seen.txt"
FEED_REVIEW = "feed_review.tsv"


@dataclass
class FeedItem:
    gd_id: str
    subject: str
    published_date: date | None


def parse_feed_xml(xml_text: str) -> list[FeedItem]:
    """The feed's items as (GovDelivery id, subject, date)."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    items: list[FeedItem] = []
    for item in ET.fromstring(xml_text).iter("item"):
        m = re.search(r"/bulletins/([0-9a-f]+)", item.findtext("link") or "")
        if not m:
            continue
        published = None
        try:
            published = parsedate_to_datetime((item.findtext("pubDate") or "").strip()).date()
        except (TypeError, ValueError):
            pass
        items.append(FeedItem(m.group(1), _strip_tags(item.findtext("title") or ""), published))
    return items


def seen_ids(ids_file: Path) -> set[str]:
    """Every id already decided: the ids file plus feed_seen.txt."""
    seen = set(_read_ids_file(ids_file)) if ids_file.exists() else set()
    feed_seen = ids_file.parent / FEED_SEEN
    if feed_seen.exists():
        seen |= set(_read_ids_file(feed_seen))
    return seen


async def _process_feed_items(
    items: list[FeedItem], anthropic_key: str | None, out_dir: Path,
) -> tuple[list[AcceptedBulletin], list[FeedItem], dict]:
    """Fetch and build the accepted items. Returns (accepted, for review, stats)."""
    from collections import Counter

    stats: Counter = Counter()
    accepted: list[AcceptedBulletin] = []
    review: list[FeedItem] = []
    ambiguous: list[ParsedBulletin] = []
    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, follow_redirects=True) as client:
        for it in items:
            verdict, _detail = subject_verdict(it.subject, it.published_date, it.gd_id)
            stats[f"feed_{verdict}"] += 1
            if verdict == "ambiguous" and not anthropic_key:
                review.append(it)
            if verdict != "accept" and not (verdict == "ambiguous" and anthropic_key):
                continue
            html, _status = await _fetch_bulletin_html(client, it.gd_id)
            parsed = _parse_bulletin_html(it.gd_id, html) if html else None
            if parsed is None:
                stats["fetch_or_parse_failed"] += 1
                continue
            # the page's subject and dateline are authoritative
            verdict, detail = subject_verdict(parsed.subject, parsed.published_date, parsed.gd_id)
            if verdict == "accept":
                pdf_text = await _fetch_pdfs_for_accepted(client, parsed, stats)
                accepted.append(_build_accepted_from_parsed(parsed, detail[0], detail[1], pdf_text, stats))
            elif verdict == "ambiguous" and anthropic_key:
                ambiguous.append(parsed)
        if ambiguous:
            with (out_dir / "llm_classifications.log").open("a", encoding="utf-8") as fh:
                results = await _classify_batch(ambiguous, anthropic_key, fh)
            for parsed in ambiguous:
                res = results.get(parsed.gd_id)
                if not (res and res[0]):
                    stats["llm_rejected"] += 1
                    continue
                canonical, type_tag = _canonical_from_llm_accept(
                    parsed.subject, res[1], parsed.published_date, parsed.gd_id)
                pdf_text = await _fetch_pdfs_for_accepted(client, parsed, stats)
                accepted.append(_build_accepted_from_parsed(parsed, canonical, type_tag, pdf_text, stats))
    stats["accepted"] = len(accepted)
    return accepted, review, dict(stats)


def parse_feed(ids_file: Path) -> list[Section]:
    """Sections for bulletins in the feed that no earlier run decided.

    Every new id goes to feed_seen.txt, accepted ones also to the ids file
    (so a full --fresh run keeps them), ambiguous ones to feed_review.tsv.
    The feed covers about 30 hours, so a gap of more than a day misses
    bulletins; the log warns when every item in the feed was new.
    """
    import concurrent.futures
    import json

    ids_file = Path(ids_file)
    out_dir = ids_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(FEED_URL, headers={"User-Agent": _USER_AGENT}, timeout=_FETCH_TIMEOUT,
                     follow_redirects=True)
    resp.raise_for_status()
    items = parse_feed_xml(resp.text)
    seen = seen_ids(ids_file)
    new = [it for it in items if it.gd_id not in seen]
    logger.info("uscg_bulletin feed: %d items, %d new", len(items), len(new))
    if items and len(new) == len(items) and seen:
        logger.warning("uscg_bulletin feed: every item is new; bulletins older than the feed "
                       "(about 30 hours) were missed since the last run")

    anthropic_key = None
    if os.environ.get("USCG_BULLETIN_LLM") == "1":
        from ingest.config import settings as _ingest_settings
        anthropic_key = _ingest_settings.anthropic_api_key or None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        accepted, review, stats = pool.submit(
            lambda: asyncio.run(_process_feed_items(new, anthropic_key, out_dir))).result()

    if new:
        with (out_dir / FEED_SEEN).open("a", encoding="utf-8") as fh:
            fh.writelines(f"{it.gd_id}\n" for it in new)
    if accepted:
        with ids_file.open("a", encoding="utf-8") as fh:
            fh.writelines(f"{a.gd_id}\n" for a in accepted)
    if review:
        review_path = out_dir / FEED_REVIEW
        header = not review_path.exists()
        with review_path.open("a", encoding="utf-8") as fh:
            if header:
                fh.write("gd_id\tdate\tsubject\n")
            fh.writelines(f"{it.gd_id}\t{it.published_date or ''}\t{it.subject[:200]}\n" for it in review)
    (out_dir / "feed_stats.json").write_text(json.dumps(
        {"items": len(items), "new": len(new), **stats, "review": len(review)}, indent=2), encoding="utf-8")
    logger.info("uscg_bulletin feed: %d accepted, %d for review, %s", len(accepted), len(review), stats)
    return _build_sections(accepted)


# ── Prune (2026-09-30) ───────────────────────────────────────────────────
#
# A parse of this source re-fetches every bulletin in the ids file, so the
# generic stale report (parse, then compare) is not used. The stored rows are
# judged by their titles instead: rows of ephemeral or internal kinds, and
# second copies of one bulletin stored under different section numbers (the
# LLM labelled it differently on different runs), are stale.

_TYPE_ORDER = ("POLICY_LETTER", "NVIC", "NMC", "MSIB", "REGULATORY", "OTHER_REGULATORY")


def _doc_rank(section_number: str) -> tuple:
    """Which copy of a bulletin to keep: a Pass 1 id ("MSIB 07-20",
    "NMC Announcement 2024-02-26") first, then LLM ids in _TYPE_ORDER."""
    m = re.match(r"USCG (\S+) ", section_number)
    if not m:
        return (0, section_number)
    kind = m.group(1)
    return (1 + (_TYPE_ORDER.index(kind) if kind in _TYPE_ORDER else len(_TYPE_ORDER)), section_number)


def gd_id_of(section_number: str, text: str) -> str | None:
    """The GovDelivery id of a stored bulletin: its Source URL, or the
    "[hex]" suffix _build_sections adds (7 characters for LLM ids)."""
    m = re.search(r"/bulletins/([0-9a-f]+)", text or "")
    if m:
        return m.group(1)
    m = re.search(r"\[([0-9a-f]{6,})\]\s*$", section_number or "")
    return m.group(1) if m else None


def prune_plan(docs: list[dict]) -> dict[str, str]:
    """section_number -> why it goes, for stored documents
    [{"section_number", "section_title", "gd_id"}]."""
    drop: dict[str, str] = {}
    by_gd: dict[str, list[str]] = {}
    for d in docs:
        reason = drop_reason(strip_alias_tail(d["section_title"] or ""))
        if reason:
            drop[d["section_number"]] = reason
        elif d.get("gd_id"):
            # LLM ids carry only the first 7 characters of the id
            by_gd.setdefault(d["gd_id"][:7], []).append(d["section_number"])
    for secs in by_gd.values():
        if len(secs) > 1:
            keep = min(secs, key=_doc_rank)
            for sec in secs:
                if sec != keep:
                    drop[sec] = f"duplicate of {keep}"
    return drop


async def stale_report(pool):
    """A prune.StaleReport of the stored rows prune_plan removes. Its
    `produced` counts the rows kept, so a plan that would empty the source
    is refused like an empty parse."""
    from ingest.prune import StaleReport

    rows = await pool.fetch(
        "SELECT id, section_number, section_title, chunk_index, left(full_text, 300) AS head, "
        "created_at::date AS created FROM regulations WHERE source = $1 "
        "ORDER BY section_number, chunk_index",
        SOURCE,
    )
    docs: dict[str, dict] = {}
    for r in rows:
        d = docs.setdefault(r["section_number"], {"section_number": r["section_number"],
                                                  "section_title": r["section_title"] or "",
                                                  "gd_id": None})
        d["gd_id"] = d["gd_id"] or gd_id_of(r["section_number"], r["head"])
    plan = prune_plan(list(docs.values()))
    report = StaleReport(source=SOURCE, stored=len(rows))
    for r in rows:
        why = plan.get(r["section_number"])
        if why is None:
            report.produced += 1
            continue
        report.stale.append({"id": str(r["id"]), "section_number": r["section_number"],
                             "chunk_index": r["chunk_index"], "created": str(r["created"]),
                             "reason": why})
    return report
