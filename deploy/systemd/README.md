# RegKnots systemd units

Sprint D6.75 — scheduled corpus refresh. After Karynn caught us 4+ months
behind on the NMC ASAP portal launch, we needed a baseline cron-style job
to keep static-ingest sources current.

## What's here

- `regknots-nmc-refresh.service` — one-shot job that runs
  `scripts/refresh_nmc_corpus.py`. Discovers new NMC PDFs at the canonical
  landing pages, downloads any we don't have, and re-ingests if anything
  changed.
- `regknots-nmc-refresh.timer` — schedules the service weekly (Mon 06:00 UTC).

## Install on the VPS

```bash
# As root on the VPS:
cp /opt/RegKnots/deploy/systemd/regknots-nmc-refresh.service /etc/systemd/system/
cp /opt/RegKnots/deploy/systemd/regknots-nmc-refresh.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now regknots-nmc-refresh.timer

# Verify schedule:
systemctl list-timers regknots-nmc-refresh.timer

# One-shot dry run to verify everything works (won't ingest if nothing new):
systemctl start regknots-nmc-refresh.service
journalctl -u regknots-nmc-refresh.service -n 50 --no-pager
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
