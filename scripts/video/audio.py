"""Original score + sound design for the RegKnot ads, synthesized from scratch.

    uv run --with numpy --with scipy python audio.py main|cutA|cutB [voice]

Reads out/<cut>_events.json (written by render.js) for the SFX sync points and
writes out/<cut>_music.wav (48 kHz stereo, peak-normalized; loudness is set
later with ffmpeg loudnorm). D minor. Main: 100 BPM with the grid anchored on
the 13.8 s drop; cuts: 94.1 BPM anchored on the 5.9 s drop so the end impact at
11.0 s lands on a downbeat.
"""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
OUT = DATA / "out"
rng = np.random.default_rng(20260929)


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def sos(kind, f, order=2):
    return signal.butter(order, f, kind, fs=SR, output="sos")


def filt(x, kind, f, order=2):
    return signal.sosfilt(sos(kind, f, order), x, axis=0)


def ramp_in(x, a=0.003):
    n = min(len(x), max(1, int(a * SR)))
    x[:n] *= np.linspace(0, 1, n) if x.ndim == 1 else np.linspace(0, 1, n)[:, None]
    return x


def polyblep_saw(f, n, phase0=0.0):
    dt = f / SR
    ph = (phase0 + dt * np.arange(n)) % 1.0
    y = 2 * ph - 1
    m = ph < dt
    x = ph[m] / dt
    y[m] -= x + x - x * x - 1
    m = ph > 1 - dt
    x = (ph[m] - 1) / dt
    y[m] -= x * x + x + x + 1
    return y


# ── mixer ──────────────────────────────────────────────────────────────────
class Mix:
    def __init__(self, dur):
        self.dur = dur
        self.n = int((dur + 3) * SR)
        self.bus = {k: np.zeros((self.n, 2)) for k in ("drums", "bass", "pad", "arp", "keys", "sfx", "low")}
        self.rev = np.zeros((self.n, 2))

    def add(self, bus, t0, sig, pan=0.0, gain=1.0, send=0.0):
        if sig.ndim == 1:
            a = (pan + 1) * math.pi / 4
            sig = np.stack([sig * math.cos(a), sig * math.sin(a)], axis=1) * math.sqrt(2)
        sig = sig * gain
        i0 = int(round(t0 * SR))
        if i0 < 0:
            sig, i0 = sig[-i0:], 0
        i1 = min(self.n, i0 + len(sig))
        if i1 <= i0:
            return
        self.bus[bus][i0:i1] += sig[: i1 - i0]
        if send:
            self.rev[i0:i1] += sig[: i1 - i0] * send


# ── instruments ────────────────────────────────────────────────────────────
def kick(gain=1.0):
    t = tt(0.6)
    f = 44 + 115 * np.exp(-t / 0.028) + 26 * np.exp(-t / 0.13)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.3)
    click = filt(rng.standard_normal(len(t)), "high", 1800) * np.exp(-t / 0.0022) * 0.5
    return np.tanh(1.6 * (body + click)) * gain


def clap(gain=1.0):
    t = tt(0.4)
    env = np.zeros_like(t)
    for d in (0.0, 0.010, 0.021):
        env += (t >= d) * np.exp(-np.clip(t - d, 0, None) / 0.006)
    env += (t >= 0.03) * np.exp(-np.clip(t - 0.03, 0, None) / 0.12) * 0.55
    n = filt(rng.standard_normal(len(t)), "band", [900, 5200])
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.05) * 0.35
    return (n * env * 0.9 + body) * gain


def hat(gain=1.0, dec=0.035):
    t = tt(dec * 9)
    n = filt(rng.standard_normal(len(t)), "high", 7200)
    return n * np.exp(-t / dec) * gain * 1.3


def bass_note(m, dur, gain=1.0):
    t = tt(dur + 0.08)
    f = hz(m)
    s = polyblep_saw(f, len(t)) + polyblep_saw(f * 1.004, len(t), 0.37)
    s = filt(s, "low", 700) * 0.7 + np.sin(2 * np.pi * f * t) * 0.5
    env = np.minimum(1, t / 0.006) * (0.72 + 0.28 * np.exp(-t / 0.25))
    rel = np.clip((dur + 0.08 - t) / 0.08, 0, 1)
    return s * env * rel * gain


def pad_chord(notes, dur, cutoff, gain=1.0, attack=0.4, release=1.1):
    total = dur + release
    t = tt(total)
    out = np.zeros((len(t), 2))
    for m in notes:
        for det, pan in ((-9, -0.7), (0, 0.0), (9, 0.7)):
            f = hz(m) * 2 ** (det / 1200)
            v = polyblep_saw(f, len(t), rng.random())
            a = (pan + 1) * math.pi / 4
            out[:, 0] += v * math.cos(a)
            out[:, 1] += v * math.sin(a)
    out = filt(out, "low", cutoff)
    env = np.minimum(1, t / attack) * np.clip((total - t) / release, 0, 1)
    env = np.minimum(env, np.where(t < dur, 1, np.clip(1 - (t - dur) / release, 0, 1)))
    return out * env[:, None] * gain / (len(notes) * 2.2)


def pluck(m, gain=1.0, dec=0.17):
    t = tt(0.7)
    f = hz(m)
    s = np.sin(2 * np.pi * f * t + 0.9 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.045))
    s = s * np.exp(-t / dec) + 0.22 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / (dec * 0.4))
    return ramp_in(s, 0.0015) * gain


def piano(m, gain=1.0):
    t = tt(3.2)
    f = hz(m)
    s = np.zeros_like(t)
    for k in range(1, 8):
        fk = k * f * (1 + 0.00035 * k * k)
        if fk > SR / 2.2:
            break
        s += (1 / k ** 1.25) * np.sin(2 * np.pi * fk * t + rng.random()) * np.exp(-t / (1.9 / k ** 0.75))
    hammer = filt(rng.standard_normal(len(t)), "low", 2500) * np.exp(-t / 0.004) * 0.15
    return ramp_in(s + hammer, 0.003) * gain * 0.55


def drone(dur, gain=1.0):
    t = tt(dur)
    f = hz(26)                                   # D1
    s = np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * 2 * f * t + 0.3) + 0.12 * np.sin(2 * np.pi * 3 * f * t)
    lfo = 0.8 + 0.2 * np.sin(2 * np.pi * 0.21 * t)
    return s * lfo * gain


# ── sound effects ──────────────────────────────────────────────────────────
def sweep_filter(x, f0, f1, q=1.3, block=256):
    """Band-pass whose centre glides f0 → f1 (log), block-wise with carried state."""
    out = np.zeros_like(x)
    nb = math.ceil(len(x) / block)
    zi = None
    for b in range(nb):
        c = f0 * (f1 / f0) ** (b / max(1, nb - 1))
        lo, hi = c / (1 + 1 / (2 * q)), min(c * (1 + 1 / (2 * q)), SR / 2.1)
        s = signal.butter(2, [lo, hi], "band", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((s.shape[0], 2) + x.shape[1:])
        seg = x[b * block:(b + 1) * block]
        y, zi = signal.sosfilt(s, seg, axis=0, zi=zi)
        out[b * block:(b + 1) * block] = y
    return out


def whoosh(gain=1.0, dur=0.55, f0=350, f1=2800):
    t = tt(dur)
    n = rng.standard_normal((len(t), 2))
    y = sweep_filter(n, f0, f1)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    pan = np.linspace(-0.6, 0.6, len(t))
    y[:, 0] *= env * np.cos((pan + 1) * np.pi / 4) * 1.4
    y[:, 1] *= env * np.sin((pan + 1) * np.pi / 4) * 1.4
    return y * gain


def riser(dur, gain=1.0):
    t = tt(dur)
    x = t / dur
    n = sweep_filter(rng.standard_normal((len(t), 2)), 180, 7000, q=1.6)
    tone = np.sin(2 * np.pi * np.cumsum(220 + 900 * x ** 2) / SR) * 0.18
    env = x ** 2.2
    return (n + tone[:, None]) * env[:, None] * gain


def impact(big=False, gain=1.0):
    t = tt(2.8 if big else 1.4)
    f = 36 + 72 * np.exp(-t / 0.07)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (1.0 if big else 0.55))
    thump = filt(rng.standard_normal(len(t)), "low", 260) * np.exp(-t / 0.09) * 0.8
    y = np.tanh(1.4 * (boom + thump))
    st = np.stack([y, y], axis=1)
    if big:
        cr = filt(rng.standard_normal((len(t), 2)), "high", 3800) * np.exp(-t / 1.1)[:, None] * 0.28
        st = st + cr
    return st * gain


def hit(gain=1.0):
    t = tt(0.9)
    f = 48 + 60 * np.exp(-t / 0.05)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.35)
    snap = filt(rng.standard_normal(len(t)), "band", [900, 4200]) * np.exp(-t / 0.05) * 0.5
    return np.tanh(1.3 * (boom + snap)) * gain


def ping(gain=1.0):
    t = tt(2.4)
    f = 1240 * (1 - 0.015 * (1 - np.exp(-t / 0.4)))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.5)
    s += 0.18 * np.sin(2 * np.pi * np.cumsum(f * 2.004) / SR) * np.exp(-t / 0.25)
    return ramp_in(s, 0.002) * gain


def key_click(gain=1.0):
    t = tt(0.035)
    c = 1800 + rng.random() * 2200
    n = filt(rng.standard_normal(len(t)), "band", [c * 0.6, min(c * 2.2, 20000)]) * np.exp(-t / 0.0035)
    s = np.sin(2 * np.pi * (1900 + rng.random() * 600) * t) * np.exp(-t / 0.005) * 0.3
    return (n + s) * gain


def tap_snd(gain=1.0):
    t = tt(0.2)
    s = np.sin(2 * np.pi * 640 * t) * np.exp(-t / 0.028) + filt(rng.standard_normal(len(t)), "high", 1500) * np.exp(-t / 0.0025) * 0.4
    return s * gain


def pop(gain=1.0):
    t = tt(0.25)
    f = 430 + 480 * np.minimum(1, t / 0.05)
    return ramp_in(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.065), 0.002) * gain


def chime(gain=1.0):
    t = tt(2.2)
    s = np.zeros_like(t)
    for f, a, d in ((hz(88), 1.0, 1.1), (hz(95), 0.55, 0.8), (hz(100), 0.3, 0.55)):
        s += a * np.sin(2 * np.pi * f * t) * np.exp(-t / d)
        s += a * 0.3 * np.sin(2 * np.pi * f * 1.0025 * t) * np.exp(-t / d)
    return ramp_in(s, 0.002) * gain * 0.6


def tick(gain=1.0):
    t = tt(0.06)
    return (np.sin(2 * np.pi * 3100 * t) * np.exp(-t / 0.009) + filt(rng.standard_normal(len(t)), "high", 4000) * np.exp(-t / 0.002) * 0.3) * gain


def stream_blips(gain=1.0):
    t = tt(0.9)
    y = np.zeros_like(t)
    for i in range(14):
        a = i * 0.055 + rng.random() * 0.02
        f = 1800 + rng.random() * 2600
        m = t >= a
        y[m] += np.sin(2 * np.pi * f * (t[m] - a)) * np.exp(-(t[m] - a) / 0.012) * (0.5 + 0.5 * rng.random())
    return y * gain


def shimmer(gain=1.0):
    t = tt(2.0)
    y = np.zeros_like(t)
    for i, m in enumerate((86, 89, 93, 98, 101, 105)):
        a = i * 0.045
        msk = t >= a
        tl = t[msk] - a
        y[msk] += np.sin(2 * np.pi * hz(m) * tl) * np.exp(-tl / 0.5) * (0.9 - i * 0.1)
    return y * gain


# ── arrangement ────────────────────────────────────────────────────────────
CH = {
    "Dm": {"pad": [50, 53, 57, 62], "bass": 38, "arp": [62, 69, 74, 77, 74, 69, 65, 69]},
    "Bb": {"pad": [46, 50, 53, 58], "bass": 34, "arp": [58, 65, 70, 74, 70, 65, 62, 65]},
    "F": {"pad": [53, 57, 60, 65], "bass": 41, "arp": [65, 69, 72, 77, 72, 69, 65, 69]},
    "C": {"pad": [48, 52, 55, 60], "bass": 36, "arp": [60, 67, 72, 76, 72, 67, 64, 67]},
}

PLANS = {
    "main": {
        "bpm": 100, "anchor": 13.8, "dur": 45.0,
        "chords": [(-0.6, "Dm"), (1.8, "Dm"), (4.2, "Bb"), (6.6, "C"), (9.0, "Dm"), (11.4, "C"), (13.8, "Dm"), (16.2, "Bb"),
                   (18.6, "F"), (21.0, "C"), (23.4, "Dm"), (25.8, "Bb"), (28.2, "F"), (30.6, "Bb"), (33.0, "F"), (35.4, "C"),
                   (37.8, "C"), (40.2, "Dm"), (42.6, "Dm")],
        "sections": [
            ("intro", 0.0, 4.8), ("build", 4.8, 9.0), ("pull", 9.0, 12.2), ("think", 12.2, 13.8),
            ("groove", 13.8, 30.0), ("stop", 30.0, 30.6), ("break", 30.6, 33.0), ("rebuild", 33.0, 40.2), ("outro", 40.2, 45.0),
        ],
        "roll": (38.4, 40.2), "fade": (43.6, 45.0),
    },
    "cut": {
        "bpm": 60 / (5.1 / 8), "anchor": 5.9, "dur": 15.0,
        "chords": [(-1.75, "Dm"), (0.8, "Dm"), (3.35, "Bb"), (5.9, "Dm"), (8.45, "C"), (11.0, "Dm"), (13.55, "Dm")],
        "sections": [("intro", 0.0, 3.0), ("pull", 3.0, 4.85), ("think", 4.85, 5.9), ("groove", 5.9, 10.7), ("stop", 10.7, 11.0), ("outro", 11.0, 15.0)],
        "roll": (10.2, 11.0), "fade": (13.9, 15.0),
    },
}


def section_at(plan, t):
    for name, a, b in plan["sections"]:
        if a <= t < b:
            return name
    return None


def chord_at(plan, t):
    cur = plan["chords"][0][1]
    for a, c in plan["chords"]:
        if t >= a - 1e-6:
            cur = c
    return cur


def build(cut: str, variant: str | None = None):
    stem = f"{cut}_{variant}" if variant else cut      # a voice-over variant has its own event log
    ev = json.loads((OUT / f"{stem}_events.json").read_text())
    plan = PLANS["main" if cut == "main" else "cut"]
    dur = plan["dur"]
    beat = 60 / plan["bpm"]
    bar = beat * 4
    mx = Mix(dur)
    origin = plan["anchor"] - bar * math.ceil(plan["anchor"] / bar)
    kicks = []

    # Pads: one chord per bar, brightness by section.
    cut_by = {"intro": 650, "build": 1800, "pull": 1300, "think": 2000, "groove": 2600, "stop": 2600, "break": 3200, "rebuild": 2700, "outro": 3400}
    gain_by = {"intro": 0.5, "build": 0.55, "pull": 0.5, "think": 0.55, "groove": 0.42, "stop": 0.0, "break": 0.62, "rebuild": 0.5, "outro": 0.6}
    for i, (a, c) in enumerate(plan["chords"]):
        nxt = plan["chords"][i + 1][0] if i + 1 < len(plan["chords"]) else a + bar
        sec = section_at(plan, max(a, 0) + 0.01) or "outro"
        if sec == "stop":
            continue
        g = gain_by[sec]
        start = max(a, 0.0)
        if cut == "main" and a <= 28.2 < nxt:       # groove chord cut off at the stop
            nxt = 30.0
        p = pad_chord(CH[c]["pad"], nxt - start, cut_by[sec], gain=g, attack=0.5 if sec in ("intro", "break") else 0.12)
        if sec == "think":                           # gated eighths while it "thinks"
            tl = np.arange(len(p)) / SR
            gate = 0.35 + 0.65 * (0.5 + 0.5 * np.cos(2 * np.pi * (tl + (start - origin)) / (beat / 2))) ** 2
            p *= gate[:, None]
        mx.add("pad", start, p, send=0.25)

    # Drone under intro / break / outro.
    for name, a, b in plan["sections"]:
        if name in ("intro", "build", "break", "outro"):
            d = drone(b - a + 0.6)
            env = np.minimum(1, np.arange(len(d)) / (0.4 * SR)) * np.clip((len(d) - np.arange(len(d))) / (0.6 * SR), 0, 1)
            mx.add("low", a, d * env, gain=0.2 if name != "build" else 0.13)

    # Grid-driven parts.
    t = origin
    step = beat / 4
    k = 0
    while t < dur:
        if t >= 0:
            sec = section_at(plan, t + 1e-6)
            c = chord_at(plan, t + 1e-6)
            b16 = k % 16                             # position in the bar (16ths)
            barn = int((t - origin + 1e-6) // bar)
            beat_i = b16 // 4
            on_beat = b16 % 4 == 0
            # clock ticks in the intro
            if sec == "intro" and b16 % 2 == 0 and t > 0.5:
                mx.add("drums", t, hat(0.10 + 0.05 * (b16 % 4 == 0)), pan=0.3)
            if sec == "build":
                if b16 in (0, 8):
                    mx.add("drums", t, kick(0.5)); kicks.append((t, 0.5))
                mx.add("drums", t, hat(0.12 if b16 % 2 else 0.2), pan=0.25)
                if b16 % 2 == 0:
                    mx.add("arp", t, pluck(CH[c]["arp"][(b16 // 2) % 8], 0.2), pan=(-0.5 if b16 % 4 else 0.5), send=0.3)
                if b16 == 0:
                    mx.add("bass", t, bass_note(CH[c]["bass"], bar * 0.98, 0.42))
            if sec == "pull":
                if b16 == 0:
                    mx.add("drums", t, kick(0.35)); kicks.append((t, 0.35))
                    mx.add("bass", t, bass_note(CH[c]["bass"], bar * 0.98, 0.35))
                if b16 % 4 == 2:
                    mx.add("arp", t, pluck(CH[c]["arp"][(b16 // 2) % 8], 0.17), pan=(-0.4 if b16 % 8 else 0.4), send=0.35)
            if sec == "groove":
                if b16 in (0, 8) or (b16 == 14 and barn % 2 == 1):
                    mx.add("drums", t, kick(0.95)); kicks.append((t, 0.95))
                if b16 in (4, 12):
                    mx.add("drums", t, clap(0.55), send=0.18)
                if b16 % 2 == 0:
                    mx.add("drums", t, hat(0.28 if b16 % 4 == 2 else 0.18), pan=0.2)
                else:
                    mx.add("drums", t, hat(0.09), pan=-0.2)
                if b16 == 14:
                    mx.add("drums", t, hat(0.16, dec=0.16), pan=0.15)
                if b16 % 2 == 0:
                    root = CH[c]["bass"] + (12 if b16 % 8 == 6 else 0)
                    mx.add("bass", t, bass_note(root, step * 1.8, 0.62))
                mx.add("arp", t, pluck(CH[c]["arp"][b16 % 8] + (12 if b16 % 8 == 3 else 0), 0.22), pan=(-0.55 if b16 % 2 else 0.55), send=0.28)
            if sec == "break" and on_beat:
                notes = CH[c]["pad"]
                mx.add("keys", t, piano(notes[(beat_i + 1) % 4] + 12, 0.42), pan=(-0.3 if beat_i % 2 else 0.3), send=0.45)
                if beat_i == 0:
                    mx.add("keys", t, piano(notes[0], 0.35), send=0.45)
            if sec == "rebuild":
                late = t >= (35.4 if cut == "main" else 99)
                if b16 in (0, 8):
                    g = 0.6 if not late else 0.9
                    mx.add("drums", t, kick(g)); kicks.append((t, g))
                if late:
                    if b16 in (4, 12):
                        mx.add("drums", t, clap(0.5), send=0.18)
                    if b16 % 2 == 0:
                        mx.add("drums", t, hat(0.24 if b16 % 4 == 2 else 0.15), pan=0.2)
                        mx.add("bass", t, bass_note(CH[c]["bass"] + (12 if b16 % 8 == 6 else 0), step * 1.8, 0.58))
                    mx.add("arp", t, pluck(CH[c]["arp"][b16 % 8], 0.2), pan=(-0.55 if b16 % 2 else 0.55), send=0.3)
                elif on_beat:
                    mx.add("keys", t, piano(CH[c]["pad"][(beat_i + 1) % 4] + 12, 0.34), pan=(-0.3 if beat_i % 2 else 0.3), send=0.45)
            if sec == "outro":
                lt = t - plan["sections"][-1][1]
                decay = max(0.0, 1 - lt / (bar * 1.6))
                if decay > 0:
                    mx.add("arp", t, pluck(CH[c]["arp"][b16 % 8] + 12, 0.2 * decay), pan=(-0.55 if b16 % 2 else 0.55), send=0.45)
        t += step
        k += 1

    # Outro: a held chord on the downbeat.
    out_t = plan["sections"][-1][1]
    for m in CH["Dm"]["pad"]:
        mx.add("keys", out_t, piano(m, 0.32), send=0.5)
    mx.add("bass", out_t, bass_note(CH["Dm"]["bass"], 2.6, 0.55))
    kicks.append((out_t, 1.0))

    # Snare roll into the final impact.
    ra, rb = plan["roll"]
    tr = ra
    while tr < rb - 0.01:
        x = (tr - ra) / (rb - ra)
        mx.add("drums", tr, clap(0.12 + 0.4 * x ** 1.5), send=0.15)
        tr += (beat / 2) if x < 0.34 else (beat / 4)
    mx.add("sfx", rb - (rb - ra), riser(rb - ra, 0.35), send=0.2)

    # Riser into the drop.
    think = [s for s in plan["sections"] if s[0] == "think"][0]
    mx.add("sfx", think[1], riser(think[2] - think[1], 0.3), send=0.2)
    tr = think[2] - beat
    while tr < think[2] - 0.01:
        x = (tr - (think[2] - beat)) / beat
        mx.add("drums", tr, clap(0.1 + 0.35 * x), send=0.12)
        tr += beat / 4

    # SFX from the stage's event log.
    # Voiced versions: soften the effects that land on consonants (chip ticks, data
    # blips, typing, risers) so the narration stays clear over them.
    soft = {"key": 0.55, "tick": 0.3, "stream": 0.3, "riser": 0.4, "pop": 0.7, "chime": 0.8} if variant else {}
    for e in ev["events"]:
        et, ty = e["t"], e["type"]
        g = e.get("gain", 1.0) * soft.get(ty, 1.0)
        if ty == "key":
            mx.add("sfx", et, key_click(0.22 * g), pan=rng.uniform(-0.2, 0.2))
        elif ty == "tap":
            mx.add("sfx", et, tap_snd(0.5 * g))
        elif ty == "whoosh":
            mx.add("sfx", et - 0.18, whoosh(0.28 * g), send=0.15)
        elif ty == "swoosh":
            mx.add("sfx", et - 0.1, whoosh(0.22 * g, dur=0.38, f0=700, f1=4200), send=0.12)
        elif ty == "sweep":
            mx.add("sfx", et - 0.1, whoosh(0.34, dur=0.8, f0=250, f1=3500), send=0.25)
        elif ty == "pop":
            mx.add("sfx", et, pop(0.22 * g), send=0.1)
        elif ty == "tick":
            mx.add("sfx", et, tick(0.2 * g), pan=rng.uniform(-0.3, 0.3))
        elif ty == "chime":
            mx.add("sfx", et, chime(0.3 * g), send=0.45)
        elif ty == "ping":
            mx.add("sfx", et, ping(0.22 * g), send=0.7)
        elif ty == "impact":
            mx.add("sfx", et, impact(e.get("big", False), 0.62 if e.get("big") else 0.55), send=0.3)
        elif ty == "hit":
            mx.add("sfx", et, hit(0.42 * g), send=0.25)
        elif ty == "riser":
            mx.add("sfx", et, riser(e.get("dur", 1.5), 0.14 * g), send=0.2)
        elif ty == "stream":
            mx.add("sfx", et, stream_blips(0.1 * g), send=0.2)
        elif ty == "shimmer":
            mx.add("sfx", et, shimmer(0.12), send=0.5)

    # Sidechain: pads/arp/bass duck under each kick.
    duck = np.zeros(mx.n)
    tl = np.arange(int(0.4 * SR)) / SR
    shape = np.exp(-tl / 0.16)
    for kt, kg in kicks:
        i0 = int(kt * SR)
        i1 = min(mx.n, i0 + len(shape))
        duck[i0:i1] = np.maximum(duck[i0:i1], shape[: i1 - i0] * min(1, kg))
    for b, depth in (("pad", 0.45), ("arp", 0.3), ("bass", 0.5)):
        mx.bus[b] *= (1 - depth * duck)[:, None]

    # Reverb: synthetic stereo room, 2.2 s.
    irt = tt(2.4)
    ir = rng.standard_normal((len(irt), 2)) * np.exp(-irt / 0.42)[:, None]
    ir = filt(ir, "low", 5200)
    ir[: int(0.018 * SR)] = 0
    ir /= np.sqrt((ir ** 2).sum(axis=0))
    wet = np.stack([signal.fftconvolve(mx.rev[:, c], ir[:, c])[: mx.n] for c in range(2)], axis=1)

    lvl = {"drums": 0.9, "bass": 0.75, "pad": 0.8, "arp": 0.85, "keys": 0.85, "sfx": 1.0, "low": 0.6}
    mix = sum(mx.bus[b] * g for b, g in lvl.items()) + wet * 0.55
    mix = filt(mix, "high", 34)
    # Phone speakers stop around 150 Hz: lift presence and top so the track still reads.
    mix = mix + 0.3 * filt(mix, "band", [1200, 4500]) + 0.6 * filt(mix, "high", 5000)
    # Fade at the very end.
    fa, fb = plan["fade"]
    tl = np.arange(mx.n) / SR
    mix *= np.clip(1 - (tl - fa) / (fb - fa), 0, 1)[:, None] ** 1.5
    mix = mix[: int(dur * SR)]
    # Level: RMS to about -17 dBFS, soft-clip, peak -1 dBFS.
    rms = np.sqrt((mix ** 2).mean())
    mix *= 10 ** (-17 / 20) / max(rms, 1e-9)
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    mix *= 10 ** (-1 / 20) / np.abs(mix).max()
    f = OUT / f"{stem}_music.wav"
    wavfile.write(f, SR, (mix * 32767).astype(np.int16))
    print(f, f"{len(mix) / SR:.2f}s", "kicks", len(kicks))


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "main", sys.argv[2] if len(sys.argv) > 2 else None)
