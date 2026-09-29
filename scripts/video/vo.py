"""Temp AI voice-over for the RegKnot ads, until Karynn's own recording arrives.

    python vo.py requests            -> data/video/vo/requests.json (lines not yet cached)
    (run vo_tts_remote.py where a working OpenAI key lives; unpack into data/video/vo/cache/)
    python vo.py build <cut> <voice> -> data/video/vo/<cut>_<voice>.wav (the VO track)
                                        data/video/vo/<cut>_<voice>.js  (caption timings for the stage)

The narrator is a stock OpenAI voice, never Karynn's: her line 6 is read in the
third person ("Built by Captain Karynn Marchal…") so the synthetic voice never
claims to be her. Each line is generated whole for natural phrasing, split at its
own pauses, and each piece is placed at its caption's time; the captions are then
retimed to the speech.
"""
import hashlib
import json
import math
import os
import sys
import wave
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
VO = DATA / "vo"
CACHE = VO / "cache"
SR = 48000

VOICES = {"marin": "female narrator", "cedar": "male narrator"}
MODEL = "gpt-4o-mini-tts"
STYLE = (
    "Voice: an experienced American merchant mariner: calm, confident, warm and plain-spoken. "
    "Delivery: unhurried and natural, like one captain talking to another on the bridge, with short "
    "natural pauses at commas, colons and full stops. No announcer hype. "
    "Pronunciation: 'RegKnot' is said 'REG-not' (the K is silent); 'regknots.com' is 'reg-nots dot com'; "
    "spell out U-S-C-G, T-V-R and T-P-O letter by letter."
)
STYLE_SHORT = STYLE + " These are short, punchy lines for a 15-second social ad: crisp, with a little more energy."

# Each line: chunks of (spoken text, caption text or None, anchor time or None).
# A caption of None means the words are already on screen (hero text, name card,
# end card). An anchor is where that piece should start; None follows the previous
# piece at its natural gap. A line whose only anchor is on a later piece is placed
# backwards from it.
PLANS = {
    "main": {
        "style": STYLE,
        "lines": [
            [("Every captain gets the question", "Every captain gets the question", None),
             ("at the worst moment:", "at the worst moment:", None),
             ("is that actually required?", None, 3.30)],
            [("The answer's in there somewhere.", "The answer's in there somewhere.", 5.0),
             ("Thousands of pages of it.", "*Thousands* of pages of it.", 6.85)],
            [("So I ask RegKnot,", "So I ask *RegKnot*,", 9.1),
             ("the way I'd ask another captain.", "the way I'd ask another captain.", 10.55)],
            [("It answers for my vessel,", "It answers for *my vessel*,", 13.9),
             ("in plain English,", "in plain English,", 15.6),
             ("and it shows exactly where it's written.", "and it shows exactly *where it's written.*", 16.85)],
            [("Tap the citation,", "Tap the citation,", 24.1),
             ("and there's the regulation itself.", "and there's *the regulation itself.*", 25.3)],
            [("Built by Captain Karynn Marchal, a USCG Master Unlimited.", None, 30.55)],
            [("Made for working mariners,", "Made for *working mariners*,", 33.7),
             ("and for fleets, it answers", "and for fleets, it answers", 36.1),
             ("from your own safety management system, too.", "from your own *safety management system*, too.", None)],
            [("Try it free at regknots.com.", None, 41.1)],
        ],
        "cap_limits": {1: 8.9, 3: 19.3, 6: 40.1},
        # Line 1 lands its last phrase on the 3.3 s title slam; the name-card line
        # reads long, so it starts with the card and runs a little quicker.
        "opts": {0: {"tempo": 1.08}, 5: {"anchor0": 30.0, "tempo": 1.15}, 6: {"tempo": 1.06}},
    },
    "cutA": {
        "style": STYLE_SHORT,
        "tempo": 1.1,
        "opts": {0: {"anchor0": 0.1, "gap_scale": 0.5}},
        "stack": 0,       # line 0's pieces drive the opener's stacked words
        "lines": [
            [("New deckhand.", None, 0.2), ("First trip.", None, None), ("Orientation first?", None, None)],
            [("Ask RegKnot.", "Ask *RegKnot*.", 3.1)],
            [("Yes, before the boat gets underway.", "*Yes,* before the boat gets underway.", 6.0)],
            [("Ten topics.", "*10* topics.", 7.9)],
            [("Logged.", "*Logged.*", 9.55)],
            [("Try it free at regknots.com.", None, 12.2)],
        ],
        "cap_limits": {4: 10.95},
    },
    "cutB": {
        "style": STYLE_SHORT,
        "tempo": 1.1,
        "opts": {2: {"anchor0": 5.95}, 3: {"tempo": 1.18}},
        "lines": [
            [("TPO audit coming?", None, 0.3)],
            [("Ask RegKnot.", "Ask *RegKnot*.", 3.1)],
            [("Here's what your TVR has to show.", "Here's what your *TVR* has to show.", 6.0)],
            [("Ten required items, each one cited.", "*Ten required items,* each one cited.", 8.3)],
            [("Try it free at regknots.com.", None, 12.2)],
        ],
        "cap_limits": {3: 10.85},
    },
}


def line_text(line):
    return " ".join(c[0] for c in line)


def cache_key(text, voice, style):
    return hashlib.sha1(f"{MODEL}|{voice}|{style}|{text}".encode()).hexdigest()[:16]


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:                                   # TTS returns 24 kHz
        from scipy.signal import resample_poly
        g = math.gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g)
    return x


def trim(x, thresh_db=-45):
    """Strip leading/trailing silence; returns (audio, seconds cut from the front)."""
    env = np.abs(x)
    lvl = 10 ** (thresh_db / 20) * env.max()
    idx = np.where(env > lvl)[0]
    if not len(idx):
        return x, 0.0
    a, b = max(0, idx[0] - int(0.01 * SR)), min(len(x), idx[-1] + int(0.04 * SR))
    return x[a:b], a / SR


def pauses(x, min_len=0.07, thresh_db=-38):
    """Silent runs inside x as (start_s, end_s)."""
    hop = int(0.01 * SR)
    frames = len(x) // hop
    rms = np.array([np.sqrt((x[i * hop:(i + 1) * hop] ** 2).mean() + 1e-12) for i in range(frames)])
    lvl = rms.max() * 10 ** (thresh_db / 20)
    quiet = rms < lvl
    out, i = [], 0
    while i < frames:
        if quiet[i]:
            j = i
            while j < frames and quiet[j]:
                j += 1
            if (j - i) * 0.01 >= min_len and i > 0 and j < frames:
                out.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return out


def frame_rms(x, hop):
    frames = len(x) // hop
    return np.array([np.sqrt((x[i * hop:(i + 1) * hop] ** 2).mean() + 1e-12) for i in range(frames)])


def split_at_words(x, chunks, words):
    """Cut between the last word of each chunk and the first word of the next.
    Whisper's word times can be off by tens of milliseconds, so only audio that is
    actually silent (the longest quiet run near the boundary) is removed as the gap;
    with no quiet run, cut at the quietest 10 ms and remove nothing. None when
    Whisper's word count differs from the script's."""
    counts = [len(c[0].split()) for c in chunks]
    if not words or len(words) != sum(counts):
        return None
    rms = frame_rms(x, int(0.01 * SR))
    quiet = rms < rms.max() * 10 ** (-40 / 20)
    pieces, gaps, prev, w = [], [], 0.0, 0
    for k in range(len(chunks) - 1):
        w += counts[k]
        end, start = words[w - 1][2], words[w][1]
        lo = max(int((min(end, start) - 0.06) / 0.01), int(prev / 0.01) + 5)
        hi = min(int((max(end, start) + 0.06) / 0.01), len(rms) - 1)
        runs, i = [], lo
        while i <= hi:
            if quiet[i]:
                j = i
                while j <= hi and quiet[j]:
                    j += 1
                runs.append((i, j))
                i = j
            else:
                i += 1
        if runs:
            ra, rb = max(runs, key=lambda r: r[1] - r[0])
            a, b = (ra + 1) * 0.01, max((ra + 1) * 0.01, (rb - 1) * 0.01)   # keep 10 ms either side
        else:
            a = b = (lo + int(np.argmin(rms[lo:hi + 1]))) * 0.01
        pieces.append(x[int(prev * SR):int(a * SR)])
        gaps.append(b - a)
        prev = b
    pieces.append(x[int(prev * SR):])
    return pieces, gaps


def split_line(x, chunks, words=None):
    """Split one generated line into len(chunks) pieces: at Whisper's word
    boundaries when they line up with the chunks, otherwise at the line's own
    pauses (the longest pause near each expected boundary, by character share),
    or, when the voice ran the words together, the quietest 10 ms there."""
    n = len(chunks)
    if n == 1:
        return [x], []
    by_words = split_at_words(x, chunks, words)
    if by_words:
        return by_words
    ps = pauses(x)
    total = sum(len(c[0]) for c in chunks)
    dur = len(x) / SR
    win = 0.22 * dur
    cuts, acc, floor = [], 0, 0.0
    for k in range(n - 1):
        acc += len(chunks[k][0])
        want = dur * acc / total
        near = [p for p in ps if p[0] > floor + 0.15 and abs((p[0] + p[1]) / 2 - want) <= win]
        if near:
            best = min(near, key=lambda p: abs((p[0] + p[1]) / 2 - want) - 0.5 * (p[1] - p[0]))
        else:
            rms = frame_rms(x, int(0.01 * SR))
            lo = max(int((want - win) / 0.01), int(floor / 0.01) + 15)
            hi = min(int((want + win) / 0.01), len(rms) - 2)
            i = lo + int(np.argmin(rms[lo:hi]))
            best = (i * 0.01, (i + 1) * 0.01)
        cuts.append(best)
        floor = best[1]
    pieces, gaps, prev = [], [], 0.0
    for (a, b) in cuts:
        pieces.append(x[int(prev * SR):int(a * SR)])
        gaps.append(b - a)
        prev = b
    pieces.append(x[int(prev * SR):])
    return pieces, gaps


def atempo(x, tempo):
    """Pitch-preserving speed change through ffmpeg's atempo."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / "out.wav"
        with wave.open(str(src), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        subprocess.run([os.environ["FFMPEG"], "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-filter:a", f"atempo={tempo}", str(dst)], check=True)
        return load_wav(dst)


def place(anchors, durs, gaps, min_start):
    """Start times for one line's pieces. Anchored pieces start at their anchor
    (never overlapping the piece before); a line anchored only on a later piece is
    laid out backwards from it; nothing starts before min_start."""
    n = len(durs)
    starts = [None] * n
    if anchors[0] is None:
        j = next(i for i, a in enumerate(anchors) if a is not None)
        starts[j] = anchors[j]
        for i in range(j - 1, -1, -1):
            starts[i] = starts[i + 1] - gaps[i] - durs[i]
        if starts[0] < min_start:
            shift = min_start - starts[0]
            starts[:j + 1] = [s + shift for s in starts[:j + 1]]
    else:
        starts[0] = max(anchors[0], min_start)
    for i in range(1, n):
        floor = starts[i - 1] + durs[i - 1] + 0.1
        if starts[i] is None:
            starts[i] = starts[i - 1] + durs[i - 1] + gaps[i - 1] if anchors[i] is None else max(anchors[i], floor)
        else:
            starts[i] = max(starts[i], floor)
    return starts


def requests():
    VO.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    reqs, seen = [], set()
    for cut, plan in PLANS.items():
        for line in plan["lines"]:
            text = line_text(line)
            for voice in VOICES:
                k = cache_key(text, voice, plan["style"])
                if k in seen or (CACHE / f"{k}.wav").exists():
                    continue
                seen.add(k)
                reqs.append({"id": k, "model": MODEL, "voice": voice, "text": text, "instructions": plan["style"]})
    (VO / "requests.json").write_text(json.dumps(reqs, indent=1), encoding="utf-8")
    print(f"{len(reqs)} requests -> {VO / 'requests.json'} ({sum(len(r['text']) for r in reqs)} chars)")


WORDS = json.loads((VO / "words.json").read_text(encoding="utf-8")) if (VO / "words.json").exists() else {}


def build(cut, voice):
    plan = PLANS[cut]
    lines = plan["lines"]
    dur = 45.0 if cut == "main" else 15.0
    track = np.zeros(int((dur + 1) * SR))
    caps, stack, report, placed = [], [], [], []
    prev_end = 0.1 - 0.22
    for li, line in enumerate(lines):
        opts = plan.get("opts", {}).get(li, {})
        k = cache_key(line_text(line), voice, plan["style"])
        x, lead = trim(load_wav(CACHE / f"{k}.wav"))
        tempo = opts.get("tempo", plan.get("tempo", 1.0))
        words = [[w, (a - lead) / tempo, (b - lead) / tempo] for w, a, b in WORDS.get(k, [])]
        if tempo != 1.0:
            x = atempo(x, tempo)
        pieces, gaps = split_line(x, line, words)
        gaps = [g * opts.get("gap_scale", 1.0) for g in gaps]
        durs = [len(p) / SR for p in pieces]
        anchors = [c[2] for c in line]
        if "anchor0" in opts:
            anchors[0] = opts["anchor0"]
        starts = place(anchors, durs, gaps, prev_end + 0.22)   # lines never overlap
        prev_end = starts[-1] + durs[-1]
        placed.append((starts, durs))
        for s, p in zip(starts, pieces):
            a = int(round(s * SR))
            fade = np.ones(len(p))
            f = min(len(p), int(0.008 * SR))
            fade[:f] = np.linspace(0, 1, f)
            fade[-f:] = np.linspace(1, 0, f)
            track[a:a + len(p)] += p * fade
        if plan.get("stack") == li:
            stack = [round(s, 3) for s in starts]
        report.append(f"x{tempo:<4} " + " | ".join(f"{s:5.2f}+{d:4.2f} {c[0][:26]!r}" for s, d, c in zip(starts, durs, line)))
    # Captions follow the speech: each shows from its words until the next piece
    # (or 0.55 s after the line), never into the next line or past the scene's limit.
    for li, line in enumerate(lines):
        starts, durs = placed[li]
        capd = [(i, c[1]) for i, c in enumerate(line) if c[1]]
        for n, (i, text) in enumerate(capd):
            a = starts[i] - 0.06
            b = starts[i] + durs[i] + 0.55
            if i + 1 < len(starts):
                b = min(b, starts[i + 1] - 0.03)
            if n + 1 < len(capd):
                b = starts[capd[n + 1][0]] - 0.03
            if li + 1 < len(lines):
                b = min(b, placed[li + 1][0][0] - 0.08)
            b = min(b, plan.get("cap_limits", {}).get(li, b))
            caps.append([round(a, 3), round(max(b, a + 0.6), 3), text])
    peak = np.abs(track).max()
    track *= 10 ** (-3 / 20) / max(peak, 1e-9)
    out = VO / f"{cut}_{voice}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((track[: int(dur * SR)] * 32767).astype(np.int16).tobytes())
    js = VO / f"{cut}_{voice}.js"
    js.write_text("window.VO = " + json.dumps({"voice": voice, "caps": caps, "stack": stack}) + ";\n", encoding="utf-8")
    print(out)
    for r in report:
        print("  ", r)
    for c in caps:
        print(f"   cap {c[0]:6.2f}-{c[1]:6.2f} {c[2]}")


if __name__ == "__main__":
    if sys.argv[1] == "requests":
        requests()
    elif sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
