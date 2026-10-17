"""Import the outreach lead list into a salesperson's lead tracker (2026-10-16).

Run on the VPS from apps/api, after copying data/outreach/leads.csv there:

    .venv/bin/python /opt/RegKnots/scripts/sales/import_leads.py /root/rk-tmp/leads.csv jordan@example.com [--niche towing]

Admin > Sales does the same from the browser (Import leads on a salesperson).
The import rules live in app/sales_leads_import.py.
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, "/opt/RegKnots/apps/api")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("owner_email")
    ap.add_argument("--niche", default="towing")
    a = ap.parse_args()
    import asyncpg
    from app.config import settings
    from app.sales_leads_import import import_lead_rows
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"), min_size=1, max_size=2)
    owner = await pool.fetchval("SELECT id FROM users WHERE email = $1", a.owner_email.lower())
    if owner is None:
        raise SystemExit(f"no user {a.owner_email}")
    rows = list(csv.DictReader(Path(a.csv).open(encoding="utf-8", newline="")))
    res = await import_lead_rows(pool, owner, rows, a.niche or None)
    await pool.close()
    print(f"inserted {res['inserted']}, updated {res['updated']}, skipped {res['skipped']} of {res['rows']} rows")


if __name__ == "__main__":
    asyncio.run(main())
