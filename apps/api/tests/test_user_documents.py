"""2026-10-05 — PDF and Word uploads in chat (app/user_docs.py)."""
import asyncio
import io
import uuid
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, UploadFile

from app import user_docs
from app.company_docs import UnreadableDocument
from app.config import settings
from app.routers import admin_documents, user_documents

UID = uuid.uuid4()


def _docx(extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


# ── validation ────────────────────────────────────────────────────────────────

def test_type_comes_from_the_content(monkeypatch):
    assert user_docs.sniff_type(b"%PDF-1.7\n...") == user_docs.PDF
    assert user_docs.sniff_type(_docx()) == user_docs.DOCX
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("readme.txt", "hi")
    assert user_docs.sniff_type(plain_zip.getvalue()) is None
    assert user_docs.sniff_type(b"\x89PNG\r\n") is None
    monkeypatch.setattr(user_docs, "MAX_DOCX_UNCOMPRESSED", 100)
    with pytest.raises(UnreadableDocument):
        user_docs.sniff_type(_docx({"word/media/big.bin": "x" * 1000}))   # a zip bomb dressed as .docx


def test_limits_and_the_keep_decision():
    assert user_docs.keep_limit("free") == 3 and user_docs.keep_limit(None) == 3
    assert user_docs.keep_limit("mate") == 20 and user_docs.keep_limit("free", privileged=True) == 20
    assert user_docs.keep_decision({"doc_type": "sms_manual", "maritime": True})
    assert not user_docs.keep_decision({"doc_type": "other", "maritime": True})
    assert not user_docs.keep_decision({"doc_type": "form", "maritime": False})
    assert user_docs.keep_decision(None)          # check unavailable: keep, admin sees it unlabelled


def test_labels_and_the_block():
    assert user_docs.parse_label(user_docs.label("SMS Manual", "4.2 Drills")) == ("SMS Manual", "4.2 Drills")
    assert user_docs.parse_label("[Company: X §1]") is None
    assert user_docs.format_block([], [], []) is None
    heads = [f"{i} Heading" for i in range(1, 46)]
    block = user_docs.format_block(
        [{"title": "SMS Manual", "pages": 42, "outline": heads}],
        [{"title": "SMS Manual", "section": "8 Emergency Preparedness", "text": "Drills are held monthly."}],
    )
    assert block.startswith("YOUR DOCUMENTS")
    assert "Attached in this conversation: SMS Manual, 42 pages. Outline: 1 Heading;" in block
    assert "(5 more)" in block
    assert "[Doc: SMS Manual §8 Emergency Preparedness]\nDrills are held monthly." in block
    assert "not attached here" not in block
    saved = user_docs.format_block([], [], [{"title": "Watch Plan", "section": "2 Bridge", "text": "Two on watch."}])
    assert "Attached in this conversation" not in saved
    assert saved.index("not attached here") < saved.index("[Doc: Watch Plan §2 Bridge]")   # flagged as loosely related


# ── upload endpoint ───────────────────────────────────────────────────────────

class UploadPool:
    def __init__(self, today=0, counted=0, tier="free"):
        self.today, self.counted, self.tier = today, counted, tier
        self.inserted = None

    async def fetchval(self, sql, *args):
        return self.today

    async def fetchrow(self, sql, *args):
        if "FROM users u" in sql:
            return {"subscription_tier": self.tier, "is_admin": False, "is_internal": False, "counted": self.counted}
        self.inserted = args
        doc_id, user_id, filename, title, mime, path, size = args
        return {"id": doc_id, "title": title, "filename": filename, "mime_type": mime, "size_bytes": size,
                "pages": None, "chunk_count": 0, "status": "pending", "error": None, "doc_type": None,
                "maritime": None, "summary": None, "kept": False, "delete_after": None,
                "created_at": datetime.now(timezone.utc)}


class _User:
    user_id = str(UID)
    email = "crew@example.com"


def _upload(pool, content: bytes, name="SMS_Manual.pdf"):
    return asyncio.run(user_documents.upload_document(user=_User(), pool=pool,
                                                     file=UploadFile(file=io.BytesIO(content), filename=name)))


@pytest.fixture
def queued(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    sent = []
    from app import tasks
    monkeypatch.setattr(tasks.process_user_document, "delay", lambda doc_id: sent.append(doc_id))
    return sent


def test_upload_saves_the_file_and_queues_it(queued, tmp_path):
    pool = UploadPool()
    doc = _upload(pool, b"%PDF-1.7 hello")
    assert doc.status == "pending" and doc.title == "SMS Manual" and doc.mime_type == user_docs.PDF
    assert queued == [doc.id]
    saved = list((tmp_path / "user_docs" / str(UID)).iterdir())
    assert [p.name for p in saved] == [f"{doc.id}.pdf"] and saved[0].read_bytes() == b"%PDF-1.7 hello"


@pytest.mark.parametrize("pool,content,code", [
    (UploadPool(today=10), b"%PDF-1.7", 429),                 # 10 uploads a day
    (UploadPool(counted=3), b"%PDF-1.7", 409),                # free plan keeps 3
    (UploadPool(), b"GIF89a....", 422),                       # not a PDF or Word file
    (UploadPool(), b"", 422),
])
def test_upload_refusals(queued, pool, content, code):
    with pytest.raises(HTTPException) as exc:
        _upload(pool, content)
    assert exc.value.status_code == code and queued == []


def test_paid_plans_keep_twenty(queued):
    _upload(UploadPool(counted=3, tier="mate"), b"%PDF-1.7")
    with pytest.raises(HTTPException) as exc:
        _upload(UploadPool(counted=20, tier="mate"), b"%PDF-1.7")
    assert exc.value.status_code == 409


def test_upload_size_cap(queued, monkeypatch):
    monkeypatch.setattr(user_docs, "MAX_FILE_BYTES", 10)
    with pytest.raises(HTTPException) as exc:
        _upload(UploadPool(), b"%PDF-1.7 more than ten bytes")
    assert exc.value.status_code == 422


# ── chat preflight ────────────────────────────────────────────────────────────

class ChatPool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        return [r for r in self.rows if r["id"] in args[1]]


def _check(rows, ids):
    from app.routers import chat
    body = chat.ChatRequestBody(query="review this", document_ids=ids)
    asyncio.run(chat._validate_documents(body, _User(), ChatPool(rows)))
    return body


def test_attached_documents_must_be_the_callers_and_ready():
    a, b = uuid.uuid4(), uuid.uuid4()
    ready = {"id": a, "title": "SMS Manual", "status": "ready", "error": None}
    assert _check([ready], [a, a]).document_ids == [a]                       # duplicates dropped
    with pytest.raises(HTTPException) as exc:
        _check([ready], [a, b])                                              # b isn't theirs
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _check([{**ready, "status": "pending"}], [a])
    assert exc.value.status_code == 409 and "Still reading SMS Manual" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        _check([{**ready, "status": "failed", "error": "This PDF has no text layer"}], [a])
    assert exc.value.status_code == 400 and "no text layer" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        _check([], [uuid.uuid4() for _ in range(4)])
    assert exc.value.status_code == 400


# ── processing and the internal check ─────────────────────────────────────────

class _Conn:
    def __init__(self, log):
        self.log = log

    async def execute(self, sql, *args):
        self.log.append(("execute", sql, args))

    async def executemany(self, sql, rows):
        self.log.append(("executemany", sql, rows))

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *exc):
                return False
        return _Tx()


class ProcessPool:
    def __init__(self):
        self.log = []

    async def fetchrow(self, sql, *args):
        return {"id": args[0], "user_id": UID, "title": "Holiday Photos", "mime_type": user_docs.PDF,
                "file_path": "/tmp/x.pdf"}

    async def execute(self, sql, *args):
        self.log.append(("execute", sql, args))

    def acquire(self):
        conn = _Conn(self.log)

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


@pytest.mark.parametrize("check,kept", [
    ({"doc_type": "sms_manual", "maritime": True, "summary": "The fleet SMS manual."}, True),
    ({"doc_type": "other", "maritime": False, "summary": "A holiday itinerary."}, False),
])
def test_processing_chunks_checks_and_decides(monkeypatch, check, kept):
    monkeypatch.setattr(user_docs, "extract_pages", lambda path, mime, max_pages: ["1 PURPOSE\nText one.", "2 SCOPE\nText two."])

    async def embed(texts, key):
        return [[0.0] * 3 for _ in texts]

    async def classify(client, title, text):
        return check

    monkeypatch.setattr(user_docs, "embed_texts", embed)
    monkeypatch.setattr(user_docs, "classify", classify)
    pool = ProcessPool()
    asyncio.run(user_docs.process_document(pool, uuid.uuid4(), "key", None))
    rows = next(e[2] for e in pool.log if e[0] == "executemany")
    assert [r[4] for r in rows] == list(range(len(rows)))                      # positions in document order
    update = next(e for e in pool.log if e[0] == "execute" and "SET status = 'ready'" in e[1])[2]
    assert update[3] == check["doc_type"] and update[6] is kept
    assert (update[7] is None) is kept                                         # delete_after only when not kept


def test_a_scanned_pdf_fails_with_the_photos_hint(monkeypatch):
    def scanned(path, mime, max_pages):
        raise UnreadableDocument("This PDF has no text layer (it looks scanned). Upload the Word version")

    monkeypatch.setattr(user_docs, "extract_pages", scanned)
    pool = ProcessPool()
    asyncio.run(user_docs.process_document(pool, uuid.uuid4(), "key", None))
    failed = next(e for e in pool.log if "status = 'failed'" in e[1])[2]
    assert "Send photos of the pages" in failed[1]


# ── answering, purge, admin ───────────────────────────────────────────────────

def test_no_documents_means_no_block_and_no_embedding(monkeypatch):
    class Empty:
        async def fetch(self, sql, *args):
            return []

    import rag.retriever as retriever

    async def boom(*a, **k):
        raise AssertionError("embedded without documents")

    monkeypatch.setattr(retriever, "_embed_query", boom)
    assert asyncio.run(user_docs.context_block(Empty(), UID, [], "key", "fire drills")) is None


def test_a_document_stays_attached_for_the_conversation():
    a, b, c, d = (uuid.uuid4() for _ in range(4))

    class Pool:
        async def fetch(self, sql, *args):
            assert "d.user_id = $2" in sql and args[1] == UID                     # only the caller's own
            return [{"id": b}, {"id": a}, {"id": c}][: args[2]]                    # most recently attached first

    conv = uuid.uuid4()
    assert asyncio.run(user_docs.conversation_documents(Pool(), conv, UID, [])) == [b, a, c]
    assert asyncio.run(user_docs.conversation_documents(Pool(), conv, UID, [d, a])) == [d, a, b]   # this question's first


def test_one_failing_document_block_keeps_the_other(monkeypatch):
    from app.routers import chat

    async def company_ctx(pool, conversation_id, key):
        async def provide(query):
            raise RuntimeError("workspace lookup failed")
        return provide

    async def conv_docs(pool, conversation_id, user_id, ids):
        return ids

    async def block(pool, user_id, ids, key, query):
        return f"YOUR DOCUMENTS for {query}"

    monkeypatch.setattr(chat, "_company_context", company_ctx)
    monkeypatch.setattr(user_docs, "conversation_documents", conv_docs)
    monkeypatch.setattr(user_docs, "context_block", block)

    async def run():
        provide = await chat._document_context(None, uuid.uuid4(), UID, [], "key")
        return await provide("fire drills")

    assert asyncio.run(run()) == "YOUR DOCUMENTS for fire drills"


def test_purge_deletes_rows_and_files(tmp_path):
    f = tmp_path / "old.pdf"
    f.write_bytes(b"%PDF")

    class Pool:
        async def fetch(self, sql, *args):
            assert "delete_after < now()" in sql and "status = 'failed'" in sql
            return [{"file_path": str(f)}, {"file_path": None}]

    assert asyncio.run(user_docs.purge(Pool())) == 2 and not f.exists()


def test_admin_text_is_audit_logged(monkeypatch):
    logged = []

    async def audit(pool, admin, action, target_id=None, details=None):
        logged.append((action, target_id, details))

    monkeypatch.setattr(admin_documents, "audit_log", audit)
    doc_id = uuid.uuid4()

    class Pool:
        async def fetchrow(self, sql, *args):
            return {"id": doc_id, "user_email": "crew@example.com", "title": "SMS Manual", "filename": "sms.pdf",
                    "doc_type": "sms_manual", "summary": "The SMS manual."}

        async def fetch(self, sql, *args):
            return [{"section": "1 Purpose", "text": "a"}, {"section": "1 Purpose", "text": "b"},
                    {"section": "2 Scope", "text": "c"}]

    out = asyncio.run(admin_documents.user_document_text(doc_id, admin=None, pool=Pool()))
    assert out.sections == [{"section": "1 Purpose", "text": "a\n\nb"}, {"section": "2 Scope", "text": "c"}]
    assert logged == [("view_user_document", str(doc_id), {"user_email": "crew@example.com", "title": "SMS Manual"})]
