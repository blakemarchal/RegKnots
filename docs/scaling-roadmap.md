# RegKnot — Scaling Roadmap

**Last updated:** 2026-04-25 (Sprint D6.6 — Caddy access logging enabled)

This document tracks operational + capacity items that aren't urgent today but become critical at specific user-volume thresholds. The goal is to make growth-driven scrambles preventable: when a threshold is approaching, we know exactly what work it triggers.

---

## Current state (2026-04-25)

| Resource | Capacity | Current usage |
|---|---|---|
| VPS (DigitalOcean) | 2 vCPU, 3.8 GB RAM, no swap | <1% CPU, ~47% RAM |
| Postgres + pgvector | Dockerized on same box | Trivial query load |
| Redis | Dockerized on same box | Trivial |
| `regknots-api` (FastAPI/uvicorn) | **Single worker** on port 8000 | <5% RAM, <1% CPU |
| `regknots-web` (Next.js) | Single process on port 3000 | Trivial |
| `regknots-worker` (Celery) | Single process | Idle most of the time |
| Reverse proxy | Caddy (auto-TLS, on-demand) | Healthy |
| Anthropic API | Per-tier rate limits (check console) | Not yet hitting caps |
| OpenAI API | Per-tier rate limits | Not yet hitting caps |

Daily traffic (week of 2026-04-19 → 2026-04-25):
- New signups: 1-2 / day
- Active users: 1-4 / day
- Messages: 4-22 / day

**Headroom is generous.** The current bottleneck during a spike isn't the VPS — it's API rate limits on Anthropic and a single uvicorn worker.

---

## Tonight's freebie (DONE — Sprint D6.6)

✅ **Caddy access logging enabled** — `/var/log/caddy/regknots-access.log`, JSON format, 100MiB rotation, 5 files retained, 30-day max age.

Useful one-liners against the log:

```bash
# Top URLs in the last hour
ssh root@68.183.130.3 "tail -10000 /var/log/caddy/regknots-access.log | jq -r '.request.uri' | sort | uniq -c | sort -rn | head -20"

# Top referrers
ssh root@68.183.130.3 "tail -10000 /var/log/caddy/regknots-access.log | jq -r '.request.headers.Referer[0] // \"direct\"' | sort | uniq -c | sort -rn | head -10"

# Status code distribution
ssh root@68.183.130.3 "tail -10000 /var/log/caddy/regknots-access.log | jq -r '.status' | sort | uniq -c | sort -rn"

# Slow requests (>2s)
ssh root@68.183.130.3 "tail -10000 /var/log/caddy/regknots-access.log | jq 'select(.duration > 2) | {uri: .request.uri, duration, status}'"

# Live tail of just /api/* requests
ssh root@68.183.130.3 "tail -f /var/log/caddy/regknots-access.log | jq 'select(.request.uri | startswith(\"/api/\"))'"
```

Cost: $0. Effort: 5 minutes including the permission-error sidequest.

---

## Threshold tiers — when each item becomes critical

### Tier 1 — Visibility (operational basics)

**Threshold:** As soon as you have organic traffic you don't directly control. Right now (post atseastories Instagram plug).

| Item | Current state | What to do | Effort | Cost |
|---|---|---|---|---|
| Caddy access logging | ✅ DONE 2026-04-25 | — | — | — |
| Frontend analytics (Plausible) | ❌ Not installed | Drop-in script tag in `apps/web/src/app/layout.tsx` + Plausible account setup | 30 min | $9/mo |
| Uptime monitor (UptimeRobot or Better Uptime) | ❌ Not installed | Free tier: 5-min interval ping on `/api/health`, email alert | 10 min | $0 |
| Error monitoring (Sentry) | ✅ Already wired | Verify alerts go somewhere you check | 5 min | Free tier ample |

**These three together turn "blind operation" into "live operational dashboard." Total cost of Tier 1: ~45 minutes one-time + $9/month.**

### Tier 2 — Concurrency basics (becomes critical at ~10 concurrent active chatters)

**Threshold:** When you start regularly seeing 10+ active chat users in the same minute. (You'll see this as `select count(distinct user_id) from messages where created_at > now() - interval '5 minutes'` rising into double digits.)

| Item | Why it matters at this scale | What to do | Effort |
|---|---|---|---|
| Multi-worker uvicorn | Single worker blocks on slow requests; one stuck request stalls others | Add `--workers 2` (or `--workers 4` if Anthropic Tier 4) to the systemd unit | 10 min |
| 2GB swap file | RAM pressure during concurrent SSE chats can OOM postgres | `fallocate -l 2G /swapfile && mkswap` etc. | 10 min |
| Redis used for rate limiting / sessions only | Doesn't scale concurrency itself; mention here for awareness | No action | — |

**Trigger to act:** alert from Plausible saying live-visitor count crossed 25, OR a slow-request blip in Caddy logs (>5% requests over 5s in a 5-min window).

### Tier 3 — API rate-limit ceiling (becomes critical at ~30-50 concurrent active chatters)

**Threshold:** When concurrent active chat users start running into Anthropic per-minute rate limits. Anthropic's per-tier limits roughly:
- Tier 1: 50 req/min, 40K input tokens/min — caps you at ~5-10 concurrent chats
- Tier 2: 1000 req/min — comfortable for 50+ concurrent chats
- Tier 4: 4000 req/min — comfortable for hundreds of concurrent chats

| Item | What to do | Effort |
|---|---|---|
| Verify your Anthropic tier | Log into Anthropic console → Limits | 2 min (you) |
| Auto-upgrade Anthropic tier | Tied to monthly spend; happens automatically once you've spent enough | — |
| Implement request queue + backpressure | When near rate limit, return 503 with Retry-After instead of stacking requests | 1 session |
| Per-user rate limit | Cap individual users to N msg/min so one person can't starve others | 1 session |

**Trigger to act:** Sentry alert on `RateLimitError` from Anthropic SDK. Currently the engine has try/except for it but no graceful UX — user just sees "model failed."

### Tier 4 — Database-side concurrency (becomes critical at ~500 active users / day)

**Threshold:** When the single Postgres process starts seeing real query queue depth, or when individual queries start taking >100ms regularly.

| Item | What to do | Effort |
|---|---|---|
| pgvector HNSW tuning | Raise `ef_search`, increase `work_mem` if queries get slow | 1 session |
| Connection pool sizing | asyncpg pool currently default ~10; raise to 20-30 | 5 min |
| Move Postgres off the API box | Separate DB host or DigitalOcean Managed Postgres | 1 session + ongoing cost |
| Read replica for retrieval-heavy queries | If retrieval becomes the bottleneck specifically | 2 sessions |

**Trigger to act:** queries in `pg_stat_statements` showing p99 > 500ms for retrieval, or pool waits showing in API logs.

### Tier 5 — Multi-region / HA (becomes critical at ~5K active users / day)

**Threshold:** When a single DigitalOcean region outage costs you real revenue, OR when international users (Karynn's Asia-Europe pilots) complain about latency.

| Item | What to do | Effort |
|---|---|---|
| Multi-region deploy | Caddy + API in 2+ regions, GeoDNS routing | 1-2 weeks |
| Postgres HA / failover | Streaming replication or managed solution | 1 week |
| CDN for static Next.js assets | Cloudflare or Vercel | 1 day |
| On-call rotation / runbook | A second human who knows what to do at 3am | Process, not code |

**Trigger to act:** ~5K daily actives, OR a noticeable revenue dip during a single-region outage.

### Tier 6 — Real ops org (becomes critical when "Blake gets the page" stops scaling)

**Threshold:** When the founder is no longer an effective on-call rotation. Probably ~$50K MRR or 50+ paying enterprise accounts.

This is a hiring problem, not a tech problem. Listed for completeness.

---

## "I am specifically anxious about X" — quick reference

### "What if 1000 people hit the landing page in an hour?"
**You're fine.** Static Next.js pages, served from disk via Caddy. The box won't notice. The DB won't be touched. Cost: zero.

### "What if 100 people register and start chatting at once?"
**You'd hit Anthropic rate limits before the VPS.** A few users would see "model failed" or hedged responses. The box itself stays healthy. Recovery: Anthropic limits reset by the minute, so the experience self-heals as load disperses.

### "What if there's a sudden spike at 3am while I'm asleep?"
**You won't know unless an uptime monitor exists.** Tier 1 fixes this.

### "What if Postgres falls over?"
**Realistic at our current scale: very unlikely.** No swap means a memory spike could OOM-kill it (Tier 2 fix). Otherwise it's a stable boring database with trivial query load.

### "What if Anthropic goes down?"
**Existing fallback to OpenAI GPT-4o is already wired** in `packages/rag/rag/fallback.py`. Verified working in past incidents. Quality is degraded but you stay online.

### "What if someone DDoSes us?"
**Caddy + DigitalOcean network handles small floods well.** A real DDoS would need Cloudflare in front. Threshold: only matters if you become a target, which you currently aren't.

---

## Bookkeeping

This doc is a living roadmap. When a threshold is crossed, mark the tier item DONE and update the threshold of the next tier as needed. Each Tier completion makes the next one easier — Tier 1 Plausible installation gives you the data to know when Tier 2 thresholds are approaching, and so on.

**Next decision point:** when do you want to install Plausible + UptimeRobot? Tonight, this week, or after the Instagram bump settles?

---

## Sprint history relevant to scaling

- **Sprint D6.6 (2026-04-25):** Caddy access logging enabled. JSON format, rotation, retention. First operational visibility into HTTP-layer traffic.
- **(future)** Tier 1: Plausible Analytics + UptimeRobot
- **(future)** Tier 2: Multi-worker uvicorn + swap file
- **(future)** Tier 3: Rate-limit handling + per-user throttling
- **(future)** Tier 4: DB tuning + connection pool resize
