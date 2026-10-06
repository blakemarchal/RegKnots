# PDF and Word uploads in chat (spec, 2026-10-05)

**Status: shipped 2026-10-05** (migration 0121; deployed `6be8d6d`). Blake, 2026-10-05: "it
makes sense to add PDF uploads. We can run an internal check on the doc and save it to their data
if it's useful to help us give them better answers and train on." His answers to the open
questions: the privacy wording as proposed, non-maritime documents deleted after 7 days, the
limits as proposed, and admins may open a document's text (audit-logged).

**Changed while building:** a document stays attached for the rest of the conversation it came in
(a follow-up such as "and the drill section?" is about the document already on the table), so a
non-maritime document serves its conversation, not only its first question. Passages from other
kept documents are introduced to the model as possibly loosely related. The 0.45 similarity floor
was measured on prod with a 10-page document: relevant questions scored 0.57–0.72, a generic
question 0.38–0.44, a different maritime topic 0.29–0.33, an unrelated one 0.01–0.04.

**Why:** a crew member asked RegKnot to review their ship's SMS emergency procedure and asked
"i can not attach our manual?" (2026-10-06). In chat the paperclip takes photos only (JPEG, PNG,
WebP); a whole manual can only go in as a company document in a Wheelhouse workspace, which an
individual mariner doesn't have. A user's own documents are the one source a general model
can't know, and they keep the user coming back.

## v1 scope

- **Who:** any signed-in user, in their own chats (workspace chats keep company documents as
  they are; a file attached there stays the user's own, not the fleet's).
- **Files:** PDF with a text layer and DOCX, up to 25 MB and 300 pages each. A scanned PDF (no
  text layer) is refused with "send photos of the pages instead"; OCR is v2 (tesseract is on the
  VPS, but ~5 s a page is too slow to wait on).
- **Attach flow:** the paperclip also accepts PDF and DOCX. The file uploads as soon as it is
  picked (`POST /me/documents`, multipart). The chip shows "Reading SMS-Manual.pdf (42 pages)…"
  and the send button waits for it to be ready (seconds for a text PDF). The message carries the
  document ids.
- **Answering with it:** for a question with a document attached, the engine adds a YOUR
  DOCUMENTS block: the document's section outline (headings) and the 8 chunks nearest the
  question. The prompt rule is the company-documents one: the user's document is their own
  procedure, the regulations are the legal minimum; say where the document is stricter,
  different or silent, and never present it as law.
- **Saved to their account, if useful:** after processing, an internal check (below) labels the
  document. A maritime document (SMS manual, procedure, checklist, certificate, form, letter from
  a flag or the Coast Guard) is kept: later questions in any of the user's chats consult it,
  through a lane that returns its 4 nearest chunks when they are close enough (similarity floor,
  so an unrelated question isn't padded with manual text). A document the check finds not
  maritime is used for the question it came with and deleted after 7 days.
- **Account page:** "My documents" lists each document (title, pages, type, kept or not, when),
  with delete. Deleting removes the file, its chunks and embeddings.
- **Citations:** `[Doc: <title> §<section>]`, a distinct chip; the excerpt opens through an
  owner-only endpoint.

## The internal check

At processing time, on every document:

1. **Safety and quality:** magic bytes match the type; size, pages, encryption; the share of
   pages with real text (a scan or a garbled text layer is refused, not half-read). The file is
   only ever parsed for text server-side and never served to anyone but its owner.
2. **Classification:** the small model (Haiku 4.5, `SIDECAR_MODEL`) reads the first ~3K tokens
   and returns structured `{doc_type, maritime, vessel_name, flag, company, summary}`. About
   $0.002 a document.
3. **Decision:** keep when maritime and doc_type isn't "other"; otherwise transient.

Admin: a Documents page lists uploads (user, file, pages, type, maritime, summary, kept, status).
That is where "train on" happens: we see which documents mariners bring, which questions they
ask about them, where answers fell short, and which public sources the corpus is missing. Opening
a document's text from admin is audit-logged. **A user's document never reaches another user**:
chunks live in their own tables (never `regulations`), every read is filtered by owner, and
nothing from a user's document is ingested into the shared corpus.

## Schema (migration 0121)

- `user_documents`: id, user_id (FK, cascade), filename, title, mime_type, file_path, size_bytes,
  pages, chunk_count, status (pending / ready / failed), error, doc_type, maritime, summary,
  kept, delete_after, created_at, last_used_at.
- `user_document_chunks`: id, document_id (FK, cascade), user_id (indexed), section,
  chunk_index, text, embedding vector(1536), created_at.
- `messages.document_ids uuid[]`: the documents attached to a message (history shows the chips).

Separate tables from the workspace ones on purpose: the isolation rule stays one-owner-per-table,
and the shipped company-documents tables aren't touched. Extraction, sectioning, chunking and
embedding reuse `app/company_docs.py` as it is (`extract_pages`, `split_sections`,
`chunk_sections`, `embed_texts`).

## Privacy (Blake to approve the wording)

The privacy page doesn't list uploaded documents, and it names Anthropic but not OpenAI, which
already embeds every question. Proposed additions:

- What we collect: "**Documents you upload:** files you attach in chat, such as manuals or
  procedures."
- How we use it: "Documents you upload are used to answer your questions. If a document is
  relevant to your work, we keep it in your account so later answers can use it, and we may
  review it to improve RegKnot. We never show your documents to other users or use them to
  answer anyone else's questions. You can delete any document at any time in Account settings."
- Data sharing: "**OpenAI:** text from your questions and documents is sent to OpenAI's API to
  index it for search."

## Limits and cost

- 3 kept documents on the free plan and trial, 20 on paid plans (old ones can be deleted).
- Embeddings: about half a cent for a 500-page manual. Classification: ~$0.002 a document.
- Answers with a document attached carry 2–4K more input tokens, ~$0.01–0.02 at Opus prices.

## Tests

- Validation: type sniffing, size and page caps, encrypted and scanned PDFs refused.
- Isolation: user A's chats never retrieve user B's chunks; workspace chats unchanged.
- The check: keep / transient decisions; transient documents are deleted after 7 days.
- Prompt assembly with and without documents; citation chips and the owner-only lookup.
- Account deletion removes the files (`app/account_deletion.py` already clears `upload_dir`).

## Out of scope (v2)

- OCR of scanned PDFs (background, with progress).
- Attaching a document straight into a Wheelhouse workspace as a company document.
- Comparing a whole manual against the regulations section by section (the company-documents
  "gap analysis" idea, for one user's manual).

## Effort

About two to three days, most of it the attach flow in the web client and the account page.

## Decisions (Blake, 2026-10-05)

1. The privacy wording above: yes (shipped with "no other user can open them", since admins can).
2. Not-maritime documents: deleted after 7 days.
3. Limits: 3 kept documents on free and trial, 20 on paid.
4. Admins can open a document's text for review, audit-logged.
