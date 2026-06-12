"""MLC 2006 — Maritime Labour Convention, 2006 (as amended) adapter.

Sprint D6.97 audit follow-up (2026-06). The ILO Maritime Labour
Convention is the international "fourth pillar" of maritime regulation
(alongside SOLAS, MARPOL, STCW). It binds every ratifying flag and is
the daily reference for shore-side compliance officers: seafarer
employment agreements, wages, hours of work/rest, leave, repatriation,
manning, accommodation, **food and catering** (Reg 3.2 / Standard
A3.2 — Nirmal Chopra's 2026-06-04 provisions question), medical care,
shipowner liability, health & safety, social security, and the flag-/
port-State compliance regime (Title 5).

Before this, the corpus held 458 "MLC" sections — but all were German
(BG Verkehr) and Liberian (LISCR) *implementations*, never the
convention text itself. A query about MLC food/catering surfaced
nothing authoritative; the hedge classifier even mis-recommended
SOLAS Ch. VI (cargo), showing the cost of the gap.

License: ILO standards texts are freely published and redistributable
with attribution. Consolidated text incl. 2014/2016/2018/2022
amendments, downloaded from ilo.org (ilo.org WAF-blocks the prod IP, so
the PDF is manually placed in data/raw/mlc/ — same pattern as ABS /
COSWP / Lloyd's).

Input layout — data/raw/mlc/
  *.pdf  (ILO consolidated MLC 2006 as amended)

Section numbering — one Section per structural unit, so compliance
officers can cite the exact instrument and it structured-matches:
  "MLC Article II"
  "MLC Title 3"
  "MLC Reg 3.2"          — Food and catering (the binding Regulation)
  "MLC Standard A3.2"    — the mandatory Code Part A
  "MLC Guideline B3.2"   — the advisory Code Part B
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE        = "mlc"
TITLE_NUMBER  = 0
SOURCE_DATE   = date(2026, 6, 6)
# Consolidated text including the 2022 amendments (in force 23 Dec 2024).
UP_TO_DATE_AS_OF = date(2024, 12, 23)
PARENT_LABEL  = "MLC 2006"


# Heading detector. Matches the five structural unit types on their own
# line. Sub-numbered Regulations (5.1.1) and Guidelines (B2.7.1) are
# supported. The en-dash title (Regulation 3.2 – Food and catering) is
# captured where present.
_HEADING_RE = re.compile(
    r"(?m)^[ \t]*"
    r"(?P<kind>Article\s+[IVXL]+"
    r"|Title\s+\d+"
    r"|Regulation\s+\d+(?:\.\d+){1,2}"
    r"|Standard\s+A\d+(?:\.\d+){1,2}"
    r"|Guideline\s+B\d+(?:\.\d+){1,2})"
    r"(?P<rest>[^\n]{0,120})$"
)


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op: the ILO PDF is manually placed (ilo.org WAF-blocks the
    prod IP). The CLI dispatcher expects this function."""
    _ = failed_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    count = len(list(raw_dir.glob("*.pdf")))
    console.print(
        f"  [cyan]mlc:[/cyan] {count} MLC PDF file(s) (manually placed, no download)"
    )
    return count, 0


def get_source_date(raw_dir: Path) -> date:
    _ = raw_dir
    return SOURCE_DATE


def parse_source(raw_dir: Path) -> list[Section]:
    pdfs = list(raw_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("mlc: no PDF found in %s", raw_dir)
        return []
    pdf_path = pdfs[0]
    text = _extract_pdf_text(pdf_path)
    if len(text) < 10_000:
        logger.warning("mlc: extracted text suspiciously short (%d chars)", len(text))
    sections = _split_into_units(text)
    logger.info("mlc: parsed %d sections from %s", len(sections), pdf_path.name)
    return sections


# ── PDF extraction ────────────────────────────────────────────────────────

_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        page_texts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                t = _PAGE_NUMBER_LINE.sub("", t)
                t = re.sub(r"[ \t]+", " ", t)
                t = re.sub(r"\n{3,}", "\n\n", t)
                page_texts.append(t.strip())
        return "\n\n".join(p for p in page_texts if p)
    except Exception as exc:
        logger.warning("mlc: pdfplumber failed (%s); falling back to pdftotext", exc)
        out = subprocess.run(
            ["pdftotext", "-q", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=120,
        )
        return out.stdout


# ── Splitting ─────────────────────────────────────────────────────────────


def _canonical(kind: str, rest: str) -> tuple[str, str]:
    """Return (section_number, section_title) for a heading."""
    kind = re.sub(r"\s+", " ", kind).strip()
    # Title text: take the part after an en/em dash or after a period+space
    # ("Title 3. Accommodation..."), stripping dotted leaders.
    title = ""
    cleaned = rest.strip()
    cleaned = re.sub(r"\.{3,}.*$", "", cleaned).strip()  # drop TOC dot leaders
    m = re.match(r"^[–—-]\s*(.+)$", cleaned)
    if m:
        title = m.group(1).strip()
    elif cleaned.startswith("."):
        title = cleaned.lstrip(". ").strip()
    else:
        title = cleaned

    if kind.startswith("Regulation"):
        num = kind.split()[1]
        sn = f"{PARENT_LABEL} Reg {num}"
        st = title or f"Regulation {num}"
    elif kind.startswith("Standard"):
        code = kind.split()[1]  # "A3.2"
        sn = f"{PARENT_LABEL} Standard {code}"
        st = title or f"Standard {code}"
    elif kind.startswith("Guideline"):
        code = kind.split()[1]  # "B3.2"
        sn = f"{PARENT_LABEL} Guideline {code}"
        st = title or f"Guideline {code}"
    elif kind.startswith("Title"):
        num = kind.split()[1]
        sn = f"{PARENT_LABEL} Title {num}"
        st = title or f"Title {num}"
    else:  # Article
        roman = kind.split()[1]
        sn = f"{PARENT_LABEL} Article {roman}"
        st = title or f"Article {roman}"
    return sn, st[:200]


def _split_into_units(text: str) -> list[Section]:
    """Split MLC text into one Section per structural unit.

    Every heading appears twice — once in the Table of Contents (with
    dotted-leader '......' and no body) and once at the real body. We
    slice between consecutive headings, then dedup by section_number
    keeping the LONGEST body (the real text, not the TOC stub).
    """
    matches = list(_HEADING_RE.finditer(text))
    if len(matches) < 10:
        logger.warning("mlc: only %d headings — emitting whole-doc fallback", len(matches))
        return [_whole_doc(text)]

    # Build (section_number, section_title, body) for each heading slice.
    best: dict[str, tuple[str, str]] = {}  # sn -> (title, body), longest body wins
    for i, m in enumerate(matches):
        sn, st = _canonical(m.group("kind"), m.group("rest"))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if sn not in best or len(body) > len(best[sn][1]):
            best[sn] = (st, body)

    sections: list[Section] = []
    for sn, (st, body) in best.items():
        if len(body) < 200:
            continue  # TOC stub or trivially short
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=sn,
            section_title=st,
            full_text=body,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number=PARENT_LABEL,
            published_date=UP_TO_DATE_AS_OF,
        ))
    # Stable order: Articles, Titles, then Reg/Standard/Guideline by number.
    sections.sort(key=lambda s: s.section_number)
    return sections


def _whole_doc(text: str) -> Section:
    return Section(
        source=SOURCE, title_number=TITLE_NUMBER,
        section_number=PARENT_LABEL,
        section_title="Maritime Labour Convention, 2006 (as amended)",
        full_text=text,
        up_to_date_as_of=UP_TO_DATE_AS_OF,
        parent_section_number=PARENT_LABEL,
        published_date=UP_TO_DATE_AS_OF,
    )


def dry_run(raw_dir: Path) -> None:
    sections = parse_source(raw_dir)
    print(f"\nmlc: {len(sections)} sections\n")
    for s in sections:
        print(f"  {s.section_number:28s} {len(s.full_text):6d}ch  {s.section_title[:60]}")


def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("raw_dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.dry_run:
        dry_run(args.raw_dir)
    else:
        print(f"sections={len(parse_source(args.raw_dir))}")


if __name__ == "__main__":
    _main()
