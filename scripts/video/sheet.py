"""Tile render stills into one review image: python sheet.py out.jpg a.png b.png ..."""
import sys
from PIL import Image, ImageDraw, ImageFont

out, files = sys.argv[1], sys.argv[2:]
scale = float(__import__("os").environ.get("SHEET_SCALE", "0.36"))
cw, ch = int(1080 * scale), int(1920 * scale)
cols = min(len(files), int(__import__("os").environ.get("SHEET_COLS", "4")))
rows = (len(files) + cols - 1) // cols
img = Image.new("RGB", (cols * (cw + 8), rows * (ch + 30)), "white")
d = ImageDraw.Draw(img)
font = ImageFont.truetype("arial.ttf", 20)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB").resize((cw, ch), Image.LANCZOS)
    x, y = (i % cols) * (cw + 8), (i // cols) * (ch + 30)
    img.paste(im, (x, y))
    d.text((x + 4, y + ch + 4), f.rsplit("_", 1)[-1].replace(".png", "s"), fill="black", font=font)
img.save(out, quality=88)
print(out, img.size)
