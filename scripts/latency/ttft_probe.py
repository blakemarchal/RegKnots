"""Where the seconds before the first word go (2026-10-17). Spends Claude credit (~$1).

For each question: runs the production engine with the chat route's flags,
captures the real rewrite, rerank and coverage requests (Haiku) and the
answer request (Opus), then replays them:
  Haiku calls    as sent (effort low, thinking on) vs thinking off ("between_tools"),
                 twice each, timing the call and checking it still returns its JSON;
  answer call    as sent twice (the second normally hits the prompt cache), with
                 the system prompt uncached, and with half the library text; each
                 replay is stopped at its first text token, so only input and
                 thinking are billed. Reports when thinking started (≈ prefill done),
                 when the first word came, and how much was thought.

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/ttft_probe.py
"""
import asyncio
import copy
import json
import statistics
import sys
import time
from uuid import uuid4

sys.path.insert(0, "/opt/RegKnots/apps/api")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

import rag.engine as E  # noqa: E402
import rag.llm as L  # noqa: E402
import rag.query_rewrite as QR  # noqa: E402
import rag.reranker as RR  # noqa: E402
from app.config import settings  # noqa: E402

QUESTIONS = [
    ("What records does a Subchapter M towboat have to keep?", "towing"),
    ("How often do the lifeboats on a containership have to be launched with their crews?", "container"),
    ("How many portable fire extinguishers does a 120-foot towing vessel need?", "towing"),
]
PROFILES = {
    "towing": {"vessel_name": "probe", "vessel_type": "Towing / Tugboat", "flag_state": "United States"},
    "container": {"vessel_name": "probe", "vessel_type": "Containership", "flag_state": "United States"},
}


class _Captured(BaseException):
    pass


async def capture(client, pool, question, profile, user_id, conv_id):
    """The engine's real sidecar requests (by label) and the answer request."""
    seen: dict = {"sidecar": {}}
    orig = L.create_json

    async def rec(c, **kw):
        seen["sidecar"].setdefault(kw.get("label"), copy.deepcopy(kw))
        return await orig(c, **kw)

    def stop(**kw):
        seen["answer"] = copy.deepcopy(kw)
        raise _Captured()

    QR.create_json = RR.create_json = L.create_json = rec
    orig_stream = client.messages.stream
    client.messages.stream = stop
    try:
        async for _ in E.chat_with_progress(
            query=question, conversation_history=[], vessel_profile=profile, pool=pool,
            anthropic_client=client, openai_api_key=settings.openai_api_key, conversation_id=conv_id,
            user_id=user_id, subscription_tier="captain", user_jurisdiction_focus="us",
            web_fallback_enabled=False, hedge_judge_enabled=False,
            query_rewrite_enabled=settings.query_rewrite_enabled, reranker_enabled=settings.reranker_enabled,
            whole_sections_enabled=settings.whole_sections_enabled,
            provenance_prompt_enabled=settings.provenance_prompt_enabled,
            imo_dates_prompt_enabled=settings.imo_dates_prompt_enabled,
            model_led_grounding_enabled=settings.model_led_grounding_enabled,
            pipeline_v2_enabled=settings.answer_pipeline_v2_enabled,
            speculative_answer_enabled=False,
            synthesis_model_floor=settings.synthesis_model_floor or None,
        ):
            pass
    except _Captured:
        pass
    finally:
        QR.create_json, RR.create_json, L.create_json = orig, orig, orig
        client.messages.stream = orig_stream
    return seen


async def time_sidecar(client, kw: dict, think_off: bool) -> dict:
    kw = copy.deepcopy(kw)
    if think_off:
        kw.pop("output_config", None)
        kw["thinking"] = {"type": "between_tools"}
    t = time.perf_counter()
    try:
        res = await L.create_json(client, **kw)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"s": round(time.perf_counter() - t, 2), "ok": res.data is not None}


async def first_word(client, kw: dict) -> dict:
    """Stream until the first text token, then stop."""
    t0 = time.perf_counter()
    think_start = None
    think_chars = 0
    usage = {}
    try:
        async with client.messages.stream(**kw) as s:
            async for ev in s:
                t = time.perf_counter() - t0
                if ev.type == "message_start":
                    u = ev.message.usage
                    usage = {"input": u.input_tokens, "cache_read": u.cache_read_input_tokens or 0,
                             "cache_write": u.cache_creation_input_tokens or 0}
                elif ev.type == "content_block_start" and ev.content_block.type == "thinking" and think_start is None:
                    think_start = t
                elif ev.type == "content_block_delta":
                    dt = getattr(ev.delta, "type", "")
                    if dt == "thinking_delta":
                        think_chars += len(getattr(ev.delta, "thinking", "") or "")
                    elif dt == "text_delta":
                        return {"ttft": round(t, 2), "think_start": None if think_start is None else round(think_start, 2),
                                "think_chars": think_chars, **usage}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"ttft": None, "think_chars": think_chars, **usage}


def uncached(kw: dict) -> dict:
    kw = copy.deepcopy(kw)
    if isinstance(kw.get("system"), list):
        kw["system"] = "\n\n".join(b.get("text", "") for b in kw["system"])
    return kw


def half_context(kw: dict) -> dict:
    kw = copy.deepcopy(kw)
    msg = kw["messages"][-1]
    text = msg["content"] if isinstance(msg["content"], str) else None
    if text and "Regulation context:" in text and "Question:" in text:
        a = text.index("Regulation context:")
        b = text.rindex("Question:")
        ctx = text[a:b]
        msg["content"] = text[:a] + ctx[: len(ctx) // 2] + "\n\n" + text[b:]
    return kw


async def main():
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[ttft probe 2026-10-17]")
    report = []
    try:
        for question, pk in QUESTIONS:
            seen = await capture(client, pool, question, PROFILES[pk], user_id, conv_id)
            row = {"question": question, "sidecar": {}, "answer": {}}
            for label, kw in seen["sidecar"].items():
                runs = {"as_sent": [], "think_off": []}
                for _ in range(2):
                    for name, off in (("as_sent", False), ("think_off", True)):
                        runs[name].append(await time_sidecar(client, kw, off))
                row["sidecar"][label] = runs
            if "answer" in seen:
                a = seen["answer"]
                ctx_chars = len(str(a["messages"][-1]["content"]))
                row["answer"] = {
                    "model": a.get("model"), "user_turn_chars": ctx_chars,
                    "as_sent_1": await first_word(client, a),
                    "as_sent_2": await first_word(client, a),
                    "uncached": await first_word(client, uncached(a)),
                    "half_context": await first_word(client, half_context(a)),
                }
            report.append(row)
            print(json.dumps(row, indent=1), flush=True)
    finally:
        refs = await pool.fetch("SELECT table_name FROM information_schema.columns WHERE column_name = 'conversation_id' "
                                "AND table_schema = 'public' AND table_name <> 'conversations'")
        for r in refs:
            await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE conversation_id = $1', conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        await client.close()
        await pool.close()

    print("\n== summary (seconds)")
    for label in ("query_rewrite", "reranker", "coverage check"):
        for name in ("as_sent", "think_off"):
            vals = [r["s"] for row in report for r in row["sidecar"].get(label, {}).get(name, []) if "s" in r]
            oks = [r["ok"] for row in report for r in row["sidecar"].get(label, {}).get(name, []) if "s" in r]
            errs = [r["error"] for row in report for r in row["sidecar"].get(label, {}).get(name, []) if "error" in r]
            if vals:
                print(f"  {label:15} {name:9} median {statistics.median(vals):.2f}  max {max(vals):.2f}  "
                      f"json ok {sum(oks)}/{len(oks)}")
            if errs:
                print(f"  {label:15} {name:9} errors: {errs[:1]}")
    for name in ("as_sent_1", "as_sent_2", "uncached", "half_context"):
        vals = [row["answer"][name] for row in report if row["answer"].get(name, {}).get("ttft")]
        if vals:
            print(f"  answer {name:12} first word median {statistics.median(v['ttft'] for v in vals):.2f}  "
                  f"thinking starts {statistics.median(v['think_start'] or 0 for v in vals):.2f}  "
                  f"thought {statistics.median(v['think_chars'] for v in vals):.0f} chars  "
                  f"cache read {[v.get('cache_read') for v in vals]}")


if __name__ == "__main__":
    asyncio.run(main())
