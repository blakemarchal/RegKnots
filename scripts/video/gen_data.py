"""Curate real section titles from the corpus sample into stage/data.js."""
import json
import os
import random
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
rows = [ln.split("|", 2) for ln in (DATA / "regs_sample.txt").read_text(encoding="utf-8").splitlines() if ln.count("|") >= 2]

BAD = re.compile(r"(None|DISCUSSION|IMPLEMENTATION|REPORTS|DIRECTIVES|Unified|Reserved|^Rule |^Article |:$|\(Part \d\))")


def ok(src: str, sec: str, title: str) -> bool:
    title = title.strip()
    if not (8 <= len(title) <= 44):
        return False
    if BAD.search(title) or re.search(r"[a-z]\d$", title):
        return False
    letters = [c for c in title if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.5:
        return False
    if title.lower() in ("definitions", "applicability", "application", "purpose", "general", "scope"):
        return random.random() < 0.15       # keep a few; real regs are full of them
    return True


random.seed(7)
by_src: dict[str, list] = {}
for src, sec, title in rows:
    if ok(src, sec, title):
        by_src.setdefault(src, []).append((sec.strip(), title.strip()))

QUOTA = {"cfr_46": 44, "cfr_33": 26, "cfr_49": 8, "usc_46": 8, "solas": 14, "marpol": 6,
         "stcw": 10, "mlc": 10, "imdg": 10, "nvic": 6, "colregs": 2, "ism": 1}
picked = []
for src, n in QUOTA.items():
    pool = by_src.get(src, [])
    random.shuffle(pool)
    picked += pool[:n]
random.shuffle(picked)
# The two sections the ad is about sit in view of the counter.
picked.insert(9, ("46 CFR 140.410", "Safety orientation"))
picked.insert(31, ("46 CFR 140.915", "Items to be recorded"))

out = HERE / "stage" / "data.js"
out.parent.mkdir(exist_ok=True)
out.write_text("window.REGS = " + json.dumps(picked, ensure_ascii=False) + ";\n", encoding="utf-8")
print(len(picked), "rows ->", out)
print(picked[:12])
