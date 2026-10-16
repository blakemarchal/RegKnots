"""Bring a new browser-pane capture into the raw format prep.py expects, and say
how far it sits from the frame it replaces (2026-10-16 recapture).

The September frames were a 390x844 phone viewport drawn at 464/390 into a
488x1055 image (the app is the top-left 464x1003). The pane returns the same
viewport at whatever scale it is shown at (780x1688 hidden, 434x938 shown on a
750 px tall pane), so a new frame is scaled to 464 wide and pasted into a
488x1055 canvas of the old page colour.

    python recapture.py NEW.jpg OUT.jpg [OLD.jpg]

With OLD, prints the vertical shift d such that the new frame's row y shows
the old frame's row y+d (content rows 80..840): d > 0 means the new frame is
scrolled d image px further down, so scroll up by d * 390/464 CSS px.
"""
import sys

import numpy as np
from PIL import Image

W, H, FRAME = 464, 1003, (488, 1055)


def main():
    new, out = sys.argv[1], sys.argv[2]
    old = sys.argv[3] if len(sys.argv) > 3 else None
    im = Image.open(new).convert("RGB")
    if im.size == FRAME:
        # Shown pane: the viewport sits top-left on the page colour; find its edges.
        a = np.asarray(im).astype(np.int16)
        page = a[-4, -4]
        off = np.abs(a - page).max(axis=2) > 8
        bottom = int(np.where(off[:, :400].any(axis=1))[0].max()) + 1
        right = round(bottom * 390 / 844)      # the right edge blurs into a shadow
        im = im.crop((0, 0, right, bottom))
        print(f"viewport {right}x{bottom} inside the {FRAME[0]}x{FRAME[1]} frame")
    if abs(im.width / im.height - 390 / 844) > 0.01:
        raise SystemExit(f"expected a capture of a 390x844 viewport, got {im.size}")
    small = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
    bg = (10, 14, 26)
    if old:
        bg = Image.open(old).convert("RGB").getpixel((FRAME[0] - 4, FRAME[1] - 4))
    canvas = Image.new("RGB", FRAME, bg)
    canvas.paste(small.crop((0, 0, W, H)), (0, 0))
    canvas.save(out, quality=95)
    if not old:
        return
    a = np.asarray(Image.open(old).convert("L")).astype(np.float32)[:H, :440]
    b = np.asarray(canvas.convert("L")).astype(np.float32)[:H, :440]
    best = None
    for d in range(-500, 501):
        lo, hi = max(80, 80 - d), min(840, 840 - d)
        if hi - lo < 160:
            continue
        diff = float(np.abs(b[lo:hi] - a[lo + d:hi + d]).mean())
        if best is None or diff < best[1]:
            best = (d, diff)
    d, diff = best
    print(f"shift d={d} image px (scroll {'up' if d > 0 else 'down'} {abs(d) * 390 / 464:.1f} CSS px), diff={diff:.2f}")


if __name__ == "__main__":
    main()
