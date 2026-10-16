"""Karynn's name in Blake's own pronunciation (2026-10-16): convert a recording
of a line into the narrator voices with ElevenLabs speech-to-speech, and put it
in the vo cache where `vo.py build` expects that line's TTS take.

    python vo_sts.py RECORDING [--voices chris,river] [--cut main --line 5] [--dry]

RECORDING is anything ffmpeg reads (m4a, mp3, wav, …). Steps: decode to mono
24 kHz, high-pass, denoise, trim the silence at both ends, normalise; then
POST /v1/speech-to-speech/{voice} (the voice changer: Blake's delivery and
pronunciation, the narrator's voice) and write cache/<key>.wav for each voice.
The key is vo.cache_key for that line, so the normal build picks it up; any
Whisper / alignment word times for the key are dropped (the line is one piece).
Needs FFMPEG in the environment (or imageio-ffmpeg). Prints no secrets.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STS_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.1, "use_speaker_boost": True}


def ffmpeg():
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def api_key():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ELEVENLABS_API_KEY")


def clean(src: Path, dst: Path):
    """Mono 24 kHz, high-pass 80 Hz, light denoise, -18 LUFS, then the silence at
    both ends trimmed (ffmpeg's silenceremove also cuts at pauses between words)."""
    import wave

    import numpy as np
    af = "highpass=f=80,afftdn=nf=-25,loudnorm=I=-18:TP=-2:LRA=7"
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-af", af,
                    "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(dst)], check=True)
    with wave.open(str(dst)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    env = np.abs(x.astype(np.int32))
    loud = np.where(env > env.max() * 10 ** (-40 / 20))[0]
    if len(loud):
        a, b = max(0, loud[0] - int(0.12 * 24000)), min(len(x), loud[-1] + int(0.3 * 24000))
        x = x[a:b]
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(x.tobytes())


def sts_model(key: str) -> str:
    models = requests.get("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": key}, timeout=30).json()
    ids = [m["model_id"] for m in models if m.get("can_do_voice_conversion")]
    for want in ("eleven_english_sts_v2", "eleven_multilingual_sts_v2"):
        if want in ids:
            return want
    if not ids:
        raise SystemExit("no voice-conversion model on this account")
    return ids[0]


def convert(key: str, model: str, voice_id: str, wav: bytes) -> bytes:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}", params={"output_format": "pcm_24000"},
        headers={"xi-api-key": key},
        files={"audio": ("line.wav", wav, "audio/wav")},
        data={"model_id": model, "voice_settings": json.dumps(STS_SETTINGS), "remove_background_noise": "false"},
        timeout=180)
    if r.status_code != 200:
        raise SystemExit(f"speech-to-speech HTTP {r.status_code}: {r.text[:300]}")
    return r.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--voices", default="chris,river")
    ap.add_argument("--cut", default="main")
    ap.add_argument("--line", type=int, default=5, help="0-based line index in vo.PLANS[cut]")
    ap.add_argument("--dry", action="store_true", help="clean and report, no API call")
    ap.add_argument("--out", help="write <voice>.wav here instead of the cache (a test)")
    a = ap.parse_args()

    plan = vo.PLANS[a.cut]
    line = plan["lines"][a.line]
    text = vo.line_text(line)
    print(f"line {a.line} of {a.cut}: {text!r}")
    with tempfile.TemporaryDirectory() as d:
        cleaned = Path(d) / "clean.wav"
        clean(Path(a.recording), cleaned)
        wav = cleaned.read_bytes()
        secs = (len(wav) - 44) / (2 * 24000)
        print(f"cleaned recording: {secs:.2f}s")
        if a.dry:
            return
        key = api_key()
        model = sts_model(key)
        print("model:", model)
        words_path = vo.VO / "words.json"
        words = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else {}
        vo.CACHE.mkdir(parents=True, exist_ok=True)
        for voice in a.voices.split(","):
            pcm = convert(key, model, vo.EL_VOICES[voice], wav)
            k = vo.cache_key(text, voice, plan["style"])
            out = Path(a.out) / f"{voice}.wav" if a.out else vo.CACHE / f"{k}.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            import wave
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            words.pop(k, None)
            print(f"{voice:6} -> {out.name} ({len(pcm) / 48000:.2f}s)")
        if not a.out:
            words_path.write_text(json.dumps(words, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
