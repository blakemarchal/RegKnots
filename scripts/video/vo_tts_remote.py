"""Generate the temp voice-over lines with OpenAI TTS, and transcribe each one back
as a check (the words, not the voice). Runs wherever a working OPENAI_API_KEY is:

    python vo_tts_remote.py requests.json OUTDIR [ENV_FILE]      # TTS + transcript check
    python vo_tts_remote.py --words WAV_DIR OUT.json [ENV_FILE]  # word timestamps for splitting

Writes OUTDIR/<id>.wav and OUTDIR/results.json. Prints no secrets.
"""
import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

words_mode = sys.argv[1] == "--words"
args = sys.argv[2:] if words_mode else sys.argv[1:]
env_file = Path(args[2]) if len(args) > 2 else None
if env_file and not os.environ.get("OPENAI_API_KEY"):
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
client = OpenAI()

if words_mode:
    wav_dir, out = Path(args[0]), Path(args[1])
    result = {}
    for wav in sorted(wav_dir.glob("*.wav")):
        with wav.open("rb") as fh:
            tr = client.audio.transcriptions.create(model="whisper-1", file=fh, response_format="verbose_json",
                                                    timestamp_granularities=["word"])
        result[wav.stem] = [[w.word, round(w.start, 3), round(w.end, 3)] for w in (tr.words or [])]
        print(wav.stem, len(result[wav.stem]), "words")
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    raise SystemExit(0)

req_file, outdir = Path(args[0]), Path(args[1])
outdir.mkdir(parents=True, exist_ok=True)
FALLBACK = {"marin": "sage", "cedar": "ash"}

results = []
for r in json.loads(req_file.read_text(encoding="utf-8")):
    t0 = time.monotonic()
    voice = r["voice"]
    audio = None
    for attempt in (voice, FALLBACK.get(voice)):
        if not attempt:
            break
        try:
            audio = client.audio.speech.create(model=r["model"], voice=attempt, input=r["text"],
                                               instructions=r["instructions"], response_format="wav").read()
            voice = attempt
            break
        except Exception as e:  # noqa: BLE001 - try the fallback voice once
            print(f"{r['id']} {attempt}: {type(e).__name__}: {str(e)[:160]}")
    if not audio:
        results.append({**r, "error": "tts failed"})
        continue
    wav = outdir / f"{r['id']}.wav"
    wav.write_bytes(audio)
    with wav.open("rb") as fh:
        text = client.audio.transcriptions.create(model="whisper-1", file=fh, response_format="text")
    results.append({"id": r["id"], "voice_requested": r["voice"], "voice_used": voice, "text": r["text"],
                    "transcript": str(text).strip(), "bytes": len(audio), "secs": round(time.monotonic() - t0, 1)})
    print(f"{r['id']} {voice:6} {results[-1]['secs']:4.1f}s  {r['text'][:50]!r} -> {results[-1]['transcript'][:60]!r}")
(outdir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
print(f"done: {len(results)} lines")
