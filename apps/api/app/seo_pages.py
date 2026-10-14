"""Plain-English regulation pages for search (growth plan step 3, 2026-10-14).

Each page at /regs/<slug> explains one U.S. regulation section beside that
section's own text: 46 / 33 CFR, the Coast Guard's Navigation Rules handbook
(COLREGs with the Inland Rules), or an NVIC's main body. All are U.S.
government works; no IMO text is used (imo.org's terms bar commercial reuse).

Sonnet 5.5 writes each explanation (Batch API, structured output). A page is
published only when every check passes; otherwise it is held with its
failures and never served:

  quotes     every requirement and FAQ answer carries a quote found in the
             section text (whitespace, case and typographic marks normalised)
  numbers    every number in the plain-English text appears in the section text
  citations  every section the page names exists in the corpus
  support    Haiku confirms each statement says what its quote and the
             section text say, adding nothing

CLI, on the VPS from apps/api (reads the prod .env):

  uv run python -m app.seo_pages select          # (re)build the draft list
  uv run python -m app.seo_pages pilot 20        # write + check 20 drafts now
  uv run python -m app.seo_pages batch           # all drafts through one Message Batch
  uv run python -m app.seo_pages recheck         # re-run checks on held pages
  uv run python -m app.seo_pages check-stale     # hold pages whose text changed
  uv run python -m app.seo_pages status
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GEN_MODEL = "claude-sonnet-5-5"
GEN_MAX_TOKENS = 8000
PROMPT_TEXT_CHARS = 40_000       # section text sent to the writer (the checks read all of it)
NVIC_BODY_CHARS = 60_000         # an NVIC page shows its main body up to this length
MIN_BODY_CHARS = 250             # shorter sections (reserved, headings) get no page
TARGET_PAGES = 1500              # frequently-cited sections fill the selection up to this


# ── Collections ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Collection:
    slug: str
    title: str
    blurb: str
    source: str
    pattern: str | None = None   # Postgres regex on section_number


COLLECTIONS: tuple[Collection, ...] = (
    Collection(
        "subchapter-m", "Subchapter M: Towing Vessels",
        "46 CFR Parts 136 to 144: certificates of inspection, the Towing Safety Management System, "
        "third-party organizations, operations, lifesaving, fire protection, machinery and electrical "
        "systems for U.S. towing vessels.",
        "cfr_46", r"^46 CFR 1(3[6-9]|4[0-4])\.",
    ),
    Collection(
        "mariner-credentials", "Merchant Mariner Credentials",
        "46 CFR Parts 10 to 16: merchant mariner credentials, officer and rating endorsements, STCW, "
        "medical certificates, manning, and chemical testing.",
        "cfr_46", r"^46 CFR 1[0-6]\.",
    ),
    Collection(
        "pollution-prevention", "Oil, Garbage and Ballast Water Pollution Prevention",
        "33 CFR Parts 151 and 155: discharges of oil, garbage and ballast water, record books, "
        "pollution emergency plans, vessel response plans and oil transfer procedures.",
        "cfr_33", r"^33 CFR 15[15]\.",
    ),
    Collection(
        "navigation-safety", "Navigation Safety Regulations",
        "33 CFR Part 164: required navigation equipment such as radar, AIS, ECDIS, charts and "
        "publications, tests before getting underway, and navigation rules for towing vessels.",
        "cfr_33", r"^33 CFR 164\.",
    ),
    Collection(
        "navigation-rules", "Navigation Rules: COLREGs and Inland Rules",
        "The International Regulations for Preventing Collisions at Sea and the U.S. Inland "
        "Navigation Rules, rule by rule, from the Coast Guard's Navigation Rules handbook.",
        "colregs",
    ),
    Collection(
        "nvics", "Navigation and Vessel Inspection Circulars",
        "Coast Guard NVICs: guidance on how the Coast Guard applies the regulations, circular by "
        "circular.",
        "nvic",
    ),
    Collection(
        "frequently-cited", "Frequently Cited Regulations",
        "Other sections of 46, 33 and 49 CFR that mariners ask RegKnot about most.",
        "cfr",
    ),
)
COLLECTION_BY_SLUG = {c.slug: c for c in COLLECTIONS}
PUBLIC_SOURCES = ("cfr_46", "cfr_33", "cfr_49", "colregs", "nvic")


# ── Section text ─────────────────────────────────────────────────────────────

_SEARCH_TERMS_RE = re.compile(r"^\[Search terms:[^\]]*\]\s*", re.MULTILINE)
_RESERVED_RE = re.compile(r"\[(Reserved|Removed)\]|^\s*(Reserved|Removed)\.?\s*$", re.IGNORECASE)


def chunk_body(text: str, section_number: str) -> str:
    """A chunk without its "[section] title" header line and enrichment block."""
    lines = text.lstrip().split("\n", 1)
    if lines and lines[0].startswith(f"[{section_number}]"):
        text = lines[1] if len(lines) > 1 else ""
    return _SEARCH_TERMS_RE.sub("", text).strip()


def join_chunks(chunks: list[str], section_number: str) -> str:
    """The section text from its chunks in chunk_index order. Each continuation
    chunk repeats the previous chunk's last paragraphs (ingest.chunker's
    50-token overlap); the repeat is dropped."""
    units: list[str] = []
    for chunk in chunks:
        parts = [p for p in chunk_body(chunk, section_number).split("\n\n") if p.strip()]
        if units:
            for k in range(min(len(parts), len(units), 12), 0, -1):
                if units[-k:] == parts[:k]:
                    parts = parts[k:]
                    break
        units.extend(parts)
    return "\n\n".join(units)


def is_substantive(title: str | None, body: str) -> bool:
    return len(body) >= MIN_BODY_CHARS and not _RESERVED_RE.search(title or "")


def slugify(section_number: str) -> str:
    s = unicodedata.normalize("NFKD", section_number).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def display_number(section_number: str) -> str:
    return re.sub(r"^COLREGS\b", "COLREGs", section_number)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ecfr_url(section_number: str) -> str | None:
    m = re.match(r"^(\d+) CFR (\d+)\.(\S+)$", section_number)
    if not m:
        return None
    return f"https://www.ecfr.gov/current/title-{m.group(1)}/section-{m.group(2)}.{m.group(3)}"


# ── The writer ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You write the plain-English half of a public web page about one U.S. maritime regulation. The page shows your explanation beside the regulation's own text, for working mariners, vessel operators and compliance staff. Everything you write is checked automatically against the text, and a page that fails any check is not published.

Rules:
1. Use only the text you are given. Do not add requirements, exceptions, numbers, dates, vessel types or other sections from memory, even when you know them. When the text sends the reader to another section for a detail, say so and name that section as the text does.
2. Every requirement and every FAQ answer carries a quote: one passage copied exactly from the text, character for character, 6 to 50 words long. No ellipses, no brackets, no added, dropped or changed words, and never two passages joined together.
3. Write every number exactly as the text gives it, with its unit. Never compute, convert, round or total numbers, and never introduce a number the text doesn't contain.
4. Plain English: short sentences and active voice. Keep the text's strength: "must" where it requires, "may" where it permits, "should" where it recommends. Keep defined terms as the text uses them.
5. No legal advice, and nothing about what the reader should do beyond what the text says. Don't tell the reader to consult anyone.
6. If the text is reserved, removed or only a heading, return empty lists and say so in the summary.
7. Navigation Rules: the text gives the International rule and the Inland rule, marked [INTERNATIONAL] and [INLAND]. Say where they differ. Start a statement with "International:" or "Inland:" when it applies to only one of them.
8. NVICs are Coast Guard guidance, not regulations. Describe them as guidance ("the Coast Guard will", "should") exactly as the text puts it.

Fields:
- topic: what the section covers, 3 to 8 words, sentence case, no section number. Example: "Portable fire extinguishers on towing vessels".
- meta_description: one sentence of at most 150 characters for search results, saying what the section requires or covers.
- summary: 2 or 3 sentences: what the section is about and its main requirement.
- applies_to: one sentence on who or what the section applies to, only when the text says; otherwise "".
- requirements: the 3 to 8 most important requirements, permissions or definitions, in the order of the text. statement: plain English. quote: rule 2. paragraph: the designator of the paragraph the quote sits in as printed, such as "(a)(1)", or "".
- faqs: 2 to 4 questions a mariner would type into a search engine about this section, each answered in 1 or 2 sentences from the text, each with a quote.
- related_sections: the other sections the text itself names, in full form ("46 CFR 142.240", "33 CFR 164.72", "COLREGs Rule 13"); [] if none.
"""


def page_schema() -> dict:
    from rag.llm import STR, arr, obj
    return obj({
        "topic": STR,
        "meta_description": STR,
        "summary": STR,
        "applies_to": STR,
        "requirements": arr(obj({"statement": STR, "quote": STR, "paragraph": STR})),
        "faqs": arr(obj({"question": STR, "answer": STR, "quote": STR})),
        "related_sections": arr(STR),
    })


def user_prompt(page: dict) -> str:
    collection = COLLECTION_BY_SLUG[page["collection"]]
    text = page["source_text"]
    if len(text) > PROMPT_TEXT_CHARS:
        text = text[:PROMPT_TEXT_CHARS] + "\n\n[The text continues; explain only the part above.]"
    as_of = f" (current as of {page['up_to_date_as_of']})" if page.get("up_to_date_as_of") else ""
    return (
        f"Section: {page['display_number']}\n"
        f"Heading: {page.get('section_title') or ''}\n"
        f"Collection: {collection.title}\n\n"
        f"Text{as_of}:\n<<<\n{text}\n>>>"
    )


def request_params(page: dict) -> dict:
    from rag.llm import cached_system, json_output_config
    return {
        "model": GEN_MODEL,
        "max_tokens": GEN_MAX_TOKENS,
        "output_config": json_output_config(page_schema(), effort="low"),
        "system": cached_system(SYSTEM_PROMPT),
        "messages": [{"role": "user", "content": user_prompt(page)}],
    }


# ── Checks ───────────────────────────────────────────────────────────────────

_MARKS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "­": None, "…": "...",
})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_MARKS)
    text = re.sub(r"\s*-\s*", "-", text)          # "1 - 3" and "1-3" match
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_found(quote: str, source_norm: str) -> bool:
    q = normalize(quote).strip(" .;:,\"'")
    return len(q.split()) >= 4 and q in source_norm


_CITATION_RE = re.compile(
    r"""(?xi)
      \b\d+\s*(?:CFR|U\.?\s?S\.?\s?C\.?)\s*(?:parts?\s*)?\d+(?:\.\d+)?(?:-\d+)?(?:\([a-z0-9]+\))*
    | §+\s*\d+(?:\.\d+)?(?:-\d+)?(?:\([a-z0-9]+\))*(?:\s*(?:through|to|and|-)\s*\d+(?:\.\d+)?)?
    | \b(?:parts?|subparts?|subchapters?|sections?|rules?|annex(?:es)?|regulations?|chapters?|appendix|
          appendices|tables?|figures?|enclosures?|encl\.|paragraphs?|items?|forms?|CG-|NVIC)\s*
          [A-Z0-9]+(?:[.\-][A-Z0-9]+)*(?:\([a-z0-9]+\))*
    | \(\d+\)|\([a-z]{1,2}\)|\([ivx]+\)
    """
)
_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
    "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "half": "2",
    "once": "1", "twice": "2", "single": "1", "dozen": "12",
}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "")
            for n in _NUMBER_RE.findall(text)}


_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_COMPOUND_RE = re.compile(rf"\b({'|'.join(_TENS)})[- ](one|two|three|four|five|six|seven|eight|nine)\b")


def source_numbers(source_text: str) -> set[str]:
    lower = source_text.lower()
    nums = _numbers(source_text)
    for word in re.findall(r"[a-z]+", lower):
        if word in _WORD_NUMBERS:
            nums.add(_WORD_NUMBERS[word])
    for tens, unit in _COMPOUND_RE.findall(lower):
        nums.add(str(int(_WORD_NUMBERS[tens]) + int(_WORD_NUMBERS[unit])))
    return nums


def stray_numbers(text: str, allowed: set[str]) -> list[str]:
    """Numbers in `text` (citations and paragraph designators aside) that the
    section text doesn't contain."""
    return sorted(n for n in _numbers(_CITATION_RE.sub(" ", text)) if n not in allowed)


_CFR_REF_RE = re.compile(r"\b(\d+)\s*CFR\s*(\d+\.\d+[a-z]?)\b", re.IGNORECASE)
_SECTION_SIGN_RE = re.compile(r"§+\s*(\d+\.\d+[a-z]?)")
_RULE_REF_RE = re.compile(r"\bCOLREGs?\s+(Rule\s+\d+|Annex\s+[IVX]+)\b", re.IGNORECASE)


def cited_sections(text: str, default_title: str | None) -> set[str]:
    """Section numbers a page names, in corpus form ("46 CFR 142.240", "COLREGS Rule 13")."""
    found = {f"{t} CFR {s}" for t, s in _CFR_REF_RE.findall(text)}
    if default_title:
        found |= {f"{default_title} CFR {s}" for s in _SECTION_SIGN_RE.findall(text)}
    for ref in _RULE_REF_RE.findall(text):
        kind, num = ref.split()
        found.add(f"COLREGS {kind.capitalize()} {num.upper()}")
    return found


def default_cfr_title(section_number: str) -> str | None:
    m = re.match(r"^(\d+) CFR ", section_number)
    return m.group(1) if m else None


def page_texts(content: dict) -> list[str]:
    """Every plain-English string on a page (quotes excluded)."""
    out = [content.get("topic", ""), content.get("meta_description", ""), content.get("summary", ""),
           content.get("applies_to", "")]
    out += [r.get("statement", "") for r in content.get("requirements", [])]
    for f in content.get("faqs", []):
        out += [f.get("question", ""), f.get("answer", "")]
    return [t for t in out if t]


def static_checks(page: dict, content: dict, corpus_sections: set[str]) -> dict:
    """The quote, number and citation checks. Returns {"ok": bool, "failures": [...]}."""
    source = page["source_text"]
    source_norm = normalize(source)
    failures: list[str] = []

    reqs, faqs = content.get("requirements", []), content.get("faqs", [])
    if not reqs:
        failures.append("no requirements")
    if not content.get("topic") or not content.get("summary"):
        failures.append("missing topic or summary")
    if len(content.get("meta_description", "")) > 170:
        failures.append("meta description too long")
    for i, item in enumerate(reqs):
        if not quote_found(item.get("quote", ""), source_norm):
            failures.append(f"requirement {i + 1}: quote not in the text")
    for i, item in enumerate(faqs):
        if not quote_found(item.get("quote", ""), source_norm):
            failures.append(f"faq {i + 1}: quote not in the text")

    allowed = source_numbers(source) | _numbers(page["section_number"])
    for text in page_texts(content):
        stray = stray_numbers(text, allowed)
        if stray:
            failures.append(f"numbers not in the text: {', '.join(stray)} (in: {text[:80]})")

    title = default_cfr_title(page["section_number"])
    named = cited_sections(" ".join(page_texts(content)), title)
    for ref in content.get("related_sections", []):
        named |= cited_sections(ref, title) or {ref.strip()}
    missing = sorted(n for n in named if n not in corpus_sections and n != page["section_number"])
    if missing:
        failures.append(f"sections not in the corpus: {', '.join(missing)}")
    return {"ok": not failures, "failures": failures}


SUPPORT_PROMPT = """\
You check a plain-English explanation of a regulation against the regulation text. For each numbered item, decide whether the statement is supported: everything it says must be stated or directly implied by its quote, or by the section text when no quote is given. Paraphrase, simplification and leaving details out are fine. A statement is NOT supported if it adds a requirement, number, deadline, condition, exception or vessel type, changes who must do something, makes a permission into a requirement (or the reverse), or reverses the meaning. Give a short reason for each unsupported item."""


def support_items(content: dict) -> list[dict]:
    items = [{"statement": content.get("summary", ""), "quote": ""},
             {"statement": content.get("meta_description", ""), "quote": ""}]
    if content.get("applies_to"):
        items.append({"statement": content["applies_to"], "quote": ""})
    items += [{"statement": r.get("statement", ""), "quote": r.get("quote", "")}
              for r in content.get("requirements", [])]
    items += [{"statement": f"Q: {f.get('question', '')} A: {f.get('answer', '')}", "quote": f.get("quote", "")}
              for f in content.get("faqs", [])]
    return items


async def support_check(client, page: dict, content: dict) -> dict:
    """Haiku's verdict on every statement. Returns {"ok", "failures"}."""
    from rag.llm import BOOL, INT, SIDECAR_MODEL, STR, arr, create_json, obj, small_call_kwargs
    items = support_items(content)
    listing = "\n".join(
        f"{i + 1}. Statement: {it['statement']}\n   Quote: {it['quote'] or '(none: check against the section text)'}"
        for i, it in enumerate(items)
    )
    text = page["source_text"][:PROMPT_TEXT_CHARS]
    schema = obj({"items": arr(obj({"index": INT, "supported": BOOL, "reason": STR}))})
    kwargs = small_call_kwargs(SIDECAR_MODEL, 3000)
    result = await create_json(
        client, schema=schema, label="seo support check", model=SIDECAR_MODEL,
        system=SUPPORT_PROMPT,
        messages=[{"role": "user", "content": f"Section text:\n<<<\n{text}\n>>>\n\nItems:\n{listing}"}],
        **kwargs,
    )
    if result.data is None:
        return {"ok": False, "failures": ["support check returned nothing"]}
    verdicts = {v["index"]: v for v in result.data.get("items", [])}
    failures = [f"item {i}: {verdicts[i].get('reason', '')[:200]}"
                for i in range(1, len(items) + 1) if i in verdicts and not verdicts[i]["supported"]]
    if len(verdicts) < len(items):
        failures.append(f"support check covered {len(verdicts)} of {len(items)} items")
    return {"ok": not failures, "failures": failures}


def compose_title(page: dict, content: dict) -> str:
    topic = (content.get("topic") or page.get("section_title") or "").strip().rstrip(".")
    return f"{page['display_number']}: {topic}" if topic else page["display_number"]


# ── Selection ────────────────────────────────────────────────────────────────

_NVIC_DOC_RE = re.compile(r"^NVIC (\d{1,2}-\d{2})(?: (CH-\d+))?")


async def _sections(conn, source: str, pattern: str | None) -> list[dict]:
    rows = await conn.fetch(
        f"""
        SELECT section_number, max(section_title) AS section_title, max(up_to_date_as_of) AS as_of,
               array_agg(full_text ORDER BY chunk_index) AS chunks
        FROM regulations
        WHERE source = $1 {"AND section_number ~ $2" if pattern else ""}
        GROUP BY section_number
        """,
        *([source, pattern] if pattern else [source]),
    )
    return [dict(r) for r in rows]


def _nvic_sort_key(section_number: str) -> tuple:
    m = re.search(r"§\s*(\d+)", section_number)
    return (0 if "§" not in section_number else 1, int(m.group(1)) if m else 0, section_number)


async def select_pages(conn) -> list[dict]:
    """Every page the selection calls for, with its text (not yet written)."""
    pages: list[dict] = []
    taken: set[tuple[str, str]] = set()

    def add(collection: str, source: str, section_number: str, title: str | None, body: str,
            as_of, priority: int) -> None:
        if (source, section_number) in taken or not is_substantive(title, body):
            return
        taken.add((source, section_number))
        pages.append({
            "slug": slugify(section_number), "collection": collection, "source": source,
            "section_number": section_number, "section_title": title,
            "display_number": display_number(section_number), "source_text": body,
            "source_hash": text_hash(body), "up_to_date_as_of": as_of, "priority": priority,
        })

    for col in COLLECTIONS:
        if col.source in ("nvic", "cfr"):
            continue
        for s in await _sections(conn, col.source, col.pattern):
            add(col.slug, col.source, s["section_number"], s["section_title"],
                join_chunks(s["chunks"], s["section_number"]), s["as_of"], 1)

    # NVICs: one page per circular, from its main body (enclosures are listed, not explained).
    docs: dict[str, list[dict]] = {}
    for s in await _sections(conn, "nvic", None):
        m = _NVIC_DOC_RE.match(s["section_number"])
        if not m or "Encl" in s["section_number"]:
            continue
        doc = f"NVIC {m.group(1)}" + (f" {m.group(2)}" if m.group(2) else "")
        docs.setdefault(doc, []).append(s)
    for doc, secs in docs.items():
        secs.sort(key=lambda s: _nvic_sort_key(s["section_number"]))
        parts, title = [], None
        for s in secs:
            body = join_chunks(s["chunks"], s["section_number"])
            if s["section_number"] == doc:
                title = s["section_title"]
            elif s["section_title"]:
                body = f"{s['section_title']}\n\n{body}"
            parts.append(body)
        body = "\n\n".join(p for p in parts if p)[:NVIC_BODY_CHARS]
        title = (title or secs[0]["section_title"] or "").split(" — ")[0]
        add("nvics", "nvic", doc, title, body, None, 1)

    # Frequently cited: the most-cited CFR sections not already selected.
    room = max(0, TARGET_PAGES - len(pages))
    if room:
        cited = await conn.fetch(
            """
            SELECT r.source, r.section_number, count(*) AS n
            FROM messages m CROSS JOIN LATERAL unnest(m.cited_regulation_ids) AS rid
            JOIN regulations r ON r.id = rid
            WHERE r.source IN ('cfr_46', 'cfr_33', 'cfr_49')
            GROUP BY 1, 2 HAVING count(*) >= 2
            ORDER BY n DESC
            """
        )
        picked = [(r["source"], r["section_number"]) for r in cited
                  if (r["source"], r["section_number"]) not in taken][:room]
        for source, number in picked:
            rows = await conn.fetch(
                """SELECT section_title, up_to_date_as_of, full_text FROM regulations
                   WHERE source = $1 AND section_number = $2 ORDER BY chunk_index""",
                source, number,
            )
            if rows:
                add("frequently-cited", source, number, rows[0]["section_title"],
                    join_chunks([r["full_text"] for r in rows], number), rows[0]["up_to_date_as_of"], 0)
    return pages


async def corpus_section_set(conn) -> set[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT section_number FROM regulations WHERE source = ANY($1::text[])",
        list(PUBLIC_SOURCES) + ["cfr_40", "cfr_47", "cfr_50", "cfr_29", "usc_46", "usc_33"],
    )
    return {r["section_number"] for r in rows}


# ── Storage ──────────────────────────────────────────────────────────────────

async def save_selection(conn, pages: list[dict]) -> dict:
    """Insert new drafts; hold published pages whose text changed; retire
    pages the selection no longer includes. Written pages keep their content."""
    existing = {(r["source"], r["section_number"]): r for r in await conn.fetch(
        "SELECT id, source, section_number, source_hash, status FROM seo_pages")}
    new = changed = 0
    for p in pages:
        key = (p["source"], p["section_number"])
        row = existing.pop(key, None)
        if row is None:
            await conn.execute(
                """INSERT INTO seo_pages (slug, collection, source, section_number, section_title, display_number,
                                          source_text, source_hash, up_to_date_as_of, priority)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                   ON CONFLICT (slug) DO NOTHING""",
                p["slug"], p["collection"], p["source"], p["section_number"], p["section_title"],
                p["display_number"], p["source_text"], p["source_hash"], p["up_to_date_as_of"], p["priority"],
            )
            new += 1
        elif row["source_hash"] != p["source_hash"]:
            await conn.execute(
                """UPDATE seo_pages SET source_text = $2, source_hash = $3, up_to_date_as_of = $4,
                          status = CASE WHEN status = 'draft' THEN 'draft' ELSE 'held' END,
                          checks = CASE WHEN status = 'draft' THEN checks
                                        ELSE jsonb_build_object('ok', false, 'failures',
                                             jsonb_build_array('the regulation text changed')) END,
                          updated_at = now()
                   WHERE id = $1""",
                row["id"], p["source_text"], p["source_hash"], p["up_to_date_as_of"],
            )
            changed += 1
    retired = [r["id"] for r in existing.values() if r["status"] != "retired"]
    if retired:
        await conn.execute(
            "UPDATE seo_pages SET status = 'retired', updated_at = now() WHERE id = ANY($1::bigint[])", retired)
    return {"selected": len(pages), "new": new, "text_changed": changed, "retired": len(retired)}


async def store_result(conn, page: dict, content: dict | None, checks: dict) -> str:
    status = "published" if checks["ok"] else "held"
    await conn.execute(
        """UPDATE seo_pages SET title = $2, meta_description = $3, content = $4::jsonb, checks = $5::jsonb,
                  status = $6, model = $7, generated_at = now(), updated_at = now(),
                  published_at = CASE WHEN $6 = 'published' THEN COALESCE(published_at, now()) END
           WHERE id = $1""",
        page["id"],
        compose_title(page, content) if content else None,
        (content or {}).get("meta_description"),
        json.dumps(content) if content else None,
        json.dumps(checks), status, GEN_MODEL,
    )
    return status


async def check_and_store(conn, client, page: dict, content: dict | None,
                          corpus_sections: set[str]) -> str:
    if content is None:
        return await store_result(conn, page, None, {"ok": False, "failures": ["the writer returned nothing"]})
    checks = static_checks(page, content, corpus_sections)
    support = await support_check(client, page, content)
    checks = {"ok": checks["ok"] and support["ok"],
              "failures": checks["failures"] + support["failures"],
              "static_ok": checks["ok"], "support_ok": support["ok"]}
    return await store_result(conn, page, content, checks)


# ── Runs ─────────────────────────────────────────────────────────────────────

class _Locked:
    """One asyncpg connection shared by concurrent tasks, one statement at a time."""

    def __init__(self, conn):
        self._conn, self._lock = conn, asyncio.Lock()

    async def execute(self, *args):
        async with self._lock:
            return await self._conn.execute(*args)


_PAGE_COLS = ("id, slug, collection, source, section_number, section_title, display_number, "
              "source_text, up_to_date_as_of, content")


async def _connect():
    import asyncpg
    from app.config import settings
    return await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))


def _client():
    from anthropic import AsyncAnthropic
    from app.config import settings
    return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=4)


async def cmd_select() -> None:
    conn = await _connect()
    try:
        pages = await select_pages(conn)
        by_col: dict[str, int] = {}
        for p in pages:
            by_col[p["collection"]] = by_col.get(p["collection"], 0) + 1
        print("selection:", json.dumps(by_col))
        print(json.dumps(await save_selection(conn, pages)))
    finally:
        await conn.close()


async def cmd_pilot(n: int, collection: str | None = None) -> None:
    """Write and check n drafts now (online calls), spread over the collections."""
    from rag.llm import create_json
    conn, client = await _connect(), _client()
    try:
        drafts = [dict(r) for r in await conn.fetch(
            f"SELECT {_PAGE_COLS} FROM seo_pages WHERE status = 'draft'"
            + (" AND collection = $1" if collection else ""), *([collection] if collection else []))]
        random.seed(14)
        by_col: dict[str, list[dict]] = {}
        for d in drafts:
            by_col.setdefault(d["collection"], []).append(d)
        picked: list[dict] = []
        while len(picked) < n and any(by_col.values()):
            for col in list(by_col):
                if by_col[col] and len(picked) < n:
                    picked.append(by_col[col].pop(random.randrange(len(by_col[col]))))
        corpus = await corpus_section_set(conn)
        sem, locked = asyncio.Semaphore(4), _Locked(conn)

        async def one(page: dict) -> tuple[str, str]:
            async with sem:
                params = request_params(page)
                result = await create_json(client, schema=page_schema(), label=f"seo page {page['slug']}",
                                           output_config={"effort": "low"},
                                           **{k: v for k, v in params.items() if k != "output_config"})
                return page["slug"], await check_and_store(locked, client, page, result.data, corpus)

        for slug, status in await asyncio.gather(*(one(p) for p in picked)):
            print(f"{status:9s} {slug}")
    finally:
        await conn.close()


async def cmd_batch(limit: int | None = None) -> None:
    """Every draft through one Message Batch (half price), then the checks."""
    conn, client = await _connect(), _client()
    try:
        drafts = [dict(r) for r in await conn.fetch(
            f"SELECT {_PAGE_COLS} FROM seo_pages WHERE status = 'draft' ORDER BY priority DESC, id"
            + (f" LIMIT {int(limit)}" if limit else ""))]
        if not drafts:
            print("no drafts")
            return
        by_id = {f"p{d['id']}": d for d in drafts}
        batch = await client.messages.batches.create(
            requests=[{"custom_id": cid, "params": request_params(d)} for cid, d in by_id.items()])
        print(f"batch {batch.id}: {len(by_id)} pages", flush=True)
        while batch.processing_status != "ended":
            await asyncio.sleep(60)
            try:
                batch = await client.messages.batches.retrieve(batch.id)
            except Exception as exc:  # noqa: BLE001 — transient; keep polling
                print(f"poll failed: {exc}", flush=True)
                continue
            print(f"{datetime.now(timezone.utc):%H:%M} {batch.processing_status} {batch.request_counts}", flush=True)
        await collect(conn, client, batch.id, by_id)
    finally:
        await conn.close()


async def collect(conn, client, batch_id: str, by_id: dict[str, dict]) -> None:
    from rag.llm import parse_json_text, text_of
    corpus = await corpus_section_set(conn)
    results: list[tuple[dict, dict | None]] = []
    decoder = await client.messages.batches.results(batch_id)
    async for entry in decoder:
        page = by_id.get(entry.custom_id)
        if page is None:
            continue
        content = None
        if entry.result.type == "succeeded":
            content = parse_json_text(text_of(entry.result.message))
        results.append((page, content))
    sem, locked = asyncio.Semaphore(8), _Locked(conn)
    counts: dict[str, int] = {}

    async def one(page, content):
        async with sem:
            try:
                status = await check_and_store(locked, client, page, content, corpus)
            except Exception as exc:  # noqa: BLE001 — one page's failure doesn't stop the run
                logger.warning("seo page %s: %s", page["slug"], exc)
                status = "error"
            counts[status] = counts.get(status, 0) + 1

    await asyncio.gather(*(one(p, c) for p, c in results))
    print("collected:", json.dumps(counts), flush=True)


async def cmd_recheck() -> None:
    """Re-run the checks on held pages (after a check is fixed); no rewriting."""
    conn, client = await _connect(), _client()
    try:
        rows = [dict(r) for r in await conn.fetch(
            f"SELECT {_PAGE_COLS} FROM seo_pages WHERE status = 'held' AND content IS NOT NULL")]
        corpus = await corpus_section_set(conn)
        counts: dict[str, int] = {}
        for page in rows:
            content = json.loads(page["content"]) if isinstance(page["content"], str) else page["content"]
            status = await check_and_store(conn, client, page, content, corpus)
            counts[status] = counts.get(status, 0) + 1
        print(json.dumps(counts))
    finally:
        await conn.close()


async def cmd_status() -> None:
    conn = await _connect()
    try:
        for r in await conn.fetch(
                "SELECT collection, status, count(*) n FROM seo_pages GROUP BY 1, 2 ORDER BY 1, 2"):
            print(f"{r['collection']:20s} {r['status']:10s} {r['n']}")
        rows = await conn.fetch(
            "SELECT f AS failure, count(*) n FROM seo_pages, jsonb_array_elements_text(checks->'failures') f "
            "WHERE status = 'held' GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
        for r in rows:
            print(f"  {r['n']:4d}  {r['failure'][:150]}")
    finally:
        await conn.close()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cmd = argv[0] if argv else "status"
    if cmd == "select" or cmd == "check-stale":
        asyncio.run(cmd_select())
    elif cmd == "pilot":
        asyncio.run(cmd_pilot(int(argv[1]) if len(argv) > 1 else 10, argv[2] if len(argv) > 2 else None))
    elif cmd == "batch":
        asyncio.run(cmd_batch(int(argv[1]) if len(argv) > 1 else None))
    elif cmd == "recheck":
        asyncio.run(cmd_recheck())
    else:
        asyncio.run(cmd_status())


if __name__ == "__main__":
    main(sys.argv[1:])
