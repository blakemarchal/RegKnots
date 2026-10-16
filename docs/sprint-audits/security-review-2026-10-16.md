# Security review, 2026-10-16

**Source:** a code-read review from another Claude session ("Job application material research"). This thread owns the follow-up.

**Method:** every item was verified here by reading the code and running read-only SQL on prod. Nothing was exercised against prod.

## Status

| # | Finding | Verified | Priority | Status |
|---|---|---|---|---|
| 1 | Document preview attach: `preview_id` is a free string passed to `glob`, with no owner check | **Yes, and worse than reported** | **P0** | Fix built and tested; awaiting deploy go |
| 2 | No rate limits on login, register, forgot / reset password, extraction, transcription | Yes | P1 | Planned |
| 3 | Changing or resetting the password doesn't revoke refresh tokens | Yes | P1 | Planned |
| 4 | Register accepts any password length (the API has no minimum; the web form has `minLength=8`) | Yes | P1 | Planned |
| 5 | `environment` defaults to `development`; the default JWT secret isn't refused at startup | Yes | P1 | Planned |
| 6 | Privacy page is inaccurate or incomplete | Yes | P1 | Wording needs Blake's go |
| 7 | Hardening items (see below) | Mostly yes | P2 | Planned / decisions |

## 1. Preview attach (P0)

**The code:** `POST /vessels/{id}/documents/from-preview` checked that the caller owns the vessel. It then ran `Path(upload_dir)/"_previews".glob(f"{preview_id}.*")` and `rename`d the first match into that vessel's folder.

**What the local test showed** (Python 3.13; prod runs 3.12.3):

- `glob` follows `../` and matches dotfiles.
- `"*"` took any user's unattached preview.
- `"../<vessel_id>/*"` took another vessel's document.
- From the prod previews folder (`/opt/RegKnots/data/uploads/documents/_previews`), `../../../../*` reaches `/opt/RegKnots/`, where `.env` is. The API runs as **root**.

**Impact:**

- There is no file-download route.
- An attacker could move another user's preview or document into their own vessel and read it back through "retry extraction" (vision extraction returns its fields).
- They could also move server files, including `.env`, which takes the service down on its next restart.

**No sign of use on prod:**

- Every `vessel_documents.file_path` matches `<upload_dir>/<vessel uuid>/<uuid>.<ext>`.
- There are no `from-preview` requests in the retained API logs.
- `.env` is in place.
- 9 unattached previews are on disk.

**Fix** (`routers/documents.py`, `tests/test_document_preview.py`):

- `preview_id` is a UUID, so `*` and `../` get a 422.
- Previews are saved per user under `_previews/<user_id>/`.
- Attach looks only in the caller's folder, by exact filename, and checks that the resolved path stays inside it.
- The daily purge task deletes previews older than 48 h, including the old flat files.
- The web already sends back the UUID the server issued, so no web change is needed.

## 2–5. Auth (P1)

2. **Rate limits:** add Redis counters.

   | Endpoint | Limit |
   |---|---|
   | Login | 10 per 15 min per email and per IP |
   | Register | 10 per hour per IP |
   | Forgot-password | 3 per hour per email, 10 per IP |
   | Reset-password | 10 per hour per IP |
   | Extraction / transcription | Per-user daily caps |

   **Decision for Blake: what happens when Redis is down.**
   - Fail closed: nobody can log in.
   - Fail open: no limit at all.
   - Recommended: fall back to an in-process counter instead of either.
3. **Token revocation:** a password change revokes every other refresh token and issues a fresh cookie. A reset revokes all of them.
4. **Password length:** `RegisterRequest.password` gets the same 8-character minimum as change and reset.
5. **Startup guard:**
   - Prod sets `REGKNOTS_ENVIRONMENT=production` (checked).
   - Add: the API refuses to start when the environment isn't `development` and the JWT secret is the default.
   - Recommended: make `production` the default and set `development` in the local `.env`.

## 6. Privacy page (P1, wording needs Blake's go)

- **Passwords:** the page says bcrypt; the code uses Argon2 (`app/auth/service.py`).
- **OpenAI:** listed only for indexing. It also answers when Claude is unavailable (the fallback) and transcribes voice input (Whisper).
- **Sentry:** error reports aren't mentioned.
- **Credential scans:** passports, TWIC, drug tests and similar are sent to Anthropic for extraction (`routers/credentials.py`). Not mentioned.

## 7. Hardening (P2)

- **Sentry:** no `before_send` scrubbing, server or web. Add one that drops auth headers, cookies and request bodies.
- **Uploads:**
  - They trust the browser's MIME type and read the whole file before checking its size.
  - Fix: sniff the content type (as `/me/documents` already does), and stream with a cap.
- **Admin audit:**
  - `admin_audit_log.admin_user_id` cascades on delete (migration 0041); change it to SET NULL and keep `admin_email`.
  - `audit_log()` swallows write failures.
  - Viewing a user's chat isn't audited.
  - The table browser shows `credential_number`; mask it.
- **Backups:**
  - The nightly `pg_dump` is compressed but not encrypted.
  - Uploads aren't backed up.
  - The offsite copy waits on Blake's DO Spaces bucket and keys.
  - Plan: encrypt with `age`, and add an uploads tarball.
- **Account deletion vs the privacy page:** question text outlives the account in tables whose `user_id` is SET NULL:
  - `retrieval_misses`
  - `hedge_audits`
  - `corpus_gaps`
  - `off_topic_queries`
  - `current_events_responses`
  - `tier_router_shadow_log`

  The page says "When you delete your account, its data is deleted with it." Proposed: on deletion, scrub the question and answer text in those rows, keeping the counts. **Blake's call.**
- **Chat images** are stored as base64 in `messages.image_attachments`, outside any purge. They go with their conversation; decide on a retention.
