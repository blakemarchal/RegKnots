# Notification System — Known Issues & Follow-up Work

**Captured:** 2026-04-18 during Sprint B2 (USCG bulletin filter rewrite).

The following issues surfaced when auto-generated ingest notifications
appeared in the user-facing notification panel as active banners. They
are all non-blocking for ongoing ingest work but are worth addressing
before the next major user-facing launch — notifications are currently
a source of alarm without being actionable.

---

## Issue A — CFR weekly updates over-trigger on routine eCFR republishing

### Observation

The Sunday 02:00 UTC scheduled `update-regulations-weekly` task ran on
2026-04-19 and generated three banner notifications:

- "CFR Title 33 Updated — 5,124 sections updated with revised language"
- "CFR Title 46 Updated — 8,543 sections updated with revised language"
- "CFR Title 49 Updated — 9,955 sections updated with revised language"

Total: **23,622 CFR sections** flagged as updated in a single week.

### Root cause

Change detection in `packages/ingest/ingest/pipeline.py:208-210` is a
set difference of content hashes:

```python
existing_hashes = await store.get_existing_hashes(pool, source)
new_hashes = {c.content_hash for c in all_chunks}
result.new_or_modified_chunks = len(new_hashes - existing_hashes)
```

`content_hash = sha256(chunk_text)` where `chunk_text` prefixes every
chunk with `[section_number] section_title\n\n{body}`. eCFR republishes
entire CFR titles every week with:

- Metadata timestamps (publication date, amendment cycle ref) in
  section headers
- Whitespace / paragraph-break normalization from XML → text rendering
- Occasional attribute reordering in the source XML that changes our
  parser's output text

Any of these produce a new `chunk_text` → new hash → "modified" count.
Substantive regulatory changes (amendments that actually change what a
mariner must do) are probably in the hundreds per week, not thousands.
Our current signal is ~30-50× inflated.

### Impact

- Users see banner notifications claiming massive regulatory upheaval
  when none occurred. Undermines the notification channel's credibility.
- Email digests built on this signal would be equally noisy.
- Pilot users who opted in to immediate email alerts (`reg_alert_sources`)
  could get spammed weekly.

### Options for the fix (future sprint)

1. **Normalize before hashing.** Strip all non-substantive whitespace
   and boilerplate timestamps from `chunk_text` before computing
   `content_hash`. Store both raw and normalized hashes; use normalized
   for change detection, raw for the upsert dedup.
2. **Threshold gating.** Suppress the notification when
   `new_or_modified_chunks / total_chunks_for_source > 0.15` AND
   `net_chunk_delta == 0`. The signal is essentially "bulk republish
   without real changes."
3. **Diff-before-notify.** When change count is high, pick 5 random
   "modified" sections, compare old vs new content with a char-level
   diff, and only count those whose substantive content changed. Emit a
   more accurate count.

Option 1 is the most principled. Option 2 is a one-line heuristic.
Option 3 is overkill for v1.

---

## Issue B — Notifications do not cascade on content rollback

### Observation

Sprint B created a `uscg_bulletin updated — 3,482 new sections added`
notification (id `b5d845af-af8f-4783-a318-2beb101b764e`) when the
initial ingest landed. The subsequent
`DELETE FROM regulations WHERE source='uscg_bulletin'` rollback wiped
the chunks but left the notification row alive and active. The next
time a user logged in, the banner pointed at a dataset that no longer
existed. Cleaned up manually during Sprint B2.

### Root cause

`notifications` and `regulations` live in the same database but have no
foreign-key relationship. There is no cascade rule or application-level
hook tying notification lifecycle to its source's data lifecycle.

### Fix for future rollback operations

Whenever rolling back an ingest, also deactivate or delete any
notifications that reference that source and were created after the
rollback timestamp. Safe pattern to add to the manual rollback
playbook:

```sql
BEGIN;
DELETE FROM regulations WHERE source = 'uscg_bulletin';
DELETE FROM notifications
 WHERE notification_type = 'regulation_update'
   AND source = 'uscg_bulletin'
   AND created_at > NOW() - INTERVAL '24 hours';
COMMIT;
```

Adjust the interval based on when the bad ingest ran. For a more
durable fix, consider a `notifications.regulations_source_active`
denormalized column checked on retrieval — but that's overkill for the
current volume.

---

## Issue C — New notifications appear `is_active=true` by default

### Observation

Every auto-generated regulation_update notification pops up as an
active banner on the next user login. Users must manually deactivate
each one to clear the screen. Over time, the in-app notification list
accumulates a permanent history of every weekly CFR update.

Behavior is controlled by `packages/ingest/ingest/notify.py:251` which
inserts with `is_active = true` unconditionally.

### Options

1. **Default-off for regulation_update notifications.** Insert with
   `is_active = false`. Surface them in a dedicated "Regulation
   Updates" tab (or the existing Reference page). Users opt into active
   alerting via `notification_preferences.reg_alert_sources`.
2. **Auto-archive after N days.** Background job marks any
   `regulation_update` older than 14 days as `is_active = false`.
   Users who didn't log in during that window see a single "23 updates
   pending review" rollup.
3. **Collapse by source.** Only one active `regulation_update`
   notification per source at a time. A new one on the same source
   supersedes the prior one, which transitions to `is_active = false`.

Option 3 (collapse-per-source) is the most surgical. It matches user
expectation ("there's one regulatory-alert banner for each thing I
care about, not a running history") and requires only a short SQL
trigger or an app-level check in `create_regulation_update_notification`.

---

## Priorities for future sprint

- **Issue C** is pure UX — ~30 min to fix, big visible improvement.
- **Issue A** is the most impactful — makes the notification channel
  actually trustworthy. Estimate: half a sprint.
- **Issue B** is a process fix — add the two-line SQL to the rollback
  runbook, revisit if we ever build an automated rollback tool.
