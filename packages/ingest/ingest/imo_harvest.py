"""IMO resolution harvester (2026-10-13).

Blake, 2026-10-13: pull IMO amendments into the corpus on their own, including
the parent instruments we do not have yet. Spec:
docs/specs/imo-harvester-2026-10-13.md.

    scripts/run_ingest.sh --module ingest.imo_harvest            # weekly run
    scripts/run_ingest.sh --module ingest.imo_harvest --backlog  # first run
    uv run python -m ingest.imo_harvest --plan                   # no downloads

What it does:

  discover  IMO's Index of IMO Resolutions (imo.org Knowledge Centre) lists
            every MSC, MEPC and Assembly resolution in a table per biennium:
            number, title, a PDF on wwwcdn.imo.org and an "AWAITING
            CERTIFICATION" flag. The weekly run reads the two newest pages
            per body; --backlog reads every page.
  select    a resolution is harvested when it is not administrative (budget,
            arrears, rules of procedure, ...), not already in the corpus
            (its number in any section_number), not merged into one of our
            consolidated editions, and either
              window  adopted at MSC 104 / MEPC 77 / A 32 (late 2021) or later
              chain   an amendment to an IMO code we hold no consolidated
                      edition of (LSA, FSS, IGC, IBC, IGF, HSC, IMSBC, ESP,
                      ...), MSC 80 / MEPC 52 / A 24 (2005) or later
  route     by title to the source of its instrument (LSA Code -> imo_lsa,
            MARPOL -> marpol_amend, STCW -> stcw_amend, ...); anything else to
            imo_msc (MSC and Assembly) or imo_mepc (MEPC). No new source.
  parent    an amendment names the resolution that adopted its instrument
            ("resolution MSC.268(85), by which it adopted the IMSBC Code", or
            "(RESOLUTION MSC.81(70))" in the title). A parent missing from the
            corpus is fetched too, one level deep.
  status    the adoption and entry-into-force dates are read from the text and
            go into every section's title ("adopted 22 May 2026; entry into
            force 1 January 2028"), so the answer model sees them next to the
            text; published_date carries the entry-into-force date.
  ingest    each harvested document is recorded in <raw_dir>/harvest.json of
            its source (the imo_codes adapter reads it, so a curated re-ingest
            of that source keeps them), then only the new documents go through
            the PDF pipeline, fresh mode, with a prune scoped to them.
  recheck   a document ingested while IMO marked it AWAITING CERTIFICATION is
            downloaded again once the flag clears, and re-ingested if the PDF
            changed.

Writes data/raw/imo_harvest/report-<stamp>.json and report-latest.json
(app.tasks.harvest_imo_resolutions emails it). No Anthropic calls.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DATA_RAW = _REPO / "data" / "raw"
HARVEST_DIR = _DATA_RAW / "imo_harvest"
OCR_DIR = _REPO / "data" / "ocr" / "imo_harvest"

INDEX_BASE = "https://www.imo.org/en/knowledgecentre/indexofimoresolutions/pages/"
CDN_BASE = "https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions"
BODIES: dict[str, tuple[str, str]] = {
    # body: (index top page, CDN folder)
    "MSC": ("msc.aspx", "MSCResolutions"),
    "MEPC": ("mepc.aspx", "MEPCDocuments"),
    "A": ("assembly.aspx", "AssemblyDocuments"),
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 RegKnots/1.0 (+https://regknots.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # no "br": httpx needs the brotli package to read it (the eCFR lesson)
    "Accept-Encoding": "gzip, deflate",
}
REQUEST_DELAY = 1.5
TIMEOUT = 120.0
MAX_PDF_BYTES = 60 * 1024 * 1024
BATCH = 20               # documents per pipeline run

# Window: everything adopted from late 2021 (MSC 104, MEPC 77, A 32).
WINDOW_FLOOR = {"MSC": 104, "MEPC": 77, "A": 32}
# Chains: amendments to codes we hold no consolidated edition of, from 2005.
CHAIN_FLOOR = {"MSC": 80, "MEPC": 52, "A": 24}
# Parents older than this (the 1983 IBC / IGC originals, long since rewritten,
# and mostly scans) are not fetched.
PARENT_FLOOR = {"MSC": 60, "MEPC": 40, "A": 18}

CODE_RE = re.compile(r"\b(MSC|MEPC|A)\.(\d{1,4})\((\d{1,3})\)")


# ── Index ─────────────────────────────────────────────────────────────────────

@dataclass
class IndexEntry:
    code: str           # "MSC.583(111)"
    body: str           # "MSC" | "MEPC" | "A"
    number: int
    session: int
    title: str          # as IMO lists it (upper case)
    pdf_url: str        # "" when IMO lists no PDF
    awaiting: bool      # "AWAITING CERTIFICATION"
    # older pages add notes after a "|": "Amends MSC.98(73)", "Revoked by A.1054(27)"
    notes: str = ""


def parse_code(code: str) -> tuple[str, int, int] | None:
    m = CODE_RE.fullmatch(code.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3))


def cdn_url(code: str) -> str:
    body = parse_code(code)[0]
    return f"{CDN_BASE}/{BODIES[body][1]}/{code}.pdf"


def biennium_pages(top_html: str, body: str) -> list[str]:
    """Per-period page names linked from a body's top page, oldest first
    ("msc-2024-25.aspx", "mepc-2026-27.aspx", "a-2025-27.aspx")."""
    top = BODIES[body][0].lower()
    names = re.findall(r'href="/en/knowledgecentre/indexofimoresolutions/pages/([a-z0-9-]+\.aspx)"',
                       top_html, re.I)
    out: list[str] = []
    for n in names:
        n = n.lower()
        if n in (top, "default.aspx") or n in out:
            continue
        if not re.match(rf"{'a' if body == 'A' else body.lower()}-\d{{4}}", n):
            continue
        out.append(n)
    return sorted(out, key=lambda n: int(re.search(r"\d{4}", n).group()))


def parse_index_page(html: str) -> list[IndexEntry]:
    """Rows of the resolution tables on one index page. HTML comments (IMO
    leaves old markup commented out) are ignored."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out: list[IndexEntry] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        code_text = " ".join(tds[0].get_text(" ", strip=True).split())
        m = CODE_RE.search(code_text)
        if not m:
            continue
        body, number, session = m.group(1), int(m.group(2)), int(m.group(3))
        title = " ".join(tds[1].get_text(" ", strip=True).split())
        awaiting = "AWAITING CERTIFICATION" in title.upper()
        title = re.sub(r"\s*\|?\s*AWAITING CERTIFICATION\s*\|?\s*", " ", title, flags=re.I).strip(" |")
        title, _, notes = (s.strip() for s in title.partition(" | "))
        link = tds[0].find("a", href=True) or tds[1].find("a", href=True)
        pdf = link["href"].strip() if link and ".pdf" in link["href"].lower() else ""
        out.append(IndexEntry(code=m.group(0), body=body, number=number, session=session,
                              title=title, pdf_url=pdf, awaiting=awaiting, notes=notes))
    return out


def crawl_index(client: httpx.Client, *, full: bool, console=None) -> dict[str, IndexEntry]:
    """Every resolution on the index pages read: all of them with full=True,
    else the two newest pages per body."""
    entries: dict[str, IndexEntry] = {}
    for body, (top, _folder) in BODIES.items():
        top_html = _get(client, INDEX_BASE + top).text
        pages = biennium_pages(top_html, body)
        if not pages:
            raise RuntimeError(f"IMO index: no period pages linked from {top} (layout changed?)")
        if not full:
            pages = pages[-2:]
        for page in pages:
            rows = parse_index_page(_get(client, INDEX_BASE + page).text)
            if console:
                console.print(f"  index {page}: {len(rows)} resolutions")
            for r in rows:
                entries.setdefault(r.code, r)
        latest = pages[-1]
        if not any(e.body == body for e in entries.values()):
            raise RuntimeError(f"IMO index: {latest} parsed to 0 rows (layout changed?)")
    return entries


def _get(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(3):
        try:
            resp = client.get(url, headers=HEADERS)
            if resp.status_code >= 500 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


# ── Selection and routing ─────────────────────────────────────────────────────

# Organisational resolutions: nothing a ship or an operator has to do.
_ADMIN_RE = re.compile(
    r"BUDGET|ARREARS|FINANCIAL (REGULATIONS|STATEMENTS)|AUDITOR|APPRECIATION|RELATIONS WITH"
    r"|RULES OF PROCEDURE|STRATEGIC PLAN|APPOINTMENT|SECRETARY-GENERAL|MULTILINGUALISM"
    r"|WORKING LANGUAGE|INTERNATIONAL DAY|WORLD MARITIME DAY|DAY OF THE SEAFARER|LIVE-STREAMING"
    r"|APPORTIONMENT OF EXPENSES|CONTRIBUTIONS|CAPACITY-(BUILDING|DEVELOPMENT)"
    r"|TECHNICAL CO-?OPERATION|CONVENTION ON THE INTERNATIONAL MARITIME ORGANIZATION"
    r"|AMENDMENTS TO THE IMO CONVENTION|WORLD MARITIME UNIVERSITY|MARITIME LAW INSTITUTE"
    r"|HEADQUARTERS|WORK PROGRAMME|PROGRAMME OF WORK|INCENTIVE SCHEME|ELECTION OF"
    r"|WOMEN IN MARITIME|AWARD|MEMBER STATE AUDIT SCHEME|INTEGRATED TECHNICAL"
    r"|INSTITUTIONALIZATION|PARTNERSHIP|RESOURCE MOBILIZATION",
    re.I,
)

# (title pattern, imo_codes key). First match wins; MARPOL only for amendments.
_ROUTES: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.I), key) for p, key in (
        (r"FISHING VESSEL PERSONNEL|STCW-F|TRAINING, CERTIFICATION AND WATCHKEEPING|\bSTCW\b", "stcw_amend"),
        (r"LIFE-SAVING APPLIANCE|\bLSA CODE\b", "lsa"),
        (r"FIRE SAFETY SYSTEMS|\bFSS CODE\b", "fss"),
        (r"LIQUEFIED GASES IN BULK|\bIGC CODE\b", "igc"),
        (r"DANGEROUS CHEMICALS IN BULK|\bIBC CODE\b", "ibc"),
        (r"LOW-FLASHPOINT FUELS|\bIGF CODE\b", "igf"),
        (r"HIGH-SPEED CRAFT|\bHSC CODE\b", "hsc"),
        (r"POLAR WATERS|POLAR CODE", "polar"),
        (r"LOAD LINES", "loadlines"),
        (r"CARGO STOWAGE AND SECURING|\bCSS CODE\b", "css"),
        (r"BALLAST WATER|BIOFOULING", "bwm"),
    )
)
_MARPOL_RE = re.compile(r"PREVENTION OF POLLUTION FROM SHIPS|\bMARPOL\b|PROTOCOL OF 1997|NOX TECHNICAL CODE", re.I)

# Instruments we hold as a consolidated edition, and the last session whose
# amendments that edition already contains. An amendment adopted then or
# earlier is not harvested (its text is in the base). Newer ones are.
#   SOLAS Consolidated Edition 2024 (amendments up to MSC 105)
#   IMDG Code 2024 Edition = Amendment 42-24 (MSC.556(108))
#   MARPOL Consolidated Edition 2022 (in force 1 Nov 2022: up to MEPC 76)
#   STCW Consolidated Edition 2017 (up to MSC 97; the supplements and
#     stcw_amend hold MSC 103-107, found by number)
#   ISM Code 2018 edition (up to MSC 98)
_CONSOLIDATED: tuple[tuple[re.Pattern, str, int], ...] = tuple(
    (re.compile(p, re.I), body, last) for p, body, last in (
        (r"SAFETY OF LIFE AT SEA", "MSC", 105),
        (r"DANGEROUS GOODS \(IMDG\)|\bIMDG CODE\b", "MSC", 108),
        (r"PREVENTION OF POLLUTION FROM SHIPS|\bMARPOL\b|PROTOCOL OF 1997", "MEPC", 76),
        (r"^(?!.*FISHING VESSEL).*(TRAINING, CERTIFICATION AND WATCHKEEPING|\bSTCW\b)", "MSC", 97),
        (r"SAFE OPERATION OF SHIPS AND FOR POLLUTION PREVENTION|\bISM CODE\b", "MSC", 98),
    )
)
# "AMENDMENTS TO THE ... CODE" / Load Lines Protocol / BWM Convention: a chain.
_CHAIN_RE = re.compile(r"^(20\d\d\s+)?AMENDMENTS TO .*(\bCODE\b|LOAD LINES|BALLAST WATER)", re.I)
_REVOKED_RE = re.compile(r"\b(revoked|superseded|replaced)\s+by\b", re.I)

LABELS: dict[str, str] = {
    "css": "IMO CSS Code", "loadlines": "IMO Load Lines", "igc": "IMO IGC Code",
    "ibc": "IMO IBC Code", "hsc": "IMO HSC Code", "polar": "IMO Polar Code",
    "igf": "IMO IGF Code", "bwm": "IMO BWM Convention", "stcw_amend": "STCW Amendments",
    "marpol_amend": "MARPOL Amendments", "lsa": "IMO LSA Code", "fss": "IMO FSS Code",
    "mepc_res": "IMO MEPC Resolution", "msc_res": "IMO MSC Resolution",
}


def is_administrative(title: str) -> bool:
    return bool(_ADMIN_RE.search(title))


def route(body: str, title: str) -> str:
    """The imo_codes key (and so the source) a resolution belongs to."""
    for pat, key in _ROUTES:
        if pat.search(title):
            return key
    if re.match(r"(20\d\d\s+)?AMENDMENTS", title, re.I) and _MARPOL_RE.search(title):
        return "marpol_amend"
    return "mepc_res" if body == "MEPC" else "msc_res"


def parent_label(key: str, body: str) -> str:
    if key == "msc_res" and body == "A":
        return "IMO Assembly Resolution"
    return LABELS[key]


def consolidated(entry: IndexEntry) -> bool:
    """Already merged into one of our consolidated editions."""
    if not re.match(r"(20\d\d\s+)?AMENDMENTS", entry.title, re.I):
        return False
    for pat, body, last in _CONSOLIDATED:
        if pat.search(entry.title) and entry.body == body and entry.session <= last:
            return True
    return False


def is_consolidated_instrument(title: str) -> bool:
    """A text of SOLAS, MARPOL, IMDG, STCW or the ISM Code itself (any date):
    we hold those as consolidated editions, so an older resolution text of
    them is never fetched as a parent."""
    return any(pat.search(title or "") for pat, _b, _l in _CONSOLIDATED)


def selection_reason(entry: IndexEntry) -> str | None:
    """'window' / 'chain', or None when the resolution is out of scope."""
    if entry.session >= WINDOW_FLOOR[entry.body]:
        return "window"
    # (amendments our consolidated editions already contain are dropped later,
    # by consolidated(); newer ones to those instruments are a chain too)
    if entry.session >= CHAIN_FLOOR[entry.body] and _CHAIN_RE.search(entry.title):
        return "chain"
    return None


# ── Text: status and parent ───────────────────────────────────────────────────

_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_DATE = r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})"
_ADOPTED_RE = re.compile(r"adopted\s+on\s+" + _DATE, re.I)
# Operative wording only: a recital ("NOTING that the amendments ... entered
# into force on 1 November 2022") is history, not this resolution's date.
_EIF_RE = re.compile(
    r"(?:shall|will|would)\s+(?:enter|come)\s+into\s+(?:force|effect)\s+(?:on|from)\s+" + _DATE
    + r"|(?:shall|will|would)\s+take\s+effect\s+(?:on|from)\s+" + _DATE
    + r"|enter\s+into\s+force\s+on\s+" + _DATE + r"\s+upon\s+(?:their\s+)?acceptance",
    re.I,
)
# The operative paragraphs start at the first "ADOPTS" (always in capitals).
_OPERATIVE_RE = re.compile(r"\b(?:ADOPTS|DECIDES|DETERMINES|DESIGNATES|AGREES)\b")
_ACCEPTED_RE = re.compile(r"deemed\s+to\s+have\s+been\s+accepted\s+on\s+" + _DATE, re.I)
# "(RESOLUTION MSC.81(70))" in an amendment's title names its parent.
_TITLE_PARENT_RE = re.compile(r"\((?:RESOLUTION\s+)?((?:MSC|MEPC|A)\.\d{1,4}\(\d{1,3}\))\)", re.I)


def _to_date(groups: Iterable[str | None]) -> date | None:
    g = [x for x in groups if x]
    if len(g) < 3:
        return None
    try:
        return date(int(g[2]), _MONTHS.index(g[1].lower()) + 1, int(g[0]))
    except ValueError:
        return None


def parse_dates(text: str) -> tuple[date | None, date | None]:
    """(adopted, entry into force) from a resolution's opening pages. The
    entry-into-force date is the first one stated after the adoption line."""
    head = re.sub(r"\s+", " ", text[:20000])
    m = _ADOPTED_RE.search(head)
    adopted = _to_date(m.groups()) if m else None
    eif = None
    op = _OPERATIVE_RE.search(head)
    operative = head[op.start():] if op else head
    for m in _EIF_RE.finditer(operative):
        d = _to_date(m.groups())
        if d and (adopted is None or d >= adopted):
            eif = d
            break
    if eif is None:
        m = _ACCEPTED_RE.search(operative)
        if m:  # accepted then; in force six months later (SOLAS / MARPOL tacit acceptance)
            acc = _to_date(m.groups())
            if acc:
                month = acc.month + 6
                eif = date(acc.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)
    return adopted, eif


_REVOKES_RE = re.compile(r"\b(?:revokes?|supersedes?|replaces?)\b", re.I)
# An amendment to a convention or protocol amends the treaty itself; the
# resolutions its preamble recalls are other instruments, not its parent.
_TREATY_ONLY_RE = re.compile(r"^(?!.*\bCODE\b).*\b(CONVENTION|PROTOCOL)\b", re.I)


def find_revoked(text: str, own_code: str) -> list[str]:
    """Resolutions this one revokes or supersedes ("REVOKES resolution
    A.1185(33)"), from its operative paragraphs."""
    head = re.sub(r"\s+", " ", text[:15000])
    out: list[str] = []
    for m in _REVOKES_RE.finditer(head):
        # the clause runs to a semicolon or a sentence-ending period (not the
        # dot inside "A.1185(33)")
        clause = re.split(r";|\.(?=\s|$)", head[m.end():m.end() + 240])[0]
        for c in CODE_RE.finditer(clause):
            code = _norm_code(c.group(0))
            if code != own_code and code not in out:
                out.append(code)
    return out


def find_parent(title: str, text: str, own_code: str) -> str | None:
    """The resolution that adopted the instrument this one amends, if named:
    "(RESOLUTION MSC.81(70))" in the title, or, for an amendment to a code or
    guideline, "resolution MSC.268(85), by which it adopted ..." in the
    preamble. Never a resolution the text revokes."""
    m = _TITLE_PARENT_RE.search(title)
    if m and m.group(1).upper() != own_code.upper():
        return _norm_code(m.group(1))
    if not re.match(r"(20\d\d\s+)?AMENDMENTS\s+TO", title, re.I) or _TREATY_ONLY_RE.search(title):
        return None
    revoked = set(find_revoked(text, own_code))
    head = re.sub(r"\s+", " ", text[:12000])
    keys = _title_keys(title)
    best: tuple[int, int, str] | None = None
    for m in CODE_RE.finditer(head):
        code = _norm_code(m.group(0))
        if code == own_code or code in revoked:
            continue
        # The recital the number sits in: back to the clause before, on to the
        # next recital or operative verb. A preamble often recalls an older
        # edition first ("resolution MSC.61(67) ... the FTP Code", then
        # "resolution MSC.307(88) ... the 2010 FTP Code"); the title's words
        # ("2010", "FTP") pick the one amended.
        nxt = _CLAUSE_START_RE.search(head, m.end())
        end = min(nxt.start() if nxt else len(head), m.end() + 300)
        clause = head[max(0, m.start() - 150):end]
        heading = head[max(0, m.start() - 12):m.start()].lower().endswith("resolution ") and \
            head[m.end():m.end() + 1] == ")"          # the annex's "(Resolution A.1023(26))"
        if not (re.search(r"\badopt", clause, re.I) or heading):
            continue
        low = clause.lower()
        score = sum(1 for k in keys if k in low) + (1 if heading else 0)
        if best is None or score > best[0]:
            best = (score, m.start(), code)
    if best is None or best[0] < min(2, len(keys)):
        return None
    return best[2]


_CLAUSE_START_RE = re.compile(
    r"\b(?:RECALLING|NOTING|HAVING|BEARING|RECOGNIZING|CONSIDERING|DESIRING|ADOPTS|DECIDES|DETERMINES"
    r"|INVITES|REQUESTS|URGES)\b")
_KEY_STOP = {"amendments", "the", "and", "for", "international", "code", "resolution", "with", "part",
             "ships", "ship", "safety", "revised", "annex", "convention", "requirements", "standards"}


def _title_keys(title: str) -> set[str]:
    """The distinctive words of a title ("2010", "ftp", "fire", "procedures")."""
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", title.lower()) if w not in _KEY_STOP}


def _norm_code(code: str) -> str:
    p = parse_code(code.upper())
    return f"{p[0]}.{p[1]}({p[2]})" if p else code


def fill_session_dates(items: Iterable["Item"]) -> None:
    """A resolution printed as an annex of the meeting report carries no
    "(adopted on ...)" line; its session adopted it on the date most of its
    siblings give. Fills item.adopted / item.status in place."""
    from collections import Counter
    by_session: dict[tuple[str, int], Counter] = {}
    for i in items:
        if i.adopted:
            by_session.setdefault((i.body, i.session), Counter())[i.adopted] += 1
    for i in items:
        if not i.adopted and by_session.get((i.body, i.session)):
            i.adopted = by_session[(i.body, i.session)].most_common(1)[0][0]
            i.status = status_text(date.fromisoformat(i.adopted),
                                   date.fromisoformat(i.in_force) if i.in_force else None, i.awaiting)


def status_text(adopted: date | None, eif: date | None, awaiting: bool) -> str:
    parts = []
    if adopted:
        parts.append(f"adopted {_fmt(adopted)}")
    if eif and eif != adopted:
        parts.append(f"entry into force {_fmt(eif)}")
    if awaiting:
        parts.append("certified text pending")
    return "; ".join(parts)


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%B')} {d.year}"


_ACRONYMS = {
    "IMO", "MSC", "MEPC", "SOLAS", "MARPOL", "STCW", "STCW-F", "IMDG", "IMSBC", "LSA", "FSS", "IGC",
    "IBC", "IGF", "HSC", "ESP", "SPS", "MODU", "IP", "MASS", "VDES", "AIS", "ECDIS", "GMDSS", "VDR",
    "S-VDR", "NOX", "SOX", "EEDI", "EEXI", "CII", "SEEMP", "GHG", "BWM", "BWMS", "ISM", "ISPS", "LRIT",
    "SAR", "MSI", "EGCS", "SCR", "ODME", "OCM", "PSPC", "HSSC", "III", "CSS", "RO", "FTP", "DSC",
    "INF", "BLU", "BCH", "GC", "EGC", "NAVTEX", "NBDP", "HF", "MF", "VHF", "UHF", "EPIRB", "SART",
    "ICS", "CTTIC", "BDMSS", "PSSA", "ECA", "IHM", "TWTD", "ELM", "CEMS", "CH4", "N2O", "LNG", "LPG",
    "IAMSAR", "COLREG", "COLREGS", "HNS", "OPRC", "AFS", "CLC", "ADRIREP", "RIT", "CO2", "UN", "UK",
    "US", "IACS", "ILO", "WHO", "PSC", "IV", "V", "VI", "VII", "II", "II-1", "II-2", "III-1", "XI-1",
    "XI-2", "XII", "XIII", "XIV", "XV", "I", "X", "IX", "VIII",
}
_SMALL = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the",
          "to", "under", "with", "within"}


def nice_title(title: str) -> str:
    """IMO lists newer titles in capitals; give them title case, keeping
    acronyms ("IMSBC", "MF/HF", "G4") and "Part A"."""
    if sum(c.isupper() for c in title) < 0.6 * sum(c.isalpha() for c in title):
        return title
    words = title.split(" ")
    out = []
    for i, w in enumerate(words):
        core = w.strip("()\"',;:.")
        prev = words[i - 1].upper() if i else ""
        if (CODE_RE.search(w) or core.upper() in _ACRONYMS
                or all(part.upper() in _ACRONYMS for part in core.split("/") if part)
                or re.fullmatch(r"[\d.()/-]+|[A-Z]\d+", core.upper()) and any(ch.isdigit() for ch in core)
                or (len(core) == 1 and prev in ("PART", "ANNEX", "APPENDIX", "CHAPTER", "SCHEDULE"))):
            out.append(w.upper() if not CODE_RE.search(w) else w)
        elif i > 0 and core.lower() in _SMALL:
            out.append(w.lower())
        else:
            out.append("-".join(_cap(p) for p in w.lower().split("-")))
    return " ".join(out)


def _cap(word: str) -> str:
    """Capitalise the first letter, after any opening bracket or quote."""
    for k, ch in enumerate(word):
        if ch.isalpha():
            return word[:k] + ch.upper() + word[k + 1:]
    return word


# ── PDF text ──────────────────────────────────────────────────────────────────

def pdf_text(path: Path) -> str:
    """The PDF's text: pdfplumber, or tesseract OCR for a scan. Cached in
    data/ocr/imo_harvest/<stem>.txt (newer than the PDF), where the imo_codes
    adapter reads it too, so a document is extracted once. '' when there is no
    text layer and no OCR on this machine."""
    cache = OCR_DIR / f"{path.stem}.txt"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    text = _extract_isolated(path)
    if len(text.strip()) < 400 and not is_placeholder(text):
        if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
            return text
        from ingest.ocr import ocr_pdf
        text = ocr_pdf(path).replace(chr(12), chr(10) * 2)
    OCR_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


_EXTRACTOR = None


def _extract_worker(path: str) -> str:
    from ingest.sources.imo_codes import _extract_pdf_text
    return _extract_pdf_text(Path(path))


def _extract_isolated(path: Path) -> str:
    """pdfplumber in a fresh child process per document. 2026-10-13: in one
    process the backlog run held 1.0 GB plus 0.9 GB of swap after 170 PDFs
    (pdfminer does not hand memory back) and filled the box's swap."""
    global _EXTRACTOR
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    if _EXTRACTOR is None:
        _EXTRACTOR = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"),
                                         max_tasks_per_child=1)
    return _EXTRACTOR.submit(_extract_worker, str(path)).result(timeout=1800)


def is_placeholder(text: str) -> bool:
    """IMO posts a one-page "RESOLUTION AWAITING CERTIFICATION" PDF until the
    certified text is ready: nothing to ingest yet."""
    return len(text.strip()) < 400 and "AWAITING CERTIFICATION" in text.upper()


# ── Plan ──────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    code: str
    body: str
    session: int
    title: str
    pdf_url: str
    awaiting: bool
    reason: str               # window | chain | parent | recertified
    key: str                  # imo_codes key
    source: str = ""
    label: str = ""
    adopted: str = ""
    in_force: str = ""
    status: str = ""
    parent: str = ""
    revokes: list[str] = field(default_factory=list)
    sha256: str = ""
    path: str = ""
    error: str = ""


def plan(index: dict[str, IndexEntry], in_corpus: set[str], manifest: dict[str, dict]
         ) -> tuple[list[Item], dict[str, list[str]]]:
    """What to harvest now, and why the rest was skipped (reason -> codes)."""
    from ingest.sources.imo_codes import _CODE_TO_SOURCE
    items: list[Item] = []
    skipped: dict[str, list[str]] = {}

    def skip(why: str, code: str) -> None:
        skipped.setdefault(why, []).append(code)

    # revoked by a resolution already harvested (MSC.581(110) revokes A.1050(27))
    revoked = {c for row in manifest.values() for c in row.get("revokes") or []}
    for e in sorted(index.values(), key=lambda e: (e.body, e.session, e.number)):
        prev = manifest.get(e.code)
        if prev:
            # Harvested before: re-fetch once IMO certifies it.
            if prev.get("awaiting") and not e.awaiting and e.pdf_url:
                key = prev["key"]
                items.append(Item(code=e.code, body=e.body, session=e.session, title=e.title,
                                  pdf_url=e.pdf_url, awaiting=False, reason="recertified", key=key,
                                  source=_CODE_TO_SOURCE[key], label=prev.get("label", "")))
            continue
        reason = selection_reason(e)
        if reason is None:
            continue
        if e.code in in_corpus:
            skip("in corpus", e.code)
        elif e.code in revoked:
            skip("revoked by a harvested resolution", e.code)
        elif _REVOKED_RE.search(e.notes):
            skip("revoked or superseded", e.code)
        elif is_administrative(e.title):
            skip("administrative", e.code)
        elif consolidated(e):
            skip("in a consolidated edition", e.code)
        elif not e.pdf_url:
            skip("no PDF listed", e.code)
        else:
            key = route(e.body, e.title)
            hint = re.search(r"\bamends\s+((?:MSC|MEPC|A)\.\d{1,4}\(\d{1,3}\))", e.notes, re.I)
            items.append(Item(code=e.code, body=e.body, session=e.session, title=e.title,
                              pdf_url=e.pdf_url, awaiting=e.awaiting, reason=reason, key=key,
                              source=_CODE_TO_SOURCE[key], label=parent_label(key, e.body),
                              parent=_norm_code(hint.group(1)) if hint else ""))
    return items, skipped


# ── Manifest (per source raw dir) ─────────────────────────────────────────────

def raw_dir_for(source: str) -> Path:
    from ingest.cli import _PDF_SOURCE_CONFIG
    return Path(_PDF_SOURCE_CONFIG[source]["raw_dir"])


def load_manifest(sources: Iterable[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in sorted(set(sources)):
        p = raw_dir_for(s) / "harvest.json"
        if p.exists():
            for row in json.loads(p.read_text(encoding="utf-8")):
                out[row["code"]] = row
    return out


def save_manifest_rows(source: str, rows: list[dict]) -> None:
    p = raw_dir_for(source) / "harvest.json"
    existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    by_code = {r["code"]: r for r in existing}
    for r in rows:
        by_code[r["code"]] = r
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(by_code.values(), key=lambda r: r["code"]), indent=2), encoding="utf-8")
    tmp.replace(p)


def manifest_row(item: Item, harvested: date) -> dict:
    """The row the imo_codes adapter reads (CodeDocMeta fields + status)."""
    eff = item.in_force or item.adopted or harvested.isoformat()
    return {
        "code": item.code, "title": nice_title(item.title), "pdf_url": item.pdf_url,
        "effective_date": eff, "parent_label": item.label, "status": item.status,
        "harvested": harvested.isoformat(), "key": item.key, "source": item.source, "reason": item.reason,
        "adopted": item.adopted, "in_force": item.in_force, "awaiting": item.awaiting,
        "parent": item.parent, "revokes": item.revokes, "sha256": item.sha256,
    }


# ── Corpus ────────────────────────────────────────────────────────────────────

async def corpus_codes(pool) -> set[str]:
    """Resolution numbers present as a document of their own in the corpus."""
    rows = await pool.fetch(
        r"""SELECT DISTINCT (regexp_matches(section_number, '((?:MSC|MEPC|A)\.[0-9]+\([0-9]+\))', 'g'))[1] AS code
            FROM regulations WHERE section_number ~ '(MSC|MEPC|A)\.[0-9]+\('"""
    )
    return {r["code"] for r in rows}


# ── Run ───────────────────────────────────────────────────────────────────────

@dataclass
class Report:
    started: str
    mode: str
    index_rows: int = 0
    planned: int = 0
    harvested: list[dict] = field(default_factory=list)
    parents: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    ingest: dict[str, dict] = field(default_factory=dict)
    # revoked by a newer resolution: dropped from this run / removed from the
    # library (harvested ones), or listed for review (curated rows)
    superseded: list[dict] = field(default_factory=list)
    error: str = ""


def _download(client: httpx.Client, item: Item, raw_dir: Path) -> Path:
    from ingest.sources.imo_codes import CodeDocMeta
    meta = CodeDocMeta(code=item.code, title=item.title, pdf_url=item.pdf_url,
                       effective_date=date.today(), parent_label=item.label)
    out = raw_dir / f"{meta.filename_stub}.pdf"
    if item.reason != "recertified" and out.exists() and out.stat().st_size > 1024:
        # already downloaded (an interrupted run): keep it, and its cached text
        item.sha256 = hashlib.sha256(out.read_bytes()).hexdigest()
        item.path = str(out)
        return out
    resp = _get(client, item.pdf_url)
    body = resp.content
    if not body.startswith(b"%PDF"):
        raise ValueError(f"not a PDF ({body[:24]!r})")
    if len(body) > MAX_PDF_BYTES:
        raise ValueError(f"PDF is {len(body) // (1024 * 1024)} MB (cap {MAX_PDF_BYTES // (1024 * 1024)})")
    raw_dir.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    item.sha256 = hashlib.sha256(body).hexdigest()
    item.path = str(out)
    return out


class AwaitingText(Exception):
    """The PDF is IMO's "awaiting certification" placeholder."""


def _read(item: Item, path: Path) -> str:
    text = pdf_text(path)
    if is_placeholder(text):
        raise AwaitingText("IMO has not published the text yet (awaiting certification)")
    if len(text.strip()) < 400:
        raise ValueError(f"no usable text ({len(text.strip())} chars; scan without OCR here)")
    adopted, eif = parse_dates(text)
    item.adopted = adopted.isoformat() if adopted else ""
    item.in_force = eif.isoformat() if eif else ""
    item.status = status_text(adopted, eif, item.awaiting)
    item.parent = item.parent or find_parent(item.title, text, item.code) or ""
    item.revokes = find_revoked(text, item.code)
    return text


def _title_from_text(text: str, code: str) -> str:
    """A parent's title when the crawled index pages don't list it: the
    capitalised lines after "(adopted on ...)"."""
    head = text[:3000]
    m = re.search(r"adopted\s+on[^)\n]*\)?\s*\n", head, re.I)
    lines = head[m.end():].splitlines() if m else head.splitlines()
    caps = []
    for ln in lines:
        s = ln.strip()
        if not s:
            if caps:
                break
            continue
        if s.isupper() and not CODE_RE.fullmatch(s):
            caps.append(s)
        elif caps:
            break
    return " ".join(caps)[:300] or code


async def run(*, backlog: bool, plan_only: bool, limit: int | None, notify: bool,
              no_parents: bool, console) -> Report:
    import asyncpg

    from ingest.config import settings
    from ingest.pdf_pipeline import run_pdf_pipeline
    from ingest.sources import imo_codes
    from ingest.sources.imo_codes import _CODE_TO_SOURCE

    report = Report(started=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    mode="backlog" if backlog else "weekly")
    HARVEST_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        in_corpus = await corpus_codes(pool)
        manifest = load_manifest(_CODE_TO_SOURCE.values())
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            index = crawl_index(client, full=backlog, console=console)
            report.index_rows = len(index)
            # parents may sit on older pages than the weekly run reads
            cached = HARVEST_DIR / "index-full.json"
            if backlog:
                cached.write_text(json.dumps({c: asdict(e) for c, e in index.items()}, indent=1),
                                  encoding="utf-8")
            elif cached.exists():
                # the weekly pages win over the cache (setdefault)
                for c, row in json.loads(cached.read_text(encoding="utf-8")).items():
                    index.setdefault(c, IndexEntry(**row))

            items, report.skipped = plan(index, in_corpus, manifest)
            if not backlog:
                # weekly: new pages only; the backlog run owns the history
                items = [i for i in items if i.reason == "recertified"
                         or i.session >= WINDOW_FLOOR[i.body]]
            if limit:
                items = items[:limit]
            report.planned = len(items)
            console.print(f"  planned {len(items)} resolutions "
                          f"({sum(1 for i in items if i.reason == 'window')} window, "
                          f"{sum(1 for i in items if i.reason == 'chain')} chain, "
                          f"{sum(1 for i in items if i.reason == 'recertified')} re-certified)")
            if plan_only:
                for i in items:
                    console.print(f"    {i.code:<15} {i.reason:<7} -> {i.source:<13} {nice_title(i.title)[:90]}")
                report.harvested = [asdict(i) for i in items]
                return report

            done: dict[str, Item] = {}
            # never fetched as a parent: held, harvested, or skipped on purpose
            taken = (set(in_corpus) | set(manifest) | {c for codes in report.skipped.values() for c in codes}
                     | {c for row in manifest.values() for c in row.get("revokes") or []})

            def fetch(item: Item) -> None:
                raw_dir = raw_dir_for(item.source)
                try:
                    path = _download(client, item, raw_dir)
                    _read(item, path)
                    done[item.code] = item
                    taken.add(item.code)
                except AwaitingText:
                    # tried again every week until IMO posts the certified text
                    report.skipped.setdefault("awaiting certification (no text yet)", []).append(item.code)
                    Path(item.path).unlink(missing_ok=True)
                except Exception as exc:  # one bad document never stops the run
                    item.error = f"{type(exc).__name__}: {exc}"[:300]
                    report.failed.append(asdict(item))
                    logger.warning("IMO harvest %s: %s", item.code, item.error)

            for n, item in enumerate(items, 1):
                console.print(f"  [{n}/{len(items)}] {item.code} -> {item.source}")
                fetch(item)

            fill_session_dates(done.values())

            # A newer edition revokes the older one (PSC procedures 2021 / 2023 /
            # 2025, HSSC survey guidelines, ...): keep the current edition only.
            revoked_by: dict[str, str] = {}
            for i in done.values():
                for code in i.revokes:
                    revoked_by.setdefault(code, i.code)
            for code, by in sorted(revoked_by.items()):
                if code in done:
                    gone = done.pop(code)
                    Path(gone.path).unlink(missing_ok=True)
                    report.superseded.append({"code": code, "by": by, "action": "not harvested"})
                elif code in manifest:
                    report.superseded.append({"code": code, "by": by, "action": "removed",
                                              "source": manifest[code]["source"] if "source" in manifest[code]
                                              else _CODE_TO_SOURCE[manifest[code]["key"]]})
                elif code in in_corpus:
                    report.superseded.append({"code": code, "by": by, "action": "review (curated)"})
            taken |= set(revoked_by)

            # Parents, one level: the instrument an amendment amends.
            if not no_parents:
                wanted = sorted({i.parent for i in done.values() if i.parent and i.parent not in taken})
                for code in wanted:
                    e = index.get(code)
                    p = parse_code(code)
                    if p is None:
                        continue
                    body, number, session = p
                    if session < PARENT_FLOOR[body]:
                        report.skipped.setdefault("parent too old", []).append(code)
                        continue
                    title = e.title if e else ""
                    if is_consolidated_instrument(title):
                        # e.g. MEPC.176(58), the 2008 Revised MARPOL Annex VI: an old
                        # text of an instrument we hold consolidated
                        report.skipped.setdefault("parent in a consolidated edition", []).append(code)
                        continue
                    key = route(body, title) if title else ("mepc_res" if body == "MEPC" else "msc_res")
                    item = Item(code=code, body=body, session=session, title=title or code,
                                pdf_url=(e.pdf_url if e and e.pdf_url else cdn_url(code)),
                                awaiting=bool(e and e.awaiting), reason="parent", key=key,
                                source=_CODE_TO_SOURCE[key], label=parent_label(key, body))
                    console.print(f"  parent {code} -> {item.source}")
                    fetch(item)
                    if code in done and not e:
                        # not on the pages read: title from the PDF, then route again
                        txt = pdf_text(Path(item.path))
                        item.title = _title_from_text(txt, code)
                        if is_consolidated_instrument(item.title):
                            Path(done.pop(code).path).unlink(missing_ok=True)
                            report.skipped.setdefault("parent in a consolidated edition", []).append(code)
                            continue
                        new_key = route(body, item.title)
                        if new_key != item.key:
                            Path(item.path).replace(raw_dir_for(_CODE_TO_SOURCE[new_key]) / Path(item.path).name)
                            item.key, item.source = new_key, _CODE_TO_SOURCE[new_key]
                            item.label = parent_label(new_key, body)
                            item.path = str(raw_dir_for(item.source) / Path(item.path).name)
                    if code in done:
                        report.parents.append({"code": code, "for": sorted(
                            i.code for i in done.values() if i.parent == code and i.reason != "parent")})

        for s in report.superseded:
            if s["action"] == "removed":
                n = await remove_harvested(pool, s["source"], s["code"])
                s["rows"] = n

        # Ingest only these documents, per source, BATCH at a time (memory: the
        # pipeline holds a batch's chunks and embeddings). A document is recorded
        # in harvest.json once its sections are written; one that parsed to
        # nothing is reported and tried again next run.
        by_source: dict[str, list[Item]] = {}
        for item in done.values():
            by_source.setdefault(item.source, []).append(item)
        for source, its in sorted(by_source.items()):
            raw_dir = raw_dir_for(source)
            stats = {"documents": 0, "sections": 0, "chunks": 0, "written": 0,
                     "new_or_modified": 0, "pruned": 0, "errors": []}
            for k in range(0, len(its), BATCH):
                batch = its[k:k + BATCH]
                metas = [imo_codes.meta_from_row(manifest_row(i, today)) for i in batch]
                codes = {i.code for i in batch}
                produced: set[str] = set()

                def loader(raw_dir=raw_dir, metas=metas, source=source, codes=codes, produced=produced):
                    secs = imo_codes.parse_docs(raw_dir, metas, source)
                    produced.update(c for c in (_doc_of(s.section_number, codes) for s in secs) if c)
                    return secs

                result = await run_pdf_pipeline(
                    source=source, mode="fresh", section_loader=loader,
                    source_date=today, pool=pool, console=console,
                    prune="after", prune_scope=lambda sn, codes=codes: _doc_of(sn, codes),
                )
                ok = [i for i in batch if i.code in produced]
                for i in batch:
                    if i.code not in produced:
                        i.error = "no sections parsed"
                        report.failed.append(asdict(i))
                if ok:
                    save_manifest_rows(source, [manifest_row(i, today) for i in ok])
                    report.harvested.extend(asdict(i) for i in ok)
                stats["documents"] += len(ok)
                stats["sections"] += result.sections_found
                stats["chunks"] += result.chunks_created
                stats["written"] += result.upserts
                stats["new_or_modified"] += result.new_or_modified_chunks
                stats["pruned"] += result.pruned
                stats["errors"] += result.error_details[:3]
                if notify and result.new_or_modified_chunks > 0:
                    from ingest.notify import create_regulation_update_notification
                    await create_regulation_update_notification(pool, result)
            report.ingest[source] = stats
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("IMO harvest failed")
    finally:
        await pool.close()
        _write_report(report)
    return report


async def remove_harvested(pool, source: str, code: str) -> int:
    """Delete a harvested resolution's rows and its manifest entry (a newer
    resolution revoked it). Only ever called for documents this harvester
    added; curated rows are reported, never removed."""
    rows = await pool.fetch(
        "SELECT id, section_number FROM regulations WHERE source = $1 AND section_number LIKE '%' || $2 || '%'",
        source, code,
    )
    ids = [r["id"] for r in rows if _doc_of(r["section_number"], {code})]
    if ids:
        await pool.execute("DELETE FROM regulations WHERE id = ANY($1::uuid[])", ids)
    p = raw_dir_for(source) / "harvest.json"
    if p.exists():
        kept = [r for r in json.loads(p.read_text(encoding="utf-8")) if r["code"] != code]
        p.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return len(ids)


def _doc_of(section_number: str, codes: set[str]) -> str | None:
    """prune scope: the harvested document a stored row belongs to; rows of
    other documents in the same source are never pruned."""
    m = CODE_RE.search(section_number or "")
    return m.group(0) if m and m.group(0) in codes else None


def _write_report(report: Report) -> None:
    HARVEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    body = json.dumps(asdict(report), indent=1, default=str)
    (HARVEST_DIR / f"report-{stamp}.json").write_text(body, encoding="utf-8")
    (HARVEST_DIR / "report-latest.json").write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from rich.console import Console
    ap = argparse.ArgumentParser(description="Harvest IMO MSC / MEPC / Assembly resolutions into the corpus.")
    ap.add_argument("--backlog", action="store_true",
                    help="read every index page and harvest the whole window and the code chains")
    ap.add_argument("--plan", action="store_true", help="list what would be harvested; no downloads, no writes")
    ap.add_argument("--limit", type=int, default=None, help="harvest at most N resolutions (testing)")
    ap.add_argument("--no-parents", action="store_true", help="do not fetch the instruments amendments amend")
    ap.add_argument("--no-notify", action="store_true", help="no regulation-update notifications")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    console = Console()
    report = asyncio.run(run(backlog=args.backlog, plan_only=args.plan, limit=args.limit,
                             notify=not (args.no_notify or args.backlog), no_parents=args.no_parents,
                             console=console))
    console.print(f"  harvested {len(report.harvested)}, parents {len(report.parents)}, "
                  f"failed {len(report.failed)}{'; ERROR ' + report.error if report.error else ''}")
    return 1 if report.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
