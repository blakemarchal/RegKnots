"""Generate the ElevenLabs voice-over lines for vo.py (2026-10-16).

    python vo.py requests sarah bill        # data/video/vo/requests.json
    python vo_elevenlabs.py [ENV_FILE]      # default: the repo's .env (ELEVENLABS_API_KEY)

For each ElevenLabs request it calls text-to-speech with timestamps, writes
data/video/vo/cache/<id>.wav (24 kHz mono) and merges the word times into
data/video/vo/words.json, where vo.py's splitter reads them (the OpenAI voices
get theirs from Whisper). The words come from ElevenLabs' character alignment of
the text sent. Stock voices only; prints no secrets.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", ROOT / "data" / "video"))
VO = DATA / "vo"
CACHE = VO / "cache"
RATE = 24000


def api_key(env_file: Path) -> str:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"no ELEVENLABS_API_KEY in {env_file}")


def words_from(alignment: dict) -> list[list]:
    """[[word, start_s, end_s], …] from the character alignment."""
    out, cur, start, end = [], "", 0.0, 0.0
    for ch, s, e in zip(alignment["characters"], alignment["character_start_times_seconds"],
                        alignment["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                out.append([cur, round(start, 3), round(end, 3)])
                cur = ""
            continue
        if not cur:
            start = s
        cur += ch
        end = e
    if cur:
        out.append([cur, round(start, 3), round(end, 3)])
    return out


def main():
    key = api_key(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".env")
    reqs = [r for r in json.loads((VO / "requests.json").read_text(encoding="utf-8"))
            if r.get("provider") == "elevenlabs"]
    words_path = VO / "words.json"
    words = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else {}
    CACHE.mkdir(parents=True, exist_ok=True)
    chars = 0
    for r in reqs:
        body = json.dumps({"text": r["text"], "model_id": r["model"], "voice_settings": r["settings"]}).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{r['voice_id']}/with-timestamps?output_format=pcm_24000",
            data=body, method="POST", headers={"xi-api-key": key, "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.load(resp)
        except urllib.error.HTTPError as e:
            print(f"{r['id']} {r['voice']}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}")
            continue
        pcm = base64.b64decode(out["audio_base64"])
        with wave.open(str(CACHE / f"{r['id']}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        words[r["id"]] = words_from(out["alignment"])
        chars += len(r["text"])
        print(f"{r['id']} {r['voice']:6} {len(pcm) / (2 * RATE):5.2f}s {len(words[r['id']]):3} words "
              f"{time.monotonic() - t0:4.1f}s  {r['text'][:60]!r}")
    words_path.write_text(json.dumps(words, indent=1), encoding="utf-8")
    print(f"done: {len(reqs)} lines, {chars} characters")


if __name__ == "__main__":
    main()
