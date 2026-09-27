"""Company documents: a fleet's own manuals in workspace chat (2026-09-27).

Spec: docs/specs/company-documents-2026-09-27.md. A workspace owner or admin
uploads the company's SMS / TSMS manual and procedures (PDF with a text layer,
DOCX, TXT, MD). A Celery task extracts the text locally (no API spend), splits
it at headings, chunks it and embeds the chunks (text-embedding-3-small).
Workspace chats then retrieve the nearest chunks alongside the regulations,
and the answer cites them as [Company: <title> §<section>].

Tenancy: chunks live in workspace_document_chunks, never in `regulations`, and
every read here filters on workspace_id.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import tiktoken

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DOCS_PER_WORKSPACE = 20
MAX_PAGES = 1500
ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
CHUNK_TOKENS = 400
SEARCH_LIMIT = 6
_EMBED_MODEL = "text-embedding-3-small"
_EMBED_BATCH = 64
_MIN_TEXT_CHARS = 300          # less than this from a whole PDF means no text layer
_ENC = tiktoken.get_encoding("cl100k_base")

# Headings: "4.2 Emergency Drills", "4.2. Drills", "SECTION 4 - DRILLS", "Chapter 3 Crew",
# "Appendix B Forms", or a short ALL-CAPS line.
_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,3}){0,3})\.?\s+([A-Z][^\n]{2,90})$")
_WORDED = re.compile(r"^((?:SECTION|Section|CHAPTER|Chapter|PART|Part|APPENDIX|Appendix)\s+[\dA-Z]{1,4}\b[^\n]{0,80})$")
_CAPS = re.compile(r"^[A-Z][A-Z0-9 &/,()'-]{2,58}[A-Z)]$")
_LABEL = re.compile(r"^\s*\[?\s*Company:\s*(.+?)\s*§\s*(.+?)\s*\]?\s*$")


@dataclass
class Section:
    heading: str
    text: str


class UnreadableDocument(ValueError):
    """The file has no extractable text (e.g. a scanned PDF)."""


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_pages(path: str | Path, mime_type: str) -> list[str]:
    """Text per page for a PDF, one element for other types."""
    path = Path(path)
    if mime_type == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if len(reader.pages) > MAX_PAGES:
            raise UnreadableDocument(f"This PDF has {len(reader.pages)} pages; the limit is {MAX_PAGES}.")
        pages = [(p.extract_text() or "") for p in reader.pages]
        if sum(len(p.strip()) for p in pages) < _MIN_TEXT_CHARS:
            raise UnreadableDocument(
                "This PDF has no text layer (it looks scanned). Upload the Word version, "
                "or export the PDF with text."
            )
        return pages
    if mime_type.endswith("wordprocessingml.document"):
        import docx
        document = docx.Document(str(path))
        lines = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        return ["\n".join(lines)]
    return [path.read_text(encoding="utf-8", errors="replace")]


def _heading(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 100:
        return None
    m = _NUMBERED.match(s)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    if _WORDED.match(s):
        return s
    if _CAPS.match(s) and sum(c.isalpha() for c in s) >= 4:
        return s.title()
    return None


def split_sections(pages: list[str]) -> list[Section]:
    """Split at headings; without any headings, one section per page."""
    sections: list[Section] = []
    heading, body = "", []
    found = False
    for page in pages:
        for line in page.splitlines():
            h = _heading(line)
            if h:
                found = True
                if body and "".join(body).strip():
                    sections.append(Section(heading or "Introduction", "\n".join(body).strip()))
                heading, body = h, []
            else:
                body.append(line)
        body.append("")
    if body and "".join(body).strip():
        sections.append(Section(heading or "Introduction", "\n".join(body).strip()))
    if not found:
        return [Section(f"p.{i}", p.strip()) for i, p in enumerate(pages, 1) if p.strip()]
    return sections


def chunk_sections(sections: list[Section], max_tokens: int = CHUNK_TOKENS) -> list[tuple[str, int, str]]:
    """(heading, chunk_index, text), packing paragraphs up to max_tokens."""
    out: list[tuple[str, int, str]] = []
    for sec in sections:
        pieces: list[str] = []
        for para in re.split(r"\n\s*\n", sec.text):
            para = " ".join(para.split())
            if not para:
                continue
            tokens = _ENC.encode(para)
            if len(tokens) <= max_tokens:
                pieces.append(para)
            else:
                pieces.extend(_ENC.decode(tokens[i:i + max_tokens]) for i in range(0, len(tokens), max_tokens))
        current: list[str] = []
        size = 0
        idx = 0
        for p in pieces:
            n = len(_ENC.encode(p))
            if current and size + n > max_tokens:
                out.append((sec.heading, idx, "\n\n".join(current)))
                idx += 1
                current, size = [], 0
            current.append(p)
            size += n
        if current:
            out.append((sec.heading, idx, "\n\n".join(current)))
    return out


# ── Labels ────────────────────────────────────────────────────────────────────

def label(title: str, section: str) -> str:
    return f"Company: {title} §{section}"


def parse_label(text: str) -> tuple[str, str] | None:
    m = _LABEL.match(text or "")
    return (m.group(1), m.group(2)) if m else None


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[_\s]+", " ", stem).strip()[:80] or "Company document"


# ── Embeddings ────────────────────────────────────────────────────────────────

async def embed_texts(texts: list[str], openai_api_key: str) -> list[list[float]]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=openai_api_key)
    vectors: list[list[float]] = []
    try:
        for i in range(0, len(texts), _EMBED_BATCH):
            resp = await client.embeddings.create(model=_EMBED_MODEL, input=texts[i:i + _EMBED_BATCH])
            vectors.extend(d.embedding for d in resp.data)
    finally:
        await client.close()
    return vectors


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


# ── Processing (Celery) ───────────────────────────────────────────────────────

async def process_document(pool, document_id: uuid.UUID, openai_api_key: str) -> None:
    """Extract, split, chunk and embed one upload; status becomes ready or failed."""
    doc = await pool.fetchrow(
        "SELECT id, workspace_id, title, mime_type, file_path FROM workspace_documents WHERE id = $1",
        document_id,
    )
    if doc is None:
        return
    try:
        pages = extract_pages(doc["file_path"], doc["mime_type"])
        chunks = chunk_sections(split_sections(pages))
        if not chunks:
            raise UnreadableDocument("No text found in this document.")
        vectors = await embed_texts(
            [f"{doc['title']} — {heading}\n\n{text}" for heading, _, text in chunks], openai_api_key,
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM workspace_document_chunks WHERE document_id = $1", doc["id"])
                await conn.executemany(
                    "INSERT INTO workspace_document_chunks "
                    "(document_id, workspace_id, section, chunk_index, text, embedding) "
                    "VALUES ($1, $2, $3, $4, $5, $6::vector)",
                    [(doc["id"], doc["workspace_id"], heading[:200], idx, text, _vec(vec))
                     for (heading, idx, text), vec in zip(chunks, vectors)],
                )
                await conn.execute(
                    "UPDATE workspace_documents SET status = 'ready', error = NULL, pages = $2, "
                    "chunk_count = $3, updated_at = now() WHERE id = $1",
                    doc["id"], len(pages) if doc["mime_type"] == "application/pdf" else None, len(chunks),
                )
        logger.info("company doc %s ready: %d chunks", doc["id"], len(chunks))
    except UnreadableDocument as exc:
        await _fail(pool, doc["id"], str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("company doc %s failed", doc["id"])
        await _fail(pool, doc["id"], f"Processing failed ({type(exc).__name__}). Try again or contact support.")


async def _fail(pool, document_id, message: str) -> None:
    await pool.execute(
        "UPDATE workspace_documents SET status = 'failed', error = $2, updated_at = now() WHERE id = $1",
        document_id, message[:500],
    )


# ── Retrieval for workspace chats ─────────────────────────────────────────────

_BLOCK_HEADER = (
    "COMPANY DOCUMENTS — this fleet's own procedures, uploaded by the company. They are the "
    "company's requirements, not law. Cite each one exactly as its label reads, e.g. "
    "[Company: TSMS Manual §4.2 Emergency Drills]. When a procedure is stricter than, different "
    "from, or silent on what the regulations require, say so. Never present a company procedure "
    "as a regulation."
)


async def search(pool, workspace_id: uuid.UUID, query_vec: str, limit: int = SEARCH_LIMIT) -> list:
    """The chunks of this workspace's ready documents nearest the query."""
    return await pool.fetch(
        """
        SELECT c.id, c.section, c.chunk_index, c.text, d.title
        FROM workspace_document_chunks c
        JOIN workspace_documents d ON d.id = c.document_id AND d.status = 'ready'
        WHERE c.workspace_id = $1
        ORDER BY c.embedding <=> $2::vector
        LIMIT $3
        """,
        workspace_id, query_vec, limit,
    )


def format_block(rows) -> str | None:
    if not rows:
        return None
    parts = [_BLOCK_HEADER]
    for r in rows:
        parts.append(f"[{label(r['title'], r['section'])}]\n{r['text']}")
    return "\n\n".join(parts)


async def context_block(pool, workspace_id: uuid.UUID, openai_api_key: str, query: str) -> str | None:
    """The COMPANY DOCUMENTS block for one workspace chat turn; None without ready documents."""
    has_docs = await pool.fetchval(
        "SELECT 1 FROM workspace_documents WHERE workspace_id = $1 AND status = 'ready' LIMIT 1",
        workspace_id,
    )
    if not has_docs:
        return None
    from rag.retriever import _embed_query
    rows = await search(pool, workspace_id, await _embed_query(openai_api_key, query))
    return format_block(rows)


async def lookup(pool, workspace_id: uuid.UUID, citation: str) -> dict | None:
    """Resolve a [Company: title §section] citation to its text, within one workspace."""
    parsed = parse_label(citation)
    if not parsed:
        return None
    title, section = parsed
    rows = await pool.fetch(
        """
        SELECT d.title, c.section, c.text
        FROM workspace_document_chunks c
        JOIN workspace_documents d ON d.id = c.document_id AND d.status = 'ready'
        WHERE c.workspace_id = $1 AND lower(d.title) = lower($2)
          AND (lower(c.section) = lower($3) OR lower(c.section) LIKE lower($3) || '%')
        ORDER BY (lower(c.section) = lower($3)) DESC, c.section, c.chunk_index
        LIMIT 8
        """,
        workspace_id, title, section,
    )
    if not rows:
        return None
    first = rows[0]["section"]
    text = "\n\n".join(r["text"] for r in rows if r["section"] == first)
    return {"title": rows[0]["title"], "section": first, "text": text[:8000]}
