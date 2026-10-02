"""NGA navigation publications (2026-10-02): Bowditch, Pub 1310 and Pub 102.

Why: license-exam and watch-standing questions (the sailings, piloting, tides,
celestial, radar plotting, CPA, ARPA, flag and sound signals) had no reference
text in the corpus; the regulations say what to do, these books say how. All
three are U.S. government works (public domain) from the National
Geospatial-Intelligence Agency, served by msi.nga.mil's publications API.

  Pub 9    The American Practical Navigator (Bowditch), Volume I: one section
           per numbered article, "Bowditch Art.1301" (articles are numbered
           chapter x 100, so Art.1301 is in Ch.13). Volume II is tables,
           almanac and tide-table extracts and the glossary: not ingested.
  Pub 1310 Radar Navigation and Maneuvering Board Manual, chapters 1-6:
           each chapter split at its headings, "Pub 1310 Ch.3 Sec.4". The
           appendices are left out: Appendix A is a 1983 extract of SOLAS V/12
           (superseded) and the rest are worked plotting problems.
  Pub 102  International Code of Signals, chapters 1-4 and the appendix: split
           at the SECTION headings, "Pub 102 Ch.2 Sec.1".

Text comes from pdftotext. Plain mode reads Bowditch's and Pub 1310's two
columns in order (pdfplumber interleaves them line by line); layout mode keeps
each Pub 102 signal code on the line with its meaning.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date
from pathlib import Path

from ingest.models import Section, merge_duplicate_sections
from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

SOURCE = "nga_pubs"
TITLE_NUMBER = 0

LISTING_URL = "https://msi.nga.mil/api/publications/stored-pubs?pubTypeId={}"
DOWNLOAD_URL = "https://msi.nga.mil/api/publications/download?key={}&type=view"

# (doc_id, title, NGA pubTypeId, fullFilename, s3Key as of 2026-10-02, date).
# discover() takes the current s3Key from the listing when it answers.
_DOCS: list[tuple[str, str, int, str, str, str]] = [
    ("Bowditch Vol. I", "The American Practical Navigator (Bowditch), Pub. 9, Volume I",
     2, "Bowditch_Vol_1_LoRes.pdf", "16693975/SFH00000/Bowditch_Vol_1_LoRes.pdf", "2024-05-17"),
    ("Pub 1310 Ch.1", "Basic Radar Principles and General Characteristics",
     10, "310ch1.pdf", "16694476/SFH00000/310ch1.pdf", "2019-09-20"),
    ("Pub 1310 Ch.2", "Radar Operation", 10, "310ch2.pdf", "16694476/SFH00000/310ch2.pdf", "2019-09-20"),
    ("Pub 1310 Ch.3", "Collision Avoidance", 10, "310ch3.pdf", "16694476/SFH00000/310ch3.pdf", "2019-09-20"),
    ("Pub 1310 Ch.4", "Radar Navigation", 10, "310ch4.pdf", "16694476/SFH00000/310ch4.pdf", "2019-09-20"),
    ("Pub 1310 Ch.5", "Automatic Radar Plotting Aids (ARPA)",
     10, "310ch5.pdf", "16694476/SFH00000/310ch5.pdf", "2019-09-20"),
    ("Pub 1310 Ch.6", "Maneuvering Board Manual", 10, "310ch6.pdf", "16694476/SFH00000/310ch6.pdf", "2019-09-20"),
    ("Pub 102 Ch.1", "Signaling Instructions", 7, "Chapter1.pdf", "16694273/SFH00000/Chapter1.pdf", "2020-10-30"),
    ("Pub 102 Ch.2", "General Signal Code", 7, "Chapter2.pdf", "16694273/SFH00000/Chapter2.pdf", "2020-10-30"),
    ("Pub 102 Ch.3", "Medical Signal Code", 7, "Chapter3.pdf", "16694273/SFH00000/Chapter3.pdf", "2020-10-30"),
    ("Pub 102 Ch.4", "Distress and Lifesaving Signals; Radiotelephone Procedures",
     7, "Chapter4.pdf", "16694273/SFH00000/Chapter4.pdf", "2020-10-30"),
    ("Pub 102 Appendix", "Appendix", 7, "Appendix.pdf", "16694273/SFH00000/Appendix.pdf", "2020-10-30"),
]

# ── Discovery and download ───────────────────────────────────────────────────


def _listing_keys(pub_type_ids: set[int]) -> dict[tuple[int, str], tuple[str, str | None]]:
    """(pubTypeId, fullFilename) -> (s3Key, last-modified date) from the
    listings that answer; a listing that fails is logged and skipped."""
    found: dict[tuple[int, str], tuple[str, str | None]] = {}
    with u.client() as http:
        for pub_type in sorted(pub_type_ids):
            try:
                rows = json.loads(u.get(http, LISTING_URL.format(pub_type)).text)
            except Exception as exc:
                logger.warning("nga_pubs: listing %s failed (%s); using the saved keys", pub_type, exc)
                continue
            for row in rows:
                if row.get("fullFilename") and row.get("s3Key"):
                    modified = (row.get("sectionLastModified") or "")[:10] or None
                    found[(pub_type, row["fullFilename"])] = (row["s3Key"], modified)
    return found


def discover(listing: dict[tuple[int, str], tuple[str, str | None]] | None = None) -> list[u.Doc]:
    listing = listing or {}
    docs = []
    for doc_id, title, pub_type, filename, key, published in _DOCS:
        key, modified = listing.get((pub_type, filename), (key, published))
        docs.append(u.Doc(doc_id=doc_id, title=title, url=DOWNLOAD_URL.format(key),
                          filename=f"{pub_type}_{filename}", published=modified or published))
    return docs


def discover_and_download(raw_dir: Path, failed_dir: Path, console=None) -> tuple[int, int]:
    docs = discover(_listing_keys({d[2] for d in _DOCS}))
    u.write_index(raw_dir, docs)
    return u.fetch_docs(docs, raw_dir, failed_dir, SOURCE, console=console)


def get_source_date(raw_dir: Path) -> date:
    return u.listing_source_date(raw_dir)


# ── Text ─────────────────────────────────────────────────────────────────────

_CHAR_FIXES = {"˚": "°", "­": "", "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
               "ﬃ": "ffi", "ﬄ": "ffl"}
_SPACED_LEADER = re.compile(r"(?:\s*\.){4,}\s*")   # ". . . . ." before a cross-referenced code
_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-z])")


def pdftotext(path: Path, layout: bool = False) -> str:
    args = ["pdftotext", "-enc", "UTF-8"] + (["-layout"] if layout else []) + [str(path), "-"]
    return subprocess.check_output(args, text=True, encoding="utf-8", stderr=subprocess.DEVNULL, timeout=600)


def normalize(text: str) -> str:
    for bad, good in _CHAR_FIXES.items():
        text = text.replace(bad, good)
    return _HYPHEN_BREAK.sub(r"\1", text)


_SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
_ACRONYMS = {"ARPA", "ECDIS", "GPS", "GNSS", "LORAN", "SAR", "SART", "CPA", "DGPS", "AIS", "GMDSS",
             "IMO", "NAVTEX", "PPI", "CRT", "TDZ", "MDZ", "RT"}


def title_case(caps: str) -> str:
    """"SHORT RANGE AIDS TO NAVIGATION" -> "Short Range Aids to Navigation"; acronyms stay."""
    out = []
    for i, word in enumerate(caps.split()):
        bare = word.strip("(),:;")
        if bare.upper() in _ACRONYMS:
            out.append(word)
        elif i and word.lower() in _SMALL_WORDS:
            out.append(word.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in word.split("-")))
    return " ".join(out)


# ── Bowditch ─────────────────────────────────────────────────────────────────

_CHAPTER = re.compile(r"^CHAPTER (\d{1,2})(?: ([A-Z][A-Z ,'&-]+))?$")
_ARTICLE = re.compile(r"^(\d{3,4})\. ([A-Z][^\n]{1,90})$")
_MIN_ARTICLE_CHARS = 150
_SKIP_ARTICLES = {"references", "bibliography", "suggested reading"}


def bowditch_sections(doc: u.Doc, text: str) -> list[Section]:
    """One Section per numbered article. An article line counts only when its
    number belongs to the current chapter (Art.1301 in Ch.13), or to the next
    one when that chapter's heading was missed."""
    lines = u.clean_text(normalize(text)).split("\n")
    chapter, chapter_title = 0, ""
    current: dict | None = None
    out: list[dict] = []
    pending_title = False
    for line in lines:
        s = line.strip()
        # The volume's appendices (unit tables, formulas whose radical signs
        # don't survive extraction: "D = 1.17 hf" for 1.17√hf) are not read.
        if chapter >= 40 and s in ("APPENDICES", "APPENDIX A"):
            break
        m = _CHAPTER.match(s)
        if m and 1 <= int(m.group(1)) <= 45 and int(m.group(1)) >= chapter:
            chapter, chapter_title = int(m.group(1)), title_case(m.group(2) or "")
            pending_title = not m.group(2)
            current = None
            continue
        if pending_title and s:
            if s.upper() == s and not _ARTICLE.match(s):
                chapter_title = title_case(s)
            pending_title = False
            continue
        a = _ARTICLE.match(s)
        if a and chapter and int(a.group(1)) // 100 in (chapter, chapter + 1) and not a.group(2).endswith("."):
            number = int(a.group(1))
            if number // 100 != chapter:
                chapter, chapter_title = number // 100, ""
            current = {"number": number, "title": a.group(2).strip(), "chapter": chapter,
                       "chapter_title": chapter_title, "lines": []}
            out.append(current)
            continue
        if current is not None:
            # Running heads repeat the chapter title on alternate pages.
            if chapter_title and s.lower() == chapter_title.lower():
                continue
            current["lines"].append(line)
    sections = []
    # Plain mode sometimes reads two headings in a row ("410. Introduction",
    # "411. Zones of Confidence") and then both articles' text: the empty one
    # is folded into the next, under the first number, titled with both.
    # A body under _MIN_ARTICLE_CHARS is a figure caption read out of place.
    # Reference lists ("2418. References") are left out.
    waiting: list[dict] = []
    for art in out:
        if art["title"].lower() in _SKIP_ARTICLES:
            continue
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(art["lines"])).strip()
        if len(body) < _MIN_ARTICLE_CHARS:
            if not waiting or waiting[-1]["chapter"] == art["chapter"]:
                waiting.append(art)
            else:
                waiting = [art]
            continue
        group = [w for w in waiting if w["chapter"] == art["chapter"]] + [art]
        waiting = []
        first = group[0]
        ch = f"Bowditch Ch.{art['chapter']}" + (f" {art['chapter_title']}" if art["chapter_title"] else "")
        heads = "; ".join(f"{g['number']}. {g['title']}" for g in group)
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=f"Bowditch Art.{first['number']}",
            section_title=f"{ch} — {heads}"[:500],
            full_text=body, up_to_date_as_of=doc.published_date or date.today(),
            parent_section_number=f"Bowditch Ch.{art['chapter']}",
        ))
    return sections


# ── Pub 1310 ─────────────────────────────────────────────────────────────────

_CAPS_LINE = re.compile(r"^[A-Z][A-Z ,'()/&.:-]{3,70}$")
_MIN_SECTION_CHARS = 800


def _is_heading(s: str) -> bool:
    """A Pub 1310 heading: a capitals line of real words. Figure labels
    ("M1 M2 M3", "NRML RML DRM", "T1 T2 T3") and running heads are not."""
    if not _CAPS_LINE.match(s) or s.startswith(("CHAPTER ", "FIGURE", "TABLE")):
        return False
    words = re.findall(r"[A-Z]+", s)
    if any(re.search(r"\d", w) for w in s.split()):
        return False
    long_words = [w for w in words if len(w) >= 3]
    return len(long_words) >= 2 and any(len(w) >= 5 for w in long_words) or (len(words) == 1 and len(words[0]) >= 6)


def pub1310_sections(doc: u.Doc, text: str) -> list[Section]:
    """A chapter split at its headings; a part under _MIN_SECTION_CHARS joins
    the next one, so figure-heavy pages don't become one-line sections."""
    lines = u.clean_text(normalize(text)).split("\n")
    # A heading printed on page after page ("OWN SHIP AT CENTER" in Ch.6) is a running head.
    counts: dict[str, int] = {}
    for line in lines:
        if _is_heading(line.strip()):
            counts[line.strip()] = counts.get(line.strip(), 0) + 1
    parts: list[tuple[list[str], list[str]]] = [([], [])]       # (headings, body lines)
    for line in lines:
        s = line.strip()
        if s.startswith("CHAPTER ") or counts.get(s, 0) >= 4:
            continue
        if _is_heading(s):
            parts.append(([s], []))
        else:
            parts[-1][1].append(line)
    merged: list[tuple[list[str], str]] = []
    carry: list[str] = []
    carry_body = ""
    for heads, body_lines in parts:
        body = "\n".join(body_lines).strip()
        carry += heads
        carry_body = f"{carry_body}\n\n{body}".strip() if body else carry_body
        if len(carry_body) >= _MIN_SECTION_CHARS:
            merged.append((carry, carry_body))
            carry, carry_body = [], ""
    if carry_body:
        if merged:
            merged[-1] = (merged[-1][0] + carry, f"{merged[-1][1]}\n\n{carry_body}")
        else:
            merged.append((carry, carry_body))
    sections = []
    for k, (heads, body) in enumerate(merged, 1):
        label = "; ".join(title_case(h) for h in heads[:3]) or "Introduction"
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=f"{doc.doc_id} Sec.{k}",
            section_title=f"{doc.doc_id} {doc.title} — {label}"[:500],
            full_text=re.sub(r"\n{3,}", "\n\n", body), up_to_date_as_of=doc.published_date or date.today(),
            parent_section_number=doc.doc_id,
        ))
    return sections


# ── Pub 102 ──────────────────────────────────────────────────────────────────

_SECTION_102 = re.compile(r"^SECTION (\d{1,2}): ?(.+)$")
_RUNNING_102 = re.compile(r"^(?:SECTION \d{1,2}\.\s*—.*|Code|Meaning|Code Meaning|\d+ CHAPTER)$")


def pub102_sections(doc: u.Doc, text: str) -> list[Section]:
    """A chapter split at its "SECTION n: TITLE" headings; the chapter's
    contents page (headings with dot leaders) and the page running heads
    ("SECTION 1.—DISTRESS—EMERGENCY", "Code", "Meaning") are dropped."""
    body_lines: dict[int, list[str]] = {}
    titles: dict[int, str] = {}
    current: int | None = None
    for line in u.clean_text(normalize(text)).split("\n"):
        s = line.strip()
        m = _SECTION_102.match(s)
        if m and not _SPACED_LEADER.search(m.group(2)) and not re.search(r"\.{4,}", m.group(2)):
            current = int(m.group(1))
            titles.setdefault(current, m.group(2).strip())
            body_lines.setdefault(current, [])
            continue
        if _RUNNING_102.match(s):
            continue
        if current is not None:
            body_lines[current].append(_SPACED_LEADER.sub(" … ", line).rstrip())
    as_of = doc.published_date or date.today()
    if not titles:   # the appendix has no SECTION headings
        body = _SPACED_LEADER.sub(" … ", u.clean_text(normalize(text)))
        return [Section(source=SOURCE, title_number=TITLE_NUMBER, section_number=doc.doc_id,
                        section_title=f"{doc.doc_id} — International Code of Signals, {doc.title}",
                        full_text=body, up_to_date_as_of=as_of)] if len(body) >= 40 else []
    sections = []
    for n, title in titles.items():
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines[n])).strip()
        if len(body) < 40:
            continue
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=f"{doc.doc_id} Sec.{n}",
            section_title=(f"{doc.doc_id} International Code of Signals, {doc.title} — "
                           f"Section {n}: {title_case(title.replace('—', ' — ').replace('  ', ' '))}")[:500],
            full_text=body, up_to_date_as_of=as_of, parent_section_number=doc.doc_id,
        ))
    return sections


# ── Parse ────────────────────────────────────────────────────────────────────


def parse_source(raw_dir: Path) -> list[Section]:
    sections: list[Section] = []
    for doc in u.read_index(raw_dir):
        path = raw_dir / doc.filename
        if not path.exists():
            logger.warning("nga_pubs: %s not on disk (%s) — skipped", doc.doc_id, doc.filename)
            continue
        if doc.doc_id.startswith("Bowditch"):
            sections += bowditch_sections(doc, pdftotext(path))
        elif doc.doc_id.startswith("Pub 1310"):
            sections += pub1310_sections(doc, pdftotext(path))
        else:
            sections += pub102_sections(doc, pdftotext(path, layout=True))
    sections = merge_duplicate_sections(sections)
    logger.info("nga_pubs: %d sections", len(sections))
    return sections
