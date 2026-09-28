# Outreach agent, v1 (spec, 2026-09-27)

**Status: live 2026-09-27.** Scheduled task `regknots-outreach` (weekdays 06:38 local).
Blake's decisions: hello@regknots.com in the signature, the La Marque address in the footer, and the
30-day fleet trial as the offer. regknots.com moved to Google Workspace the same evening: one mailbox,
blake@regknots.com, with hello@ and support@ as aliases, root DKIM and DMARC. Drafts go into the
account the Gmail connector uses: blakemarchal@gmail.com until Blake switches it to blake@regknots.com.

**2026-09-28: drafts go through `scripts/outreach/gmail_draft.py`, not the connector.** The first
run's 5 drafts showed the Gmail connector rewrites every link it saves (plain-text URLs, bare
`regknots.com/...` text and `<a href>` alike) into `google.com/url?q=...`, and clicking one opens
Google's "Redirect Notice" page. The script saves drafts through the Gmail API (scopes
`gmail.compose` + `gmail.metadata`; OAuth client and token in `~/.regknots/`, outside the repo,
from the `regknots-outreach` Google Cloud project). It renders one template: the routine's
paragraphs, the RegKnot line and offer, the link `regknots.com/fleet?src=ob-NNNN` (a 307 to the
fleet-trial signup with the utm tags, `apps/web/next.config.ts`), a signature with the logo, and
the opt-out line. The routine still reads Sent and replies through the connector.

**Goal:** a steady stream of personal first emails to U.S. towing operators, with Blake approving
every send, at no new monthly cost.

**Why:** product usage is not the bottleneck. On 2026-09-26, one of 64 external users had asked a
question in the previous 30 days, signups ran 36 / 22 / 4 / 1 / 1 / 0 from April to September,
and no signup had a recorded source.

## Design

| Piece | v1 (free) |
|---|---|
| Niche | U.S. towing (Subchapter M), 2 to 40 towing vessels; Gulf states first |
| Leads | U.S. Army Corps "Waterborne Transportation Lines", operator file for 2017 (public domain): 705 towing companies with address, phone, operating area and fleet counts. `scripts/outreach/build_leads.py` writes `data/outreach/leads.csv` (gitignored). The AWO public member list (about 300 current tug and towboat companies) can supplement. |
| Research | Done by the agent, per company: still operating? website? a published email (operations, safety, crewing, compliance, or a named manager)? Addresses come only from the company's own site or official listings. No address guessing, no data brokers, no LinkedIn scraping. |
| Hook | One verified Q&A per email from `scripts/outreach/hooks.md` (six Subchapter M answers checked against the corpus). The agent never writes new regulatory content. |
| Agent | A Claude desktop scheduled task (weekdays, morning) using the Gmail connector and web search. It runs on Blake's Claude plan: no API credits, no new service. It runs while the desktop app is open; a missed run fires on the next launch. |
| Approval | The agent only creates **Gmail drafts**. Blake reviews, edits, and presses Send. Nothing sends automatically. |
| Follow-ups | Two, in the same thread, 5 and 12 business days after Blake sends, only if there is no reply. Any reply or "no thanks" stops everything for that address. |
| Tracking | Status lives in `leads.csv` (new, drafted, sent, replied, opted_out, no_contact, closed). Each email links to `regknots.com/fleet?src=ob-NNNN`, which redirects to the fleet-trial signup with `utm_source=outreach`, so a signup shows under "Signups by source" on the admin Traffic page (shipped 2026-09-27, `4abf1a6`). |
| Volume | 5 drafts per weekday through 2026-10-02 while the new regknots.com mailbox warms up, then 10: about four months of runway on the towing list. |
| Compliance | CAN-SPAM: honest From and subject lines, a physical postal address, a working opt-out that is honored at once. U.S. businesses only (no EU or Canada). |

The full task instructions are in `scripts/outreach/task_prompt.md`.

## Blake decides

1. **Sending account.** Decided 2026-09-27: Google Workspace, one license ($8.40 a month on the
   flexible plan), mailbox blake@regknots.com with hello@ and support@ as aliases. Resend (our
   transactional provider) forbids cold email and carries our verification and password-reset
   mail, so it stays out of outreach.
2. **Postal address** for the footer (CAN-SPAM requires one).
3. **The offer.** The fleet plan (Wheelhouse) is $99.99 per vessel per month. Suggested:
   "your first boat free for 30 days, no card", then list price, or a founding-operator discount.

## Later (not v1)

- Passenger (467) and OSV (459) operators from the same Army Corps file, with their own hooks.
- Public "shared answer" pages so an email can link to a full cited answer.
