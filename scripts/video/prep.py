"""Crop, clean and stitch the real app captures into video assets.

Raw captures are 488x1055; the app itself is the top-left 464x1003 (the rest is
page background). Fixed chrome: header rows 0-71, composer rows 848-1002. The
right-hand scrollbar (desktop pane only; a phone shows none) is painted out.
Everything is saved at 2x with Lanczos + a light unsharp mask; the stage scales
it back down.
"""
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DATA = Path(os.environ.get("REGKNOT_VIDEO_DATA", Path(__file__).resolve().parents[2] / "data" / "video"))
RAW = DATA / "raw"
OUT = DATA / "assets"
OUT.mkdir(exist_ok=True)

W, H = 464, 1003
HEADER_END = 72          # header rows 0..71
COMPOSER_START = 848     # composer rows 848..1002
CLEAN_TOP, CLEAN_BOT = 80, 840   # content rows free of the fade overlays
BG = np.array([10, 14, 26])
SCALE = 2

F = {
    "consult1": "1790702330305-uddqkg",
    "stream1": "1790702330307-mp1ozv",
    "final_a": "1790702389647-opcztd",
    "final_b": "1790702389647-s2zkz2",
    "final_c": "1790702389647-5y1nwg",
    "bottom": "1790702356150-jv579c",
    "sheet_a": "1790702406354-l3tasu",
    "sheet_b": "1790702423400-rin8pg",
    "menu": "1790702463994-9p5zqp",
    "dossier": "1790702602104-46272o",
    "consult2": "1790702500702-mkas5w",
    "q2_top": "1790702500703-wftet1",
    "q2_list_a": "1790702541704-jlqd5q",
    "q2_list_b": "1790702541704-ohrxfm",
}


def load(key: str) -> np.ndarray:
    im = Image.open(RAW / f"{F[key]}.jpg").convert("RGB")
    return np.asarray(im).astype(np.int16)[:H, :W]


def paint_out_scrollbar(a: np.ndarray, y0: int, y1: int) -> np.ndarray:
    """Columns 452..463 carry the pane's scrollbar thumb; extend the row's
    background into them instead."""
    a = a.copy()
    for y in range(y0, y1):
        src = a[y, 446:450].mean(axis=0)
        fill = src if np.abs(src - BG).max() < 14 else a[y, 440:446].min(axis=0)
        a[y, 452:W] = fill
    return a


def save(a: np.ndarray, name: str, radius_mask: int = 0) -> dict:
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    im = im.resize((im.width * SCALE, im.height * SCALE), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))
    if radius_mask:
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, im.width - 1, im.height + radius_mask * SCALE * 2],
            radius=radius_mask * SCALE, fill=255)
        im = im.convert("RGBA")
        im.putalpha(mask)
    im.save(OUT / f"{name}.png", optimize=True)
    return {"file": f"{name}.png", "w": a.shape[1], "h": a.shape[0]}


def best_shift(a: np.ndarray, b: np.ndarray, top: int, bot: int,
               band: tuple[int, int] | None = None) -> tuple[int, float]:
    """Shift d such that b[top+k] == a[top+d+k]; compare only x < 440.

    With `band`, only b's rows band[0]..band[1] are compared (for a streaming
    frame whose lower part differs from the final answer)."""
    best = (0, 1e9)
    for d in range(1, bot - top - 40):
        if band:
            b0, b1 = band
            if b1 + d > bot:
                break
            diff = np.abs(a[b0 + d:b1 + d, :440] - b[b0:b1, :440]).mean()
        else:
            diff = np.abs(a[top + d:bot, :440] - b[top:bot - d, :440]).mean()
        if diff < best[1]:
            best = (d, float(diff))
    return best


manifest: dict = {}

# ── full frames ──────────────────────────────────────────────────────────────
for key in ("consult1", "stream1", "bottom", "menu", "consult2", "q2_top"):
    a = paint_out_scrollbar(load(key), HEADER_END, COMPOSER_START)
    manifest[key] = save(a, key)

# Vessel dossier: profile only (credentials and the official-number row stay out).
d = paint_out_scrollbar(load("dossier"), HEADER_END, 410)[:410]
manifest["dossier"] = save(d, "dossier")

# Fixed chrome, from the final (idle) and streaming states.
fa = load("final_a")
manifest["header"] = save(fa[:HEADER_END], "header")
manifest["composer_idle"] = save(fa[COMPOSER_START:], "composer_idle")
manifest["composer_busy"] = save(load("stream1")[COMPOSER_START:], "composer_busy")

# ── Q1 final answer strip: bubble + streaming top from mp1ozv, then the final
# answer's scroll positions ───────────────────────────────────────────────────
s1 = paint_out_scrollbar(load("stream1"), 0, H)
seq = [paint_out_scrollbar(load(k), 0, H) for k in ("final_a", "final_b", "final_c")]

# final_a's first clean rows (the answer's opening paragraph) inside mp1ozv.
dq, sc = best_shift(s1, seq[0], CLEAN_TOP, CLEAN_BOT, band=(CLEAN_TOP, CLEAN_TOP + 120))
print(f"stream1 -> final_a: d={dq} diff={sc:.2f}")
strip = [s1[CLEAN_TOP:CLEAN_TOP + dq]]          # bubble etc. above final_a's top
prev = seq[0]
strip.append(prev[CLEAN_TOP:CLEAN_BOT + 1])
for nxt in seq[1:]:
    dd, sc = best_shift(prev, nxt, CLEAN_TOP, CLEAN_BOT + 1)
    print(f"  next: d={dd} diff={sc:.2f}")
    strip.append(nxt[CLEAN_BOT + 1 - dd:CLEAN_BOT + 1])
    prev = nxt
q1 = np.concatenate(strip, axis=0)
manifest["q1_strip"] = save(q1, "q1_strip")
manifest["q1_strip"]["answer_top"] = dq         # strip row where final_a begins

# ── Citation sheet ───────────────────────────────────────────────────────────
sa, sb = load("sheet_a"), load("sheet_b")
diff = np.abs(sa[:, :440] - sb[:, :440]).mean(axis=1).mean(axis=1)
body_top = next(y for y in range(300, H) if diff[y] > 2.0)
body_bot = next(y for y in range(H - 1, 300, -1) if diff[y] > 2.0)
print(f"sheet body rows {body_top}..{body_bot}")
sheet_top = next(y for y in range(250, 400)
                 if np.abs(sa[y, 100:360] - np.array([20, 26, 42])).max() < 10
                 and np.abs(sa[y + 6, 100:360] - np.array([20, 26, 42])).max() < 12)
print(f"sheet top row ~{sheet_top}")
# Sheet chrome (title block + footer) from sheet_a; body stitched from both.
sa_c, sb_c = paint_out_scrollbar(sa, body_top, body_bot + 1), paint_out_scrollbar(sb, body_top, body_bot + 1)
bt, bb = body_top + 4, body_bot - 4
dd, sc = best_shift(sa_c, sb_c, bt, bb + 1)
print(f"sheet a -> b: d={dd} diff={sc:.2f}")
body = np.concatenate([sa_c[bt:bb + 1], sb_c[bb + 1 - dd:bb + 1]], axis=0)
manifest["sheet_body"] = save(body, "sheet_body")
manifest["sheet_head"] = save(sa[sheet_top - 3:bt], "sheet_head", radius_mask=20)
manifest["sheet_foot"] = save(sa[bb + 1:H], "sheet_foot")
manifest["sheet_geom"] = {"top": sheet_top - 3, "body_top": bt, "body_bot": bb + 1}
manifest["sheet_full"] = save(paint_out_scrollbar(sa, 0, H), "sheet_full")

# ── Q2 list strip ────────────────────────────────────────────────────────────
qa = paint_out_scrollbar(load("q2_list_a"), 0, H)
qb = paint_out_scrollbar(load("q2_list_b"), 0, H)
dd, sc = best_shift(qa, qb, CLEAN_TOP, CLEAN_BOT + 1)
print(f"q2 list a -> b: d={dd} diff={sc:.2f}")
q2 = np.concatenate([qa[CLEAN_TOP:CLEAN_BOT + 1], qb[CLEAN_BOT + 1 - dd:CLEAN_BOT + 1]], axis=0)
manifest["q2_strip"] = save(q2, "q2_strip")
qt = paint_out_scrollbar(load("q2_top"), 0, H)
dd2, sc2 = best_shift(qt, qa, CLEAN_TOP, CLEAN_BOT + 1)
print(f"q2 top -> list a: d={dd2} diff={sc2:.2f}  (only usable if diff is small)")

manifest["geom"] = {"W": W, "H": H, "header_end": HEADER_END, "composer_start": COMPOSER_START,
                    "clean_top": CLEAN_TOP, "clean_bot": CLEAN_BOT, "scale": SCALE}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
print(json.dumps({k: (v.get("h") if isinstance(v, dict) and "h" in v else v) for k, v in manifest.items()}, indent=None))
