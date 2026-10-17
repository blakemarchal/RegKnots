"""Import the outreach lead list into a salesperson's lead tracker (2026-10-16).

Run on the VPS from apps/api, after copying data/outreach/leads.csv there:

    .venv/bin/python /opt/RegKnots/scripts/sales/import_leads.py /root/rk-tmp/leads.csv jordan@example.com [--niche towing]

Rows already imported (same lead_ref for the owner) are updated in place with
the latest contact fields; the status is left alone once the owner has moved it
past 'new'. Outreach statuses map: new/call -> new; contacted/sent/replied ->
contacted; opted_out/closed -> lost.
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, "/opt/RegKnots/apps/api")

STATUS = {"new": "new", "call": "new", "contacted": "contacted", "sent": "contacted", "replied": "contacted",
          "opted_out": "lost", "closed": "lost"}


def num(v: str):
    v = (v or "").strip()
    return int(float(v)) if v and v.replace(".", "", 1).isdigit() else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("owner_email")
    ap.add_argument("--niche", default="towing")
    a = ap.parse_args()
    import asyncpg
    from app.config import settings
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"), min_size=1, max_size=2)
    owner = await pool.fetchval("SELECT id FROM users WHERE email = $1", a.owner_email.lower())
    if owner is None:
        raise SystemExit(f"no user {a.owner_email}")
    rows = list(csv.DictReader(Path(a.csv).open(encoding="utf-8", newline="")))
    inserted = updated = skipped = 0
    for r in rows:
        if a.niche and (r.get("niche") or "").strip() != a.niche:
            skipped += 1
            continue
        ref = (r.get("id") or "").strip()
        if not ref:
            skipped += 1
            continue
        fields = dict(
            company=(r.get("company") or "").strip()[:200], dba=(r.get("dba") or "").strip()[:200] or None,
            city=(r.get("city") or "").strip()[:100] or None, state=(r.get("state") or "").strip()[:40] or None,
            phone=(r.get("phone") or "").strip()[:60] or None, website=(r.get("website") or "").strip()[:300] or None,
            contact_name=(r.get("contact_name") or "").strip()[:120] or None,
            contact_role=(r.get("contact_role") or "").strip()[:120] or None,
            contact_email=(r.get("contact_email") or "").strip()[:200] or None,
            towboats=num(r.get("towboats")), tugs=num(r.get("tugs")), passenger=num(r.get("passenger")), osv=num(r.get("osv")),
            service=(r.get("service") or "").strip()[:300] or None, commodities=(r.get("commodities") or "").strip()[:300] or None,
            area=(r.get("area") or "").strip()[:300] or None,
            status=STATUS.get((r.get("status") or "new").strip(), "new"),
            notes=(r.get("notes") or "").strip()[:8000] or None,
        )
        if not fields["company"]:
            skipped += 1
            continue
        existing = await pool.fetchrow("SELECT id, status FROM sales_leads WHERE owner_user_id = $1 AND lead_ref = $2", owner, ref)
        if existing:
            await pool.execute(
                """UPDATE sales_leads SET company=$3, dba=$4, city=$5, state=$6, phone=$7, website=$8, contact_name=$9,
                        contact_role=$10, contact_email=$11, towboats=$12, tugs=$13, passenger=$14, osv=$15, service=$16,
                        commodities=$17, area=$18, status = CASE WHEN status = 'new' THEN $19 ELSE status END,
                        updated_at = now()
                   WHERE id = $1 AND owner_user_id = $2""",
                existing["id"], owner, fields["company"], fields["dba"], fields["city"], fields["state"], fields["phone"],
                fields["website"], fields["contact_name"], fields["contact_role"], fields["contact_email"], fields["towboats"],
                fields["tugs"], fields["passenger"], fields["osv"], fields["service"], fields["commodities"], fields["area"],
                fields["status"])
            updated += 1
        else:
            await pool.execute(
                """INSERT INTO sales_leads (owner_user_id, lead_ref, source, company, dba, city, state, phone, website,
                        contact_name, contact_role, contact_email, towboats, tugs, passenger, osv, service, commodities,
                        area, status, notes)
                   VALUES ($1, $2, 'outreach', $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)""",
                owner, ref, fields["company"], fields["dba"], fields["city"], fields["state"], fields["phone"], fields["website"],
                fields["contact_name"], fields["contact_role"], fields["contact_email"], fields["towboats"], fields["tugs"],
                fields["passenger"], fields["osv"], fields["service"], fields["commodities"], fields["area"], fields["status"],
                fields["notes"])
            inserted += 1
    await pool.close()
    print(f"inserted {inserted}, updated {updated}, skipped {skipped} of {len(rows)} rows")


if __name__ == "__main__":
    asyncio.run(main())
