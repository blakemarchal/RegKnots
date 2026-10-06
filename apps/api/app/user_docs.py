"""Documents a user attaches in chat (2026-10-05).

Spec: docs/specs/chat-document-upload-2026-10-05.md. A user attaches a PDF
(with a text layer) or a Word file, up to 25 MB and 300 pages, to a question.
A Celery task (app.tasks.process_user_document) extracts the text locally,
splits it at headings, chunks and embeds it (app/company_docs.py does the
same for workspace manuals), then runs the internal check: the small model
reads the opening pages and returns the document's type, whether it is
maritime, the vessel, flag and company it names, and a one-line summary.

A document stays attached for the rest of the conversation it came in. A
maritime document is also kept in the user's account: later questions in any
of their chats consult it when it is close to them. Anything else serves the
conversation it came with and is deleted after 7 days
(app.tasks.purge_user_documents). Kept documents are capped per plan: 3 on the
free plan and trial, 20 on paid plans.

Tenancy: chunks live in user_document_chunks, never in `regulations` or the
workspace tables, and every read here filters on user_id. The original file
is only parsed for text and is never served back to anyone.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.company_docs import (
    UnreadableDocument,
    _vec,
    chunk_sections,
    embed_texts,
    extract_pages,
    split_sections,
    title_from_filename,
)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PAGES = 300
MAX_DOCX_UNCOMPRESSED = 150 * 1024 * 1024      # a zip bomb dressed as .docx
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXTENSIONS = {PDF: ".pdf", DOCX: ".docx"}

KEEP_LIMIT_FREE = 3
KEEP_LIMIT_PAID = 20
PAID_TIERS = frozenset({"cadet", "mate", "captain", "pro", "wheelhouse"})
UPLOADS_PER_DAY = 10
TRANSIENT_DAYS = 7
MAX_PER_MESSAGE = 3

ATTACHED_CHUNKS = 8          # passages from the documents attached to this question
KEPT_CHUNKS = 4              # passages from the user's kept documents, when close enough
KEPT_MIN_SIMILARITY = 0.45   # below this a kept document is only loosely related: leave it out
OUTLINE_MAX = 40             # headings shown per attached document

DOC_TYPES = ("sms_manual", "procedure", "checklist", "certificate", "form", "correspondence",
             "regulation_copy", "plan_or_drawing", "logbook_or_record", "other")
_LABEL = re.compile(r"^\s*\[?\s*Doc:\s*(.+?)\s*§\s*(.+?)\s*\]?\s*$")


# ── Upload validation ─────────────────────────────────────────────────────────

def sniff_type(content: bytes) -> str | None:
    """PDF or DOCX by content, not by the name or the browser's claim."""
    if content[:5] == b"%PDF-":
        return PDF
    if content[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
                if "word/document.xml" not in names:
                    return None
                if sum(i.file_size for i in z.infolist()) > MAX_DOCX_UNCOMPRESSED:
                    raise UnreadableDocument("This Word file expands to more than 150 MB; upload a smaller one.")
                return DOCX
        except zipfile.BadZipFile:
            return None
    return None


def keep_limit(tier: str | None, privileged: bool = False) -> int:
    if privileged or (tier or "").lower() in PAID_TIERS:
        return KEEP_LIMIT_PAID
    return KEEP_LIMIT_FREE


def doc_title(filename: str) -> str:
    title = title_from_filename(filename)
    return "Document" if title == "Company document" else title


def label(title: str, section: str) -> str:
    return f"Doc: {title} §{section}"


def parse_label(text: str) -> tuple[str, str] | None:
    m = _LABEL.match(text or "")
    return (m.group(1), m.group(2)) if m else None


# ── The internal check ────────────────────────────────────────────────────────

_CHECK_PROMPT = (
    "You are checking a document a mariner uploaded to RegKnot, a maritime compliance assistant. "
    "From its opening text, say what kind of document it is. doc_type: sms_manual (a safety "
    "management system or TSMS manual, or a large part of one), procedure (a single company or "
    "shipboard procedure), checklist, certificate, form, correspondence (a letter or notice, e.g. "
    "from a flag state, class or the Coast Guard), regulation_copy (a copy of a law, regulation, "
    "code or circular), plan_or_drawing, logbook_or_record, or other. maritime: true when it is "
    "about ships, crews, ports, shipping companies or maritime regulation. vessel_name, flag and "
    "company: as the document states them, or null. summary: one plain sentence on what it is."
)


def check_schema() -> dict:
    from rag.llm import enum, nullable, obj
    return obj({
        "doc_type": enum(*DOC_TYPES),
        "maritime": {"type": "boolean"},
        "vessel_name": nullable({"type": "string"}),
        "flag": nullable({"type": "string"}),
        "company": nullable({"type": "string"}),
        "summary": {"type": "string"},
    })


async def classify(client, title: str, opening_text: str) -> dict | None:
    """The internal check on a document's opening ~3K tokens; None when the
    small model is unavailable or answers nothing usable."""
    from rag.llm import SIDECAR_MODEL, create_json, small_call_kwargs
    result = await create_json(
        client,
        schema=check_schema(),
        label="user document check",
        model=SIDECAR_MODEL,
        **small_call_kwargs(SIDECAR_MODEL, 400),
        messages=[{"role": "user", "content": f"{_CHECK_PROMPT}\n\nTitle: {title}\n\n{opening_text[:12000]}"}],
    )
    data = result.data
    if not data or data.get("doc_type") not in DOC_TYPES:
        return None
    return data


def keep_decision(check: dict | None) -> bool:
    """Keep what is maritime and not "other". A document the check couldn't
    label is kept (losing a user's manual is worse than keeping a stray file;
    admin sees it unlabelled)."""
    if check is None:
        return True
    return bool(check.get("maritime")) and check.get("doc_type") != "other"


# ── Processing (Celery) ───────────────────────────────────────────────────────

_SCANNED = ("This PDF has no text layer (it looks scanned). Send photos of the pages instead "
            "(the paperclip takes photos), or upload the Word version.")


async def process_document(pool, document_id: uuid.UUID, openai_api_key: str, anthropic_client) -> None:
    """Extract, split, chunk, embed and check one upload; status becomes ready or failed."""
    doc = await pool.fetchrow(
        "SELECT id, user_id, title, mime_type, file_path FROM user_documents WHERE id = $1", document_id)
    if doc is None:
        return
    try:
        try:
            pages = extract_pages(doc["file_path"], doc["mime_type"], max_pages=MAX_PAGES)
        except UnreadableDocument as exc:
            raise UnreadableDocument(_SCANNED if "no text layer" in str(exc) else str(exc)) from None
        chunks = chunk_sections(split_sections(pages))
        if not chunks:
            raise UnreadableDocument("No text found in this document.")
        vectors = await embed_texts(
            [f"{doc['title']} — {heading}\n\n{text}" for heading, _, text in chunks], openai_api_key)
        check = None
        try:
            check = await classify(anthropic_client, doc["title"], "\n\n".join(pages)[:12000])
        except Exception as exc:  # noqa: BLE001 — the check never blocks the document
            logger.warning("user doc %s: check unavailable: %s", doc["id"], exc)
        kept = keep_decision(check)
        delete_after = None if kept else datetime.now(timezone.utc) + timedelta(days=TRANSIENT_DAYS)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM user_document_chunks WHERE document_id = $1", doc["id"])
                await conn.executemany(
                    "INSERT INTO user_document_chunks "
                    "(document_id, user_id, section, chunk_index, position, text, embedding) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7::vector)",
                    [(doc["id"], doc["user_id"], heading[:200], idx, pos, text, _vec(vec))
                     for pos, ((heading, idx, text), vec) in enumerate(zip(chunks, vectors))],
                )
                await conn.execute(
                    """
                    UPDATE user_documents
                    SET status = 'ready', error = NULL, pages = $2, chunk_count = $3, doc_type = $4,
                        maritime = $5, summary = $6, kept = $7, delete_after = $8, updated_at = now()
                    WHERE id = $1
                    """,
                    doc["id"], len(pages) if doc["mime_type"] == PDF else None, len(chunks),
                    (check or {}).get("doc_type"), (check or {}).get("maritime"),
                    ((check or {}).get("summary") or "")[:500] or None, kept, delete_after,
                )
        logger.info("user doc %s ready: %d chunks, type=%s, kept=%s",
                    doc["id"], len(chunks), (check or {}).get("doc_type"), kept)
    except UnreadableDocument as exc:
        await _fail(pool, doc["id"], str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("user doc %s failed", doc["id"])
        await _fail(pool, doc["id"], f"Processing failed ({type(exc).__name__}). Try again or contact support.")


async def _fail(pool, document_id, message: str) -> None:
    await pool.execute(
        "UPDATE user_documents SET status = 'failed', error = $2, updated_at = now() WHERE id = $1",
        document_id, message[:500],
    )


# ── Answering with them ───────────────────────────────────────────────────────

_BLOCK_HEADER = (
    "YOUR DOCUMENTS — files this user uploaded: their own manuals, procedures or records, not law. "
    "Cite a passage exactly as its label reads, e.g. [Doc: SMS Manual §4.2 Emergency Drills]. For a "
    "document attached in this conversation you see its outline and the passages nearest the "
    "question, not the whole file: if the user asks about a part you can't see, say so and ask which "
    "section to look at. When a document is stricter than, different from, or silent on what the "
    "regulations require, say so. Never present the user's document as a regulation."
)
_SAVED_INTRO = (
    "From documents saved in the user's account (not attached here). They may be only loosely "
    "related: use one only where it bears on the question."
)


async def outline(pool, user_id: uuid.UUID, document_id: uuid.UUID) -> list[str]:
    rows = await pool.fetch(
        """
        SELECT section FROM user_document_chunks
        WHERE user_id = $1 AND document_id = $2
        GROUP BY section ORDER BY min(position)
        """,
        user_id, document_id,
    )
    return [r["section"] for r in rows]


def format_block(attached: list[dict], attached_rows, saved_rows=()) -> str | None:
    """The YOUR DOCUMENTS block: the outline of each document attached in this
    conversation and the passages nearest the question, then any close passages
    from the user's other saved documents."""
    if not attached and not attached_rows and not saved_rows:
        return None
    parts = [_BLOCK_HEADER]
    for d in attached:
        pages = f", {d['pages']} pages" if d.get("pages") else ""
        heads = d.get("outline") or []
        shown = "; ".join(heads[:OUTLINE_MAX]) + (f"; … ({len(heads) - OUTLINE_MAX} more)" if len(heads) > OUTLINE_MAX else "")
        parts.append(f"Attached in this conversation: {d['title']}{pages}. Outline: {shown or '(no headings)'}")
    parts += [f"[{label(r['title'], r['section'])}]\n{r['text']}" for r in attached_rows]
    if saved_rows:
        parts.append(_SAVED_INTRO)
        parts += [f"[{label(r['title'], r['section'])}]\n{r['text']}" for r in saved_rows]
    return "\n\n".join(parts)


async def conversation_documents(pool, conversation_id: uuid.UUID, user_id: uuid.UUID,
                                 current_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """The documents attached to this question, then the caller's documents
    attached earlier in the conversation, most recent first, at most
    MAX_PER_MESSAGE. A follow-up ("and the drill section?") is about the
    document already on the table, so it stays attached for the conversation.
    Owner-filtered: in a workspace chat a crewmate's attachment stays theirs."""
    rows = await pool.fetch(
        """
        SELECT d.id, max(m.created_at) AS attached_at
        FROM messages m
        JOIN user_documents d ON d.id = ANY(m.document_ids)
        WHERE m.conversation_id = $1 AND m.role = 'user' AND m.document_ids IS NOT NULL
          AND d.user_id = $2 AND d.status = 'ready'
        GROUP BY d.id
        ORDER BY attached_at DESC
        LIMIT $3
        """,
        conversation_id, user_id, MAX_PER_MESSAGE,
    )
    return list(dict.fromkeys([*current_ids, *(r["id"] for r in rows)]))[:MAX_PER_MESSAGE]


async def context_block(pool, user_id: uuid.UUID, attached_ids: list[uuid.UUID], openai_api_key: str,
                        query: str) -> str | None:
    """The YOUR DOCUMENTS block for one chat turn: the documents attached in the
    conversation, and the user's kept documents when they are close to the
    question. None when the user has neither (one cheap query, no embedding call)."""
    docs = await pool.fetch(
        """
        SELECT id, title, pages, kept FROM user_documents
        WHERE user_id = $1 AND status = 'ready' AND (kept OR id = ANY($2::uuid[]))
        """,
        user_id, list(attached_ids),
    )
    if not docs:
        return None
    wanted = set(attached_ids)
    attached_set = {d["id"] for d in docs if d["id"] in wanted}
    from rag.retriever import _embed_query
    vec = await _embed_query(openai_api_key, query)
    attached_rows, saved_rows = [], []
    if attached_set:
        attached_rows = await pool.fetch(
            """
            SELECT c.section, c.text, d.title, c.document_id
            FROM user_document_chunks c JOIN user_documents d ON d.id = c.document_id
            WHERE c.user_id = $1 AND c.document_id = ANY($2::uuid[])
            ORDER BY c.embedding <=> $3::vector
            LIMIT $4
            """,
            user_id, list(attached_set), vec, ATTACHED_CHUNKS,
        )
    if any(d["kept"] and d["id"] not in attached_set for d in docs):
        saved_rows = await pool.fetch(
            """
            SELECT * FROM (
                SELECT c.section, c.text, d.title, c.document_id, 1 - (c.embedding <=> $3::vector) AS sim
                FROM user_document_chunks c JOIN user_documents d ON d.id = c.document_id
                WHERE c.user_id = $1 AND d.kept AND d.status = 'ready' AND NOT (c.document_id = ANY($2::uuid[]))
                ORDER BY c.embedding <=> $3::vector
                LIMIT $4
            ) q WHERE sim >= $5
            """,
            user_id, list(attached_set), vec, KEPT_CHUNKS, KEPT_MIN_SIMILARITY,
        )
    order = {doc_id: i for i, doc_id in enumerate(attached_ids)}
    attached = []
    for d in sorted((d for d in docs if d["id"] in attached_set), key=lambda d: order[d["id"]]):
        attached.append({"title": d["title"], "pages": d["pages"],
                         "outline": await outline(pool, user_id, d["id"])})
    used = list({r["document_id"] for r in [*attached_rows, *saved_rows]} | attached_set)
    if used:
        await pool.execute("UPDATE user_documents SET last_used_at = now() WHERE user_id = $1 AND id = ANY($2::uuid[])",
                           user_id, used)
    return format_block(attached, attached_rows, saved_rows)


async def lookup(pool, user_id: uuid.UUID, citation: str) -> dict | None:
    """Resolve a [Doc: title §section] citation to its text, within one user's documents."""
    parsed = parse_label(citation)
    if not parsed:
        return None
    title, section = parsed
    rows = await pool.fetch(
        """
        SELECT d.title, c.section, c.text
        FROM user_document_chunks c JOIN user_documents d ON d.id = c.document_id AND d.status = 'ready'
        WHERE c.user_id = $1 AND lower(d.title) = lower($2)
          AND (lower(c.section) = lower($3) OR lower(c.section) LIKE lower($3) || '%')
        ORDER BY (lower(c.section) = lower($3)) DESC, c.position
        LIMIT 8
        """,
        user_id, title, section,
    )
    if not rows:
        return None
    first = rows[0]["section"]
    text = "\n\n".join(r["text"] for r in rows if r["section"] == first)
    return {"title": rows[0]["title"], "section": first, "text": text[:8000]}


# ── Deleting ──────────────────────────────────────────────────────────────────

def _unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("user doc: could not delete %s", path)


async def delete_document(pool, user_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    path = await pool.fetchval(
        "DELETE FROM user_documents WHERE id = $1 AND user_id = $2 RETURNING file_path", document_id, user_id)
    if path is None:
        return False
    _unlink(path)
    return True


async def purge(pool) -> int:
    """Delete documents past their delete_after (not maritime: 7 days after upload)
    and failed uploads older than 7 days, files included."""
    rows = await pool.fetch(
        """
        DELETE FROM user_documents
        WHERE (delete_after IS NOT NULL AND delete_after < now())
           OR (status = 'failed' AND created_at < now() - interval '7 days')
        RETURNING file_path
        """
    )
    for r in rows:
        _unlink(r["file_path"])
    return len(rows)
