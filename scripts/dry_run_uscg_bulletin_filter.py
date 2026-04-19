"""Classification-only dry run for the USCG bulletin filter.

Fetches every Wayback-indexed bulletin, runs the two-pass filter,
writes accept/reject results to JSON — BUT DOES NOT embed or upsert.

Output:
  data/raw/uscg_bulletins/dry_run_accepted.json    (list of accepted bulletins)
  data/raw/uscg_bulletins/rejected.log             (tab-separated rejects)
  data/raw/uscg_bulletins/llm_classifications.log  (per-call LLM audit)

Then runs regression tests against data/raw/uscg_bulletins/regression_set.json:
  - Every known_good gd_id MUST be re-accepted
  - Every mislabeled gd_id MUST be either rejected OR correctly re-labeled
    (section_number must NOT be the old wrong canonical ID)

Usage on VPS:
    cd /opt/RegKnots/packages/ingest
    uv run python /tmp/dry_run_uscg_bulletin_filter.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/opt/RegKnots/packages/ingest")

from ingest.config import settings
from ingest.sources.uscg_bulletin import (
    _fetch_and_filter_all,
    _read_ids_file,
)

IDS_FILE = Path("/opt/RegKnots/data/raw/uscg_bulletins/wayback_ids.txt")
REJECTED = Path("/opt/RegKnots/data/raw/uscg_bulletins/rejected.log")
LLM_LOG = Path("/opt/RegKnots/data/raw/uscg_bulletins/llm_classifications.log")
ACCEPTED_JSON = Path("/opt/RegKnots/data/raw/uscg_bulletins/dry_run_accepted.json")
REGRESSION_JSON = Path("/opt/RegKnots/data/raw/uscg_bulletins/regression_set.json")


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ids = _read_ids_file(IDS_FILE)
    print(f"Dry-running filter over {len(ids)} bulletin IDs")

    if not settings.anthropic_api_key:
        print("WARNING: ANTHROPIC_API_KEY not set — all LLM-candidates will be auto-rejected (fail-closed).")

    accepted, stats = asyncio.run(
        _fetch_and_filter_all(ids, REJECTED, LLM_LOG, settings.anthropic_api_key or None)
    )

    # Serialize accepted set for audit (drop body text to keep file small)
    slim = []
    for a in accepted:
        d = asdict(a)
        d["body_text"] = d["body_text"][:200] + ("…" if len(d["body_text"]) > 200 else "")
        d["pdf_text"] = ""  # drop
        d["published_date"] = d["published_date"].isoformat() if d["published_date"] else None
        d["expires_date"] = d["expires_date"].isoformat() if d["expires_date"] else None
        slim.append(d)
    ACCEPTED_JSON.write_text(json.dumps(slim, indent=2))

    # ── Stats summary ────────────────────────────────────────────────
    print()
    print("=== Stats ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # ── Regression checks ────────────────────────────────────────────
    print()
    print("=== Regression checks ===")
    if not REGRESSION_JSON.exists():
        print(f"  regression_set.json not found at {REGRESSION_JSON} — skipping")
        return

    reg = json.loads(REGRESSION_JSON.read_text())
    accepted_by_id = {a.gd_id: a for a in accepted}

    # A. known_good: every gd_id must be in accepted
    print()
    print(f"A. known_good (must re-accept): {len(reg['known_good'])} items")
    ok, missing = 0, []
    for rec in reg["known_good"]:
        if rec["gd_id"] in accepted_by_id:
            a = accepted_by_id[rec["gd_id"]]
            ok += 1
            print(f"   ✓ {rec['gd_id']}  canonical_now={a.canonical_id}  "
                  f"(was: {rec['prior_section_number']})")
        else:
            missing.append(rec)
            print(f"   ✗ {rec['gd_id']}  MISSING  (was: {rec['prior_section_number']})")
    print(f"   → {ok}/{len(reg['known_good'])} re-accepted.")

    # B. mislabeled: never re-accepted under the old wrong canonical ID
    print()
    print(f"B. mislabeled (must NOT re-accept under the old wrong canonical ID): "
          f"{len(reg['mislabeled'])} items")
    correct_reject = 0
    correct_relabel = 0
    still_wrong = []
    for rec in reg["mislabeled"]:
        gd_id = rec["gd_id"]
        prior = rec["prior_section_number"]
        a = accepted_by_id.get(gd_id)
        if a is None:
            correct_reject += 1
        elif a.canonical_id == prior:
            still_wrong.append((rec, a))
            print(f"   ✗ {gd_id}  STILL MISLABELED as {a.canonical_id}  subj={a.subject[:80]}")
        else:
            correct_relabel += 1
    print(f"   → {correct_reject} correctly rejected, {correct_relabel} correctly re-labeled, "
          f"{len(still_wrong)} STILL WRONG")

    # ── Samples for human review ───────────────────────────────────────
    print()
    print("=== Sample of accepted (first 30) ===")
    for a in accepted[:30]:
        print(f"  [{a.bulletin_type:<22}] {a.canonical_id:<48}  {a.subject[:80]}")

    print()
    print("=== By bulletin_type ===")
    c = Counter(a.bulletin_type for a in accepted)
    for t, n in sorted(c.items(), key=lambda x: -x[1]):
        print(f"  {t:<30} {n}")


if __name__ == "__main__":
    main()
