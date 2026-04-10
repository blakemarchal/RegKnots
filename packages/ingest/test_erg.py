#!/usr/bin/env python3
"""
ERG ingest diagnostic script.

Run from packages/ingest/:
    uv run python test_erg.py

Or with a custom PDF path:
    uv run python test_erg.py /path/to/ERG2024-Eng-Web-a.pdf

Tests each stage of the ERG pipeline independently and prints diagnostic
output at every step.  No database or API keys needed.
"""

import sys
import traceback
from pathlib import Path

# Resolve the PDF path
if len(sys.argv) > 1:
    pdf_path = Path(sys.argv[1])
else:
    # Default: data/raw/erg/ERG2024-Eng-Web-a.pdf relative to repo root
    pdf_path = Path(__file__).resolve().parents[2] / "data" / "raw" / "erg" / "ERG2024-Eng-Web-a.pdf"

print(f"=== ERG Ingest Diagnostic ===")
print(f"PDF path: {pdf_path}")
print(f"Exists:   {pdf_path.exists()}")
if pdf_path.exists():
    print(f"Size:     {pdf_path.stat().st_size:,} bytes")
print()

if not pdf_path.exists():
    print("ERROR: PDF file not found. Pass the path as an argument.")
    sys.exit(1)


# ── Step 1: pdfplumber extraction ────────────────────────────────────────────
print("--- Step 1: pdfplumber page extraction ---")
try:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Total pages: {total_pages}")

        # Extract first few pages as a test
        sample_pages = [0, 1, 10, 30, 100, 170, 200, 290, 350, 391]
        for pg_num in sample_pages:
            if pg_num >= total_pages:
                continue
            try:
                text = pdf.pages[pg_num].extract_text() or ""
                print(f"  Page {pg_num:>3}: {len(text):>5} chars | {text[:80].replace(chr(10), '  ')!r}")
            except Exception as exc:
                print(f"  Page {pg_num:>3}: EXTRACTION ERROR: {exc}")

    print(f"\nFull extraction uses per-page timeout — calling _extract_pages()...")

except Exception as exc:
    print(f"FATAL: pdfplumber sample failed: {exc}")
    traceback.print_exc()
    sys.exit(1)


# Full extraction using the module's timeout-protected _extract_pages
print("--- Step 1b: Full page extraction (with timeout) ---")
try:
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from ingest.sources.erg import _extract_pages
    pages = _extract_pages(pdf_path)
    non_empty = sum(1 for p in pages if p.strip())
    total_chars = sum(len(p) for p in pages)
    print(f"Extracted: {len(pages)} pages, {non_empty} non-empty, {total_chars:,} total chars")
    print()

except Exception as exc:
    print(f"FATAL: pdfplumber failed: {exc}")
    traceback.print_exc()
    sys.exit(1)


# ── Step 2: import erg module and call parse_source ──────────────────────────
print("--- Step 2: parse_source() ---")
try:
    from ingest.sources.erg import parse_source, _detect_boundaries, _extract_pages

    print("Calling parse_source()...")
    sections = parse_source(pdf_path)
    print(f"Sections returned: {len(sections)}")

    if not sections:
        print("WARNING: parse_source() returned 0 sections!")
        print()

        # Extra diagnostics: run boundary detection separately
        print("--- Step 2b: boundary detection debug ---")
        pages_for_debug = _extract_pages(pdf_path)
        boundaries = _detect_boundaries(pages_for_debug)
        print(f"Boundaries: {boundaries}")
        for key, page_idx in boundaries.items():
            if 0 <= page_idx < len(pages_for_debug):
                snippet = pages_for_debug[page_idx][:150].replace("\n", "\\n")
                print(f"  {key} (page {page_idx}): {snippet!r}")
    else:
        # Print section summary by type
        from collections import Counter
        type_counts: Counter = Counter()
        for s in sections:
            # Classify by section_number prefix
            if "Guide" in s.section_number:
                type_counts["Orange Guides"] += 1
            elif "Yellow" in s.section_number:
                type_counts["Yellow Index"] += 1
            elif "Blue" in s.section_number:
                type_counts["Blue Index"] += 1
            elif "Table" in s.section_number:
                type_counts["Green Tables"] += 1
            elif "Glossary" in s.section_number or "CBRN" in s.section_number or "Phone" in s.section_number or "IED" in s.section_number:
                type_counts["Back Matter"] += 1
            elif "Block" in s.section_number and "Full" in s.section_number:
                type_counts["Full Doc Fallback"] += 1
            else:
                type_counts["White/Front Matter"] += 1

        print(f"\nSection breakdown:")
        for cat, count in sorted(type_counts.items()):
            print(f"  {cat}: {count}")

        # Print first 3 sections
        print(f"\nFirst 3 sections:")
        for s in sections[:3]:
            text_len = len(s.full_text)
            print(f"  [{s.section_number}] {s.section_title}")
            print(f"    source={s.source}, title_number={s.title_number}, text={text_len} chars")
            print(f"    text preview: {s.full_text[:100].replace(chr(10), '  ')!r}")
            print()

        # Print Orange Guide sections
        orange = [s for s in sections if "Guide" in s.section_number]
        if orange:
            print(f"Orange Guide sections ({len(orange)} total):")
            for s in orange[:5]:
                print(f"  [{s.section_number}] {s.section_title} ({len(s.full_text)} chars)")
            if len(orange) > 5:
                print(f"  ... and {len(orange) - 5} more")
        else:
            print("WARNING: No Orange Guide sections found!")
        print()

except Exception as exc:
    print(f"FATAL: parse_source() failed with exception:")
    traceback.print_exc()
    print()


# ── Step 3: chunking ────────────────────────────────────────────────────────
print("--- Step 3: chunk_section() ---")
try:
    from ingest.chunker import chunk_section

    if sections:
        total_chunks = 0
        empty_sections = 0
        chunk_errors = 0
        for s in sections:
            try:
                chunks = chunk_section(s)
                total_chunks += len(chunks)
                if not chunks:
                    empty_sections += 1
            except Exception as exc:
                chunk_errors += 1
                if chunk_errors <= 3:
                    print(f"  Chunk error on [{s.section_number}]: {exc}")

        print(f"Total chunks: {total_chunks}")
        print(f"Sections with 0 chunks: {empty_sections}")
        print(f"Chunk errors: {chunk_errors}")

        if total_chunks > 0:
            # Show a sample chunk
            sample_chunks = chunk_section(sections[0])
            if sample_chunks:
                c = sample_chunks[0]
                print(f"\nSample chunk:")
                print(f"  section_number: {c.section_number}")
                print(f"  chunk_index:    {c.chunk_index}")
                print(f"  content_hash:   {c.content_hash[:16]}...")
                print(f"  token_count:    {c.token_count}")
                print(f"  text preview:   {c.chunk_text[:100].replace(chr(10), '  ')!r}")
    else:
        print("Skipped (no sections)")
    print()

except Exception as exc:
    print(f"FATAL: chunking failed:")
    traceback.print_exc()
    print()


# ── Step 4: TITLE_NAMES check ───────────────────────────────────────────────
print("--- Step 4: store._to_row compatibility ---")
try:
    from ingest.models import TITLE_NAMES
    title_num = 0  # ERG uses TITLE_NUMBER = 0
    if title_num in TITLE_NAMES:
        print(f"TITLE_NAMES[{title_num}] = {TITLE_NAMES[title_num]!r}")
        if "COLREGs" in TITLE_NAMES[title_num]:
            print("  NOTE: ERG chunks will be labeled with COLREGs title (cosmetic issue, not a bug)")
    else:
        print(f"ERROR: TITLE_NAMES[{title_num}] is missing — store._to_row() will crash!")
    print()
except Exception as exc:
    print(f"Error: {exc}")
    print()


# ── Summary ──────────────────────────────────────────────────────────────────
print("=== Summary ===")
if 'sections' in dir() and sections and 'total_chunks' in dir() and total_chunks > 0:
    print(f"PASS: {len(sections)} sections, {total_chunks} chunks")
    print(f"Expected range: 400-800 chunks. {'OK' if 200 <= total_chunks <= 2000 else 'UNEXPECTED COUNT'}")
elif 'sections' in dir() and sections:
    print(f"PARTIAL: {len(sections)} sections but chunking produced issues")
else:
    print("FAIL: 0 sections produced — check errors above")
