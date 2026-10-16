# Security review, 2026-10-16

**Source:** a code-read review from another Claude session ("Job application material research"). This thread owns the follow-up.

**Method:** every item was verified here by reading the code and running read-only SQL on prod. Nothing was exercised against prod.

## Status

| # | Finding | Verified | Priority | Status |
|---|---|---|---|---|
| 1 | Document preview attach: `preview_id` is a free string passed to `glob`, with no owner check | **Yes, and worse than reported** | **P0** | **Shipped** `8481878` |
| 2 | No rate limits on login, register, forgot / reset password, extraction, transcription | Yes | P1 | **Shipped** `61b9877`, `74c58c6` |
| 3 | Changing or resetting the password doesn't revoke refresh tokens | Yes | P1 | **Shipped** `61b9877` |
| 4 | Register accepts any password length (the API has no minimum; the web form has `minLength=8`) | Yes | P1 | **Shipped** `61b9877` |
| 5 | `environment` defaults to `development`; the default JWT secret isn't refused at startup | Yes | P1 | **Shipped** `61b9877` |
| 6 | Privacy page is inaccurate or incomplete | Yes | P1 | **Shipped** `61b9877` (Blake's go) |
| 7 | Hardening items (see below) | Mostly yes | P2 | **Shipped** `61b9877`; offsite needs Blake's keys |

**All deployed 2026-10-16.** Migrations 0127 and 0128 applied.

Checked on prod after the deploy:
- Eleven failed logins for one address got 401 ten times, then 429.
- The Redis keys hold only hashes. The probe's keys were deleted afterwards.
- The `admin_audit_log` foreign key is `ON DELETE SET NULL`.
- The API started past the new startup guard.

## What shipped (2026-10-16)

- **Rate limits** (`app/ratelimit.py`): Redis fixed windows, created with SET NX EX and INCR in one pipeline. When Redis is down, an in-process counter takes over (one API worker): limits stay on, and sign-in still works.

  | Endpoint | Limit |
  |---|---|
  | Login | 10 per 15 min per email, 30 per IP |
  | Register | 10 per hour per IP |
  | Forgot-password | 3 per hour per email, 10 per IP |
  | Reset-password | 10 per hour per IP |
  | Change password | 10 per hour per user |
  | Document and credential scans | 30 a day per user |
  | Voice input | 100 a day per user |

- **Sessions:**
  - A password change deletes the user's refresh tokens and gives the current device a fresh one. A reset deletes them all.
  - They are deleted, not marked revoked, because `/auth/refresh` treats a revoked token as a replay and would also end the fresh session.
- **Register:** 8-character minimum, the same as change and reset.
- **Startup guard:**
  - `environment` now defaults to `production`; the local `.env` sets `development`.
  - Outside development, the API refuses to start with the default or a short JWT secret.
- **Privacy page:**
  - Argon2, not bcrypt.
  - OpenAI also transcribes voice input and answers when Anthropic is unavailable.
  - Credential and document scans go to Anthropic.
  - Sentry is listed.
  - Usage counts survive deletion without the user's words; backups are kept 14 days.
- **Uploads** (`app/uploads.py`):
  - Chunked reads stop at the cap.
  - Image, PDF and audio types are read from the bytes, not the browser's claim. This covers vessel documents and previews, credentials and voice.
- **Sentry:**
  - The API sends no request bodies, query strings, cookies, auth headers or user emails.
  - The web drops the same, and runs URLs and breadcrumbs through the analytics URL scrubber (`lib/sentryScrub.ts`).
- **Admin:**
  - Credential numbers show only their last 4 characters in the table browser and are no longer searchable.
  - Opening a user's conversation (`/admin/chats/{id}`) writes `view_conversation` to the audit log.
  - Audit rows survive an admin's deletion (migration 0127).
  - `audit_log()` still never raises, but a failure is logged with `logger.exception`, which reaches Sentry.
- **Account deletion:** the user's questions, answers and model reasoning are blanked in the six logs that keep their rows, inside the deletion transaction (`account_deletion.SCRUB_SQL`).
- **Backups:**
  - The nightly run also archives `data/uploads` (65 MB today), with an integrity check and the same 14-day retention.
  - `backup_offsite.sh` encrypts every file with `age` to a public key before upload, and refuses to upload anything until that key exists.
  - Tested on the VPS with stand-in `age` and `rclone`: it refuses with no key, then encrypts, syncs and verifies; a rerun encrypts nothing new; a pruned backup leaves offsite too.
- **Not changed:** chat images stay base64 in `messages.image_attachments` and go with their conversation. No retention rule was decided.

## Blake's remaining step (offsite backups)

The header of `scripts/backup_offsite.sh` lists the steps, about 10 minutes:

1. A DigitalOcean Spaces bucket and keys.
2. `apt-get install -y rclone age` on the VPS.
3. The rclone config.
4. On your laptop, `age-keygen -o regknots-backup.key`. Keep that file in your password manager: it is the only way to read the offsite copies. Copy only the public key to `/etc/regknots/backup-age.pub`.
5. Enable the timer.

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
