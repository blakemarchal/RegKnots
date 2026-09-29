"""Mux the audio into the silent renders, make the 16:9 versions, covers and share copies.

    python finish.py main [cutA cutB]              # music only
    python finish.py main cutA cutB --vo marin     # temp AI voice-over (mix_vo.py output)

Outputs in out/final/ (masters) and out/share/ (small copies to send around).
Loudness: two-pass EBU R128 loudnorm to -14 LUFS integrated, -1.5 dBTP.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

FF = os.environ["FFMPEG"]
DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
OUT = DATA / "out"
FIN = OUT / "final"
SHARE = OUT / "share"
FIN.mkdir(exist_ok=True)
SHARE.mkdir(exist_ok=True)
NAMES = {"main": "RegKnot_main_45s", "cutA": "RegKnot_first-trip_15s", "cutB": "RegKnot_audit_15s"}
VOICE_TAG = {"marin": "AI-voice-female", "cedar": "AI-voice-male"}
COVER_T = {"main": 3.9, "cutA": 2.6, "cutB": 2.4}


def run(args):
    p = subprocess.run([FF, "-hide_banner", "-y", *args], capture_output=True, text=True)
    if p.returncode:
        print(p.stderr[-3000:])
        raise SystemExit(p.returncode)
    return p.stderr


def loudnorm_filter(wav: Path) -> str:
    err = run(["-i", str(wav), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = json.loads(re.findall(r"\{[^{}]*\}", err, re.S)[-1])
    print(f"  measured I={m['input_i']} TP={m['input_tp']} LRA={m['input_lra']}")
    return (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")


def finish(cut, voice=None):
    key = f"{cut}_{voice}" if voice else cut
    name = NAMES[cut] + (f"_{VOICE_TAG[voice]}" if voice else "")
    silent = OUT / f"{key}_9x16_silent.mp4"
    wav = OUT / (f"{key}_mix.wav" if voice else f"{key}_music.wav")
    v = FIN / f"{name}_9x16.mp4"
    print(key)
    af = loudnorm_filter(wav)
    run(["-i", str(silent), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", af + ",aresample=48000", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(v)])
    # 16:9: the vertical video, rounded, centred on the brand panel.
    w = FIN / f"{name}_16x9.mp4"
    run(["-loop", "1", "-i", str(OUT / "wide_bg.png"), "-i", str(v), "-i", str(OUT / "wide_mask.png"),
         "-filter_complex",
         "[1:v]scale=562:1000:flags=lanczos,format=rgba[v];[2:v]format=gray,scale=562:1000[m];[v][m]alphamerge[vr];"
         "[0:v][vr]overlay=679:40:shortest=1,format=yuv420p[out]",
         "-map", "[out]", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-r", "30",
         "-c:a", "copy", "-movflags", "+faststart", str(w)])
    # Covers.
    run(["-ss", str(COVER_T[cut]), "-i", str(v), "-frames:v", "1", "-q:v", "2", str(FIN / f"{name}_cover_9x16.jpg")])
    run(["-ss", str(COVER_T[cut]), "-i", str(w), "-frames:v", "1", "-q:v", "2", str(FIN / f"{name}_cover_16x9.jpg")])
    # Share copies: small enough for email and messaging.
    share_base = name.replace("_9x16", "")
    run(["-i", str(v), "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-maxrate", "4M", "-bufsize", "8M",
         "-c:a", "copy", "-movflags", "+faststart", str(SHARE / f"{share_base}_vertical.mp4")])
    run(["-i", str(w), "-c", "copy", "-movflags", "+faststart", str(SHARE / f"{share_base}_widescreen.mp4")])
    for f in (v, w, SHARE / f"{share_base}_vertical.mp4"):
        print(f"  {f.name}  {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    argv = sys.argv[1:]
    voice = None
    if "--vo" in argv:
        i = argv.index("--vo")
        voice = argv[i + 1]
        del argv[i:i + 2]
    for c in argv or ["main"]:
        finish(c, voice)
