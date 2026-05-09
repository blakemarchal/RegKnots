# RegKnots systemd units

Production schedules: corpus refresh + daily Postgres backup.

## What's here

- `regknots-nmc-refresh.service` / `.timer` — Sprint D6.75. One-shot job
  that runs `scripts/refresh_nmc_corpus.py`. Discovers new NMC PDFs at
  the canonical landing pages, downloads any we don't have, and
  re-ingests if anything changed. Schedules weekly (Mon 06:00 UTC).
- `regknots-backup.service` / `.timer` — Sprint post-D6.83 audit (2026-05-08).
  Daily Postgres backup via `scripts/backup_postgres.sh`. pg_dump from
  the regknots-postgres container, gzipped, written to
  `/var/backups/regknots/`, 14-day retention. Schedules daily (03:00 UTC).
- `regknots-{api,web,worker}.service.d/memory.conf` — Sprint post-D6.83
  audit (2026-05-08). Cgroup `MemoryHigh`/`MemoryMax` caps as a
  drop-in overlay on the master unit files (which live only on the
  VPS, not in this repo). When a service grows past `MemoryMax` it's
  killed by its own cgroup and `Restart=always` brings it back —
  global OOM (the May 1 incident class) doesn't fire and the rest of
  the box stays up. Install via the steps below.

## Install on the VPS

```bash
# As root on the VPS — install the unit you want.

# NMC corpus refresh:
cp /opt/RegKnots/deploy/systemd/regknots-nmc-refresh.service /etc/systemd/system/
cp /opt/RegKnots/deploy/systemd/regknots-nmc-refresh.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now regknots-nmc-refresh.timer

# Daily Postgres backup:
cp /opt/RegKnots/deploy/systemd/regknots-backup.service /etc/systemd/system/
cp /opt/RegKnots/deploy/systemd/regknots-backup.timer /etc/systemd/system/
chmod +x /opt/RegKnots/scripts/backup_postgres.sh
systemctl daemon-reload
systemctl enable --now regknots-backup.timer

# Memory cgroup caps for api/web/worker (drop-in overlays — does NOT
# replace the master unit files):
mkdir -p /etc/systemd/system/regknots-api.service.d
mkdir -p /etc/systemd/system/regknots-web.service.d
mkdir -p /etc/systemd/system/regknots-worker.service.d
cp /opt/RegKnots/deploy/systemd/regknots-api.service.d/memory.conf \
   /etc/systemd/system/regknots-api.service.d/memory.conf
cp /opt/RegKnots/deploy/systemd/regknots-web.service.d/memory.conf \
   /etc/systemd/system/regknots-web.service.d/memory.conf
cp /opt/RegKnots/deploy/systemd/regknots-worker.service.d/memory.conf \
   /etc/systemd/system/regknots-worker.service.d/memory.conf
systemctl daemon-reload
systemctl restart regknots-api regknots-web regknots-worker
# Confirm caps are active:
systemctl show regknots-api regknots-web regknots-worker \
   --property=MemoryHigh --property=MemoryMax

# Verify schedule:
systemctl list-timers --all --no-pager | grep regknots

# One-shot dry run to verify everything works:
systemctl start regknots-backup.service
journalctl -u regknots-backup.service -n 50 --no-pager
ls -la /var/backups/regknots/
```

## Operations

- **View next run:** `systemctl list-timers regknots-nmc-refresh.timer`
- **View last run output:** `journalctl -u regknots-nmc-refresh.service -n 200 --no-pager`
- **Force a run now:** `systemctl start regknots-nmc-refresh.service`
- **Disable temporarily:** `systemctl stop regknots-nmc-refresh.timer`
- **Re-enable:** `systemctl start regknots-nmc-refresh.timer`

## Adding new sources to the cadence

To add a similar refresh for, say, `mca` or `amsa`:

1. Write a `scripts/refresh_<source>_corpus.py` modeled on
   `refresh_nmc_corpus.py`.
2. Copy `regknots-nmc-refresh.{service,timer}` to
   `regknots-<source>-refresh.{service,timer}` and update the
   `ExecStart` and `Description`. Stagger `OnCalendar` so different
   sources don't all hammer on Monday morning.
3. `systemctl daemon-reload && systemctl enable --now regknots-<source>-refresh.timer`.

## Why not crontab?

systemd timers are easier to operate:
- Logs land in journald (one query for all history).
- `Persistent=true` means we don't miss a run if the VPS was down.
- `RandomizedDelaySec` spreads load across a fleet without manual jitter.
- Failure handling is integrated with `systemctl status`.

## Safety

The refresh script is **deliberately conservative**: it downloads new PDFs
to `data/raw/nmc/` but only ingests them if their basename is already
declared in `packages/ingest/ingest/sources/nmc.py`. Adding a new file to
the actual ingest set requires a code change. This prevents a rogue or
mislabeled NMC PDF from silently entering the corpus — a human reviews
new filenames and adds them to `_DOC_META` first.
