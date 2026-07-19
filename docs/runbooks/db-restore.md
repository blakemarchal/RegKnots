# Runbook — Postgres restore from backup

**Last verified: 2026-07-19** (dump `regknots-20260719-030001.sql.gz`,
762 MB, restored into a clean pgvector/pg16 container in **421 s** with
**0 errors**; row counts matched live modulo the morning corpus-refresh
churn; all 105,895 regulation embeddings present; alembic head 0114).
Re-verify quarterly or after any major schema change — the test script
pattern is at the bottom.

## Where backups live

- **Local:** `/var/backups/regknots/regknots-YYYYMMDD-HHMMSS.sql.gz`
  on the VPS (`root@68.183.130.3`). Daily 03:00 UTC via
  `regknots-backup.timer`, 14-day retention, `chmod 600`.
- **Offsite:** DO Spaces bucket `regknots-backups/postgres` via
  `regknots-backup-offsite.timer` (03:45 UTC) — once the one-time rclone
  setup in `scripts/backup_offsite.sh` is done. Fetch with
  `rclone copy offsite:regknots-backups/postgres/<file> .`
- Freshness is asserted two ways: the weekly maintenance unit fails if
  the newest dump is >26 h old, and `scripts/smoke.sh` probes backup age
  from the laptop on every deploy.

## Scenario A — restore into the running stack (data loss / bad migration)

> ~10 minutes of downtime. The API keeps serving until you drop the DB,
> so announce/stop first.

```bash
ssh root@68.183.130.3
cd /opt/RegKnots

# 1. Stop writers (leave postgres up)
systemctl stop regknots-api regknots-worker regknots-web

# 2. Pick the dump
DUMP=$(ls -t /var/backups/regknots/*.sql.gz | head -1); echo "$DUMP"

# 3. Drop + recreate the DB, then restore (~7 min for 762 MB)
docker exec regknots-postgres psql -U regknots -d postgres \
  -c "DROP DATABASE regknots WITH (FORCE)" \
  -c "CREATE DATABASE regknots OWNER regknots"
gunzip -c "$DUMP" | docker exec -i regknots-postgres \
  psql -U regknots -d regknots -q -v ON_ERROR_STOP=0 2>/tmp/restore_errors.log
wc -l /tmp/restore_errors.log   # expect 0

# 4. Sanity: counts + migration head + embeddings
docker exec regknots-postgres psql -U regknots -d regknots -tAc \
  "SELECT 'regs='||count(*) FROM regulations
   UNION ALL SELECT 'users='||count(*) FROM users
   UNION ALL SELECT 'head='||version_num FROM alembic_version
   UNION ALL SELECT 'embedded='||count(*) FROM regulations WHERE embedding IS NOT NULL"

# 5. Restart + verify
systemctl start regknots-api regknots-worker regknots-web
# from the laptop:
scripts/smoke.sh
```

Note: the dump is from 03:00 UTC — chat messages, signups, and corpus
refreshes after that time are lost. Check `journalctl -u regknots-api
--since "03:00"` for what happened in the gap if you need to notify users.

## Scenario B — VPS is gone (disk death, provider failure)

1. Provision a new droplet (Ubuntu 22.04+, ≥4 GB RAM), install Docker +
   Caddy, clone the repo to `/opt/RegKnots`.
2. Fetch the newest offsite dump:
   `rclone copy offsite:regknots-backups/postgres/<newest>.sql.gz /var/backups/regknots/`
   (rclone keys live in Blake's password manager, not on the dead box).
3. Start postgres from `infra/docker-compose.yml`
   (image **pgvector/pgvector:pg16** — same major version, or pg_dump
   compatibility is on you), create the `regknots` role/database with the
   password from `.env`, then restore as in Scenario A step 3.
4. Restore `.env` files (password manager), install systemd units from
   `deploy/systemd/`, run `scripts/deploy.sh`, point DNS, wait for ACME.
5. `scripts/smoke.sh` must pass before you call it done.

## Quarterly re-verify (throwaway container, zero prod impact)

The 2026-07-19 verification ran exactly this shape — restore the newest
dump into a disposable `pgvector/pgvector:pg16` container capped at 1 GB
(`--memory=1g`, `-c shared_buffers=256MB`), compare row counts against
live for `regulations users conversations messages vessels workspaces`,
assert `embedding IS NOT NULL` count and `alembic_version`, then destroy
the container. Budget ~10 min. If counts diverge beyond same-day churn
or stderr is non-empty, treat the backup pipeline as broken and fix
before the next nightly cycle.
