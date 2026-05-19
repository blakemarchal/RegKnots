# Tier Router Kill — Shadow Mode Audit (D6.84 → D6.97)

**Date:** 2026-05-19
**Decision:** Remove tier_router from the chat pipeline. Keep `tier_router_shadow_log` table + migration 0093 for 90-day archival.
**Author:** Claude (with Blake)

## Why the tier router shipped (D6.84 Sprint A, 2026-05-09)

The tier router was designed to close the "partial_miss-low-web dead
zone" that surfaced in Jordan Dusek's gasket-class question: the
hedge_judge correctly identified that the corpus didn't have a perfect
match, but the web_fallback layer surfaced low-confidence external
results that the user couldn't act on. The synthesizer hedged. The
hypothesis was that a classifier could route between four explicit
trust tiers (✓ Verified / ⚓ Industry Standard / 🌐 Relaxed Web / ⚠
Best-effort) instead of the binary verified/blocked the existing path
produced.

Shadow mode was the right rollout strategy at the time — write
proposed decisions to `tier_router_shadow_log` without affecting user
output, so we could measure whether the classifier's verdict was an
improvement before flipping it live.

## What 14 days of shadow data tell us

Queried 2026-05-19 against `tier_router_shadow_log`:

| Metric | Value |
|---|---:|
| Total shadow log entries (last 14 days) | 50 |
| Cases where shadow verdict ≠ current judge verdict | **17 (34%)** |
| `shadow=verified` while `current_judge=precision_callout` | **23 (46%)** |
| `shadow=best_effort` aligned with `current_judge=complete_miss` | 7 |
| `shadow=best_effort` aligned with `current_judge=partial_miss` | 6 |
| `shadow=relaxed_web` aligned with miss-class verdicts | 5 |

The headline finding is the **23 cases where shadow=verified but the
hedge_judge flagged precision_callout** — meaning the synthesizer's
answer overclaimed something the judge caught. If tier_router had been
in `live` mode, those 23 answers would have surfaced with the ✓
Verified badge while the existing pipeline correctly demoted them.

That is the **opposite of the win case** we shipped the tier router
for. Promoting it to live would have degraded user trust on roughly
half the queries the classifier touched.

The remaining alignment cases (best_effort → complete_miss /
partial_miss) are not net-new value — the existing hedge_judge +
web_fallback ladder already produces the same outcome at that
confidence level. The tier_router is being **redundant** there, not
additive.

## What we lost to ship and audit it

- **~300 lines** of classifier + self-consistency dispatch in
  `packages/rag/rag/tier_router.py`
- **~$9/month** in Haiku classifier costs running on 100% of queries
  for telemetry no one acted on
- **Architecture complexity:** the audit doc (full-system-audit
  2026-05-08) called tier_router the hardest layer to read cold — a
  5-tier decision tree with classifier + self-consistency sub-gates
  and a shadow-vs-live mode duality
- **A defensive hedge regex in tier_router.py** that exists
  specifically because the classifier doesn't trust hedge_judge —
  three layers redundantly checking "is this answer hedging?"

## Why this isn't "the partial-miss dead zone is back"

The misfires that originally motivated tier_router (Karynn ETA
2026-05-11, Karynn fire-extinguisher 2026-05-11, Kenan fire-doors
2026-05-13) were diagnosed during the tier_router's shadow phase and
ultimately addressed by the **D6.92 hedge_judge prompt rewrite**.
That rewrite shipped to the existing pipeline and closed the dead
zone without needing the tier_router layer to ever go live.

Karynn's last 72h of compliance queries (audit 2026-05-19) showed
8/9 GOOD outcomes with no partial-miss dead-zone misfires. The single
hedge was a retrieval miss on her vocab ("Foreign box" / "Coastwise
box"), not a tier-routing problem. The dead zone the tier_router was
designed to close is closed by other means.

## What we keep

- `apps/api/alembic/versions/0093_tier_router_shadow_log.py` — migration stays
- `tier_router_shadow_log` table — kept for 90-day archival forensics
- `messages.tier_metadata` JSONB column — kept (small, free)
- The `current_judge_verdict` + `current_judge_reasoning` columns on the table — these were the most valuable telemetry from the shadow phase and remain useful even without the classifier running

## What we delete

- `packages/rag/rag/tier_router.py` — the entire module
- Dispatch calls from `engine.py` (both `chat()` and `chat_with_progress()` paths)
- The `confidence_tiers_mode` config flag (or coerce to single value `"off"`)
- The defensive hedge regex in tier_router.py that re-implemented hedge_judge's job
- Frontend rendering of the 4-tier chip if any (none visible in production — UI was waiting on `live` flip)

## Revert path

If a future quarter surfaces a class of queries the existing pipeline
mishandles in the way tier_router was designed to catch, the work
isn't lost:

1. Migration 0093 is intact.
2. Shadow data through 2026-05-19 is preserved in the table.
3. The classifier design (4 tiers + self-consistency) is documented in
   the original D6.84 sprint plan.
4. Reviving requires resurrecting `tier_router.py` (in git history) +
   re-wiring dispatch. ~2-3 hours, plus a fresh shadow phase to
   validate against the then-current pipeline.

## The bigger lesson

The full-system audit identified tier_router as the hardest layer to
read cold. We shipped it in shadow because we weren't confident it
was net-positive. Shadow data proved it isn't. Removing it is the
honest follow-through on the shadow rollout strategy that worked
exactly as intended — it told us "don't ship this live" before we
inflicted it on users.

The next architectural step (Track B — rationalize the fallback
pipeline into an explicit `AnswerPipeline` with named `Transform`s)
benefits from a smaller surface area to refactor.
