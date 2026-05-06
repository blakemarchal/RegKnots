"""
NMC (National Maritime Center) source adapter.

Handles two sibling sources drawn from the same data/raw/nmc/ directory:

  - nmc_policy    — authoritative policy letters and crediting guidance
                    (CG-MMC, CG-OES, CG-CVC policy letters, military
                    sea-service crediting, etc.). Binding CFR interpretation.
  - nmc_checklist — procedural guidance: application-acceptance checklists
                    and form-instruction guides. Not binding, but mariners
                    hit them constantly during renewal and endorsement work.

Both are U.S. Coast Guard public-domain works — full text may be stored
and quoted verbatim; no copyright paraphrase guard applies.

Structural choices (deliberately simpler than the NVIC adapter):

  - section_number is filename-derived, NOT derived from internal numbered
    headings. The NVIC parser's "match ^1\\. PATTERN" approach produced
    81 false-positive sections on a 94-page document (per the NVIC 04-08
    ingest in the prior sprint); avoiding that here.
  - One Section per document. The shared chunker handles the 512-token
    split downstream — so a 94-page policy letter becomes N chunks but
    they share a single section_number like "CG-MMC PL 01-18".
  - section_title carries ERG-style credential-domain alias enrichment
    (see erg.py:425 for the precedent) selected per document based on
    filename + content keywords. Because the chunker prefixes every
    chunk's text with "[section_number] section_title", those aliases
    land in every chunk's embedding — critical for a 19-document corpus
    competing against 41K+ existing chunks.

Usage:
  uv run python -m ingest.cli --source nmc_policy --fresh
  uv run python -m ingest.cli --source nmc_checklist --fresh
"""

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

TITLE_NUMBER = 0

# ── Source date ──────────────────────────────────────────────────────────────
# NMC corpus doesn't have a single "publication date" — each file has its
# own effective date. The pipeline's update-mode short-circuit uses this as
# a collective watermark, so we set it to today on every run. Per-document
# dates are carried on the Section's up_to_date_as_of via filename parsing.
SOURCE_DATE = date.today()


# ── File → bucket classification (Step 1) ────────────────────────────────────

_POLICY_FILES: frozenset[str] = frozenset({
    "01-00.pdf",
    "01-16.pdf",  # CG-MMC PL 01-16 — ROUPV endorsements
    "04-03.pdf",
    "07-01.pdf",
    "11-12.pdf",
    "11-15.pdf",
    "CG OES Policy Letter 01-15 signature with Enclosures.pdf",
    "CG-CVC_pol15-03.pdf",
    "CG-MMC 01-18 Harmonization.pdf",
    "Liftboat Policy Letter_Signed 20150406.pdf",
    "PolicyLetter01_16.pdf",  # CG-OES PL 01-16 — Polar Code training (different letter from 01-16.pdf)
    "cg-mmc_policy_letter_01-17_final_3_9_17-date.pdf",
    "crediting_military_ss.pdf",
    # Sprint D6.75 — 2026 NMC announcements + FAQs. Same "Mariner Ready,
    # Mission Steady" newsletter format as the policy letters and
    # mariner-impacting in the same way (process changes, credential
    # validity extensions). Bundled into nmc_policy because they're
    # functionally interpretive guidance from NMC even if not formally
    # "policy letters" — and the source-affinity / retrieval pathways
    # already privilege this source for medical-cert / MMC questions.
    "nmc_asap_portal_launch_010726.pdf",        # ASAP portal launch (2026-01-26)
    "nmc_digital_medical_cert_032626.pdf",      # Digital med cert launch (2026-03-26)
    "nmc_med_cert_faq.pdf",                     # Medical cert FAQ (2026-04-07)
    "nmc_credential_faq.pdf",                   # Credential FAQ (2026-01-23)
    "nmc_govt_shutdown_update_031926.pdf",      # Govt shutdown extensions (2026-03-19)
})

_CHECKLIST_FILES: frozenset[str] = frozenset({
    "application_acceptance_checklist.pdf",
    "cg719b_application_guide.pdf",
    "mcp_fm_nmc5_01_web.pdf",
    "mcp_fm_nmc5_27_web.pdf",
    "mcp_fm_nmc5_209_web.pdf",
    "mcp_fm_nmc5_224_web.pdf",
})

# Blank forms, no substantive text — excluded from RAG.
_EXCLUDED_FILES: frozenset[str] = frozenset({
    "cg_719b (1).pdf",
    "cg_719c.pdf",
    "cg_719k.pdf",
    "cg_719ke.pdf",
    "cg_719p.pdf",
    "cg_719s.pdf",
})


def _files_for(source: str) -> frozenset[str]:
    if source == "nmc_policy":
        return _POLICY_FILES
    if source == "nmc_checklist":
        return _CHECKLIST_FILES
    raise ValueError(f"nmc adapter called with unknown source={source!r}")


# ── Per-document section metadata ────────────────────────────────────────────
#
# For each file, we hand-assign a human-readable section_number that a
# mariner or USCG inspector would recognize on a citation line. This is
# used verbatim in chat responses.  Keys must match filenames in the
# data/raw/nmc/ directory exactly.

_DOC_META: dict[str, dict[str, str]] = {
    # ── Policy letters ────────────────────────────────────────────────────
    "01-00.pdf": {
        "section_number": "NMC PL 01-00",
        "section_title": "NMC Policy Letter 01-00",
    },
    "01-16.pdf": {
        "section_number": "CG-MMC PL 01-16",
        "section_title": "Restricted Operator of Uninspected Passenger Vessels (ROUPV) Endorsements",
    },
    "04-03.pdf": {
        "section_number": "NMC PL 04-03",
        "section_title": "NMC Policy Letter 04-03",
    },
    "07-01.pdf": {
        "section_number": "NMC PL 07-01",
        "section_title": "NMC Policy Letter 07-01",
    },
    "11-12.pdf": {
        "section_number": "NMC PL 11-12",
        "section_title": "NMC Policy Letter 11-12",
    },
    "11-15.pdf": {
        "section_number": "NMC PL 11-15",
        "section_title": "NMC Policy Letter 11-15",
    },
    "CG OES Policy Letter 01-15 signature with Enclosures.pdf": {
        "section_number": "CG-OES PL 01-15",
        "section_title": "CG-OES Policy Letter 01-15",
    },
    "CG-CVC_pol15-03.pdf": {
        "section_number": "CG-CVC PL 15-03",
        "section_title": "CG-CVC Policy Letter 15-03",
    },
    "CG-MMC 01-18 Harmonization.pdf": {
        "section_number": "CG-MMC PL 01-18",
        "section_title": "CG-MMC Policy Letter 01-18 — Harmonization",
    },
    "Liftboat Policy Letter_Signed 20150406.pdf": {
        "section_number": "Liftboat Policy Letter",
        "section_title": "Liftboat Policy Letter (Signed 2015-04-06)",
    },
    "PolicyLetter01_16.pdf": {
        "section_number": "CG-OES PL 01-16",
        "section_title": "CG-OES Policy Letter 01-16 — Polar Code Training Guidelines",
    },
    "cg-mmc_policy_letter_01-17_final_3_9_17-date.pdf": {
        "section_number": "CG-MMC PL 01-17",
        "section_title": "CG-MMC Policy Letter 01-17",
    },
    "crediting_military_ss.pdf": {
        "section_number": "NMC Military Sea Service Crediting",
        "section_title": "Crediting Military Sea Service Toward MMC",
    },
    # ── 2026 NMC announcements (Sprint D6.75) ─────────────────────────────
    # Section numbers prefixed with the publication date so they sort
    # chronologically and mariners citing them on a deficiency report
    # can include the date inline.
    "nmc_asap_portal_launch_010726.pdf": {
        "section_number": "NMC Announcement 2026-01-26",
        "section_title": "ASAP Portal and Redesigned Website Launch (Application Submission and Additional Information Portal — online MMC and medical certificate submission)",
    },
    "nmc_digital_medical_cert_032626.pdf": {
        "section_number": "NMC Announcement 2026-03-26",
        "section_title": "Digital Medical Certificate Launch (electronic delivery of medical certificates begins)",
    },
    "nmc_med_cert_faq.pdf": {
        "section_number": "NMC Medical Certificate FAQ",
        "section_title": "Medical Certificate FAQ — email delivery, ASAP portal submission, signed copies, waiver exceptions",
    },
    "nmc_credential_faq.pdf": {
        "section_number": "NMC Credential FAQ",
        "section_title": "Merchant Mariner Credential FAQ — application submission, ASAP portal, REC vs NMC, processing times",
    },
    "nmc_govt_shutdown_update_031926.pdf": {
        "section_number": "NMC Announcement 2026-03-19",
        "section_title": "Lapse in Appropriations / Government Shutdown Update — credential validity extensions and STCW dispensations through 2026",
    },
    # ── Checklists & form guides ──────────────────────────────────────────
    "application_acceptance_checklist.pdf": {
        "section_number": "NMC Application Acceptance Checklist",
        "section_title": "MMC Application Acceptance Checklist",
    },
    "cg719b_application_guide.pdf": {
        "section_number": "CG-719B Application Guide",
        "section_title": "CG-719B Application Guide — Instructions for Merchant Mariner Credential",
    },
    "mcp_fm_nmc5_01_web.pdf": {
        "section_number": "MCP-FM-NMC5-01",
        "section_title": "MCP-FM-NMC5-01 — MMC Renewal Application Checklist",
    },
    "mcp_fm_nmc5_27_web.pdf": {
        "section_number": "MCP-FM-NMC5-27",
        "section_title": "MCP-FM-NMC5-27 — Checklist",
    },
    "mcp_fm_nmc5_209_web.pdf": {
        "section_number": "MCP-FM-NMC5-209",
        "section_title": "MCP-FM-NMC5-209 — Checklist",
    },
    "mcp_fm_nmc5_224_web.pdf": {
        "section_number": "MCP-FM-NMC5-224",
        "section_title": "MCP-FM-NMC5-224 — Checklist",
    },
}


# ── ERG-style alias enrichment (§4 of the sprint) ────────────────────────────
#
# Each bucket is a tuple of short alias phrases to append to section_title
# when the source document's filename OR extracted full_text contains the
# bucket's trigger keywords. Aliases ride with the section_title through
# the chunker's header prefix into every chunk's embedding — raises
# retrieval recall for mariners who phrase queries in informal vocabulary.

_ALIAS_BUCKETS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # (bucket_name, trigger_keywords, aliases)
    (
        "credential_lifecycle",
        (
            "mmc", "merchant mariner", "credential", "endorsement",
            "renewal", "raise of grade", "raise in grade",
            "original issuance", "application", "continuity",
            "document of continuity", "harmonization",
        ),
        (
            "MMC", "Merchant Mariner Credential", "mariner credential",
            "renewal", "raise of grade", "original issuance",
            "continuity", "document of continuity",
        ),
    ),
    (
        "medical",
        (
            "medical", "physical evaluation", "physical exam",
            "medical waiver", "medical certificate", "cg-719k", "cg 719k",
            "fitness for duty",
        ),
        (
            "medical certificate", "physical evaluation",
            "medical waiver", "CG-719K", "medical requirements",
        ),
    ),
    (
        "sea_service",
        (
            "sea service", "service time", "military", "navy",
            "uscg reserve", "uniformed service", "credit for service",
            "crediting",
        ),
        (
            "sea service", "service time", "credit for service",
            "military sea service", "uniformed service",
        ),
    ),
    (
        "stcw",
        (
            "stcw", "training, certification", "officer in charge",
            "watchkeeping", "officer endorsement", "national endorsement",
            "rating endorsement", "basic training",
        ),
        (
            "STCW endorsement", "national endorsement",
            "officer endorsement", "rating endorsement",
        ),
    ),
    (
        "psc",
        (
            "psc", "proficiency in survival craft",
            "survival craft", "lifeboatman", "rescue boat",
        ),
        (
            "PSC", "Proficiency in Survival Craft", "lifeboatman",
        ),
    ),
    (
        "deck_officer",
        (
            "oicnw", "officer in charge of a navigational watch",
            "master", "mate", "able seaman", "able-bodied seaman",
            " ab ", "rating forming part of a navigational watch", "rfpnw",
        ),
        (
            "OICNW", "Master", "Mate", "AB", "Able Seaman",
        ),
    ),
    (
        "tankerman",
        (
            "tankerman", "tanker", "dangerous liquid",
            "liquefied gas", "tankerman-pic", "tankerman pic",
        ),
        (
            "Tankerman PIC", "Tankerman", "tanker endorsement",
        ),
    ),
    (
        "passenger",
        (
            "passenger", "roupv", "uninspected passenger vessel",
            "small passenger vessel",
        ),
        (
            "passenger endorsement", "ROUPV",
            "uninspected passenger vessel", "small passenger vessel",
        ),
    ),
    (
        "polar",
        (
            "polar code", "ice", "polar waters", "ships operating in polar",
        ),
        (
            "Polar Code", "polar waters",
        ),
    ),
    (
        "liftboat",
        (
            "liftboat", "lift boat",
        ),
        (
            "liftboat", "offshore supply vessel",
        ),
    ),
]

_MAX_ALIASES_PER_TITLE = 8


def _select_aliases(filename: str, full_text: str) -> list[str]:
    """Return a deduplicated ordered list of aliases that apply to this doc.

    Buckets are evaluated against (filename + first 8KB of body). Aliases
    from all matched buckets are concatenated in bucket-declaration order,
    with duplicates removed and the total capped at _MAX_ALIASES_PER_TITLE.
    """
    haystack = (filename + "\n" + full_text[:8000]).lower()
    seen: set[str] = set()
    picked: list[str] = []
    for _name, triggers, aliases in _ALIAS_BUCKETS:
        if not any(t in haystack for t in triggers):
            continue
        for alias in aliases:
            key = alias.lower()
            if key in seen:
                continue
            # Skip any alias that already appears in the title (to avoid
            # "Title — MMC, MMC" style redundancy when the title itself
            # already contains the acronym).
            seen.add(key)
            picked.append(alias)
            if len(picked) >= _MAX_ALIASES_PER_TITLE:
                return picked
    return picked


def _title_with_aliases(title: str, aliases: list[str]) -> str:
    """Append aliases in parenthetical form, ERG-style.

    Skips aliases already present (case-insensitive) in the title so the
    enriched line doesn't double-print acronyms like "CG-719K" when the
    title already names it.
    """
    if not aliases:
        return title
    title_lower = title.lower()
    fresh = [a for a in aliases if a.lower() not in title_lower]
    if not fresh:
        return title
    return f"{title} ({', '.join(fresh)})"


# ── Text cleaning ────────────────────────────────────────────────────────────

_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)
_DASH_LINE = re.compile(r"^[\-\u2013\u2014]{4,}\s*$", re.MULTILINE)


def _clean_text(text: str) -> str:
    """Minimal PDF cleanup — preserve everything that could inform an answer."""
    text = text.replace("\x00", "")
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Filename-date parsing ────────────────────────────────────────────────────

_FILENAME_YYYYMMDD = re.compile(r"\b(19|20)(\d{2})(\d{2})(\d{2})\b")
_FILENAME_YY_DASH = re.compile(r"\b\d{2}-(\d{2})\b")  # e.g. "01-16" → year 20YY


def _infer_effective_date(filename: str) -> date:
    """Guess an up_to_date_as_of date from the filename. Falls back to today."""
    stem = Path(filename).stem
    m = _FILENAME_YYYYMMDD.search(stem)
    if m:
        yyyy = int(m.group(1) + m.group(2))
        mm = int(m.group(3))
        dd = int(m.group(4))
        try:
            return date(yyyy, mm, dd)
        except ValueError:
            pass
    m = _FILENAME_YY_DASH.search(stem)
    if m:
        yy = int(m.group(1))
        year = 2000 + yy if yy <= 50 else 1900 + yy
        try:
            return date(year, 1, 1)
        except ValueError:
            pass
    return date.today()


# ── PDF text extraction ──────────────────────────────────────────────────────


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract all pages of a PDF as a single joined string."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            stripped = raw.strip()
            if stripped:
                parts.append(stripped)
    return "\n\n".join(parts)


# ── Public API ───────────────────────────────────────────────────────────────


def parse_source(raw_dir: Path, source: str) -> list[Section]:
    """Parse NMC PDFs in ``raw_dir`` for the requested source bucket.

    Args:
        raw_dir: Path to data/raw/nmc/ containing the full NMC corpus.
        source: "nmc_policy" or "nmc_checklist" — selects which files
                this run ingests. Unknown sources raise ValueError.

    Returns:
        One Section per matched PDF (not per internal heading — the
        chunker handles the 512-token split downstream). Files in the
        excluded set or outside the requested bucket are skipped silently.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        logger.error("NMC raw_dir does not exist: %s", raw_dir)
        return []

    wanted = _files_for(source)
    sections: list[Section] = []

    on_disk = sorted(p.name for p in raw_dir.iterdir() if p.suffix.lower() == ".pdf")
    missing = [f for f in wanted if f not in set(on_disk)]
    if missing:
        logger.warning(
            "nmc/%s: %d expected file(s) not on disk: %s",
            source, len(missing), ", ".join(missing),
        )

    for name in on_disk:
        if name not in wanted:
            # Files in the other bucket or the excluded set — this is
            # expected; the other bucket will pick them up on its own run.
            continue

        pdf_path = raw_dir / name
        try:
            full_text = _extract_pdf_text(pdf_path)
        except Exception as exc:
            logger.warning("nmc/%s: failed to extract %s: %s", source, name, exc)
            continue

        cleaned = _clean_text(full_text)
        if not cleaned:
            logger.warning("nmc/%s: %s produced no text — skipping", source, name)
            continue

        meta = _DOC_META.get(name)
        if meta is None:
            logger.warning("nmc/%s: %s has no _DOC_META entry — skipping", source, name)
            continue

        aliases = _select_aliases(name, cleaned)
        enriched_title = _title_with_aliases(meta["section_title"], aliases)

        section = Section(
            source=source,
            title_number=TITLE_NUMBER,
            section_number=meta["section_number"],
            section_title=enriched_title[:500],
            full_text=cleaned,
            up_to_date_as_of=_infer_effective_date(name),
            parent_section_number=None,
        )
        sections.append(section)
        logger.info(
            "nmc/%s: %s → %d chars, aliases=%s",
            source, meta["section_number"], len(cleaned),
            ",".join(aliases) if aliases else "(none)",
        )

    logger.info("nmc/%s: parsed %d/%d expected documents", source, len(sections), len(wanted))
    return sections
