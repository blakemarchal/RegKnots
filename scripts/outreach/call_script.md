# Phone script (2026-10-02)

For the leads in `data/outreach/call_list.csv` (`python scripts/outreach/call_list.py`): towing
companies with a phone number and no published email. Two minutes at most. The aim is a
name and an email address to send one link to, not a sale on the phone.

**Opening.** "Hi, this is Blake Marchal with RegKnot in La Marque. Who handles safety or
Subchapter M compliance for your boats?" Ask to be put through, or for that person's name.

**Why you're calling.** "We built a tool with Captain Karynn Marchal, a USCG Master Unlimited,
that answers Subchapter M questions with the exact CFR citation, set up for each boat. Your first
boat is free for 30 days, no card. Can I email you the link?"

**If they want an example,** use the lead's hook from `hooks.md`, as written there, citation
included. H1 is the safe default: a new deckhand needs a logged safety orientation before the
boat first gets underway (46 CFR 140.410). Never answer a regulatory question beyond the hooks
on the phone; offer to send the cited answer instead.

**If they say no:** thank them, and mark the row `opted_out` so nobody writes or calls again.

**Logging.** In `leads.csv`, for the row:
- They gave an email: put it in `contact_email` (and `contact_name` / `contact_role`), set
  status `new`, and note "email from call <date>". The next outreach run drafts to it, and the
  first sentence can mention the call.
- Call back later, or voicemail: note it with the date and keep status `call`.
- Wrong number or out of business: status `closed` with the reason.

Fill `called_at` and `outcome` in call_list.csv as you go; the next export starts fresh from
leads.csv.
