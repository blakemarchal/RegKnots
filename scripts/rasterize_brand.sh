#!/usr/bin/env bash
# Rasterize the SVG brand assets to PNG using rsvg-convert.
# Run on a host with librsvg2-bin + Barlow Condensed Bold + IBM Plex Mono Regular installed.

set -euo pipefail

BRAND_DIR="${BRAND_DIR:-apps/web/public/brand}"
cd "$(git rev-parse --show-toplevel)"

if ! command -v rsvg-convert >/dev/null; then
  echo "rsvg-convert not found. apt install librsvg2-bin" >&2
  exit 1
fi

# Logo marks → 512x512 square
for name in logo-mark-teal-transparent logo-mark-navy-transparent logo-mark-white-transparent; do
  rsvg-convert -w 512 -h 512 "$BRAND_DIR/$name.svg" -o "$BRAND_DIR/$name.png"
  echo "  $name.png"
done

# Full horizontal logos → 1200x300 (4:1 viewBox 480x120)
for name in logo-full-dark logo-full-light logo-full-white; do
  rsvg-convert -w 1200 -h 300 "$BRAND_DIR/$name.svg" -o "$BRAND_DIR/$name.png"
  echo "  $name.png"
done

# Tagline horizontal logos → 1300x300 (viewBox 520x120)
for name in logo-tagline-dark logo-tagline-light; do
  rsvg-convert -w 1300 -h 300 "$BRAND_DIR/$name.svg" -o "$BRAND_DIR/$name.png"
  echo "  $name.png"
done

# Stacked logos → 600x600
for name in logo-stacked-dark logo-stacked-light; do
  rsvg-convert -w 600 -h 600 "$BRAND_DIR/$name.svg" -o "$BRAND_DIR/$name.png"
  echo "  $name.png"
done

# ── Social cards ─────────────────────────────────────────────────────────────
# Render the tagline-dark SVG centered onto a navy background canvas of the
# requested size. We do this by writing a wrapper SVG with a navy <rect> +
# the tagline composition, then rasterize.

mkdir -p "$BRAND_DIR/.tmp"

cat > "$BRAND_DIR/.tmp/og.svg" <<'OG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <rect width="1200" height="630" fill="#0a0e1a"/>
  <g transform="translate(220 235) scale(1.5)">
    OG_INNER
  </g>
</svg>
OG

cat > "$BRAND_DIR/.tmp/tw.svg" <<'TW'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600">
  <rect width="1200" height="600" fill="#0a0e1a"/>
  <g transform="translate(220 220) scale(1.5)">
    TW_INNER
  </g>
</svg>
TW

# Pull the inner content of logo-tagline-dark.svg (everything between <svg ...> and </svg>)
INNER=$(sed -n '/<svg/,/<\/svg>/p' "$BRAND_DIR/logo-tagline-dark.svg" | sed '1d;$d')
# Escape & for sed
ESCAPED=$(printf '%s\n' "$INNER" | sed 's/[&/\]/\\&/g')

# Use python for safer substitution
python3 - <<PY
from pathlib import Path
inner = Path("$BRAND_DIR/logo-tagline-dark.svg").read_text()
import re
m = re.search(r"<svg[^>]*>(.*)</svg>", inner, re.S)
body = m.group(1).strip()
for src, marker in [("$BRAND_DIR/.tmp/og.svg", "OG_INNER"), ("$BRAND_DIR/.tmp/tw.svg", "TW_INNER")]:
    p = Path(src)
    p.write_text(p.read_text().replace(marker, body))
PY

rsvg-convert -w 1200 -h 630 "$BRAND_DIR/.tmp/og.svg" -o "$BRAND_DIR/og-image.png"
echo "  og-image.png"
rsvg-convert -w 1200 -h 600 "$BRAND_DIR/.tmp/tw.svg" -o "$BRAND_DIR/twitter-card.png"
echo "  twitter-card.png"

rm -rf "$BRAND_DIR/.tmp"
echo "Done."
