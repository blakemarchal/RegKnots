"""Export the phone call list (2026-10-02).

Most towing companies publish no email address: 43 of the first ~60 researched were
`no_contact`, and 42 of those have a phone number in the lead row. This writes them,
and every row the outreach task marks `call`, to data/outreach/call_list.csv for Blake
to phone, best prospects first: Gulf states, then fleets of 3 to 15 towing vessels.
scripts/outreach/call_script.md is what to say and how to log the result.

    python scripts/outreach/call_list.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEADS = REPO / "data" / "outreach" / "leads.csv"
OUT = REPO / "data" / "outreach" / "call_list.csv"
GULF = {"LA", "TX", "MS", "AL", "FL"}
HOOK = {"towing": "H1 safety orientation (or H3 navigation assessment for river operators)",
        "school": "S1 free practice page", "tpo": "P1 records their auditors check"}
FIELDS = ["id", "niche", "company", "city", "state", "phone", "fleet", "website", "hook", "notes",
          "called_at", "outcome"]


def _int(value: str) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def callable_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    picked = [r for r in rows if r.get("phone", "").strip()
              and (r.get("status") == "call" or r.get("status") == "no_contact")]

    def rank(r: dict[str, str]) -> tuple:
        fleet = _int(r.get("towboats")) + _int(r.get("tugs"))
        return (r.get("state") not in GULF, not (3 <= fleet <= 15), r.get("company", ""))

    return sorted(picked, key=rank)


def main() -> None:
    rows = list(csv.DictReader(LEADS.open(encoding="utf-8", newline="")))
    picked = callable_rows(rows)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in picked:
            w.writerow({
                "id": r["id"], "niche": r.get("niche", ""), "company": r["company"], "city": r.get("city", ""),
                "state": r.get("state", ""), "phone": r["phone"],
                "fleet": str(_int(r.get("towboats")) + _int(r.get("tugs"))), "website": r.get("website", ""),
                "hook": HOOK.get(r.get("niche", ""), ""), "notes": r.get("notes", ""), "called_at": "", "outcome": "",
            })
    print(f"{len(picked)} leads to call -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
