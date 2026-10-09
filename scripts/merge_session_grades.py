"""Merge Claude Code session grades into a compare_synthesis_models.py run (2026-10-09).

`compare_synthesis_models.py --session-judge` writes one blind packet per question to
OUT/judge_packets/<qid>.json (labels shuffled; the label -> variant map stays in
results.json under judges.session.order). Grade each packet in a Claude Code session with
its rubric (subagents on the Claude subscription instead of the paid Opus judge) and save
OUT/session_grades/<qid>.json as:

    {"grades": [{"label": "A", "accuracy": 0-10, "applicability": 0-10, "completeness": 0-10,
                 "clarity": 0-10, "overall": 0-10, "errors": ["..."]}, ...],
     "best": "A", "worst": "B"}

Then:  python scripts/merge_session_grades.py data/eval/model_compare/<run>
Writes results_merged.json and prints the judge table for the session judge and GPT-4o.
"""
import json
import statistics
import sys
from pathlib import Path


def ranks(scores: dict[str, float]) -> dict[str, float]:
    items = sorted(scores.items(), key=lambda kv: -kv[1])
    out, i = {}, 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1][1] == items[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[items[k][0]] = (i + j) / 2 + 1
        i = j + 1
    return out


def mean(xs, nd=2):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), nd) if xs else None


def main(out_dir: str) -> None:
    out = Path(out_dir)
    recs = json.loads((out / "results.json").read_text(encoding="utf-8"))
    missing = []
    for r in recs:
        sess = (r.get("judges") or {}).get("session")
        if not sess:
            continue
        f = out / "session_grades" / f"{r['qid']}.json"
        if not f.exists():
            missing.append(r["qid"])
            continue
        g = json.loads(f.read_text(encoding="utf-8"))
        lab2var = sess["order"]
        scores = {}
        for row in g.get("grades", []):
            v = lab2var.get(row.get("label"))
            if v:
                scores[v] = {k: row.get(k) for k in ("accuracy", "applicability", "completeness", "clarity",
                                                     "overall", "errors")}
        r["judges"]["session"] = {"scores": scores, "best": lab2var.get(g.get("best")),
                                  "worst": lab2var.get(g.get("worst")), "order": lab2var}
    (out / "results_merged.json").write_text(json.dumps(recs, indent=1, default=str), encoding="utf-8")
    if missing:
        print("no session grades for:", ", ".join(missing))

    variants = sorted({v for r in recs for v in (r.get("runs") or {})})
    print(f"\n{'judge metric':30}" + "".join(f"{v:>12}" for v in variants))
    for judge in ("session", "gpt4o"):
        for key in ("overall", "accuracy"):
            row = [mean([((r.get("judges") or {}).get(judge, {}).get("scores") or {}).get(v, {}).get(key)
                         for r in recs]) for v in variants]
            print(f"{judge + ' ' + key:30}" + "".join(f"{str(x):>12}" for x in row))
        errs = [sum(len((((r.get("judges") or {}).get(judge, {}).get("scores") or {}).get(v, {}).get("errors")
                         or [])) for r in recs) for v in variants]
        best = [sum(1 for r in recs if (r.get("judges") or {}).get(judge, {}).get("best") == v) for v in variants]
        rk = []
        for v in variants:
            vals = []
            for r in recs:
                sc = {k: s.get("overall") for k, s in (((r.get("judges") or {}).get(judge, {}).get("scores")) or {}).items()
                      if isinstance(s.get("overall"), (int, float))}
                if v in sc:
                    vals.append(ranks(sc)[v])
            rk.append(round(statistics.mean(vals), 2) if vals else None)
        print(f"{judge + ' errors flagged':30}" + "".join(f"{x:>12}" for x in errs))
        print(f"{judge + ' judged best':30}" + "".join(f"{x:>12}" for x in best))
        print(f"{judge + ' mean rank':30}" + "".join(f"{str(x):>12}" for x in rk))
    print("\nper question (session / gpt4o overall):")
    for r in recs:
        cells = []
        for v in variants:
            so = (((r.get("judges") or {}).get("session", {}).get("scores") or {}).get(v) or {}).get("overall")
            go = (((r.get("judges") or {}).get("gpt4o", {}).get("scores") or {}).get(v) or {}).get("overall")
            cells.append(f"{v}={so}/{go}")
        print(f"  {r['qid']:7} " + " ".join(cells))


if __name__ == "__main__":
    main(sys.argv[1])
