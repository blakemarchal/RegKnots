# Cowork Scheduled-Task Prompts — RegKnot

Copy/paste these into Cowork when creating the scheduled tasks. They are written to be **self-contained and unambiguous** because a scheduled task has no opportunity for mid-run clarification — whatever the prompt says is what runs every week.

**Boundary reminder (applies to every task below):** Cowork NEVER writes to the RegKnot repo (`C:\Users\Blake Marchal\Documents\RegKnots\` except for `data/raw/` subfolders explicitly listed). Cowork does NOT classify bulletins for ingest purposes — only descriptive labels for summary docs. Canonical MSIB/ALCOAST/NMC classification lives in `packages/ingest/sources/uscg_bulletin.py` and runs at ingest time.

---

## Task 1 — GovDelivery inbox → ingest staging

**Name:** `RegKnot — GovDelivery weekly staging`
**Schedule:** Every Monday at 0700 America/Detroit
**Connectors required:** Gmail, Local Filesystem (scoped to `C:\Users\Blake Marchal\Documents\RegKnots\data\raw\uscg_bulletins\`)

### Prompt

```
You are staging USCG GovDelivery bulletin emails for a weekly ingest run. You do NOT classify, summarize, or interpret regulatory content — you only move files into a folder the ingest pipeline will process.

STEP 1 — Read Gmail.
Search for emails received in the past 7 days where the sender contains "govdelivery.com" OR the subject contains one of: "MSIB", "ALCOAST", "NMC Announcement", "Safety Information Bulletin", "Navigation and Vessel Inspection Circular". Include items in the Primary inbox, Updates tab, and Promotions tab. Do NOT read items older than 7 days — the ingest pipeline has already processed those.

STEP 2 — For each matching email:
  (a) Create the subfolder "C:\Users\Blake Marchal\Documents\RegKnots\data\raw\uscg_bulletins\incoming\<YYYY-MM-DD>\" if it does not exist, where <YYYY-MM-DD> is today's date in ISO format.
  (b) Download every PDF attachment into that folder. If filenames collide, prefix with a zero-padded index like "01_<originalname>.pdf".
  (c) If the email body contains bulletin URLs (look for links to https://content.govdelivery.com/... or https://www.navcen.uscg.gov/... or https://www.dco.uscg.mil/...), capture those URLs — do NOT follow them to download additional content, just record them in the manifest.

STEP 3 — Write a manifest file named "manifest.json" at the root of that same <YYYY-MM-DD>/ folder. Structure:
[
  {
    "email_message_id": "<Gmail message id>",
    "received_at": "<ISO 8601 datetime>",
    "sender": "<from address>",
    "subject": "<exact subject line>",
    "descriptive_label": "<one of: msib | alcoast | nmc_announcement | other — this is a NON-AUTHORITATIVE label for the weekly summary doc only; the ingest pipeline will reclassify>",
    "body_urls": ["<captured URL>", "..."],
    "attached_files": ["<relative filename 1>", "..."]
  },
  ...
]

If there were zero matching emails this week, still create the dated folder AND write an empty array "[]" to manifest.json so the absence of output is explicit, not ambiguous.

STEP 4 — Do NOT trigger ingest. Do NOT edit any file outside "C:\Users\Blake Marchal\Documents\RegKnots\data\raw\uscg_bulletins\incoming\". Do NOT delete or modify source emails. Do NOT run git commands. Do NOT write to other RegKnot folders.

STEP 5 — Email Blake (blakemarchal@gmail.com) with subject "RegKnot staging — <YYYY-MM-DD>" and a 2-line body: total emails processed, total PDFs downloaded, and the absolute path of the staging folder. No other content.

Hard stop: if ANY step fails (folder creation, download, manifest write, permissions), stop immediately and email Blake with the failure. Do not attempt to recover by restarting — partial runs are worse than no runs because they create ambiguous state for the ingest pipeline.
```

---

## Task 2 — Weekly RegKnot ops one-pager for Karynn

**Name:** `RegKnot — weekly ops one-pager`
**Schedule:** Every Monday at 0800 America/Detroit (runs AFTER Task 1)
**Connectors required:** Gmail, Local Filesystem (read-only access to `C:\Users\Blake Marchal\Documents\RegKnots\data\raw\`), GitHub (read-only), Google Drive

### Prompt

```
You are composing a weekly internal ops one-pager for Karynn Marchal, CEO and co-founder of RegKnot. The document is an internal coordination artifact, not a pilot-facing communication. Keep it to one page, factual, no marketing voice.

STEP 1 — Collect inputs (read-only; do not modify any of these sources):
  (a) Gmail — count USCG GovDelivery emails received in the past 7 days. Group by descriptive label: MSIB, ALCOAST, NMC Announcement, other. List up to 5 most recent subject lines under each group. Note: these labels are descriptive, not authoritative — the ingest pipeline does the real classification.
  (b) Local filesystem — list files added or modified in "C:\Users\Blake Marchal\Documents\RegKnots\data\raw\" (recursive, but exclude anything under a "node_modules", ".git", or "__pycache__" path) within the past 7 days. Group by immediate subdirectory under data/raw/. Show filename + size + mtime.
  (c) GitHub — for the repository blakemarchal/RegKnots on the main branch, list commit subjects (first line only) from the past 7 days. Exclude merge commits whose subject starts with "Merge ". Show commit short-hash + subject + author date.
  (d) Local filesystem — check if a file "data/metrics/weekly-<YYYY-MM-DD>.csv" exists (where the date is any date in the past 7 days). If yes, read DAU, messages_per_user, checklist_edit_rate from the most recent such file and include those three numbers verbatim. If no such file exists, write "Ops metrics export not present this week" and move on — do NOT invent numbers, do NOT reach for any other data source.

STEP 2 — Compose a Google Doc titled exactly "RegKnot weekly — <YYYY-MM-DD>" (today's date in ISO format) with this structure:

  # RegKnot weekly — <YYYY-MM-DD>
  ## Regulatory intake this week
  <content from 1a — counts + subject lines>

  ## Code + data changes
  ### Repo commits
  <content from 1c>
  ### Data folder additions
  <content from 1b>

  ## Product metrics
  <content from 1d>

  ## Notes from Cowork
  <1-3 bullet points of anything unusual the task noticed: e.g., "Zero GovDelivery emails this week — check Gmail filter rules" or "Unusually high data/raw/ churn — 47 new NMC PDFs" or "No commits since <date>". Factual only, no speculation about reasons.>

STEP 3 — Share the doc with Karynn (use her email; if Blake has not provided it as an environment-variable or saved preference yet, email Blake asking for Karynn's email and DO NOT create or share the doc until Blake replies). Share with "Anyone with the link — Viewer" access. Do NOT grant edit access. Do NOT share publicly.

STEP 4 — Email Blake (blakemarchal@gmail.com) with subject "RegKnot weekly — <YYYY-MM-DD> — sent" and a 1-line body containing the shareable Google Doc URL.

Hard stop: if you cannot access any of the four input sources (Gmail, filesystem, GitHub, Drive), do NOT produce a partial document. Email Blake describing which source failed and why, and abort.
```

---

## Task 3 — `data/raw/` folder hygiene (future, not yet scheduled)

Deferred until Tasks 1 and 2 have run cleanly for two weeks. See roadmap §5.3 for scope.

---

## How to add these to Cowork

1. Open Cowork, go to **Scheduled Tasks** (sidebar).
2. Click **New scheduled task**.
3. Paste the prompt from inside the triple-backtick block (not the meta info above it).
4. Set the schedule (Mon 0700 for Task 1, Mon 0800 for Task 2, both America/Detroit).
5. Confirm the required connectors are listed and authorized.
6. Run once manually via **Run now** to verify before letting the schedule take over. If the first manual run fails or produces unexpected output, fix the prompt before leaving it scheduled — a broken scheduled task will silently corrupt the `incoming/` staging folder week after week before anyone notices.

## Review cadence

- After week 1 manual run: verify the `<YYYY-MM-DD>/manifest.json` is well-formed and the Google Doc is coherent.
- After week 2 scheduled run: verify no drift in folder naming, no duplicate files, no missing PDFs.
- After week 4: if clean, move on to Task 3.
- After week 8: revisit whether V2 (Resend webhook) is now warranted.
