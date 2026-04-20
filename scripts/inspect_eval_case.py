"""Inspect a single eval case by vessel + qid."""
import json
import sys

path = sys.argv[1]
target_v = sys.argv[2]
target_q = sys.argv[3]

for line in open(path):
    r = json.loads(line)
    if r["vessel_code"] == target_v and r["qid"] == target_q:
        print(f"=== {target_v} / {target_q} — grade {r['grade']} ===")
        print(f"Reason: {r['grade_reason']}")
        print()
        print("Citations:")
        for i, c in enumerate(r["citations"], 1):
            print(f"  {i:2}. [{c['source']}] {c['section_number']} — {c['section_title'][:70]}")
        print()
        print("Unverified:", r.get("unverified", []))
        print()
        print("ANSWER (first 1200 chars):")
        print(r["answer"][:1200])
        break
