"""Import an outreach lead list into a salesperson's lead tracker (2026-10-16,
shared with Admin > Sales on 2026-10-17).

Rows already imported (same lead_ref for the owner) are updated in place with
the latest contact fields; the status is left alone once the owner has moved it
past 'new'. Outreach statuses map: new/call -> new; contacted/sent/replied ->
contacted; opted_out/closed -> lost. The CSV is data/outreach/leads.csv's
format (scripts/outreach/build_leads.py): id, niche, company, dba, city, state,
phone, website, contact_name, contact_role, contact_email, towboats, tugs,
passenger, osv, service, commodities, area, status, notes.
"""
from __future__ import annotations

import uuid

STATUS = {"new": "new", "call": "new", "contacted": "contacted", "sent": "contacted", "replied": "contacted",
          "opted_out": "lost", "closed": "lost"}


def _num(v) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if v and v.replace(".", "", 1).isdigit() else None


def _txt(r: dict, key: str, n: int) -> str | None:
    return (r.get(key) or "").strip()[:n] or None


async def import_lead_rows(pool, owner_id: uuid.UUID, rows: list[dict], niche: str | None = "towing") -> dict:
    """Upsert rows into owner_id's leads. Returns {inserted, updated, skipped, rows}."""
    inserted = updated = skipped = 0
    for r in rows:
        if niche and (r.get("niche") or "").strip() != niche:
            skipped += 1
            continue
        ref = (r.get("id") or "").strip()[:80]
        company = (r.get("company") or "").strip()[:200]
        if not ref or not company:
            skipped += 1
            continue
        f = dict(
            company=company, dba=_txt(r, "dba", 200), city=_txt(r, "city", 100), state=_txt(r, "state", 40),
            phone=_txt(r, "phone", 60), website=_txt(r, "website", 300), contact_name=_txt(r, "contact_name", 120),
            contact_role=_txt(r, "contact_role", 120), contact_email=_txt(r, "contact_email", 200),
            towboats=_num(r.get("towboats")), tugs=_num(r.get("tugs")), passenger=_num(r.get("passenger")),
            osv=_num(r.get("osv")), service=_txt(r, "service", 300), commodities=_txt(r, "commodities", 300),
            area=_txt(r, "area", 300), status=STATUS.get((r.get("status") or "new").strip(), "new"),
            notes=_txt(r, "notes", 8000),
        )
        existing = await pool.fetchrow("SELECT id FROM sales_leads WHERE owner_user_id = $1 AND lead_ref = $2",
                                       owner_id, ref)
        if existing:
            await pool.execute(
                """UPDATE sales_leads SET company=$3, dba=$4, city=$5, state=$6, phone=$7, website=$8, contact_name=$9,
                        contact_role=$10, contact_email=$11, towboats=$12, tugs=$13, passenger=$14, osv=$15, service=$16,
                        commodities=$17, area=$18, status = CASE WHEN status = 'new' THEN $19 ELSE status END,
                        updated_at = now()
                   WHERE id = $1 AND owner_user_id = $2""",
                existing["id"], owner_id, f["company"], f["dba"], f["city"], f["state"], f["phone"], f["website"],
                f["contact_name"], f["contact_role"], f["contact_email"], f["towboats"], f["tugs"], f["passenger"],
                f["osv"], f["service"], f["commodities"], f["area"], f["status"])
            updated += 1
        else:
            await pool.execute(
                """INSERT INTO sales_leads (owner_user_id, lead_ref, source, company, dba, city, state, phone, website,
                        contact_name, contact_role, contact_email, towboats, tugs, passenger, osv, service, commodities,
                        area, status, notes)
                   VALUES ($1, $2, 'outreach', $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
                           $19, $20)""",
                owner_id, ref, f["company"], f["dba"], f["city"], f["state"], f["phone"], f["website"],
                f["contact_name"], f["contact_role"], f["contact_email"], f["towboats"], f["tugs"], f["passenger"],
                f["osv"], f["service"], f["commodities"], f["area"], f["status"], f["notes"])
            inserted += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "rows": len(rows)}
