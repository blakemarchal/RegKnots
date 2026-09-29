import sys
import numpy as np
from scipy.io import wavfile
from scipy import signal
from PIL import Image, ImageDraw, ImageFont

f = sys.argv[1]
sr, x = wavfile.read(f)
x = x.astype(np.float64) / 32768
mono = x.mean(axis=1)
print(f, x.shape, "peak", round(float(np.abs(x).max()), 3), "dc", round(float(mono.mean()), 5))
win = int(0.5 * sr)
line = []
for i in range(0, len(mono), win):
    r = np.sqrt((mono[i:i + win] ** 2).mean() + 1e-12)
    line.append(f"{i / sr:4.1f}:{20 * np.log10(r):6.1f}")
print("  ".join(line))
L, R = x[:, 0], x[:, 1]
print("stereo corr", round(float(np.corrcoef(L, R)[0, 1]), 3))
# band energy split
fr, P = signal.welch(mono, sr, nperseg=8192)
def band(a, b):
    m = (fr >= a) & (fr < b)
    return 10 * np.log10(P[m].sum() + 1e-18)
print("bands dB: sub<60 %.1f | low 60-250 %.1f | mid 250-2k %.1f | hi 2k-8k %.1f | air >8k %.1f" % (band(20, 60), band(60, 250), band(250, 2000), band(2000, 8000), band(8000, 20000)))
# spectrogram image
fS, tS, S = signal.spectrogram(mono, sr, nperseg=2048, noverlap=1536)
S = 10 * np.log10(S + 1e-12)
m = fS < 8000
S = S[m][::-1]
S = np.clip((S - (S.max() - 80)) / 80, 0, 1)
img = Image.fromarray((S * 255).astype(np.uint8)).resize((1800, 400))
d = ImageDraw.Draw(img)
dur = len(mono) / sr
for s in range(0, int(dur) + 1):
    X = int(s / dur * 1800)
    d.line([(X, 390), (X, 400)], fill=255)
    if s % 5 == 0:
        d.text((X + 2, 380), str(s), fill=255)
img.save(sys.argv[2])
