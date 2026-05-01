"""
IMO instrument codes adapter — CSS, Load Lines, IGC, IBC, HSC.

Sprint D6.23. The consolidated published forms of these IMO codes are
behind an IMO Publishing paywall. The underlying MSC/MEPC/Assembly
adoption resolutions are FREE on wwwcdn.imo.org and provide ~90% of
the operational content (the codes ARE the resolution annexes; the
paywalled book adds editorial cross-references).

License: IMO assembly resolutions and MSC/MEPC documents are freely
redistributable as adopted IMO instruments. Copyright posture is the
same as how SOLAS is handled — public regulatory content cited with
attribution.

Authority tier (set in rag/authority.py):
  imo_css       — Tier 1 (binding via SOLAS Ch.VI)
  imo_loadlines — Tier 1 (treaty)
  imo_igc       — Tier 1 (binding for gas carriers)
  imo_ibc       — Tier 1 (binding for chemical tankers)
  imo_hsc       — Tier 1 (binding for high-speed craft)

Single adapter handles all five via the `imo_code` config key in
cli.py — the kind keys into _CURATED_BY_CODE to pick which document
set to ingest.

Section numbering convention varies by code:
  CSS          → "IMO CSS Code §1" / "IMO CSS A.714(17) Annex" / etc.
  Load Lines   → "IMO Load Lines 1966" / "IMO LL 1988 Protocol"
  IGC          → "IMO IGC Code MSC.370(93)"
  IBC          → "IMO IBC Code MEPC.318(74)"
  HSC          → "IMO HSC Code MSC.97(73)"
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

from ingest.models import Section

logger = logging.getLogger(__name__)


TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class CodeDocMeta:
    code:           str    # "A.714(17)" / "MSC.370(93)" / "1966 Convention"
    title:          str
    pdf_url:        str
    effective_date: date
    parent_label:   str    # "IMO CSS Code" / "IMO Load Lines" / etc.

    @property
    def section_number(self) -> str:
        return f"{self.parent_label} {self.code}"

    @property
    def parent_section_number(self) -> str:
        return self.parent_label

    @property
    def filename_stub(self) -> str:
        return self.section_number.replace(" ", "_").replace(".", "_").replace("(", "").replace(")", "")


# ── Curated docs per IMO code ────────────────────────────────────────────────

_IMO_CDN = "https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions"

_CURATED_BY_CODE: dict[str, list[CodeDocMeta]] = {
    "css": [
        CodeDocMeta(
            code="A.714(17)",
            title="Code of Safe Practice for Cargo Stowage and Securing",
            pdf_url=f"{_IMO_CDN}/AssemblyDocuments/A.714(17).pdf",
            effective_date=date(1991, 11, 6),
            parent_label="IMO CSS Code",
        ),
    ],
    "loadlines": [
        CodeDocMeta(
            code="1966 Convention",
            title="International Convention on Load Lines, 1966 (UN Treaty Series)",
            pdf_url="https://www.austlii.edu.au/au/other/dfat/treaties/1968/22.html",
            effective_date=date(1968, 7, 21),
            parent_label="IMO Load Lines",
        ),
        # 1988 Protocol amendments via MSC resolutions live on IMO CDN.
        CodeDocMeta(
            code="MSC.375(93)",
            title="Adoption of Amendments to the Annex of the 1988 Protocol",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.375(93).pdf",
            effective_date=date(2014, 5, 22),
            parent_label="IMO Load Lines",
        ),
    ],
    "igc": [
        CodeDocMeta(
            code="MSC.370(93)",
            title="International Code for the Construction and Equipment of Ships Carrying Liquefied Gases in Bulk (IGC Code)",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.370(93).pdf",
            effective_date=date(2016, 1, 1),
            parent_label="IMO IGC Code",
        ),
    ],
    "ibc": [
        CodeDocMeta(
            code="MEPC.318(74)",
            title="Amendments to the IBC Code (Chapters 17 and 18 product list)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.318(74).pdf",
            effective_date=date(2021, 1, 1),
            parent_label="IMO IBC Code",
        ),
    ],
    "hsc": [
        CodeDocMeta(
            code="MSC.97(73)",
            title="International Code of Safety for High-Speed Craft (HSC Code 2000)",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.97(73).pdf",
            effective_date=date(2002, 7, 1),
            parent_label="IMO HSC Code",
        ),
    ],

    # Sprint D6.41 — Polar Code (standalone). Two parallel adoption resolutions
    # (one MSC for safety, one MEPC for environment) plus their respective
    # SOLAS / MARPOL implementing amendments. Together these are the full
    # Polar Code as it actually applies to ships.
    "polar": [
        CodeDocMeta(
            code="MSC.385(94)",
            title="International Code for Ships Operating in Polar Waters (Polar Code) — adoption (safety)",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.385(94).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO Polar Code",
        ),
        CodeDocMeta(
            code="MSC.386(94)",
            title="Polar Code — SOLAS Chapter XIV implementing amendments",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.386(94).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO Polar Code",
        ),
        CodeDocMeta(
            code="MEPC.264(68)",
            title="International Code for Ships Operating in Polar Waters (Polar Code) — adoption (environment)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.264(68).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO Polar Code",
        ),
        CodeDocMeta(
            code="MEPC.265(68)",
            title="Polar Code — MARPOL Annex I/II/IV/V implementing amendments",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.265(68).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO Polar Code",
        ),
    ],

    # Sprint D6.41 — IGF Code (International Code of Safety for Ships using
    # Gases or Other Low-flashpoint Fuels). Mandatory for LNG / LPG / methanol
    # / ammonia / hydrogen-fueled ships under SOLAS Ch II-1 Part G. Adoption
    # resolution + the SOLAS amendment that makes it mandatory.
    "igf": [
        CodeDocMeta(
            code="MSC.391(95)",
            title="International Code of Safety for Ships using Gases or Other Low-flashpoint Fuels (IGF Code) — adoption",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.391(95).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO IGF Code",
        ),
        CodeDocMeta(
            code="MSC.392(95)",
            title="IGF Code — SOLAS Chapter II-1 Part G mandatory-application amendments",
            pdf_url=f"{_IMO_CDN}/MSCResolutions/MSC.392(95).pdf",
            effective_date=date(2017, 1, 1),
            parent_label="IMO IGF Code",
        ),
    ],

    # Sprint D6.41 — BWM Convention (Ballast Water Management).
    # Note: the IMO consolidated BWM Convention text itself is paywalled.
    # The Convention's operational requirements (D-1 / D-2 standards, BWMS
    # approval, biofouling, PSC sampling, type-approval-Code G8) are all
    # in MEPC resolutions which ARE free. We ingest those — that's actually
    # what mariners need to comply (the Convention itself is high-level;
    # the resolutions are the implementation detail).
    "bwm": [
        CodeDocMeta(
            code="MEPC.174(58)",
            title="Guidelines for Approval of Ballast Water Management Systems (G8, original)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.174(58).pdf",
            effective_date=date(2008, 10, 10),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.207(62)",
            title="Guidelines for Control and Management of Ships' Biofouling",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.207(62).pdf",
            effective_date=date(2011, 7, 15),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.252(67)",
            title="Guidelines for Port State Control under the BWM Convention",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.252(67).pdf",
            effective_date=date(2014, 10, 17),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.279(70)",
            title="Code for Approval of Ballast Water Management Systems (BWMS Code) — adopting D-2 implementation",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.279(70).pdf",
            effective_date=date(2016, 10, 28),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.288(71)",
            title="2017 BWM Convention amendments (revised Reg A-1, B-3 + others)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.288(71).pdf",
            effective_date=date(2017, 7, 7),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.296(72)",
            title="2018 Code for Approval of Ballast Water Management Systems (BWMS Code, revised G8)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.296(72).pdf",
            effective_date=date(2018, 4, 13),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.300(72)",
            title="2018 Amendments to the BWM Convention (Annex Reg E-1)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.300(72).pdf",
            effective_date=date(2018, 4, 13),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.349(78)",
            title="2022 Amendments to the BWMS Code (test methods + electronic record-book provisions)",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.349(78).pdf",
            effective_date=date(2022, 6, 10),
            parent_label="IMO BWM Convention",
        ),
        CodeDocMeta(
            code="MEPC.380(80)",
            title="2023 Amendments to the BWM Convention",
            pdf_url=f"{_IMO_CDN}/MEPCDocuments/MEPC.380(80).pdf",
            effective_date=date(2023, 7, 7),
            parent_label="IMO BWM Convention",
        ),
    ],
}

# Source-code mapping back from the imo_code key
_CODE_TO_SOURCE = {
    "css": "imo_css",
    "loadlines": "imo_loadlines",
    "igc": "imo_igc",
    "ibc": "imo_ibc",
    "hsc": "imo_hsc",
    "polar": "imo_polar",
    "igf": "imo_igf",
    "bwm": "imo_bwm",
}


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console, imo_code: str) -> tuple[int, int]:
    if imo_code not in _CURATED_BY_CODE:
        raise ValueError(f"Unknown imo_code: {imo_code!r}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    docs = _CURATED_BY_CODE[imo_code]
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(docs, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                console.print(f"  Downloading {meta.section_number} ({i}/{len(docs)})…")
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                # 1966 Convention from austlii is HTML, not PDF — handle separately
                if meta.pdf_url.endswith(".html"):
                    out_path = raw_dir / f"{meta.filename_stub}.html"
                    out_path.write_text(resp.text, encoding="utf-8")
                else:
                    if not resp.content.startswith(b"%PDF"):
                        raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                    out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("IMO %s %s: download failed — %s", imo_code, meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(docs):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(),
             "parent_label": m.parent_label}
            for m in docs
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path, imo_code: str) -> list[Section]:
    if imo_code not in _CURATED_BY_CODE:
        raise ValueError(f"Unknown imo_code: {imo_code!r}")
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"IMO index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    source_code = _CODE_TO_SOURCE[imo_code]
    sections: list[Section] = []
    for e in entries:
        meta = CodeDocMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            parent_label=e["parent_label"],
        )
        # Choose pdf or html input based on whether we saved html
        ext = "html" if meta.pdf_url.endswith(".html") else "pdf"
        in_path = raw_dir / f"{meta.filename_stub}.{ext}"
        if not in_path.exists():
            logger.warning("IMO %s: input missing at %s, skipping", meta.section_number, in_path)
            continue
        try:
            if ext == "pdf":
                text = _extract_pdf_text(in_path)
            else:
                text = _extract_html_text(in_path)
        except Exception as exc:
            logger.warning("IMO %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("IMO %s: text too short (%d), skipping", meta.section_number, len(text))
            continue
        sections.append(Section(
            source=source_code, title_number=TITLE_NUMBER,
            section_number=meta.section_number,
            section_title=meta.title,
            full_text=text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=meta.parent_section_number,
            published_date=meta.effective_date,
        ))
    logger.info("IMO %s: parsed %d sections from %d doc(s)", imo_code, len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal ─────────────────────────────────────────────────────────────────

def _extract_pdf_text(pdf_path: Path) -> str:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _extract_html_text(html_path: Path) -> str:
    """Strip HTML chrome from the austlii UN Treaty Series page.

    austlii.edu.au treaty pages are mostly clean text wrapped in basic
    HTML; we lean on BeautifulSoup to drop nav/script/style.
    """
    from bs4 import BeautifulSoup
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("body") or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _write_failure(meta: CodeDocMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"imo_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
