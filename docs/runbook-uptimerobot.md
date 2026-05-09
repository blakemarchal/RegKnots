# UptimeRobot setup runbook

External alerting for RegKnots. Closes the gap caught in the
2026-05-08 audit (May 1 OOM crashloop ran 9 hours undetected because
Sentry uptime only checked `/landing` + `/`).

**Cost:** $0 (free tier covers everything below).

**Time:** ~15 min once.

---

## 1. Sign up

Go to https://uptimerobot.com and create an account using the email you
want to receive alerts on. The free tier gives 50 monitors, 5-min
polling interval, email + webhook alerts, multi-region probes, and —
critically — keyword/body-string assertions.

There is no payment step on the free tier.

## 2. Add monitors

In the dashboard, click **+ Add New Monitor** for each entry below.
For every monitor:

- Monitor Type: `HTTP(s)`
- Monitoring Interval: `5 minutes` (free-tier minimum)
- Monitor Timeout: `30 seconds`
- HTTP Method: `GET`
- Alert Contacts to Notify: select your email + (optional) Discord
  webhook (set up in §3 below)

The seven monitors:

| # | Monitor Name | URL | Keyword (Existing) |
|---|---|---|---|
| 1 | RegKnots — API health | `https://regknots.com/api/health` | `"postgres":true` |
| 2 | RegKnots — Landing | `https://regknots.com/landing` | `Hallucination-proof` |
| 3 | RegKnots — Study Tools | `https://regknots.com/study` | `app/study/page-` |
| 4 | RegKnots — Education | `https://regknots.com/education` | `Pass your USCG` |
| 5 | RegKnots — Account | `https://regknots.com/account` | `app/account/page-` |
| 6 | RegKnots — Login | `https://regknots.com/login` | `Sign In` |
| 7 | RegKnots — Backup heartbeat (see §4) | (UptimeRobot Heartbeat URL) | n/a |

For monitors 1-6, expand **Advanced Settings → Alert if response body
contains** and paste the keyword from the table. UptimeRobot pages
when:

- HTTP status ≠ 200 (timeout, 5xx, TLS broken), OR
- the keyword is **absent** from the response body.

The keyword check is what catches the stale-build failure mode that
hid Phase A3-A5 from us. A 200 with "Hallucination-proof" missing on
`/landing` means the build got rolled back or a Caddy misconfig is
serving the wrong content — both of which Sentry's status-only check
misses.

## 3. Optional — Discord webhook for phone push notifications

Free-tier UptimeRobot doesn't include SMS, but a Discord webhook
posting to a channel on your phone is functionally equivalent and
free.

1. In Discord, create a server (or pick an existing one), pick a
   channel like `#regknots-alerts`, **Edit Channel → Integrations →
   Webhooks → New Webhook**. Copy the webhook URL.
2. In UptimeRobot, go to **My Settings → Alert Contacts → Add Alert
   Contact**.
3. Type: `Webhook`. URL: paste the Discord webhook URL with `/slack`
   appended at the end (Discord accepts Slack-format payloads).
4. Send Notifications As: leave default. Enable for "Up", "Down", and
   "SSL Expiring".
5. Test the alert. Save.
6. Go back to each of the 7 monitors → Edit → add this alert contact
   alongside email.
7. Make sure your phone has the Discord app installed and notifications
   enabled for that channel.

When a monitor fails, you get a Discord push to your phone within
~5-7 minutes.

## 4. Backup heartbeat (Heartbeat monitor)

The 6 monitors above catch "site is down." The 7th catches "site is
up but the daily backup quietly stopped running" — a different
failure mode entirely.

1. In UptimeRobot, **+ Add New Monitor → Heartbeat**.
2. Name: `RegKnots — daily Postgres backup`.
3. Heartbeat Period: `2 hours` (the actual backup runs daily; we
   give it a 24-hour-with-margin window — set this to 30 hours).
4. UptimeRobot generates a unique URL like
   `https://heartbeat.uptimerobot.com/m<id>?hash=<hash>`.
5. SSH into the VPS and append a one-line success curl to the backup
   script's success path. The supplied path is in
   `scripts/backup_postgres.sh` — add right before the final
   `echo "[...] backup-dir summary..."` line:

   ```bash
   curl -fsS --max-time 10 -o /dev/null \
       "https://heartbeat.uptimerobot.com/m<id>?hash=<hash>" || true
   ```

   The `|| true` keeps a curl-failure (transient internet hiccup) from
   marking the backup itself as failed.
6. Commit + push + deploy this script change via `scripts/deploy.sh
   --skip-build` (api-only — no frontend rebuild needed).

When the daily backup succeeds, it pings UptimeRobot. If UR doesn't
see a ping for 30 hours, the heartbeat monitor fires — alerting you
that backups have stopped (cron broken / disk full / DB locked / VPS
rebooted and timer didn't fire).

## 5. Verify alerts work

For each of the 6 HTTP monitors, click into the monitor in the
UptimeRobot dashboard → **Send Test Alert**. You should get an email
+ (if configured) Discord push within 1-2 minutes. If not, check the
alert-contact configuration.

For the heartbeat: temporarily disable the monitor and re-enable —
that simulates a missed ping cycle.

## Operations

- **Pause during maintenance.** Free tier supports per-monitor pause —
  click the pause icon before a planned deploy + un-pause after smoke
  passes. Otherwise you get false alerts every time `scripts/deploy.sh`
  bounces a service.
- **Status page (optional).** Free tier includes one public status
  page. Consider publishing at status.regknots.com for transparency
  during the marketing push — customers seeing "all green" beats
  asking support.
- **Quarterly review.** Re-check that all 7 monitors still match the
  current keyword strings (e.g. "Hallucination-proof" copy could
  change on the landing page). When a monitor flaps because its
  keyword no longer matches but the page is fine, that's the signal
  to update the keyword to a more stable string.

## What this gives us

- **5-min mean detection latency** on hard-down events (vs. 9 hours
  on May 1).
- **Stale-build detection** via keyword assertions (vs. silent serving
  of old bundles).
- **Backup-cron rot detection** via heartbeat (vs. discovering you've
  had no backups for a month).
- **Independent infrastructure.** UptimeRobot probes are on different
  cloud providers than DigitalOcean (your VPS) and GCP (Sentry). If
  any one provider has a regional outage, the others still alert.
- **$0/mo recurring cost.** Trivially upgradable to paid ($7/mo) for
  1-min polling + SMS if you ever want it.
