"""USCG Marine Safety Manual (CIM 16000.X series) source adapter.

Sprint D6.4 — ingests USCG Coast Guard Marine Safety Manual volumes
and modular Marine Safety Commandant Instructions. Karynn's 2026-04-22
session surfaced PSC-enforcement questions ("penalties if PSC inspector
asks for VGM") that hedged because USCG MSM content wasn't in corpus.

Source: USCG Directives Library (cdfn.uscg.mil / dco.uscg.mil). Akamai
blocks automated fetches, so PDFs are manually downloaded by Blake and
placed under data/raw/uscg_msm/. This adapter parses whatever's present.

Documents this adapter recognizes (others are skipped with a warning):

  CIM_16000_8b   MSM Volume III — Marine Industry Personnel
  CIM_16000_10a  MSM Volume V — Investigations and Enforcement
  CIM_16000_70   Marine Safety: Marine Inspection Administration (2021)
  CIM_16000_71   Marine Safety: Domestic Inspection Programs (2021)
  CIM_16000_72   Marine Safety: Inspection of Engineering Systems (2021)
  CIM_16000_73   Marine Safety: Port State Control (2021)             ← Karynn's PSC topic
  CIM_16000_74   Marine Safety: International Conventions (2021)
  CIM_16000_75   Marine Safety: Carriage of Hazardous Materials (2021)
  CIM_16000_76   Marine Safety: Outer Continental Shelf Activities (2021)

Skipped (cancelled or partial change-notices, not full content):

  CIM_16000_6    Change-notice fragment to Vol I, not the full Vol I
  CIM_16000_9    CANCELLED Sep 28 2005
  CIM_16000_11   CANCELLED Oct 10 1997

Chunking strategy:

  * Extract via pdftotext (fast, table fidelity is OK for this content).
  * Strip repeated running headers ("CHAPTER N: TITLE" appearing on
    every page) so each chapter shows up once as a real boundary.
  * Split each PDF into one Section per CHAPTER. Sub-section splitting
    by ALL-CAPS headings is left to the downstream chunker — the MSM
    chapters are typically 5-30 pages so the chunker's 512-token slicer
    will produce reasonable sub-chunks naturally.
  * section_number format: "USCG MSM 16000.73 Ch.1"
  * parent_section_number: "USCG MSM 16000.73" (document-level)
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE = "uscg_msm"
TITLE_NUMBER = 0

# Source date — the September 2021 modular issuances are the most recent
# bulk wave; older volumes (8b, 10a) predate that. Use a conservative
# date that covers all docs in the manifest.
SOURCE_DATE = date(2021, 9, 1)


# Document manifest — file basename → (cim_number, friendly_title).
# Files outside this manifest are SKIPPED with a warning so we don't
# accidentally ingest cancelled change-notices.
_MANIFEST: dict[str, tuple[str, str]] = {
    "CIM_16000_8b.pdf":   ("16000.8B",  "MSM Volume III — Marine Industry Personnel"),
    "CIM_16000_10a.pdf":  ("16000.10A", "MSM Volume V — Investigations and Enforcement"),
    "CIM_16000_70.pdf":   ("16000.70",  "Marine Safety — Marine Inspection Administration"),
    "CIM_16000_71.pdf":   ("16000.71",  "Marine Safety — Domestic Inspection Programs"),
    "CIM_16000_72.pdf":   ("16000.72",  "Marine Safety — Inspection of Engineering Systems, Equipment, and Materials"),
    "CIM_16000_73.pdf":   ("16000.73",  "Marine Safety — Port State Control"),
    "CIM_16000_74.pdf":   ("16000.74",  "Marine Safety — International Conventions, Treaties, Standards, and Regulations"),
    "CIM_16000_75.pdf":   ("16000.75",  "Marine Safety — Carriage of Hazardous Materials"),
    "CIM_16000_76.pdf":   ("16000.76",  "Marine Safety — Outer Continental Shelf Activities"),
}


# Chapter-heading regex — "CHAPTER 1: TITLE" or "CHAPTER 12: TITLE"
_CHAPTER_RE = re.compile(
    r"^CHAPTER\s+([0-9]+(?:\.[0-9]+)?)\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)

# Page-footer / page-number lines we want to strip
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d+\s*$", re.MULTILINE)


def _extract_text(pdf_path: Path) -> str:
    out = subprocess.check_output(
        ["pdftotext", str(pdf_path), "-"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    out = _PAGE_NUMBER_LINE.sub("", out)
    return out


def _dedupe_running_headers(text: str) -> str:
    """Many USCG MSM PDFs repeat the chapter heading on every page as a
    running header. Strip duplicates so chapter splitting works cleanly:
    only the FIRST occurrence of each "CHAPTER N: TITLE" line survives.
    """
    lines = text.split("\n")
    out: list[str] = []
    seen_headers: set[str] = set()
    for line in lines:
        m = _CHAPTER_RE.match(line)
        if m:
            chap_num = m.group(1)
            if chap_num in seen_headers:
                # Replace duplicate header with a blank — preserves line
                # numbering for any debugging but disappears from text.
                out.append("")
                continue
            seen_headers.add(chap_num)
        out.append(line)
    return "\n".join(out)


def _collapse_whitespace(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_into_chapters(text: str, cim_number: str, title: str) -> list[tuple[str, str, str]]:
    """Split cleaned text into (section_number, section_title, body) tuples
    by CHAPTER markers. If no CHAPTER markers exist (some docs use a
    different structure), the entire text becomes one Section.
    """
    matches = list(_CHAPTER_RE.finditer(text))
    if not matches:
        # No chapter structure found — emit the whole doc as one section.
        return [(
            f"USCG MSM {cim_number}",
            title,
            _collapse_whitespace(text),
        )]

    sections: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        chap_num = m.group(1)
        chap_title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        body = _collapse_whitespace(body)
        if not body:
            continue
        sections.append((
            f"USCG MSM {cim_number} Ch.{chap_num}",
            f"{title} — Ch.{chap_num} {chap_title}",
            body,
        ))
    return sections


# ── Public API ────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op discovery — files are manually placed by Blake.

    The CLI's multi-PDF dispatch calls this before parse_source. For NVIC
    we use it to fetch live from the publisher; for USCG MSM the publisher
    (dco.uscg.mil) is Akamai-blocked, so files come in via scp instead.
    Reports the count of recognized files so the CLI summary is honest.
    """
    if not raw_dir.exists():
        return (0, 1)
    found = sum(1 for p in raw_dir.glob("*.pdf") if p.name in _MANIFEST)
    skipped = sum(1 for p in raw_dir.glob("*.pdf") if p.name not in _MANIFEST)
    if console:
        console.print(
            f"  [cyan]USCG MSM:[/cyan] {found} recognized files, "
            f"{skipped} non-manifest skipped"
        )
    return (found, 0)


def get_source_date(raw_dir: Path) -> date:
    """Return the source date used on every Section emitted in this run."""
    return SOURCE_DATE


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all known USCG MSM PDFs in raw_dir, return Section objects.

    Args:
        raw_dir: data/raw/uscg_msm/ — directory of CIM_16000_*.pdf files.

    Returns:
        List of Section objects. Files outside the manifest are skipped
        with a warning so cancelled change-notices don't pollute the corpus.
    """
    if not raw_dir.exists():
        raise FileNotFoundError(f"USCG MSM dir not found: {raw_dir}")

    sections: list[Section] = []
    skipped: list[str] = []

    for pdf_path in sorted(raw_dir.glob("*.pdf")):
        manifest_entry = _MANIFEST.get(pdf_path.name)
        if not manifest_entry:
            skipped.append(pdf_path.name)
            continue
        cim_number, title = manifest_entry

        logger.info("USCG MSM: parsing %s (%s)", pdf_path.name, cim_number)
        text = _extract_text(pdf_path)
        text = _dedupe_running_headers(text)
        chapters = _split_into_chapters(text, cim_number, title)

        parent = f"USCG MSM {cim_number}"
        for sec_num, sec_title, body in chapters:
            if not body.strip():
                continue
            sections.append(Section(
                source=SOURCE,
                title_number=TITLE_NUMBER,
                section_number=sec_num,
                section_title=sec_title,
                full_text=body,
                up_to_date_as_of=SOURCE_DATE,
                parent_section_number=parent,
            ))
        logger.info(
            "USCG MSM: %s yielded %d chapters",
            pdf_path.name, len(chapters),
        )

    if skipped:
        logger.warning(
            "USCG MSM: skipped %d non-manifest files (cancelled or partial): %s",
            len(skipped), skipped,
        )
    logger.info(
        "USCG MSM: parsed %d total sections from %d documents",
        len(sections), len(_MANIFEST),
    )
    return sections
