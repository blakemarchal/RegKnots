"""Mix a voice-over track over a cut's music: the music ducks under the voice and
the voice sits about 9 dB above the ducked bed.

    uv run --with numpy --with scipy python mix_vo.py <cut> <voice>

Reads out/<cut>_<voice>_music.wav and vo/<cut>_<voice>.wav; writes
out/<cut>_<voice>_mix.wav (peak -1 dBFS; finish.py sets the loudness).
"""
import os
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
SR = 48000
DUCK_DB = 10.0       # music reduction under speech
VO_OVER_DB = 10.0    # speech level above the ducked music


def read(path):
    sr, x = wavfile.read(path)
    assert sr == SR, (path, sr)
    return x.astype(np.float64) / 32768


def smooth(env, attack, release):
    """One-pole follower with separate attack/release (seconds), per 1 ms step."""
    a, r = np.exp(-1 / (attack * 1000)), np.exp(-1 / (release * 1000))
    out = np.zeros_like(env)
    y = 0.0
    for i, v in enumerate(env):
        c = a if v > y else r
        y = c * y + (1 - c) * v
        out[i] = y
    return out


def main(cut, voice):
    name = f"{cut}_{voice}"
    music = read(DATA / "out" / f"{name}_music.wav")
    vo = read(DATA / "vo" / f"{name}.wav")
    n = min(len(music), len(vo))
    music, vo = music[:n], vo[:n]
    # Voice: low cut and a little presence.
    vo = signal.sosfilt(signal.butter(2, 80, "high", fs=SR, output="sos"), vo)
    vo = vo + 0.25 * signal.sosfilt(signal.butter(2, [2200, 5000], "band", fs=SR, output="sos"), vo)
    # Speech envelope on a 1 ms grid.
    hop = SR // 1000
    frames = n // hop
    rms = np.sqrt((vo[: frames * hop].reshape(frames, hop) ** 2).mean(axis=1) + 1e-12)
    rms = np.convolve(rms, np.ones(30) / 30, mode="same")
    ref = np.percentile(rms[rms > rms.max() * 0.05], 90) if (rms > rms.max() * 0.05).any() else rms.max()
    active = np.clip(rms / ref * 1.6, 0, 1)
    duck_env = smooth(active, attack=0.04, release=0.45)
    gain = 1 - (1 - 10 ** (-DUCK_DB / 20)) * duck_env
    gain = np.repeat(gain, hop)
    gain = np.concatenate([gain, np.full(n - len(gain), gain[-1] if len(gain) else 1.0)])
    ducked = music * gain[:, None]
    # Voice level: VO_OVER_DB above the ducked music where speech is active.
    act = np.repeat(active > 0.35, hop)
    act = np.concatenate([act, np.zeros(n - len(act), bool)])
    speech = np.sqrt((vo[act] ** 2).mean())
    bed = np.sqrt((ducked[act].mean(axis=1) ** 2).mean())
    g_vo = 10 ** (VO_OVER_DB / 20) * bed / max(speech, 1e-9)
    mix = ducked + (vo * g_vo)[:, None]
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)
    mix *= 10 ** (-1 / 20) / np.abs(mix).max()
    out = DATA / "out" / f"{name}_mix.wav"
    wavfile.write(out, SR, (mix * 32767).astype(np.int16))
    print(out, f"voice gain {20 * np.log10(g_vo):+.1f} dB, speech active {act.mean() * 100:.0f}% of the cut")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
