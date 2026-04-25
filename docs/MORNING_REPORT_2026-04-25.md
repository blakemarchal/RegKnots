# Morning Report — 2026-04-25

Sprint D6.3c shipped overnight + Karynn / Nathaniel chat audit.
Read the audit findings first; sprint summary below.

---

## Sprint D6.3c — what shipped

Five distinct items in one sprint, all live in production:

1. **Chat history search** (Karynn's request — discreet, not prominent)
2. **Post-register auto-resume** of `pending_checkout_plan` (UX polish)
3. **Dynamic sample-answer carousel** on `/womenoffshore` (cosmetic)
4. **Admin `referral_source` override** UI + endpoint
5. **D2-LOG bugfix** discovered during the audit (was silently dropping Karynn's hedges — see Audit Finding #1)

Admin **impersonation** was explicitly NOT shipped tonight — security-sensitive enough that I wouldn't ship it without iteration. Tracked as a dedicated sprint candidate.

Commits: `c449b3d` (D6.3c) + `b5e8c00` (Decimal fix).

### Verifying each item

- **`/history` search:** open `/history`, type at least 2 characters in the search box at the top. Hits show below with the matched-message preview, role, vessel context, timestamp.
- **Post-register resume:** in an incognito window, visit `/womenoffshore`, click any subscribe button while logged out → register → should land on Stripe Checkout instead of the app.
- **Sample carousel:** `/womenoffshore` → scroll to "Cited answers, not summaries." Auto-rotates every 7s, dots underneath, hover to pause.
- **Admin referral override:** `/admin` → user list → "Referral" button → enter a value (or blank to clear) → save. Audit-logged.

---

## Audit Finding #1 — D2-LOG was silently dropping every Karynn hedge

**Severity: real bug, fixed tonight.**

`retrieval_misses` showed **only one row** for both Karynn and Nathaniel across the past 7 days, despite Karynn alone having 12 hedged responses in that window. Tracked it down via journalctl:

```
WARNING:rag.engine:retrieval_miss log failed (non-fatal):
TypeError: Object of type Decimal is not JSON serializable
```

Root cause: `vessel_profile.gross_tonnage` is a `numeric(12,2)` Postgres column → asyncpg returns it as `Decimal` → `json.dumps(vessel_profile)` rejects it → fire-and-forget except-block silently swallows the error → no log row written.

**Why it bit only some users:** Nathaniel's GITMO hedge logged correctly (no vessel profile, so `json.dumps(None)` was never called). Karynn's hedges all happened with a vessel profile attached → all silently dropped.

**Fix:** custom `default=` callable on every `json.dumps` in `_log_retrieval_miss` that converts `Decimal → float`. Shipped as commit `b5e8c00`. Verified syntax-clean. Going forward, vessel-profiled hedges will populate the table correctly.

**What this means for our priors:** every "we've barely seen any retrieval misses" data point I gave in past sessions was wrong for any user with a vessel set. Real hedge volume in production was higher than `retrieval_misses` suggested.

---

## Audit Finding #2 — Karynn's "it did this again" complaint, identified

**The exact incident:**

| Time | Vessel | User question | Outcome |
|---|---|---|---|
| 2026-04-23 21:34 | Maersk Seletar | "What equipment is required to be inside a lifeboat?" | OK |
| 2026-04-23 21:36 | Maersk Seletar | "Flares are also required" | OK (acknowledgment turn) |
| 2026-04-23 21:38 | Maersk Seletar | "So you can't tell me how many and what type of flares I am supposed to carry in the lifeboat" | **HEDGED** ("didn't surface") |

This is the exact pattern D5.5 was designed to fix — the multi-chunk-section dedup that lets `46 CFR 199.175` Table 1 surface alongside its intro chunk. My D5.5 smoke test confirmed it works for the question phrased as "How many parachute flares does my lifeboat need to carry?" but **explicitly noted at the time** that her conversational follow-up phrasing ("So you can't tell me...") still fails because the meta-discussion phrasing has weak vector similarity to the table content.

**She hit the exact edge case I documented but didn't close.**

D5.5 was a partial fix; the conversational-followup phrasing remains an open issue. Next-step candidates (in order of bang-for-buck):

1. **Router escalation on follow-up patterns** — when the query starts with "So you can't tell me…", "you keep saying…", "but what about…", or other follow-up markers, treat it as conversational reformulation: re-retrieve using the prior user message as additional query context, and route to Opus regardless of complexity score. Same dedup, smarter retrieval input.
2. **Force-include canonical chunks on quantity questions** — pattern-match queries with quantity intent ("how many", "what type of", "how often") on a known section. If the section is in the retrieved set already, force-include all of its chunks (not just top-2) into the context. Bypasses the dedup entirely for the specific intent that needs it.
3. **Ingest-time chunk reordering for table-bearing sections** — embed the table chunk's text alongside a synthetic question like "What are the specific quantities for [section topic]?" so vector search routes quantity questions toward it. More complex, more invasive.

I lean #1 first — cheapest, doesn't touch ingest, addresses the conversational pattern broadly (not just the flare case).

---

## Audit Finding #3 — Net trend across sessions

| Window | Hedge rate (Karynn) |
|---|---|
| 2026-04-22 (her original problem session) | 9 / 22 = **40.9%** |
| 2026-04-22 → 2026-04-24 (full 7-day window, 37 messages) | 12 / 37 = **32.4%** |

Net **~8-point improvement** since the D5.x → D6.x cleanup, but not as dramatic as the eval suggested. Real-user hedges still concentrate on the same patterns we identified before:

- **Operational specifics outside corpus** (India port docs, GITMO status, foreign-articles edge cases) — these are corpus gaps; D5.x ingests didn't close them
- **Abstract / meta questions** ("can you give me an example of cross-references between CFR/SOLAS/ISM") — Karynn asked this 2026-04-24 19:48, hedged
- **Conversational follow-ups** after partial answers — the flare case
- **Specific-quantity asks on multi-chunk sections** — the flare case again

---

## Audit Finding #4 — Encouraging data points (not all regression)

Look at these examples of QUESTIONS THAT NOW WORK that previously hedged:

- 2026-04-22 21:54 "Is a vessel required to have a slop chest" → **OK** (D5.1 46 USC ingest paid off — the answer cited 46 USC 11103)
- 2026-04-22 22:01 "Is the master of the vessel to provide a pay voucher once every month to the crew" → **OK** (also 46 USC)
- 2026-04-23 21:34 "What equipment is required to be inside a lifeboat?" → **OK** (D5.5 dedup helped this direct version)
- 2026-04-24 20:26 "For inspection of life rings, can you cross reference CFRs, ISM, AND solas on what is required" → **OK** (the SPECIFIC version of the cross-reference question that failed at 19:48 — pattern: specific > abstract)

Several questions that would have hedged in March are now clean answers. The user-perceived regression is real but selective — it's the long-tail conversational patterns, not a broad system regression.

---

## Audit Finding #5 — Nathaniel's session

Tiny dataset (2 assistant responses). One hedge:

- 2026-04-24 14:51 "Is gitmo a us port" → **HEDGED** ("does not appear in")
- 2026-04-24 14:54 "Can an American flagged non solas vessel travel from a us port to gitmo" → **OK**

The first is honestly outside our corpus scope (Naval Station Guantanamo Bay's port status under US Customs/CBP rules — not a regulatory citation we'd carry). The honest hedge is correct behavior. The follow-up question got a good answer because it shifted to the regulatory question (vessel travel rules) which IS in our corpus.

Not actionable. This is good model behavior.

---

## Recommended next-sprint priorities (no greenlight needed, just ranked)

1. **Conversational-followup retrieval** — close the flare-case edge that Karynn hit twice now. ~1 session. Highest user-felt impact.
2. **Verify D2-LOG fix is capturing data** — once Karynn or any vessel-profiled user runs a session post-`b5e8c00`, confirm `retrieval_misses` rows actually appear with vessel_profile JSON intact. Should happen automatically; just check `SELECT COUNT(*) FROM retrieval_misses WHERE created_at > NOW() - INTERVAL '24 hours';` in 24-48 hours.
3. **Admin user impersonation** — security-sensitive but useful for support and for testing referral-aware pricing. Dedicated sprint.
4. **Corpus gap audit follow-up** — India port arrival, ENOA, port-state-control penalties for missing docs — these keep coming up. May warrant a focused "operational ports" ingest sprint after Karynn's next session of data.

---

## Quick-reference: how to verify the new search feature works

```bash
# In a logged-in browser session at https://regknots.com/history
# Type: "lifeboat" or "VGM" or "MMC" — whatever Karynn would have searched

# To verify backend directly with a token:
curl -H "Authorization: Bearer <your-token>" \
  "https://regknots.com/api/conversations/search?q=flares&limit=10" | jq
```

Should return matching conversations with the matched message preview underneath.

---

## What's still on the parking lot from prior sprints

- Admin user impersonation (deferred from D6.3c)
- Karynn final review of `/womenoffshore` founder-description copy
- Logo + testimonial assets for `/womenoffshore`
- Post-launch: monitor Stripe webhook handler for any `Unmapped price_id` warnings on Karynn's existing pre-D6.1 subscription when it next renews

Sleep well.
