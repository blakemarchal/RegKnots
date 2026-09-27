"""Build the outreach seed list from public-domain U.S. Army Corps data (2026-09-27).

Source: "Waterborne Transportation Lines of the United States", vessel company
summary for calendar year 2017 (published 2018), operator file TS17OP from the
USACE Digital Library. It lists every U.S. vessel operating company with its
address, phone, operating area, principal commodities and vessel counts by type
(pushboats, tugs, passenger, OSV, ...). The newest edition in the digital library
is 2017, so each lead is verified (still operating, current contact) before any
email is drafted.

Writes data/outreach/leads.csv (gitignored: prospect state never goes into git).
Existing rows keep their status and notes; only new companies are appended.

    python scripts/outreach/build_leads.py                 # towing, 2-40 towing vessels
    python scripts/outreach/build_leads.py --niche passenger
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
from pathlib import Path

TS17OP_URL = "https://usace.contentdm.oclc.org/digital/api/collection/p16021coll2/id/2995/download"
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "outreach" / "leads.csv"

COLUMNS = [
    "id", "niche", "company", "dba", "city", "state", "phone", "towboats", "tugs", "passenger", "osv",
    "service", "commodities", "area",
    # filled in by the outreach task
    "status", "website", "contact_name", "contact_role", "contact_email",
    "drafted_at", "sent_at", "followups", "replied_at", "notes",
]


def _int(value: str) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def load_operators(url: str = TS17OP_URL) -> list[dict[str, str]]:
    with urllib.request.urlopen(url, timeout=120) as resp:
        text = resp.read().decode("latin-1")
    rows = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): (v or "").strip() if isinstance(v, str) else "" for k, v in r.items()} for r in rows]


def in_niche(op: dict[str, str], niche: str) -> bool:
    towing = _int(op.get("PUSH")) + _int(op.get("TUG"))
    if niche == "towing":
        return 2 <= towing <= 40
    if niche == "passenger":
        return _int(op.get("PASS")) >= 1
    if niche == "osv":
        return _int(op.get("OSV")) >= 1
    raise ValueError(niche)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", choices=["towing", "passenger", "osv"], default="towing")
    args = ap.parse_args()

    existing: list[dict[str, str]] = []
    if OUT.exists():
        existing = list(csv.DictReader(OUT.open(encoding="utf-8", newline="")))
    seen = {(r["company"].lower(), r["state"]) for r in existing}
    next_n = max((int(r["id"].split("-")[1]) for r in existing if r.get("id", "").startswith("ob-")), default=0) + 1

    added = 0
    for op in load_operators():
        if not in_niche(op, args.niche):
            continue
        key = (op.get("NAME", "").lower(), op.get("STATE", ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        phone = f"({op['AREA']}) {op['PHONE']}" if op.get("AREA") and op.get("PHONE") else op.get("PHONE", "")
        existing.append({
            "id": f"ob-{next_n:04d}", "niche": args.niche,
            "company": op.get("NAME", ""), "dba": op.get("DBA", ""),
            "city": op.get("CITY", "").title(), "state": op.get("STATE", ""), "phone": phone,
            "towboats": str(_int(op.get("PUSH"))), "tugs": str(_int(op.get("TUG"))),
            "passenger": str(_int(op.get("PASS"))), "osv": str(_int(op.get("OSV"))),
            "service": op.get("SERVICE", ""), "commodities": op.get("PRINC_COMM", ""),
            "area": op.get("POINT_LOC", ""), "status": "new",
        })
        next_n += 1
        added += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in existing:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    print(f"{args.niche}: {added} new leads; {len(existing)} rows in {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
