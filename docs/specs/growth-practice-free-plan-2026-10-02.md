# Growth: free exam practice, a free plan, wider outreach, NGA manuals (2026-10-02)

Blake, 2026-10-02: "Greenlight all 3." This covers what shipped and the knobs.

## Why

- Distribution is the bottleneck, not answer quality: 0 external signups since 2026-09-20,
  1 user active in 30 days, 15 cold emails sent with no reply (read-only SQL and the
  outreach log, 2026-10-02).
- About 1 in 5 researched towing companies publishes an email address (43 `no_contact` of
  ~60), and the lead list was the Army Corps' 2017 operator file.
- Study Tools sit behind the paywall, so the exam-prep audience has never been tested.
- Blake: market to individual mariners "not necessarily to convert them, but simply to get
  more data", and test whether exam prep is a vertical general AI hasn't already taken.

## 1. Free practice page and the free plan

**`/practice`** (public, no sign-up). The questions are the NMC's own published sample
exams (public domain), parsed into `exam_questions` by `packages/ingest/ingest/exam_questions.py`
and served by `GET /practice/topics` and `GET /practice/quiz?topic=&n=&exam=`
(`apps/api/app/routers/practice.py`).

- One row per question: pool, part, exam level, topic, stem, choices, the answer key.
  Questions that need an illustration, a training chart or a reference book
  (`needs_figure`) are kept and not served.
- A question printed in several sample exams counts and serves once (stem plus choices).
- Each servable question carries its nearest corpus section (OpenAI embedding of stem plus
  correct answer, computed once). The page shows it only at similarity ≥ 0.55
  (`RELATED_MIN_SIMILARITY`). An NGA manual is labelled "Read more", a regulation "The
  rule behind it".
- Each quiz served adds a `practice_quiz_starts` row (topic only: no user, no IP).
- Sign-up links carry `src=practice`; a visitor who arrived from an outreach link keeps
  that first touch.
- Topics: the NMC file names, through `nmc_exam_bank._classify`. The nine QMED rating exams
  (q800–q808) and four deck files were uncategorized until this change; they now map to a new
  `qmed` topic and to the deck topics.
- Loading: `scripts/run_ingest.sh --module ingest.exam_questions` (about $0.02 of OpenAI
  embeddings). Re-run after the NMC files change; rows a re-parse no longer yields are deleted.

**Free plan** (`apps/api/app/free_plan.py`). After the 7-day / 50-message trial, a free
account keeps `REGKNOTS_FREE_PLAN_MONTHLY_CAP` questions (default 10) per 30-day cycle
instead of the paywall, while this month's free-plan answers stay under
`REGKNOTS_FREE_PLAN_GLOBAL_MONTHLY_CAP` (default 500). Either set to 0 restores the old
paywall.

- The global cap is the spend guard: at ~$0.05–0.13 an answer (Opus 5.5 low, cached
  prompt), 500 answers is roughly $25–65 a month at most.
- Workspace (fleet) conversations, admins and internal accounts never count.
- A 402 says why: the cycle's questions are used (with the reset date), or this month's
  free pool is used (back on the 1st).
- `/billing/status` adds `free_plan` and `free_plan_paused`; the `monthly_*` fields carry
  the cycle's cap, used, remaining and reset date. A user who used the 50 trial messages
  before day 7 reads as trial over.
- Web: a chat banner, the pricing header and Free card, the landing line, the account page,
  the support FAQ and the trial-ending email.

**Measuring it.** `/admin` → "Free practice · free plan": quizzes in 7 and 30 days, signups
from /practice (`signup_source = 'src:practice'` or a `/practice` landing path), and free-plan
answers this month against the cap. Needs attention fires at 80% of the cap.

## 2. Outreach

`scripts/outreach/`:

- `build_leads.py --source mvus --file vesdocSep26Rtab.zip`: towing companies from the USCG
  vessel documentation file (Merchant Vessels of the US, monthly). Current documents, a
  company owner (personal names are redacted in the file), longest towing vessel ≥ 40 ft,
  up to 40 boats. 991 new leads; 243 existing rows confirmed. The file has no phone numbers.
- `--source nmc-courses --file courses.pdf`: 145 schools from NMC's approved-course list that
  teach a license, endorsement or STCW course. Niche `school`, offered the practice page.
- `--source tpo`: the six Coast Guard-approved Subchapter M TPOs (TVNCOE list). Niche
  `tpo`, a partnership note.
- `gmail_draft.py`: an `offer` per email: `fleet` (towing, the fleet trial), `practice`
  (schools), `partner` (TPOs).
- `call_list.py` → `data/outreach/call_list.csv`: companies with a phone and no published
  email (42 on 2026-10-02); `call_script.md` is the two-minute script.
- The `regknots-outreach` scheduled task: 10 drafts a weekday, 7 towing (MVUS rows first),
  2 schools, 1 TPO; status `call` for phone-only companies.

dco.uscg.mil's Akamai refuses curl from both the laptop and the VPS; the ingest package's
httpx client with browser headers gets the MVUS file and courses.pdf from the VPS.

## 3. NGA navigation manuals (`nga_pubs`)

Bowditch Vol. I (one section per numbered article, `Bowditch Art.1301`), Pub 1310 radar and
maneuvering board (chapters split at headings, `Pub 1310 Ch.3 Sec.26`) and Pub 102
International Code of Signals (`Pub 102 Ch.2 Sec.1`), from msi.nga.mil's publications API.
Tagged `['intl']`, Tier 4 reference, in the `imo_ref` retrieval group (IAMSAR is listed there
but was never ingested, so the group had been empty). Left out: Bowditch Vol. II (tables,
almanac extracts, glossary), Bowditch's appendices (formulas whose radical signs don't
survive extraction), and Pub 1310's appendices (a superseded 1983 extract of SOLAS V/12;
worked problems).

## Production results

Deployed `289d1c5`, then `88a28e9` (the two fixes below). Migration 0120 applied.

- `exam_questions`: 11,955 questions from 244 sample exams; 1,411 need a figure or a reference
  book; 10,544 servable, 9,766 distinct across 23 topics (`/practice/topics`). Rules of the
  Road keeps only 123 (most of its questions show an illustration); stability keeps 10 (most
  need the Stability Data Reference Book).
- Related sections: 5,983 servable questions show one (similarity ≥ 0.55). Most often:
  nga_pubs 1,919, 46 CFR 1,739, NVICs 686, 33 CFR 633, then SOLAS 120, COLREGs 116 and the MSM 111. Engine questions mostly get none: the corpus has no engineering text. The first load had matched about 950 questions to Bureau Veritas, ABS or
  Lloyd's class rules or the UK's COSWP; the lookup now searches U.S. rules and Coast Guard
  guidance, the IMO instruments and `nga_pubs` only (`exam_questions.RELATED_SOURCES`).
- `nga_pubs`: 1,133 sections / 2,376 chunks (Bowditch 907 articles, Pub 1310 198 sections,
  Pub 102 28), 2 min 15 s, 0 errors. The VPS's pdftotext splits a little differently from the
  laptop's (1,102 sections there). Corpus 102,472 chunks / 77 sources.
- Dense harness (79 pairs): strong recall@8 0.9367, weak 0.9494, MRR **0.7657** (was 0.7593):
  no pair gained or lost. `dense-prod` was not run (spend rule).
- Fix found in review before any user hit it: the free plan reused the cycle the trial's
  messages were counted in, so a trial user who asked 15 questions would have had no free
  questions for about three weeks. The first question after the trial now starts a fresh
  cycle, and running out of the 50 trial messages early ends the trial then (`6ed2472`).
- Leads: 1,847 rows (705 + 6 TPOs + 991 MVUS + 145 schools); 42 on the call list.
- Free plan: all 62 external free accounts are past their trial, so all of them now have 10
  questions per 30 days (read-only SQL, 2026-10-02). None has been told; an announcement is Blake's call.

## Not done

- Pub 117 (Radio Navigational Aids) and Bowditch's glossary: candidates, not ingested.
- Inspected passenger vessel operators from the same MVUS file (10,588 vessels): the next
  outreach niche if towing response stays low.
- `compare_synthesis_models` was not re-run for the added prompt line (~$3–4; spend rule).
