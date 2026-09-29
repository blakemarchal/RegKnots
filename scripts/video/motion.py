"""Frame-to-frame change curve of a render, to spot one-frame glitches."""
import sys
import numpy as np
import imageio_ffmpeg

f = sys.argv[1]
gen = imageio_ffmpeg.read_frames(f, output_params=["-vf", "scale=270:480"])
meta = next(gen)
w, h = meta["size"]
prev, diffs = None, []
for i, fr in enumerate(gen):
    a = np.frombuffer(fr, np.uint8).reshape(h, w, 3).astype(np.int16)
    if prev is not None:
        diffs.append(float(np.abs(a - prev).mean()))
    prev = a
d = np.array(diffs)
print("frames", len(d) + 1, "mean diff", round(d.mean(), 2))
# spikes: a frame whose change is far above both neighbours (glitch) vs sustained change (cut/motion)
for i in range(1, len(d) - 1):
    if d[i] > 6 and d[i] > 3 * max(d[i - 1], d[i + 1], 0.5):
        print(f"spike at frame {i + 1} (t={(i + 1) / 30:.2f}s): {d[i]:.1f} vs {d[i - 1]:.1f}/{d[i + 1]:.1f}")
# coarse curve
print(" ".join(f"{k}:{d[k * 30:(k + 1) * 30].mean():.1f}" for k in range(len(d) // 30)))
