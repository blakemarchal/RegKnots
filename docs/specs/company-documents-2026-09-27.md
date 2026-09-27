# Company documents in fleet chat (spec, 2026-09-27)

**Goal:** a fleet uploads its own SMS / TSMS manual and procedures. Chat then answers from the
regulations *and* the company's own procedures, citing both, and says when a procedure is
stricter than, differs from or doesn't cover what the regulation requires.

**Why:** it's the one source a general model can't know, and the reason a fleet pays per
vessel. It also keeps customers, because their manuals live here. It is also where retrieval
can't be replaced.

## v1 scope

- **Who:** workspace owners and admins upload and delete. Every chat in that workspace uses the
  documents. Wheelhouse plan only.
- **Files:** PDF with a text layer, DOCX, TXT/MD. Up to 25 MB each, 20 per workspace. A scanned
  PDF with no text is refused in v1 with a clear message.
- **Storage:** originals under `upload_dir/workspace_docs/<workspace_id>/`. Text chunks and
  embeddings go in new tables, **never** in `regulations`, so one fleet's manual can never
  surface in another fleet's chat.
- **Processing** (Celery worker): extract text locally (pdfplumber / python-docx), split at
  headings, chunk with the ingest chunker, embed with text-embedding-3-small. Status goes
  pending → ready / failed. A 500-page manual costs about half a cent in embeddings.
- **Retrieval:** for a chat bound to a workspace, a separate lane returns the 6 chunks nearest
  the question among that workspace's chunks (an exact scan filtered by `workspace_id`). They are
  added as a "COMPANY DOCUMENTS" block after the regulation excerpts.
- **Prompt rule:** company procedures are the company's own requirements, and regulations are
  the legal minimum. Say when a procedure is stricter, different, or silent. Never present a
  company procedure as law.
- **Citations:** `[Company: <title> §<heading>]`, rendered as a distinct chip. Tapping it shows
  the excerpt through a members-only endpoint.
- **UI:** a "Company documents" section on the workspace page: upload, list (title, pages,
  status, who uploaded and when) and delete.
- **Security:** the workspace comes from the conversation server-side, membership is checked on
  every read, deletion removes the file and its chunks, and uploads and deletions are
  audit-logged.

## Schema (migration 0117)

- `workspace_documents`: id, workspace_id (FK, cascade), uploaded_by, filename, title,
  mime_type, file_path, size_bytes, pages, chunk_count, status (pending / ready / failed),
  error, created_at.
- `workspace_document_chunks`: id, document_id (FK, cascade), workspace_id (indexed), section,
  chunk_index, text, embedding vector(1536), created_at.

## Cost

Embeddings only. Each workspace answer carries about 2–3K more input tokens, roughly $0.01 at
Opus input prices.

## Tests

- Text extraction and chunking.
- Isolation: a chat in workspace A never retrieves workspace B's chunks.
- Upload validation and plan gating.
- Prompt assembly with and without company documents.

## Out of scope (v2 candidates)

- OCR of scanned manuals.
- Scoping a document to specific vessels.
- Versioning.
- **Automatic gap analysis:** each company procedure checked against the regulation it
  implements. This one is a strong upsell.

## Effort

About two days.
