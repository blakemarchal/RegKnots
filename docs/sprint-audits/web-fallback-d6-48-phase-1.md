# Web search fallback — D6.48 Phase 1 reference

**Status:** Phase 1 (calibration infrastructure) shipped to prod 2026-05-01. Phase 2 (production wiring) gated on calibration data review.

---

## Mental model

The product promise stays unchanged: **authoritative when we have it, honest when we don't.** Today the "honest" path is a dead-end ("I have to be honest, I don't have specific information…"). This sprint upgrades it from a dead-end to a useful pointer — *the maritime expert who, when stumped, knows where to look.*

We are explicitly NOT turning RegKnots into a general LLM. We are turning the worst-case experience (no answer) into a less-bad experience (some answer with caveat) — without diluting the value prop.

The Venn-diagram strategic frame:
> "I want us to be on par and everything that we do different is something general cannot do and we do better."

After web fallback lands, the only things general AI does better are speed and casual tone — neither of which our buyer cares about.

---

## When fallback fires

**Trigger** (auto, not opt-in):
- The chat answer matches the existing `detect_hedge()` patterns (regex set in `packages/rag/rag/hedge.py`), AND
- Retrieval top-1 cosine similarity was < **0.5** (true corpus gap, not retrieval miss).

**Why not fire on every hedge:** retrieval misses (answer IS in corpus, embedding didn't surface it) shouldn't get masked behind a fallback — that hides corpus quality from the admin metrics. The 0.5 threshold separates "true gap" from "miss." Tune from data.

**Kill switch:** server-side feature flag (env var). No per-user opt-in UI — we don't advertise the weakness.

---

## Three gates (all must pass to surface)

1. **Domain whitelist.** The cited URL's host must match an entry in `EXACT_TRUSTED_DOMAINS`, be a subdomain of an exact-trusted domain (e.g. `wwwcdn.imo.org`), or end with a wildcard suffix (`.gov`, `.mil`, `.gov.uk`, etc.). Source: `packages/rag/rag/web_fallback.py`.
2. **Self-rated confidence ≥ 4 of 5.** Claude returns a `confidence` integer in its JSON response.
3. **Verbatim quote present in source.** Claude must return a quote string that, after light normalization (smart-quote folding, whitespace collapse, nbsp→space), appears in the source's extracted plaintext (HTML strip OR pdftotext / pdfplumber). Fails closed — unreachable source or extraction failure → block.

If any gate fails, the original hedge response stands. Nothing changes for the user. Every attempt is logged.

---

## Architectural cross-contamination guards

These are non-negotiable. They keep the product brand intact.

1. **Lane separation.** A response is either a corpus answer (Tier 1-4 styling) OR a web fallback (yellow card). **Never a hybrid.** Don't let Claude write "According to 33 CFR 110.168 (corpus) AND ALSO this Wikipedia page (web)…"
2. **Visual differentiation.** Yellow-bordered card with header "Web reference (not in RegKnots corpus)", verbatim quote in italic, summary, permanent disclaimer footer.
3. **Trigger only on corpus gap.** Cosine threshold < 0.5 protects against fallback firing when corpus would have answered.
4. **Audit trail.** Every fallback (surfaced or not) is logged to `web_fallback_responses` with `is_calibration` distinguishing replay runs from production traffic.

---

## What's live now (Phase 1)

| Component | File | Notes |
|---|---|---|
| Migration | `apps/api/alembic/versions/0073_add_web_fallback_responses.py` | Table with provenance + feedback fields, indexed by user/created/surfaced/calibration/feedback. |
| Whitelist + validator | `packages/rag/rag/web_fallback.py` | 64 exact-trusted domains, 11 wildcard suffixes, subdomain matching, smart-quote-tolerant verbatim-quote validator. |
| Orchestrator | `attempt_web_fallback()` in `web_fallback.py` | Calls Claude Sonnet-4-6 with `web_search_20250305` tool (max 3 searches). Returns `FallbackResult` dataclass with all three gate decisions. |
| Replay endpoint | `POST /admin/web-fallback/replay?n=25&cosine_threshold=0.5` | Runs stack against last N hedge queries from `retrieval_misses`, persists each attempt with `is_calibration=true`, returns aggregate counts + per-row detail. |
| Read endpoint | `GET /admin/web-fallback/recent?limit=50&only_surfaced=&only_calibration=` | Paginate stored attempts. |

---

## Trusted whitelist (current)

**Exact (64 domains):**

International / regulators: `imo.org`, `iacs.org.uk`, `emsa.europa.eu`, `iso.org`, `itu.int`, `who.int`.

Class societies (IACS members): `bureauveritas.com`, `marine-offshore.bureauveritas.com`, `rulesexplorer-docs.bureauveritas.com`, `dnv.com`, `rules.dnv.com`, `eagle.org` (ABS), `ww2.eagle.org`, `classnk.or.jp`, `lr.org` (Lloyd's Register), `rina.org`, `krs.co.kr` (KR), `ccs.org.cn`, `irclass.org`, `rs-class.org`.

US federal: `uscg.mil`, `homeport.uscg.mil`, `dco.uscg.mil`, `navcen.uscg.mil`, `cgmix.uscg.mil`, `ecfr.gov`, `govinfo.gov`, `regulations.gov`, `epa.gov`, `noaa.gov`, `nws.noaa.gov`, `nhc.noaa.gov`, `phmsa.dot.gov`, `tsa.gov`.

National flag-states (in our corpus or candidates): `amsa.gov.au`, `deutsche-flagge.de`, `transportes.gob.es`, `cdn.transportes.gob.es`, `guardiacostiera.gov.it`, `mit.gov.it`, `lavoromarittimo.mit.gov.it`, `ynanp.gr`, `hcg.gr`, `sdir.no`, `mardep.gov.hk`, `mpa.gov.sg`, `bahamasmaritime.com`, `register-iri.com`, `registry-iri.com`, `liscr.com`, `tc.gc.ca`, `tc.canada.ca`, `mca.gov.uk`, `gov.uk`.

Port-state MOUs: `tokyo-mou.org`, `parismou.org`, `blacksea-mou.org`, `caribbeanmou.org`.

Industry bodies: `ics-shipping.org`, `ocimf.org`, `intertanko.com`, `intercargo.org`, `bimco.org`.

**Wildcard suffixes (11):** `.gov`, `.mil`, `.gov.au`, `.gov.uk`, `.gov.it`, `.gov.hk`, `.gov.sg`, `.gov.bs`, `.gob.es`, `.gc.ca`, `.canada.ca`.

**Subdomain rule:** any `*.<exact-trusted>` is automatically trusted. `wwwcdn.imo.org` and `homeport.uscg.mil` work without manual additions.

---

## Smoke test result (the proof it works)

End-to-end run against IMO MSC.428(98) cyber-risk question:

```
surfaced       = True
blocked_reason = None
confidence     = 5
source_url     = https://wwwcdn.imo.org/.../MSC.428(98).pdf
source_domain  = wwwcdn.imo.org
quote_verified = True   ← we re-downloaded the PDF and confirmed
                          the verbatim quote appears in it
quote          = "an approved safety management system should take into
                  account cyber risk management in accordance with the
                  objectives and functional requirements of t..."
answer         = "MSC.428(98) affirms that an approved SMS must take
                  into account cyber risk management in accordance with
                  the ISM Code's objectives and functional requirements,
                  with full compliance required no later t..."
latency_ms     = 10,825
```

Calibration immediately paid for itself: first run caught that IMO publishes via `wwwcdn.imo.org` (CDN) which would have been blocked by strict exact-matching. Subdomain matching now handles this automatically.

---

## Calibration plan (run before Phase 2)

1. **Trigger replay:** `POST /admin/web-fallback/replay?n=25` (admin auth required). Repeat 2-3 times until ~50-100 attempts logged.
2. **Pull results:** `GET /admin/web-fallback/recent?only_calibration=true&limit=100`.
3. **Review with the team:**
   - **Surface rate.** % that pass all 3 gates. Target ~30-40%. Higher = either too lenient or our hedge rate is biased toward gaps that the open web has clear answers for. Lower = whitelist too strict OR Claude isn't quoting verbatim.
   - **`domain_blocked` reasons.** Any obvious-trusted domains we missed? Add them.
   - **`quote_unverified` reasons.** Is Claude paraphrasing despite the system prompt? If yes, tighten the prompt or temperature.
   - **Latency distribution.** Outliers concerning?
   - **Spot-check accuracy.** Pick 10 surfaced ones; verify the answer + quote actually addresses the user's question.
4. **Whitelist tuning.** PR + commit + redeploy.
5. **Greenlight Phase 2** when surface rate looks healthy AND spot-checks read well.

---

## Phase 2 plan (next session, after calibration green-lights)

| Item | Effort |
|---|---|
| Hook `attempt_web_fallback` into `engine.chat()` at the existing hedge-detection point (line 1387 in `packages/rag/rag/engine.py`), behind `WEB_FALLBACK_ENABLED` env var | 1 hr |
| Yellow-card UI component on chat frontend (apps/web) — verbatim quote + URL + summary + permanent disclaimer | 2 hr |
| Streaming status updates ("Searching authoritative sources…") during fallback latency | 2 hr |
| Per-user daily cap (10 fallbacks/day starter) — column on `users` table or in-memory counter | 1 hr |
| Thumbs-up/down feedback chip on every fallback response → `web_fallback_responses.user_feedback` | 1 hr |
| Admin metrics: hedge rate vs. fallback-success rate side-by-side | 1 hr |

Total: ~0.5-1 day of work after calibration greenlight.

---

## Phase 3 plan (lightweight, ongoing)

**Corpus-discovery feedback loop.** The strategic prize. Every fallback is a logged corpus gap; thumbs-up fallbacks are gaps that *matter to users*.

- Weekly cron pulls thumbs-up fallbacks, ranks by frequency.
- Surfaces top 10 to admin: *"these are gaps your users hit most. Ingest as full corpus sources?"*
- Each promotion is a normal D6.X+ ingest sprint (curated list adapter, migration, ingest run).

After 6 months we have an empirical, demand-ranked list of "regulators we should ingest" — not from research instinct, from real user demand.

---

## Open decisions to revisit after data

| Decision | Current | Trigger to revisit |
|---|---|---|
| Verbatim quote required | yes (strict v1) | Loosen to "summary OK if confidence = 5 AND domain is gov/mil" only after 100+ surfaced responses pass spot-check accuracy |
| Cosine threshold for "true gap" | 0.5 | Tune up if fallback fires too often, down if it misses real gaps |
| Min confidence | 4 of 5 | Probably stable; depends on how Claude calibrates |
| Daily cap per user | 10 | Tune by usage data |
| Whitelist scope | strict | Add domains as `domain_blocked` data shows legitimate sources we're missing |

---

## Risks (and how Phase 1 mitigates each)

| Risk | Mitigation |
|---|---|
| Karynn-trap recurrence (confident wrong answer) | Verbatim-quote requirement is non-negotiable. If Claude can't quote, no surface. |
| Brand erosion from random web sources | Strict whitelist of regulators + class societies + .gov/.mil only. |
| Retrieval-miss masking (corpus has answer, fallback hides our miss) | Cosine threshold < 0.5 keeps fallback off when corpus had a plausible hit. |
| Cost creep | Per-user daily cap (Phase 2) + admin kill switch + replay-only mode in Phase 1. |
| Latency on hedge path | Streaming "Searching…" status (Phase 2) + opt-out via kill switch. |
| Hybrid-citation contamination | Lane separation in UI; system prompt instructs Claude to anchor on a single source. |
| Liability if user skims the disclaimer | Yellow card visual signal + permanent disclaimer footer. Real product harm is mitigated by the verbatim-quote requirement (user can verify). |

---

## Where to look later

- DB table: `web_fallback_responses` (migration 0073).
- Whitelist + validator + orchestrator: `packages/rag/rag/web_fallback.py`.
- Admin endpoints: `apps/api/app/routers/admin.py` — search "Web fallback calibration".
- Hedge classifier (existing): `packages/rag/rag/hedge.py` — 18 regex patterns.
- Hedge trigger point in chat pipeline (where Phase 2 hook goes): `packages/rag/rag/engine.py` line 1387.
- Anthropic web_search tool docs: `web_search_20250305` (Claude Sonnet 4.6).
