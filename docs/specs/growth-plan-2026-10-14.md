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

### Blake's steps

1. **PostHog:** create a project on PostHog Cloud (US). Add `NEXT_PUBLIC_POSTHOG_KEY=phc_…` to `/opt/RegKnots/.env`, and `NEXT_PUBLIC_POSTHOG_HOST` if the project is in the EU region. Then run `scripts/deploy.sh`: the web build reads the key, and the API reads the same line.
2. **Google Search Console:** add a Domain property for regknots.com and verify it with the DNS TXT record (or the URL-prefix property and the meta tag env var). Submit `https://regknots.com/sitemap.xml`.
3. **Bing Webmaster Tools:** import from Search Console.
4. **Stripe dashboard:** add `customer.subscription.created` and `customer.subscription.deleted` to the webhook endpoint. The handler already processes both.
