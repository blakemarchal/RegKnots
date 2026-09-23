"""Chat-synthesis model comparison — the harness behind the 2026-09-23 switch
of the default answer model to Opus 5.5 (effort low). Re-run it before any
change to the synthesis model, its effort, or the synthesis prompt.

For each question, runs the real engine (routing, retrieval, rewrite, rerank, prompt
assembly) and captures the exact synthesis request at the moment it would be sent, then
replays that same request under six configurations, so the only variable is the model /
thinking setting:

  haiku         claude-haiku-4-5, the router's pick for score 1
  sonnet_today  claude-sonnet-5, no thinking param (adaptive at default effort `high`),
                as sent for score 2 before 2026-09-23
  sonnet_low    claude-sonnet-5, effort low
  sonnet_off    claude-sonnet-5, thinking disabled
  opus_low      claude-opus-5-5, effort low (the production default since 2026-09-23)
  opus_medium   claude-opus-5-5, effort medium

`router_mix` in the summary is what pure complexity routing would have sent each question
to (SYNTHESIS_MODEL_FLOOR empty). Per answer: time to first text token, total time, output
tokens, stop reason, cost at a cold and a warm prompt cache, and the engine's own post-checks
(section numbers in the text that are not in the corpus, ungrounded UN-number claims, hedge
phrases) plus gold-set citation hits. Two blind judges (Opus 5.5 at effort medium, GPT-4o)
score all six answers per question, each in its own shuffled label order; Opus judging
Opus answers is a known self-preference risk, which is why GPT-4o judges too.

Run on the VPS (~35 min, ~$6 for 16 questions); results land in data/eval/model_compare/:
    cd /opt/RegKnots/apps/api && /root/.local/bin/uv run python /opt/RegKnots/scripts/compare_synthesis_models.py
"""
import asyncio
import copy
import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path
from uuid import uuid4

REPO = Path("/opt/RegKnots")
sys.path.insert(0, str(REPO / "packages" / "rag"))
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO / "scripts"))
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from app.config import settings  # noqa: E402
import rag.engine as E  # noqa: E402
from rag.hedge import detect_hedge  # noqa: E402
from rag.llm import INT, STR, arr, create_json, enum, obj, text_of  # noqa: E402
import eval_rag_baseline as G  # noqa: E402

OUT = REPO / "data" / "eval" / "model_compare" / time.strftime("%Y%m%d-%H%M%S", time.gmtime())
OUT.mkdir(parents=True, exist_ok=True)

HAIKU, SONNET, OPUS = "claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5-5"
VARIANTS: dict[str, dict] = {
    "haiku": {"model": HAIKU, "max_tokens": 8192},
    "sonnet_today": {"model": SONNET, "max_tokens": 8192},
    "sonnet_low": {"model": SONNET, "max_tokens": 8192, "output_config": {"effort": "low"}},
    "sonnet_off": {"model": SONNET, "max_tokens": 8192, "thinking": {"type": "disabled"}},
    "opus_low": {"model": OPUS, "max_tokens": 16384, "output_config": {"effort": "low"}},
    "opus_medium": {"model": OPUS, "max_tokens": 16384, "output_config": {"effort": "medium"}},
}
ROUTER = {HAIKU: "haiku", SONNET: "sonnet_today", OPUS: "opus_low"}
# $/MTok: input, output, 5-minute cache write, cache read (claude-api skill, 2026-09-23)
PRICES = {HAIKU: (1.00, 5.00, 1.25, 0.10), SONNET: (2.00, 10.00, 2.50, 0.20), OPUS: (4.00, 20.00, 5.00, 0.20)}

GOLD = [("F1", "V2"), ("F2", "V1"), ("F5", "V5"), ("C1", "V3"), ("C3", "V1"), ("E1", "V1"),
        ("N1", "V5"), ("V1q", "V1"), ("N-O1", "V2"), ("N-S3", "V1"), ("N-F2", "V1"),
        ("M-2", "V1"), ("N-E4", "V1"), ("C4", "V3")]
REAL = ["what is the man overboard alarm", "confirming flag state"]   # the Captain's own
LABELS = ["A", "B", "C", "D", "E", "F"]

JUDGE_SCHEMA = obj({
    "grades": arr(obj({
        "label": enum(*LABELS),
        "accuracy": INT, "applicability": INT, "completeness": INT, "clarity": INT,
        "overall": INT,
        "errors": arr(STR),
    })),
    "best": enum(*LABELS),
    "worst": enum(*LABELS),
})
JUDGE_SYSTEM = """You grade answers from a regulatory copilot for U.S. commercial vessel operators. You are a U.S. Coast Guard-licensed Master (Unlimited) and a maritime compliance auditor. You will see exactly what the assistant was given (vessel profile, retrieved regulation excerpts, the mariner's question) and several candidate answers labeled with letters. The candidates came from different systems; judge each on substance only.

Score every answer from 0 to 10 on:
- accuracy: every regulatory statement is correct and consistent with the excerpts or with well-established U.S. or international regulation. A misstated number, interval or requirement, or a citation to a section that does not say what the answer claims, is a serious error.
- applicability: it answers for THIS vessel (type, size, route, U.S. flag) and leads with the governing U.S. authority where one exists.
- completeness: it gives the mariner what they need to act: the requirement, the numbers, who does what, and where it is written.
- clarity: bottom line first, well organized, no padding.
- overall: which answer you would want in a working mariner's hands.

List each answer's concrete factual or citation errors (an empty list if none). Do not reward length for its own sake. Grade every label exactly once, then name the best and the worst answer."""


class _Captured(BaseException):
    """Raised from the patched stream() so the engine stops right before synthesis."""


def gold_profile(vc: str) -> dict:
    v = G.VESSELS[vc]
    p = {"vessel_name": v.name, "vessel_type": v.vessel_type, "flag_state": "United States",
         "route_type": v.route_type, "route_types": [v.route_type] if v.route_type else [],
         "cargo_types": list(v.cargo_types)}
    if v.gross_tonnage:
        p["gross_tonnage"] = v.gross_tonnage
    if v.subchapter:
        p["subchapter"] = v.subchapter
    return p


async def capture(query, profile, pool, client, okey, conv_id, user_id) -> dict:
    box: dict = {}
    orig_ret, orig_route = E.retrieve_enhanced, E.route_query
    m = client.messages
    orig_stream = m.stream

    async def ret_wrap(*a, **kw):
        chunks = await orig_ret(*a, **kw)
        box["chunks"] = chunks
        return chunks

    async def route_wrap(*a, **kw):
        r = await orig_route(*a, **kw)
        box.update(route_model=r.model, route_score=r.score, off_topic=r.is_off_topic)
        return r

    def cap(*a, **kw):
        box["kwargs"] = copy.deepcopy(kw)
        raise _Captured()

    E.retrieve_enhanced, E.route_query, m.stream = ret_wrap, route_wrap, cap
    t0 = time.perf_counter()
    try:
        async for _ in E.chat_with_progress(
            query=query, conversation_history=[], vessel_profile=profile, pool=pool,
            anthropic_client=client, openai_api_key=okey, conversation_id=conv_id,
            user_id=user_id, subscription_tier="captain", user_jurisdiction_focus="us",
            web_fallback_enabled=False, hedge_judge_enabled=False,
            query_rewrite_enabled=settings.query_rewrite_enabled,
            reranker_enabled=settings.reranker_enabled,
        ):
            pass
    except _Captured:
        pass
    finally:
        E.retrieve_enhanced, E.route_query, m.stream = orig_ret, orig_route, orig_stream
    box["pre_synthesis_s"] = round(time.perf_counter() - t0, 1)
    return box


def cost(model: str, u: dict) -> tuple[float, float]:
    """(cold-cache $, warm-cache $) for one call. Cold = the whole cached prefix is written."""
    p_in, p_out, p_cw, p_cr = PRICES[model]
    prefix = u["cache_read"] + u["cache_write"]
    base = u["input"] * p_in + u["output"] * p_out
    return (base + prefix * p_cw) / 1e6, (base + prefix * p_cr) / 1e6


async def run_variant(client, base: dict, name: str) -> dict:
    kw = {k: v for k, v in base.items() if k not in ("model", "max_tokens", "output_config", "thinking")}
    kw.update(copy.deepcopy(VARIANTS[name]))
    t0 = time.perf_counter()
    first_text = first_think = None
    kinds: list[str] = []

    async def go():
        nonlocal first_text, first_think
        async with client.messages.stream(**kw) as s:
            async for ev in s:
                t = time.perf_counter() - t0
                if ev.type == "content_block_start":
                    kinds.append(ev.content_block.type)
                    if ev.content_block.type == "thinking" and first_think is None:
                        first_think = t
                elif (ev.type == "content_block_delta" and first_text is None
                      and getattr(ev.delta, "type", "") == "text_delta"):
                    first_text = t
            return await s.get_final_message()

    try:
        msg = await asyncio.wait_for(go(), timeout=300)
    except Exception as exc:  # noqa: BLE001
        return {"variant": name, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    u = msg.usage
    usage = {"input": u.input_tokens, "output": u.output_tokens,
             "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0}
    cold, warm = cost(kw["model"], usage)
    return {"variant": name, "model": kw["model"], "answer": text_of(msg),
            "ttft": None if first_text is None else round(first_text, 2),
            "think_start": None if first_think is None else round(first_think, 2),
            "total": round(time.perf_counter() - t0, 2), "blocks": kinds,
            "stop": msg.stop_reason, "usage": usage, "cost_cold": cold, "cost_warm": warm}


async def post_checks(r: dict, q, vc, chunks, pool) -> None:
    ans, _ = E._extract_vessel_update(r["answer"])
    r["answer"] = ans
    cits = E._extract_all_text_citations(ans)
    r["n_text_cites"] = len(cits)
    r["unverified"] = await E._verify_text_citations(cits, pool)
    r["ungrounded_un"] = E._verify_un_claims(ans, chunks or [])
    r["hedge"] = detect_hedge(ans)
    r["chars"] = len(ans)
    if q is not None:
        exp = G._expected_for_vessel(q, vc)
        r["exp_any"] = any(re.search(p, ans, re.I) for p in exp)
        spec = [p for p in exp if re.search(r"\d", p)]
        r["exp_specific"] = any(re.search(p, ans, re.I) for p in spec) if spec else None
        r["wrong_sub"] = [p for p in q.wrong_sub if re.search(p, ans, re.I)]


def judge_input(user_msg: str, answers: dict[str, str]) -> str:
    parts = ["WHAT THE ASSISTANT WAS GIVEN", "<<<", user_msg, ">>>", "", "CANDIDATE ANSWERS"]
    for lab in sorted(answers):
        parts += [f"[{lab}]", answers[lab], ""]
    return "\n".join(parts)


async def judge_opus(client, content: str) -> tuple[dict | None, dict]:
    res = await create_json(client, schema=JUDGE_SCHEMA, label="compare judge", model=OPUS,
                            max_tokens=16000, output_config={"effort": "medium"},
                            system=JUDGE_SYSTEM, messages=[{"role": "user", "content": content}])
    u = res.response.usage
    return res.data, {"input": u.input_tokens, "output": u.output_tokens}


async def judge_gpt(oai, content: str) -> tuple[dict | None, dict]:
    r = await oai.chat.completions.create(
        model="gpt-4o", temperature=0,
        response_format={"type": "json_schema",
                         "json_schema": {"name": "grades", "strict": True, "schema": JUDGE_SCHEMA}},
        messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": content}],
    )
    return json.loads(r.choices[0].message.content), {"input": r.usage.prompt_tokens, "output": r.usage.completion_tokens}


def user_text(kwargs: dict) -> str:
    content = kwargs["messages"][-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))


async def one_question(item, pool, client, oai, okey, conv_id, user_id, rng) -> dict:
    qid, query, profile, q, vc = item
    rec: dict = {"qid": qid, "vessel": vc, "query": query}
    box = await capture(query, profile, pool, client, okey, conv_id, user_id)
    rec.update({k: box.get(k) for k in ("route_model", "route_score", "off_topic", "pre_synthesis_s")})
    if "kwargs" not in box:
        rec["skipped"] = "no synthesis request (off-topic or engine short-circuit)"
        return rec
    base = box["kwargs"]
    rec["system_chars"] = sum(len(b.get("text", "")) for b in base["system"]) if isinstance(base["system"], list) else len(base["system"])
    umsg = user_text(base)
    rec["user_chars"] = len(umsg)
    rec["runs"] = {}
    for name in VARIANTS:
        r = await run_variant(client, base, name)
        if "error" not in r:
            await post_checks(r, q, vc, box.get("chunks"), pool)
        rec["runs"][name] = r
        print(f"    {qid:6} {name:13} ttft={r.get('ttft')} total={r.get('total')} out={(r.get('usage') or {}).get('output')} "
              f"stop={r.get('stop')} unverified={r.get('unverified')} {r.get('error', '')}", flush=True)
    ok = [n for n in VARIANTS if "error" not in rec["runs"][n] and rec["runs"][n]["answer"].strip()]
    rec["judges"] = {}
    for jname in ("opus", "gpt4o"):
        order = ok[:]
        rng.shuffle(order)
        lab2var = dict(zip(LABELS, order))
        content = judge_input(umsg, {lab: rec["runs"][v]["answer"] for lab, v in lab2var.items()})
        try:
            data, usage = await (judge_opus(client, content) if jname == "opus" else judge_gpt(oai, content))
        except Exception as exc:  # noqa: BLE001
            rec["judges"][jname] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            continue
        if not data:
            rec["judges"][jname] = {"error": "no structured output"}
            continue
        per_var = {}
        for g in data.get("grades", []):
            v = lab2var.get(g.get("label"))
            if v:
                per_var[v] = {k: g.get(k) for k in ("accuracy", "applicability", "completeness", "clarity", "overall", "errors")}
        rec["judges"][jname] = {"scores": per_var, "best": lab2var.get(data.get("best")),
                                "worst": lab2var.get(data.get("worst")), "usage": usage, "order": lab2var}
    return rec


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def p90(xs):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(0.9 * len(xs)))], 1) if xs else None


def mean(xs, nd=2):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), nd) if xs else None


def ranks(scores: dict[str, float]) -> dict[str, float]:
    """1 = best; ties share the average rank."""
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


def summarize(recs: list[dict]) -> dict:
    done = [r for r in recs if "runs" in r]
    rows = {}
    for name in list(VARIANTS) + ["router_mix"]:
        per = []
        for r in done:
            v = ROUTER.get(r.get("route_model"), "sonnet_today") if name == "router_mix" else name
            run = r["runs"].get(v, {})
            if "error" in run or not run:
                continue
            jr = {j: (r["judges"].get(j, {}).get("scores") or {}).get(v, {}) for j in ("opus", "gpt4o")}
            rk = {}
            for j in ("opus", "gpt4o"):
                sc = {k: s.get("overall") for k, s in (r["judges"].get(j, {}).get("scores") or {}).items()
                      if isinstance(s.get("overall"), (int, float))}
                if v in sc:
                    rk[j] = ranks(sc)[v]
            per.append({"rec": r, "run": run, "jr": jr, "rk": rk, "v": v})
        runs = [p["run"] for p in per]
        gold_runs = [p["run"] for p in per if p["rec"]["qid"] in {g[0] for g in GOLD}]

        def judged(j, key):
            return mean([p["jr"][j].get(key) for p in per])

        def best(j):
            return sum(1 for p in per if p["rec"]["judges"].get(j, {}).get("best") == p["v"])

        rows[name] = {
            "n": len(per),
            "ttft_median": med([x["ttft"] for x in runs]),
            "ttft_p90": p90([x["ttft"] for x in runs]),
            "total_median": med([x["total"] for x in runs]),
            "output_tokens_mean": mean([x["usage"]["output"] for x in runs], 0),
            "thinking_share": mean([1.0 if "thinking" in x["blocks"] else 0.0 for x in runs]),
            "truncated": sum(1 for x in runs if x["stop"] == "max_tokens"),
            "cost_cold_mean": mean([x["cost_cold"] for x in runs], 4),
            "cost_warm_mean": mean([x["cost_warm"] for x in runs], 4),
            "gold_specific_hit": mean([1.0 if x.get("exp_specific") else 0.0 for x in gold_runs
                                       if x.get("exp_specific") is not None]),
            "gold_any_hit": mean([1.0 if x.get("exp_any") else 0.0 for x in gold_runs]),
            "answers_with_unverified": sum(1 for x in runs if x.get("unverified")),
            "unverified_total": sum(len(x.get("unverified") or []) for x in runs),
            "ungrounded_un": sum(len(x.get("ungrounded_un") or []) for x in runs),
            "wrong_sub_mentions": sum(len(x.get("wrong_sub") or []) for x in runs),
            "hedged": sum(1 for x in runs if x.get("hedge")),
            "chars_median": med([x["chars"] for x in runs]),
            "judge_opus_overall": judged("opus", "overall"),
            "judge_gpt_overall": judged("gpt4o", "overall"),
            "judge_opus_accuracy": judged("opus", "accuracy"),
            "judge_gpt_accuracy": judged("gpt4o", "accuracy"),
            "mean_rank_opus": mean([p["rk"].get("opus") for p in per]),
            "mean_rank_gpt": mean([p["rk"].get("gpt4o") for p in per]),
            "best_opus": best("opus"),
            "best_gpt": best("gpt4o"),
            "errors_flagged_opus": sum(len(p["jr"]["opus"].get("errors") or []) for p in per),
            "errors_flagged_gpt": sum(len(p["jr"]["gpt4o"].get("errors") or []) for p in per),
        }
    return rows


async def main() -> None:
    rng = random.Random(20260923)
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    okey = getattr(settings, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    oai = AsyncOpenAI(api_key=okey)
    Q = {q.qid: q for q in G.QUESTIONS}
    items = [(qid, Q[qid].query, gold_profile(vc), Q[qid], vc) for qid, vc in GOLD]
    row = await pool.fetchrow("SELECT * FROM vessels WHERE imo_mmsi = '9333022'")
    cap_profile = {k: v for k, v in {
        "vessel_name": row["name"], "vessel_type": row["vessel_type"], "flag_state": row["flag_state"],
        "gross_tonnage": row["gross_tonnage"], "classification_society": row["classification_society"],
        "route_types": list(row["route_types"] or []), "cargo_types": list(row["cargo_types"] or []),
    }.items() if v not in (None, [], {})}
    items += [(f"REAL{i + 1}", qq, cap_profile, None, "captain") for i, qq in enumerate(REAL)]

    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[model compare 2026-09-23]")
    children = await pool.fetch("""
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = rc.constraint_name AND kcu.constraint_schema = rc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = rc.unique_constraint_name AND ccu.constraint_schema = rc.unique_constraint_schema
        WHERE ccu.table_name = 'conversations' AND ccu.column_name = 'id'""")
    recs: list[dict] = []
    t_all = time.perf_counter()
    try:
        for n, item in enumerate(items, 1):
            print(f"[{n}/{len(items)}] {item[0]} {item[4]}: {item[1][:80]!r}", flush=True)
            try:
                rec = await one_question(item, pool, client, oai, okey, conv_id, user_id, rng)
            except Exception as exc:  # noqa: BLE001
                rec = {"qid": item[0], "query": item[1], "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            recs.append(rec)
            (OUT / "results.json").write_text(json.dumps(recs, indent=1, default=str), encoding="utf-8")
            print(f"    route={rec.get('route_model')} pre_synthesis={rec.get('pre_synthesis_s')}s "
                  f"skipped={rec.get('skipped')} error={rec.get('error')}", flush=True)
    finally:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.wait(pending, timeout=30)
        for r in children:
            try:
                await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE "{r["column_name"]}" = $1', conv_id)
            except Exception as exc:  # noqa: BLE001
                print("  cleanup", r["table_name"], type(exc).__name__)
        print("  cleanup conversations:", await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id))
        await pool.close()

    summary = summarize(recs)
    spend = 0.0
    for r in recs:
        for run in (r.get("runs") or {}).values():
            if "error" not in run:
                p_in, p_out, p_cw, p_cr = PRICES[run["model"]]
                u = run["usage"]
                spend += (u["input"] * p_in + u["output"] * p_out + u["cache_write"] * p_cw + u["cache_read"] * p_cr) / 1e6
        ju = (r.get("judges") or {}).get("opus", {}).get("usage")
        if ju:
            spend += (ju["input"] * 4.0 + ju["output"] * 20.0) / 1e6
        gu = (r.get("judges") or {}).get("gpt4o", {}).get("usage")
        if gu:
            spend += (gu["input"] * 2.5 + gu["output"] * 10.0) / 1e6
    meta = {"questions": len(recs), "synthesized": sum(1 for r in recs if "runs" in r),
            "wall_minutes": round((time.perf_counter() - t_all) / 60, 1), "approx_spend_usd": round(spend, 2),
            "route_models": {r["qid"]: r.get("route_model") for r in recs}}
    (OUT / "summary.json").write_text(json.dumps({"meta": meta, "variants": summary}, indent=1), encoding="utf-8")
    print("\n=== META", json.dumps(meta))
    cols = ["n", "ttft_median", "ttft_p90", "total_median", "output_tokens_mean", "thinking_share", "truncated",
            "cost_cold_mean", "cost_warm_mean", "gold_specific_hit", "gold_any_hit", "answers_with_unverified",
            "unverified_total", "ungrounded_un", "wrong_sub_mentions", "hedged", "chars_median",
            "judge_opus_overall", "judge_gpt_overall", "judge_opus_accuracy", "judge_gpt_accuracy",
            "mean_rank_opus", "mean_rank_gpt", "best_opus", "best_gpt", "errors_flagged_opus", "errors_flagged_gpt"]
    print("=== VARIANTS")
    print("metric".ljust(26) + "".join(v.rjust(14) for v in summary))
    for c in cols:
        print(c.ljust(26) + "".join(str(summary[v].get(c)).rjust(14) for v in summary))
    print("\n=== PER QUESTION (overall: opus judge / gpt judge)")
    for r in recs:
        if "runs" not in r:
            print(f"{r['qid']:6} {r.get('skipped') or r.get('error')}")
            continue
        cells = []
        for v in VARIANTS:
            so = ((r["judges"].get("opus", {}).get("scores") or {}).get(v) or {}).get("overall")
            sg = ((r["judges"].get("gpt4o", {}).get("scores") or {}).get(v) or {}).get("overall")
            cells.append(f"{v}={so}/{sg}")
        print(f"{r['qid']:6} route={str(r.get('route_model'))[:14]:14} " + " ".join(cells))


asyncio.run(main())
