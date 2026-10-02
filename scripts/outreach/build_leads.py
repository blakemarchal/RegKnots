# /// script
# requires-python = ">=3.11"
# dependencies = ["pdfplumber>=0.11"]
# ///
"""Build the outreach lead list (data/outreach/leads.csv, gitignored: prospect
state never goes into git). Existing rows keep their status and notes; only new
companies are appended, with the next ob-NNNN id.

Sources:

  usace (2026-09-27)  "Waterborne Transportation Lines of the United States",
      vessel company summary for 2017, operator file TS17OP (USACE Digital
      Library): address, phone, area, commodities and vessel counts by type.
      Public domain, but 2017: each lead is verified before an email is drafted.

          python scripts/outreach/build_leads.py                  # towing, 2-40 towing vessels
          python scripts/outreach/build_leads.py --niche passenger

  mvus (2026-10-02)  USCG "Merchant Vessels of the United States", the monthly
      vessel documentation file (dco.uscg.mil, Text (Tab) download, comma-
      separated, no header). Towing companies whose documents are current:
      service "Towing Vessel", status Valid, a company owner (personal names
      are redacted in the file), longest towing vessel 40 ft or more. No phone
      numbers; the owner's address goes in the note. A company already in the
      list gets "MVUS <month>: N towing vessels" added to its note instead.
      dco.uscg.mil refuses curl and some networks: download on the VPS with the
      ingest package's client (sources/uscg_docs.py).

          python scripts/outreach/build_leads.py --source mvus --file vesdocSep26Rtab.zip

  nmc-courses (2026-10-02)  NMC's list of approved courses (courses.pdf, one
      table row per approved course with the school, state, website and phone).
      One lead per school that teaches a license, endorsement or STCW course;
      first-aid-only providers are left out. Niche "school".

          uv run scripts/outreach/build_leads.py --source nmc-courses --file courses.pdf

  tpo (2026-10-02)  The six Coast Guard-approved Subchapter M third-party
      organizations on TVNCOE's list (fetched 2026-10-02). Niche "tpo": a
      partnership conversation, not a sale.

          python scripts/outreach/build_leads.py --source tpo
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
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


_SUFFIX = re.compile(r"\b(?:inc|incorporated|llc|l l c|co|company|corp|corporation|lp|llp|ltd|pllc|the)\b")


def company_key(name: str) -> str:
    """"Kirby Inland Marine, L.P." and "KIRBY INLAND MARINE LP" -> "kirby inland marine"."""
    name = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and "))
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", name)).strip()


def phone_fmt(digits: str) -> str:
    d = re.sub(r"\D", "", digits or "")
    return f"({d[:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else digits


# ── usace ────────────────────────────────────────────────────────────────────

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


def usace_leads(niche: str) -> list[dict[str, str]]:
    leads = []
    for op in load_operators():
        if not in_niche(op, niche) or not op.get("NAME"):
            continue
        phone = f"({op['AREA']}) {op['PHONE']}" if op.get("AREA") and op.get("PHONE") else op.get("PHONE", "")
        leads.append({
            "niche": niche, "company": op.get("NAME", ""), "dba": op.get("DBA", ""),
            "city": op.get("CITY", "").title(), "state": op.get("STATE", ""), "phone": phone,
            "towboats": str(_int(op.get("PUSH"))), "tugs": str(_int(op.get("TUG"))),
            "passenger": str(_int(op.get("PASS"))), "osv": str(_int(op.get("OSV"))),
            "service": op.get("SERVICE", ""), "commodities": op.get("PRINC_COMM", ""),
            "area": op.get("POINT_LOC", ""),
        })
    return leads


# ── mvus ─────────────────────────────────────────────────────────────────────

# Column positions in the vesdoc file (no header row; read 2026-10-02).
M_NAME, M_SERVICE, M_LENGTH, M_PORT_CITY, M_PORT_STATE = 1, 7, 12, 23, 24
M_OWNER, M_ENTITY, M_STREET, M_CITY, M_STATE, M_ZIP, M_STATUS = 53, 54, 59, 63, 64, 67, 74
_COMPANY_ENTITIES = {"Corporation", "Limited Liability Company", "Partnership", "Unknown"}
_ASSISTANCE = re.compile(r"TOWBOATUS|TOW ?BOAT ?US|SEA ?TOW|BOAT TOWING|MARINE ASSIST")


def _mvus_rows(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            with z.open(name) as f:
                yield from csv.reader(io.TextIOWrapper(f, encoding="latin-1", newline=""))
    else:
        with path.open(encoding="latin-1", newline="") as f:
            yield from csv.reader(f)


def mvus_leads(path: Path, month: str, min_length: float = 40.0, max_fleet: int = 40) -> list[dict[str, str]]:
    fleets: dict[str, list[list[str]]] = defaultdict(list)
    for r in _mvus_rows(path):
        if len(r) <= M_STATUS or r[M_SERVICE] != "Towing Vessel" or r[M_STATUS] != "Valid":
            continue
        owner = r[M_OWNER].strip()
        if not owner or owner == "Privacy" or r[M_ENTITY] not in _COMPANY_ENTITIES:
            continue
        fleets[owner.upper()].append(r)
    leads = []
    for owner, boats in fleets.items():
        lengths = [float(b[M_LENGTH] or 0) if re.match(r"^[\d.]+$", b[M_LENGTH] or "") else 0.0 for b in boats]
        if max(lengths) < min_length or len(boats) > max_fleet or _ASSISTANCE.search(owner):
            continue
        first = boats[0]
        ports = Counter(f"{b[M_PORT_CITY].title()}, {b[M_PORT_STATE]}" for b in boats if b[M_PORT_CITY])
        address = ", ".join(x for x in (first[M_STREET].title() if first[M_STREET] != "Privacy" else "",
                                         first[M_CITY].title(), f"{first[M_STATE]} {first[M_ZIP][:5]}".strip()) if x)
        leads.append({
            "niche": "towing", "company": owner, "city": first[M_CITY].title(), "state": first[M_STATE],
            "towboats": str(len(boats)),
            "service": f"MVUS: {len(boats)} towing vessel{'s' if len(boats) > 1 else ''}, longest {max(lengths):.0f} ft",
            "area": "; ".join(p for p, _ in ports.most_common(2)),
            "notes": f"MVUS {month} (current USCG documentation); owner address {address}",
        })
    return leads


# ── nmc-courses ──────────────────────────────────────────────────────────────

_LICENSE_COURSE = re.compile(
    r"OUPV|Master|Mate|Able Seaman|Assistance Towing|Radar|ARPA|ECDIS|Rules of the Road|Engineer|QMED|"
    r"Tankerman|Tanker|Lifeboat|Proficiency in Survival|Basic Training|Basic Safety|Fire ?Fighting|"
    r"Navigation|Celestial|Watchkeeping|Leadership|Towing|GMDSS|Vessel Personnel|Crowd|Ratings",
    re.I)
# Facility security courses (FSO, facility personnel) are for port staff, not mariners: a
# provider that teaches only those is not a school lead. Vessel security duties match above.


def nmc_course_leads(path: Path) -> list[dict[str, str]]:
    import pdfplumber  # only this source needs it (uv run reads the script header)

    schools: dict[str, dict] = {}
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 6 or (row[0] or "").strip() == "SchoolName":
                        continue
                    name = re.sub(r"\s+", " ", (row[0] or "").replace("\n", " ")).strip()
                    if not name:
                        continue
                    course = re.sub(r"\s+", " ", (row[1] or "").replace("\n", " ")).strip()
                    url = (row[4] or "").replace("\n", "").strip("# ")
                    url = url[url.rfind("http"):] if "http" in url else url
                    s = schools.setdefault(company_key(name), {"name": name, "state": "", "phone": "", "url": "",
                                                               "courses": Counter()})
                    s["state"] = s["state"] or (row[3] or "").strip()
                    s["phone"] = s["phone"] or (row[5] or "").strip()
                    s["url"] = s["url"] or url.rstrip("#")
                    if course:
                        s["courses"][course] += 1
    leads = []
    for s in schools.values():
        teaching = [c for c in s["courses"] if _LICENSE_COURSE.search(c)]
        if not teaching:
            continue
        sample = ", ".join(sorted(teaching, key=lambda c: -s["courses"][c])[:4])
        leads.append({
            "niche": "school", "company": s["name"], "state": s["state"], "phone": phone_fmt(s["phone"]),
            "website": s["url"], "service": f"NMC-approved courses: {len(s['courses'])} ({sample})",
            "notes": "NMC approved-course list (courses.pdf)",
        })
    return leads


# ── tpo ──────────────────────────────────────────────────────────────────────

# TVNCOE "Coast Guard Approved TPOs" (46 CFR 139.115), fetched 2026-10-02. All six may
# audit TSMSs, issue TSMS certificates and survey towing vessels.
TPOS = [
    ("Gallagher Marine Systems (GMS)", "Moorestown", "NJ", "", "", "305 Harper Dr."),
    ("Inland Towing Operators Working Together (ITOW)", "Henderson", "KY", "(270) 212-2026",
     "info@inlandtowingoperators.com", "P.O. Box 1342"),
    ("Quality Management International, Inc. (QMII)", "Ashburn", "VA", "", "", "44081 Pipeline Plz, Ste 115"),
    ("Sabine Surveyors", "Metairie", "LA", "(504) 831-9100", "", "2424 Edenborn Ave., Suite 620"),
    ("Towing Vessel Inspection Bureau (TVIB)", "Channelview", "TX", "(832) 323-3992", "",
     "15201 East Freeway, Suite 213"),
    ("WaveCrest Inc.", "Katy", "TX", "", "", "21366 Provincial Blvd"),
]
_TPO_SITES = {"Sabine Surveyors": "http://sabinesurveyors.com", "Towing Vessel Inspection Bureau (TVIB)": "https://www.thetvib.org"}


def tpo_leads() -> list[dict[str, str]]:
    return [{
        "niche": "tpo", "company": name, "city": city, "state": state, "phone": phone,
        "website": _TPO_SITES.get(name, ""), "contact_email": email,
        "service": "Coast Guard-approved Subchapter M TPO (TSMS audits, surveys)",
        "notes": f"TVNCOE approved-TPO list 2026-10-02; {street}, {city}, {state}"
                 + ("; email published on the TVNCOE list" if email else ""),
    } for name, city, state, phone, email, street in TPOS]


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["usace", "mvus", "nmc-courses", "tpo"], default="usace")
    ap.add_argument("--niche", choices=["towing", "passenger", "osv"], default="towing", help="usace only")
    ap.add_argument("--file", type=Path, help="mvus: the vesdoc .zip or .txt; nmc-courses: courses.pdf")
    ap.add_argument("--month", default="2026-09", help="mvus: the file's month, for the notes")
    args = ap.parse_args()
    if args.source in ("mvus", "nmc-courses") and not args.file:
        ap.error(f"--source {args.source} needs --file")

    existing: list[dict[str, str]] = []
    if OUT.exists():
        existing = list(csv.DictReader(OUT.open(encoding="utf-8", newline="")))
    by_key = {company_key(r["company"]): r for r in existing}
    next_n = max((int(r["id"].split("-")[1]) for r in existing if r.get("id", "").startswith("ob-")), default=0) + 1

    if args.source == "usace":
        leads = usace_leads(args.niche)
    elif args.source == "mvus":
        leads = mvus_leads(args.file, args.month)
    elif args.source == "nmc-courses":
        leads = nmc_course_leads(args.file)
    else:
        leads = tpo_leads()

    added = noted = 0
    for lead in leads:
        key = company_key(lead["company"])
        if not key:
            continue
        old = by_key.get(key)
        if old is not None:
            # Already listed: an MVUS match confirms the company still documents towing vessels.
            if args.source == "mvus" and old.get("status") == "new" and "MVUS" not in old.get("notes", ""):
                old["notes"] = "; ".join(x for x in (old.get("notes", ""), lead["service"].replace("MVUS:", f"MVUS {args.month}:")) if x)
                noted += 1
            continue
        row = {c: "" for c in COLUMNS} | lead | {"id": f"ob-{next_n:04d}", "status": "new"}
        existing.append(row)
        by_key[key] = row
        next_n += 1
        added += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in existing:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    print(f"{args.source}: {added} new leads, {noted} existing rows noted; {len(existing)} rows in {OUT}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
