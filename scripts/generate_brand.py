"""Generate the RegKnot marketing brand asset set.

Single source of truth for the compass rose mark + the wordmark layouts.
Outputs to apps/web/public/brand/.

Run from repo root:
    python scripts/generate_brand.py
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "apps" / "web" / "public" / "brand"
OUT.mkdir(parents=True, exist_ok=True)

TEAL = "#2dd4bf"
NAVY = "#0a0e1a"
WHITE = "#ffffff"
TAGLINE_DARK = "#94a3b8"
TAGLINE_LIGHT = "#64748b"

WORD_FONT = "'Barlow Condensed', 'Barlow Semi Condensed', 'Oswald', 'Liberation Sans Narrow', 'Arial Narrow', Impact, sans-serif"
TAG_FONT = "'IBM Plex Mono', 'DejaVu Sans Mono', 'Liberation Mono', monospace"


def compass(color: str, cx: float = 60, cy: float = 60, scale: float = 1.0) -> str:
    """Return compass-rose markup translated/scaled into the parent viewBox.

    The base compass occupies a 120x120 box centered on (60,60).
    """
    # Translate so the 0..120 box is centered on (cx, cy) at the requested scale
    tx = cx - 60 * scale
    ty = cy - 60 * scale
    return dedent(
        f"""\
        <g transform="translate({tx} {ty}) scale({scale})" fill="none" stroke="{color}">
          <circle cx="60" cy="60" r="56" stroke-width="0.5" stroke-dasharray="3 7"/>
          <circle cx="60" cy="60" r="34" stroke-width="0.5"/>
          <line x1="60" y1="4" x2="60" y2="116" stroke-width="0.5"/>
          <line x1="4" y1="60" x2="116" y2="60" stroke-width="0.5"/>
          <line x1="20" y1="20" x2="100" y2="100" stroke-width="0.3"/>
          <line x1="100" y1="20" x2="20" y2="100" stroke-width="0.3"/>
          <path d="M60 6 L65 52 L60 57 L55 52 Z" fill="{color}" stroke="none"/>
          <path d="M60 114 L65 68 L60 63 L55 68 Z" fill="{color}" fill-opacity="0.45" stroke="none"/>
          <path d="M114 60 L68 65 L63 60 L68 55 Z" fill="{color}" fill-opacity="0.45" stroke="none"/>
          <path d="M6 60 L52 65 L57 60 L52 55 Z" fill="{color}" fill-opacity="0.45" stroke="none"/>
          <path d="M98 22 L68 56 L64 52 L71 45 Z" fill="{color}" fill-opacity="0.25" stroke="none"/>
          <path d="M22 22 L52 56 L56 52 L49 45 Z" fill="{color}" fill-opacity="0.25" stroke="none"/>
          <path d="M98 98 L68 64 L64 68 L71 75 Z" fill="{color}" fill-opacity="0.25" stroke="none"/>
          <path d="M22 98 L52 64 L56 68 L49 75 Z" fill="{color}" fill-opacity="0.25" stroke="none"/>
          <circle cx="60" cy="60" r="4" fill="{color}" stroke="none"/>
          <circle cx="60" cy="60" r="9" stroke-width="0.8"/>
          <text x="60" y="3.5" text-anchor="middle" font-size="7" fill="{color}" font-weight="700" stroke="none" font-family="{WORD_FONT}">N</text>
        </g>"""
    )


def svg(viewbox: str, body: str, width: int | None = None, height: int | None = None) -> str:
    wh = ""
    if width and height:
        wh = f' width="{width}" height="{height}"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}"{wh} fill="none">\n'
        f"{body}\n"
        "</svg>\n"
    )


def write(name: str, content: str) -> None:
    (OUT / name).write_text(content, encoding="utf-8")
    print(f"  wrote {name}  ({len(content)} bytes)")


# ─── Logo mark only (1–3) ────────────────────────────────────────────────────
def mark(color: str) -> str:
    return svg("0 0 120 120", compass(color))


write("logo-mark-teal-transparent.svg", mark(TEAL))
write("logo-mark-navy-transparent.svg", mark(NAVY))
write("logo-mark-white-transparent.svg", mark(WHITE))


# ─── Full horizontal: compass + REGKNOT (4–6) ────────────────────────────────
# viewBox: 0 0 480 120. Compass at left (0..120), gap 20, then wordmark.
# Wordmark baseline ≈ y=82, font-size 80, letter-spacing 3.
# In two-color versions: REG in `prefix` color, KNOT in teal.
def full_horizontal(compass_color: str, prefix_color: str, knot_color: str = TEAL) -> str:
    body = compass(compass_color, cx=60, cy=60, scale=1.0)
    body += dedent(
        f"""\

        <g font-family="{WORD_FONT}" font-weight="700" font-size="80" letter-spacing="3" text-rendering="geometricPrecision">
          <text x="148" y="84" fill="{prefix_color}">REG<tspan fill="{knot_color}">KNOT</tspan></text>
        </g>"""
    )
    return svg("0 0 480 120", body)


write("logo-full-dark.svg", full_horizontal(TEAL, WHITE, TEAL))
write("logo-full-light.svg", full_horizontal(NAVY, NAVY, TEAL))
write(
    "logo-full-white.svg",
    svg(
        "0 0 480 120",
        compass(WHITE, cx=60, cy=60, scale=1.0)
        + dedent(
            f"""\

            <g font-family="{WORD_FONT}" font-weight="700" font-size="80" letter-spacing="3" text-rendering="geometricPrecision">
              <text x="148" y="84" fill="{WHITE}">REGKNOT</text>
            </g>"""
        ),
    ),
)


# ─── With tagline (7–8) ──────────────────────────────────────────────────────
# Same horizontal layout; tagline below the wordmark.
# Wordmark size 72, baseline y=72; tagline size 18, baseline y=100.
def full_tagline(compass_color: str, prefix_color: str, tagline_color: str, knot_color: str = TEAL) -> str:
    body = compass(compass_color, cx=60, cy=60, scale=1.0)
    body += dedent(
        f"""\

        <g font-family="{WORD_FONT}" font-weight="700" font-size="72" letter-spacing="3" text-rendering="geometricPrecision">
          <text x="148" y="74" fill="{prefix_color}">REG<tspan fill="{knot_color}">KNOT</tspan></text>
        </g>
        <g font-family="{TAG_FONT}" font-weight="400" font-size="14" letter-spacing="2">
          <text x="150" y="100" fill="{tagline_color}">MARITIME COMPLIANCE CO-PILOT</text>
        </g>"""
    )
    return svg("0 0 520 120", body)


write("logo-tagline-dark.svg", full_tagline(TEAL, WHITE, TAGLINE_DARK))
write("logo-tagline-light.svg", full_tagline(NAVY, NAVY, TAGLINE_LIGHT))


# ─── Stacked (9–10) ──────────────────────────────────────────────────────────
# viewBox 0 0 360 360. Compass top-center (cx=180, cy=130, scale=1.5 → 180 wide),
# wordmark centered horizontally below.
def stacked(compass_color: str, prefix_color: str, knot_color: str = TEAL) -> str:
    body = compass(compass_color, cx=180, cy=130, scale=1.6)
    body += dedent(
        f"""\

        <g font-family="{WORD_FONT}" font-weight="700" font-size="72" letter-spacing="3" text-anchor="middle" text-rendering="geometricPrecision">
          <text x="180" y="300" fill="{prefix_color}">REG<tspan fill="{knot_color}">KNOT</tspan></text>
        </g>"""
    )
    return svg("0 0 360 360", body)


write("logo-stacked-dark.svg", stacked(TEAL, WHITE, TEAL))
write("logo-stacked-light.svg", stacked(NAVY, NAVY, TEAL))


print("\nAll SVGs written to", OUT)
