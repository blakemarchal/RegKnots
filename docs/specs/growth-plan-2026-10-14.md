# Growth plan, October 2026

Blake's go on 2026-10-13: "Greenlight what all that you can build without me in the loop." Anything that needs an account Blake creates (PostHog, Cloudflare Turnstile, Google Search Console, Bing Webmaster Tools, the Stripe dashboard) is built so it stays off until its key is in the prod `.env`.

## Why

Funnel on 2026-10-13, external users, read-only SQL:

| Step | Count |
|---|---|
| Signed up | 65 (Apr 36, May 22, Jun 4, Jul 1, Aug 1, Sep 0, Oct 1) |
| Asked a question | 41 |
| Came back on a second day | 15 |
| Asked 5+ questions | 8 |
| Active in the last 30 days | 2 |
| Paying | 2 ($127.95 all time) |

- Of the 24 who never asked, 12 stopped at or before the welcome wizard.
- No one stalled at the email-verification gate. No one hit the trial cap.
- Real traffic can't be read: scanners fill the Caddy logs.
- Outreach: 8 clicks, 0 signups.

Answer quality isn't the bottleneck. Getting people in front of a first answer is.

## Order and decisions

The order is 5 → 1 → 3 → 2 → 4. Steps 2 and 3 were swapped, so the SEO pages exist before the anonymous answer widget that goes on them.

| # | Step | Decisions |
|---|---|---|
| 5 | Customer research | Seven drafts in blake@regknots.com, one to each engaged user and each payer: a 15-minute call or three questions by reply. Blake sends. |
| 1 | Measurement + SEO basics | PostHog Cloud free tier, no cookies. The funnel is also kept in our own table. |
| 3 | SEO v1: regulation pages | About 1,500 pages built from public-domain U.S. sources only, with automated checks. No IMO text. |
| 2 | First answer before signup | Anonymous budget: 300 answers a month, 30 a day (about $60 a month at most). Turnstile + a per-device token + a loose per-IP backstop (crews share IPs). |
| 4 | Wheelhouse pilots + demo workspace | The pricing copy now says what the code does: a 30-day trial, read-only on day 31, archived 30 days later. Pilots get a per-workspace trial end. |

Karynn is assumed to have little time, so nothing here waits on her.

## Step 1: measurement and SEO basics (shipped 2026-10-14)

### Funnel events (`app/events.py`, migration 0123 `product_events`)

`track()` writes one row per event. When `POSTHOG_KEY` (or `NEXT_PUBLIC_POSTHOG_KEY`) is set, it also sends the event to PostHog in the background, with distinct_id set to the user id. A failure in either place never fails the request.

| Event | Where | Props |
|---|---|---|
| `signup` | `auth.register` | source (signup_source), role, invite |
| `first_question` | `chat._persist_chat_outcome`, when `message_count` becomes 1 | vessel |
| `paywall_hit` | chat preflight wrapper; study `_check_cap` | reason, tier, surface |
| `checkout_started` | `/billing/checkout`, `/workspaces/{id}/checkout` | plan |
| `checkout_completed` | Stripe webhook, personal and workspace | tier, interval, first |

Paywall reasons:

- `verify_email`
- `free_plan_cycle`
- `free_plan_paused`
- `tier_cap`
- `trial_over`
- `image_paid_only`
- `workspace_card_pending`
- `study_paid_only`
- `study_cap`

Admin › Dashboard has a "Funnel events · 30 days" card, read from the table, so the funnel is visible without PostHog.

### Web analytics (`src/components/Analytics.tsx`, `src/lib/analytics.ts`)

posthog-js is pinned to 1.434.18 and loaded with a dynamic import, only when `NEXT_PUBLIC_POSTHOG_KEY` was set at build time. Settings:

- `persistence: 'localStorage'`: no cookies.
- `respect_dnt`.
- No autocapture, session recording or surveys.
- `person_profiles: 'identified_only'`.
- Page views on route changes.

`before_send` scrubs every URL property. Only `utm_*`, `src` and `ref` survive. Private path segments (`/invite/`, `/shared/`, `/study/`, `/workspaces/`, `/account/vessel/`, `/admin/chat-preview/`) become `:id`.

Signed-in users are identified by user id and role, never by email. Admin accounts opt out on their device.

The privacy page names PostHog under data sharing and in the cookie section.

### Search basics

- `robots.ts`: the app behind sign-in, the API and one-time links are disallowed.
- `sitemap.ts`: the public pages (`PUBLIC_PAGES` in `lib/seo.ts`).
- Root `metadataBase` and the title template `%s | RegKnot`.
- `opengraph-image.tsx`: a 1200×630 card built at build time.
- `pageMetadata()` gives each public page a canonical URL, an Open Graph and Twitter card, and the share image.
- `noindex` on sign-in, reset and verify pages, the whitelisting form, and the partner promo pages (`/ass`, `/captainkarynn`, `/womenoffshore`), so promo pricing doesn't surface in search.
- Search-console verification tags are emitted only when `NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION` / `NEXT_PUBLIC_BING_SITE_VERIFICATION` are set. A DNS TXT record at Namecheap works too, and covers the whole domain.

### Found while checking: public pages served a spinner

`HydrationGate` showed the loading compass on every route outside its public list, and the list left out `/practice`, `/coverage`, `/education` and `/whale-zones`. Their server HTML had no content, so a crawler that doesn't run JavaScript saw an empty page.

- They now render at once, as do the new `/regs` pages.
- `/education` and `/whale-zones` still refresh the session in the background.

## Step 3: regulation pages (shipped 2026-10-14)

### Where it lives

- **Generator:** `app/seo_pages.py`. The pages are stored in `seo_pages` (migration 0124).
- **Read API:** `routers/public_regs.py`, read-only.
- **Web:** `/regs` (hub), `/regs/c/<collection>` (lists grouped by CFR part) and `/regs/<slug>`.
  - Each page shows a plain-English summary, then each requirement with its verbatim quote, common questions, the full regulation text, related sections (our page or eCFR) and previous / next links.
  - Structured data: JSON-LD BreadcrumbList, a WebPage about a Legislation, and FAQPage.
  - Pages render on first request and are cached for an hour (ISR). The sitemap lists every published page.

### Sources

- **Included:** U.S. government works only:
  - 46 / 33 / 49 CFR;
  - the Coast Guard's Navigation Rules handbook, which carries COLREGs and the Inland Rules side by side;
  - NVIC main bodies. Enclosures are listed but not explained.
- **Excluded:** IMO text. imo.org's terms bar commercial reuse.

### Selection: 1,194 pages

| Collection | Pages |
|---|---|
| Subchapter M (46 CFR 136–144) | 196 |
| Credentials (46 CFR 10–16) | 316 |
| 33 CFR 151 / 155 | 178 |
| 33 CFR 164 | 26 |
| Navigation Rules | 39 |
| NVICs | 247 |
| Frequently cited | 192 |

"Frequently cited" means 46 / 33 / 49 CFR sections cited at least twice in answers.

Reserved sections, and sections under 250 characters, get no page. 33 CFR 83 has no separate pages: it would duplicate the Navigation Rules pages.

### Writing and checks

Sonnet 5.5 writes each page through the Batch API, with structured output and effort `low`. The prompt says:

- Every requirement and every FAQ answer carries a quote copied exactly from the text.
- Numbers appear exactly as the text gives them.
- Every limiting qualifier is kept.
- NVICs are described as guidance.

A page is published only if every check passes:

1. **Quotes:** each quote is found in the section text, after normalising whitespace, typography and case.
2. **Numbers:** every number in the plain English appears in the text. Citations and paragraph designators are skipped, and number words are counted ("twelve" = 12).
3. **Citations:** every section named exists in the corpus, or the text itself names it.
4. **Support:** a second model (Sonnet 5.5) confirms that each statement adds nothing and drops no qualifier.

A page that fails is held, never served, and gets one rewrite with its failures fed back.

### Pilot findings (42 pages)

- **Haiku as the support checker missed a broadening:** a 33 CFR 155.1070 statement dropped "identified in paragraph (c)". The checker is now Sonnet.
- **The first citation check was too strict:** it rejected references the text itself makes, such as 46 U.S.C. 3708 and "Part 151".
- **Yield:** 67% passed on the first draft and 95% after one rewrite.

### Results

- **Full run:** 1,152 drafts.
  - The batch ended in 15 minutes with all 1,152 succeeded.
  - 787 passed on the first draft; 253 more passed after one rewrite.
- **Published:** 1,147 pages after a third pass, which recovered 65 of the 112 held:

  | Collection | Published |
  |---|---|
  | Subchapter M | 189 |
  | Credentials | 303 |
  | Pollution | 166 |
  | Navigation safety | 25 |
  | Navigation rules | 37 |
  | NVICs | 242 |
  | Frequently cited | 185 |

- **Held:** 47. They are not served. The failures are real (dropped qualifiers, broadened exceptions); review them with `status`.
- **Spend:** about $40–50 of the $200 promotional credit. That covers half-price batch writing, plus the Sonnet checks and rewrites.

### Upkeep

The weekly Celery task `refresh_seo_pages` runs Monday 12:00 UTC.

- It rebuilds the selection.
- It holds every page whose regulation text changed, and adds new sections as drafts.
- It writes those pages again, at most 50 a week.

CLI on the VPS, from apps/api: `uv run python -m app.seo_pages status | select | pilot N | batch | retry [--again] | recheck [held|published] | refresh`.

## Step 2: one free answer before signup (built 2026-10-14, off until keyed)

### How it works

- **Endpoint:** `POST /public/ask/stream` (`routers/guest_chat.py`, `app/guest.py`, migration 0125 `guest_questions`). The visitor's question goes through the normal chat stream as an internal guest account (`guest@guest.regknots.invalid`).
  - The account is verified, on the Captain tier and `is_internal`, so no cap applies and admin numbers leave it out.
  - The stream opens with a `guest` event carrying a claim secret.
- **Claim:** the browser keeps that secret, and registration sends it as `guest_claim`. Then:
  - the conversation and the vessel type the visitor picked move to the new account;
  - onboarding is marked done;
  - the web opens `/?conversation_id=…`.
- **Limits:**
  - one question per device per 30 days (a random id in localStorage, stored HMAC-hashed);
  - 6 per IP per day (crews share IPs);
  - 30 a day and 300 a month across all visitors, at most about $60 a month.
- **Bot check:** Cloudflare Turnstile.
- **Retention:** unclaimed guest conversations are deleted after 30 days, by the daily purge task.
- **Widget:** `GuestAsk` runs on `/regs` pages, where the sign-up box is the fallback, and on `/landing`, where it shows nothing while the feature is off.
  - Optional vessel-type chips.
  - The answer streams in.
  - A "Save this answer and keep asking" button follows.
- **Funnel events:** `guest_question` and `guest_claimed`.

### Verified on prod (2026-10-14)

The test ran in a separate process with Cloudflare's always-pass test secret; prod config was unchanged.

- **Stream:** the claim event came first, then 259 text chunks.
- **Answer:** an Opus 5.5 answer citing 46 CFR 138.220 / 138.310 / 137.130, in 33 s.
- **Device limit:** a second question from the same device got `429 guest_used`.
- **Cleanup:** the test rows were deleted.
- **Claim on registration:** unit-tested only, because no account was registered on prod.

### Turning it on

Set these in the prod `.env`, then run `scripts/deploy.sh` (the web build reads the site key):

- `TURNSTILE_SECRET_KEY`
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
- `REGKNOTS_ANON_CHAT_ENABLED=true`

The caps are `REGKNOTS_ANON_DAILY_CAP`, `_MONTHLY_CAP` and `_IP_DAILY_CAP`.

## Step 4: Wheelhouse pilots and the demo fleet (shipped 2026-10-14)

### Trial ends

Migration 0126 adds `workspaces.trial_ends_at` (NULL = 30 days from creation, as before).

- The daily state machine reads `COALESCE(trial_ends_at, created_at + 30 days)`.
- It sends the reminder 5 days before the end and moves the workspace to `card_pending` at the end.
- The workspace banner counts down to the real end.

### Pilot codes (`pilot_codes`, `app/pilots.py`)

- **Link:** `/register?next=/workspaces&src=pilot-<code>`.
- **New owners:** an owner who signs up from the link gets the code's trial (90 days by default) on the workspace they create.
- **Admin › Customers › Pilots:**
  - create, pause and copy codes;
  - see signups and workspaces per code;
  - see every workspace with its trial end;
  - "Set trial" for an existing customer. It reopens a card-pending workspace when the new end is still ahead, and it is audit-logged.

### Demo fleet

`scripts/demo/seed_demo_workspace.py [--reset]`, run on the VPS from apps/api.

- **The fleet:** "Gulf Coast Marine Towing (Demo)", with:
  - the M/V Bay Pioneer;
  - four fictional crew on `@demo.regknots.invalid`. They are internal and can't sign in.
- **Crew records:** credentials, including an expired TWIC and a medical due in 40 days, and sea time.
- **Also seeded:** a watch handoff note, and a fictional TSMS excerpt as a company document (`scripts/demo/demo_tsms.txt`, 10 chunks).
- **Access:** Blake owns it and Karynn is an admin.
- **Fleet Audit Readiness on it:**
  - score 45;
  - critical: no COI on file, Rosa's TWIC expired;
  - warnings: Dale's medical, missing TWIC and drug-test records.
- **Fix found in the process:** the first run listed Blake's and Karynn's own credentials among the findings. Admin accounts in an internal-only workspace are now left out of the assessment.
- **`--reset`** clears the demo's conversations and recreates everything with fresh dates.

## Blake's steps

1. **PostHog:**
   - Create a project on PostHog Cloud (US).
   - Add `NEXT_PUBLIC_POSTHOG_KEY=phc_…` to `/opt/RegKnots/.env`, plus `NEXT_PUBLIC_POSTHOG_HOST` if the project is in the EU region.
   - Run `scripts/deploy.sh`. The web build reads the key, and the API reads the same line.
2. **Cloudflare Turnstile:**
   - Add a widget for regknots.com (managed mode).
   - Put `TURNSTILE_SECRET_KEY` and `NEXT_PUBLIC_TURNSTILE_SITE_KEY` in the prod `.env`, with `REGKNOTS_ANON_CHAT_ENABLED=true`.
   - Run `scripts/deploy.sh`.
3. **Google Search Console:**
   - Add a Domain property for regknots.com and verify it with the DNS TXT record at Namecheap.
   - Submit `https://regknots.com/sitemap.xml`.
4. **Bing Webmaster Tools:** import from Search Console.
5. **Stripe dashboard:** add `customer.subscription.created` and `customer.subscription.deleted` to the webhook endpoint. The handler already processes both.
