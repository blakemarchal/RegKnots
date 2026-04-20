"""Quick: inspect the F-grade records from an eval run."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/opt/RegKnots/data/eval/2026-04-20_183232/results.jsonl"

for line in open(path):
    r = json.loads(line)
    if r["grade"] != "F":
        continue
    v = r["vessel_code"]
    qid = r["qid"]
    q = r["query"][:80]
    reason = r["grade_reason"][:140]
    ans = r["answer"][:200].replace("\n", " ")
    ncits = len(r["citations"])
    print(f"=== {v} / {qid} ===")
    print(f"  Query:    {q}")
    print(f"  Reason:   {reason}")
    print(f"  Answer:   {ans}")
    print(f"  Cits:     {ncits}")
    print()
