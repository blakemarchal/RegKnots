"""Per-request stage timeline from the API journal (read-only).

Every answered question logs "Routed query to"; the lines around it mark the
stage boundaries. The answer's persist time comes from messages.created_at.
"""
import json
import re
import subprocess
from datetime import datetime, timezone

DAYS = 45
raw = subprocess.run(
    ["journalctl", "-u", "regknots-api", "--since", f"{DAYS} days ago", "-o", "json",
     "--output-fields=MESSAGE,_PID", "--no-pager"],
    capture_output=True, text=True).stdout.splitlines()
lines = []
for r in raw:
    try:
        j = json.loads(r)
    except ValueError:
        continue
    msg = j.get("MESSAGE")
    if isinstance(msg, list):
        msg = bytes(msg).decode("utf-8", "replace")
    if not msg or "domain-check" in msg or "GET /health" in msg:
        continue
    lines.append((int(j["__REALTIME_TIMESTAMP"]) / 1e6, j.get("_PID"), msg))

asst = subprocess.run(
    ["docker", "exec", "regknots-postgres", "psql", "-U", "regknots", "-d", "regknots", "-At", "-c",
     f"select extract(epoch from created_at), coalesce(model_used,'?'), length(content) from messages "
     f"where role='assistant' and created_at > now() - interval '{DAYS} days' order by created_at"],
    capture_output=True, text=True).stdout.split()
persist = []
for row in asst:
    e, model, n = row.split("|")
    persist.append((float(e), model, int(n)))

RETR = re.compile(r"Retrieval: (\d+) candidates from (\d+) group\(s\) . top (\d+) in ([\d.]+)ms")


def first(seq, pat, after, before=None):
    for t, m in seq:
        if t >= after and (before is None or t <= before) and pat in m:
            return t
    return None


print("start = response start (access log); every other number is seconds after it")
print(f"{'when (UTC)':16} {'distill':>7} {'route':>6} {'rewrite':>7} {'fanout':>6} {'rerank':>6} "
      f"{'sects':>6} {'cover':>6} {'web':>6} {'synth@':>6} {'done@':>6} | retrieve() calls (s) | model chars")
for i, (t, pid, msg) in enumerate(lines):
    if "Routed query to" not in msg:
        continue
    win = [(tt, mm) for tt, pp, mm in lines if pp == pid and t - 25 <= tt <= t + 240]
    start = None
    for tt, mm in win:
        if tt <= t and ("POST /chat/stream" in mm or "POST /public/ask/stream" in mm or '"POST /chat ' in mm):
            start = tt
    if start is None:
        start = win[0][0]
    marks = {
        "distill": first(win, "Distilled verbose", start, t + 1),
        "route": t,
        "rewrite": first(win, "reformulations for", start),
        "fanout": first(win, "reformulations contributed", start),
        "rerank": first(win, "reranker: top-", start),
        "retrieved": first(win, "Retrieved ", start),
        "sects": first(win, "whole-section reading", start),
        "cover": first(win, "coverage: ", start),
        "web": first(win, "web research: ", start),
        "synth": first(win, "synthesis model floor", start),
    }
    calls = [round(float(m.group(4)) / 1000, 1) for tt, mm in win if tt >= start and (m := RETR.search(mm))
             and (marks["retrieved"] is None or tt <= marks["retrieved"])]
    synth = marks["synth"] or max(v for v in marks.values() if v)
    done = next(((e, mo, n) for e, mo, n in persist if e >= synth - 1 and e <= synth + 240), None)

    def rel(x):
        return f"{x - start:6.1f}" if x else "     -"
    when = datetime.fromtimestamp(start, timezone.utc).strftime("%m-%d %H:%M:%S")
    print(f"{when:16} {rel(marks['distill']):>7} {rel(marks['route'])} {rel(marks['rewrite']):>7} "
          f"{rel(marks['fanout'])} {rel(marks['rerank'])} {rel(marks['sects'])} {rel(marks['cover'])} "
          f"{rel(marks['web'])} {rel(synth)} {rel(done[0]) if done else '     -'} | {calls} | "
          f"{done[1] if done else '?'} {done[2] if done else ''}")
