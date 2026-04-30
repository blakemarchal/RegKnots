"""Sprint D6.25 — generate QR codes for brand-page sharing.

One QR per landing entry-point so Karynn (and partners) can drop them on
business cards / fliers / event handouts. Each QR points to the public
URL with a `?ref=qr-<source>` tag so we can attribute scans in Caddy
analytics. Run after editing the QR list:

    python scripts/generate_brand_qr.py

Output: apps/web/public/brand/qr/<slug>.svg
"""
from __future__ import print_function

import os
import sys

try:
    import qrcode
    import qrcode.image.svg as qrsvg
except ImportError:
    print("qrcode library not installed. Run: pip install qrcode")
    sys.exit(1)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
OUT_DIR = os.path.join(REPO_ROOT, "apps", "web", "public", "brand", "qr")

QRS = [
    ("regknot",        "https://regknots.com/?ref=qr-card"),
    ("captainkarynn",  "https://regknots.com/captainkarynn?ref=qr-card"),
    ("ass",            "https://regknots.com/ass?ref=qr-card"),
    ("womenoffshore",  "https://regknots.com/womenoffshore?ref=qr-card"),
    ("pricing",        "https://regknots.com/pricing?ref=qr-card"),
    ("coverage",       "https://regknots.com/coverage?ref=qr-card"),
]

def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    factory = qrsvg.SvgPathImage
    for slug, url in QRS:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=factory)
        out_path = os.path.join(OUT_DIR, slug + ".svg")
        with open(out_path, "wb") as f:
            img.save(f)
        print("  wrote", out_path, "->", url)
    print("Done.", len(QRS), "QR codes written to", OUT_DIR)

if __name__ == "__main__":
    main()
