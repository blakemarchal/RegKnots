"""Spot-check LLM classifications from the dry run output."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ACCEPTED = Path("/opt/RegKnots/data/raw/uscg_bulletins/dry_run_accepted.json")
LLM_LOG = Path("/opt/RegKnots/data/raw/uscg_bulletins/llm_classifications.log")

data = json.loads(ACCEPTED.read_text())

# Load LLM log for reason lookup
llm_map = {}
if LLM_LOG.exists():
    with LLM_LOG.open() as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            llm_map[row["gd_id"]] = row


def show(title, filter_fn, n=20):
    hits = [x for x in data if filter_fn(x)]
    print(f"\n=== {title} (total {len(hits)}) ===")
    for x in hits[:n]:
        subj = x["subject"][:110]
        gd = x["gd_id"][:8]
        r = llm_map.get(x["gd_id"], {})
        reason = (r.get("reason") or "")[:70]
        conf = r.get("confidence", "-")
        print(f"  {gd}  conf={conf}  {subj}")
        if reason:
            print(f"           → LLM reason: {reason}")


show("LLM_OTHER_REGULATORY samples", lambda x: x.get("bulletin_type") == "LLM_OTHER_REGULATORY", n=25)
show("LLM_ALCOAST_OPERATIONAL samples", lambda x: x.get("bulletin_type") == "LLM_ALCOAST_OPERATIONAL", n=15)
show("LLM_MSIB samples", lambda x: x.get("bulletin_type") == "LLM_MSIB", n=15)
show("Pass 1 ALCOAST samples (should mostly be dropped next run)", lambda x: x.get("bulletin_type") == "ALCOAST", n=15)
