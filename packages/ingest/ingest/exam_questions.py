"""Structured USCG exam questions for the public practice page (2026-10-02).

The NMC sample-examination PDFs (data/raw/nmc/qNNN_*.pdf, the files behind the
nmc_exam_bank source) print each question as

    12. <stem, one or more lines>
    A. <choice>            (or "A." on its own line, the text on the next)
    B. ...
    Correct answer: B

under running heads (pool title, date and page). This module parses them into
one exam_questions row each: pool (Q101), part, exam (the endorsement line),
topic (nmc_exam_bank._classify), number, stem, choices, answer, and
needs_figure for questions that need an illustration or a training chart (kept,
not served: the page shows no images).

Each question also gets the nearest corpus section to its stem plus correct
answer (related_*, with the similarity), computed once from OpenAI embeddings
(~$0.02 for the bank). The API shows it only above a similarity floor.

Run on the VPS through the capped wrapper:
  scripts/run_ingest.sh --module ingest.exam_questions [--dry-run] [--no-related]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from ingest.sources.nmc_exam_bank import _classify

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "nmc"
RELATED_EF_SEARCH = 400

_QUESTION = re.compile(r"^(\d{1,3})\.\s*(.*)$")
_CHOICE = re.compile(r"^([A-F])\.\s*(.*)$")
_ANSWER = re.compile(r"^Correct answer:\s*([A-F])\b", re.I)
_PAGE_LINE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}\s+Page\s+\d+\s+of\s+\d+$", re.I)
_POOL_LINE = re.compile(r"^(Q\d{3})\s+(.+)$")
# A stem the page cannot serve: it needs a picture ("illustration D017RR",
# "Illustration SE-0010", "diagram"), a table ("table ST-0098"), a training
# chart ("chart 12354TR") or a reference book the exam room supplies.
_FIGURE = re.compile(
    r"illustrat|diagram|\bD\d{3}[A-Z]{2}\b|\b[A-Z]{2}-\d{4}\b|\bfigure\b|\b\d{5}\s?TR\b|\bTR\s?\d{5}\b"
    r"|Stability Data Reference|Tide Tables|Tidal Current Tables|Nautical Almanac|Light List"
    r"|Coast Pilot|Sight Reduction|Pub\.?\s?(?:229|249)",
    re.I,
)
_BOILERPLATE = re.compile(
    r"^(National Maritime Center|Keep .em Safe, Keep .em Sailing|U\.S\.C\.G\.( Merchant Marine Exam)?|"
    r"Merchant Marine Exam|\(Sample Examination\)|Illustrations:\s*\d+|Choose the best answer.*|"
    r"No reference material is allowed.*|your desk, please remove it.*)$",
    re.I,
)


@dataclass
class Question:
    source_file: str
    number: int
    pool: str
    part: str
    exam: str
    topic_key: str
    topic_label: str
    stem: str = ""
    choices: dict[str, str] = field(default_factory=dict)
    answer: str = ""
    needs_figure: bool = False


def _pages(path: Path) -> list[list[str]]:
    with pdfplumber.open(str(path)) as pdf:
        return [[ln.strip() for ln in (p.extract_text() or "").splitlines() if ln.strip()] for p in pdf.pages]


def _header(pages: list[list[str]]) -> tuple[str, str, str]:
    """(pool, part, exam) from page 1: "Q101 Deck General – Part I" and the line
    after "U.S.C.G. Merchant Marine Exam"."""
    first = pages[0] if pages else []
    pool = part = exam = ""
    for i, ln in enumerate(first[:20]):
        m = _POOL_LINE.match(ln)
        if m and not pool:
            pool, part = m.group(1), m.group(2).strip()
        if ln.lower().startswith("u.s.c.g. merchant marine exam") and not exam and i + 1 < len(first):
            exam = first[i + 1]
    return pool, part, exam


def parse_lines(lines: list[str], base: Question) -> list[Question]:
    """The questions in a file's body lines (running heads already removed)."""
    out: list[Question] = []
    cur: Question | None = None
    expected = 1
    for ln in lines:
        if cur is None:
            m = _QUESTION.match(ln)
            if m and int(m.group(1)) == expected:
                cur = Question(**{**base.__dict__, "number": expected, "stem": m.group(2).strip(), "choices": {}})
            continue
        ans = _ANSWER.match(ln)
        if ans:
            cur.answer = ans.group(1).upper()
            if cur.answer in cur.choices and len(cur.choices) >= 2 and cur.stem:
                cur.needs_figure = bool(_FIGURE.search(cur.stem))
                out.append(cur)
            else:
                logger.debug("%s #%d: skipped (answer %s, %d choices)", cur.source_file, cur.number,
                             cur.answer, len(cur.choices))
            expected = cur.number + 1
            cur = None
            continue
        ch = _CHOICE.match(ln)
        next_letter = chr(ord("A") + len(cur.choices))
        if ch and ch.group(1) == next_letter:
            cur.choices[next_letter] = ch.group(2).strip()
        elif cur.choices:
            last = list(cur.choices)[-1]
            cur.choices[last] = f"{cur.choices[last]} {ln}".strip()
        else:
            cur.stem = f"{cur.stem} {ln}".strip()
    return out


def parse_pdf(path: Path) -> list[Question]:
    q_num, topic_key, topic_label = _classify(path.name)
    if q_num is None:
        return []
    pages = _pages(path)
    pool, part, exam = _header(pages)
    pool = pool or f"Q{q_num}"
    # running heads: the pool title, the date / page line, the boilerplate block
    title_lines = {ln for page in pages for ln in page[:12] if _POOL_LINE.match(ln)}
    body = [ln for page in pages for ln in page
            if ln not in title_lines and ln != exam and not _PAGE_LINE.match(ln) and not _BOILERPLATE.match(ln)]
    base = Question(source_file=path.name, number=0, pool=pool, part=part, exam=exam,
                    topic_key=topic_key, topic_label=topic_label)
    return parse_lines(body, base)


def parse_all(raw_dir: Path = RAW_DIR) -> list[Question]:
    questions: list[Question] = []
    for path in sorted(raw_dir.glob("q[0-9]*.pdf")):
        try:
            qs = parse_pdf(path)
        except Exception as exc:  # one bad file never stops the bank
            logger.warning("%s: parse failed — %s", path.name, exc)
            continue
        logger.info("%s: %d questions (%d need a figure)", path.name, len(qs), sum(q.needs_figure for q in qs))
        questions.extend(qs)
    return questions


async def _related(questions: list[Question], pool) -> dict[tuple[str, int], tuple]:
    """(source_file, number) -> (source, section, title, similarity) of the
    corpus row nearest each servable question."""
    from ingest.config import settings
    from ingest.embedder import EmbedderClient

    served = [q for q in questions if not q.needs_figure]
    texts = [f"{q.stem} {q.choices.get(q.answer, '')}" for q in served]
    client = EmbedderClient(api_key=settings.openai_api_key)
    try:
        vectors = await client.embed_texts(texts)
    finally:
        await client.close()
    sem = asyncio.Semaphore(4)

    async def one(q: Question, vec: list[float]):
        literal = "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
        # The exam-bank chunks hold these very questions and can fill the
        # HNSW scan's default 40 candidates before the source filter runs, so
        # widen the scan for this query. SET LOCAL inside the transaction:
        # asyncpg's RESET ALL on release wipes a session-level SET.
        async with sem, pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL hnsw.ef_search = {RELATED_EF_SEARCH}")
            row = await conn.fetchrow(
                """
                SELECT source, section_number, section_title, 1 - (embedding <=> $1::vector) AS sim
                FROM regulations
                WHERE embedding IS NOT NULL AND source <> 'nmc_exam_bank'
                  AND jurisdictions && ARRAY['us', 'intl']::text[]
                ORDER BY embedding <=> $1::vector
                LIMIT 1
                """,
                literal,
            )
        return (q.source_file, q.number), (row["source"], row["section_number"], row["section_title"],
                                           float(row["sim"])) if row else None

    results = await asyncio.gather(*(one(q, v) for q, v in zip(served, vectors)))
    return {k: v for k, v in results if v}


async def load(questions: list[Question], related: bool = True) -> None:
    import asyncpg

    from ingest.config import settings

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    try:
        rel = await _related(questions, pool) if related else {}
        async with pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """
                INSERT INTO exam_questions (source_file, number, pool, part, exam, topic_key, topic_label,
                    stem, choices, answer, needs_figure, related_source, related_section, related_title,
                    related_similarity, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15, now())
                ON CONFLICT (source_file, number) DO UPDATE SET
                    pool = EXCLUDED.pool, part = EXCLUDED.part, exam = EXCLUDED.exam,
                    topic_key = EXCLUDED.topic_key, topic_label = EXCLUDED.topic_label,
                    stem = EXCLUDED.stem, choices = EXCLUDED.choices, answer = EXCLUDED.answer,
                    needs_figure = EXCLUDED.needs_figure,
                    related_source = COALESCE(EXCLUDED.related_source, exam_questions.related_source),
                    related_section = COALESCE(EXCLUDED.related_section, exam_questions.related_section),
                    related_title = COALESCE(EXCLUDED.related_title, exam_questions.related_title),
                    related_similarity = COALESCE(EXCLUDED.related_similarity, exam_questions.related_similarity),
                    updated_at = now()
                """,
                [(q.source_file, q.number, q.pool, q.part, q.exam, q.topic_key, q.topic_label, q.stem,
                  json.dumps(q.choices), q.answer, q.needs_figure,
                  *(rel.get((q.source_file, q.number)) or (None, None, None, None)))
                 for q in questions],
            )
            # questions a re-parse no longer yields (a pool withdrawn or renumbered)
            keys = [f"{q.source_file}#{q.number}" for q in questions]
            removed = await conn.execute(
                "DELETE FROM exam_questions WHERE NOT (source_file || '#' || number::text = ANY($1::text[]))",
                keys,
            )
        logger.info("exam_questions: %d upserted, %s; related sections for %d", len(questions), removed, len(rel))
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse the NMC sample exams into exam_questions.")
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    ap.add_argument("--no-related", action="store_true", help="skip the related-section lookup (no OpenAI calls)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    questions = parse_all()
    figures = sum(q.needs_figure for q in questions)
    logger.info("total: %d questions in %d files; %d need a figure", len(questions),
                len({q.source_file for q in questions}), figures)
    if not questions:
        logger.warning("no questions parsed; nothing loaded")
        return 1
    if not args.dry_run:
        asyncio.run(load(questions, related=not args.no_related))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
