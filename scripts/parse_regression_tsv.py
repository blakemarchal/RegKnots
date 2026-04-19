"""Convert /tmp/regression_capture.tsv → regression_set.json."""
import json
import sys
from pathlib import Path

TSV = Path("/tmp/regression_capture.tsv")
OUT = Path("/opt/RegKnots/data/raw/uscg_bulletins/regression_set.json")

good, mis = [], []
state = None
for line in TSV.read_text().splitlines():
    line = line.rstrip()
    if "=== known_good ===" in line:
        state = "good"
        continue
    if "=== mislabeled ===" in line:
        state = "mis"
        continue
    if not line.strip():
        continue
    if "Output format" in line or "Field separator" in line:
        continue
    # psql's `\pset fieldsep E'\t'` leaks the literal "E" prefix into the
    # output — the actual separator emitted is "E\t", not "\t". Split on
    # that so we don't accidentally chew legitimate trailing Es.
    if "E\t" in line:
        parts = line.split("E\t")
    else:
        parts = line.split("\t")
    if len(parts) < 4:
        continue
    gd_id, sec, title, pub = parts[0], parts[1], parts[2], parts[3]
    rec = {
        "gd_id": gd_id,
        "prior_section_number": sec,
        "subject": title,
        "published_date": pub,
    }
    if state == "good":
        good.append(rec)
    elif state == "mis":
        mis.append(rec)

out = {"known_good": good, "mislabeled": mis}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, indent=2))

print(f"known_good: {len(good)}")
print(f"mislabeled: {len(mis)}")
print()
print("Sample mislabeled (first 5):")
for r in mis[:5]:
    gd = r["gd_id"]
    prior = r["prior_section_number"][:25]
    subj = r["subject"][:70]
    print(f"  {gd} | prior={prior} | subject={subj}")

print()
print("Full known_good:")
for r in good:
    print(f"  {r['gd_id']} | {r['prior_section_number']} | {r['subject'][:80]}")
