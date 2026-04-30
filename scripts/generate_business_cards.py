"""Sprint D6.28 - generate business-card SVG variants.

Karynn pushed back on the coverage flag-strip on the back of the card.
Rather than ping-pong on a single design, this script emits 5 distinct
variants she can pick from, plus the current default. Each variant is a
front+back pair, sized 3.5" x 2" @ 300 DPI (1050 x 600 px) with print
bleed safe-area inside the central 950 x 500 region.

Run: python scripts/generate_business_cards.py
Output: apps/web/public/brand/business-card-<slug>-{front,back}.svg

Variants:
  clean        - Navy front + Bone back, no coverage (just QR + URL)
  titles       - Navy front + Bone back, coverage = regulation title pills
  flag-chips   - Navy front + Bone back, coverage = flag+code chips (CorpusBadges-style)
  all-navy     - Navy front + Navy back, no coverage (premium dark scheme)
  all-bone     - Bone front (navy text) + Bone back, no coverage (light scheme)

The previously-shipped default (Navy + Bone with full flag strip) stays
in place at business-card-front.svg + business-card-back.svg so existing
print orders don't get clobbered.

All flag references are inlined as base64 data: URIs so the SVGs travel
self-contained when downloaded for print/email.
"""
import base64
import os
import re
from typing import Dict, List, Tuple  # noqa: F401  (kept for forward-compat)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PUBLIC_DIR = os.path.join(REPO_ROOT, "apps", "web", "public")
BRAND_DIR = os.path.join(PUBLIC_DIR, "brand")
FLAGS_DIR = os.path.join(BRAND_DIR, "flags")
QR_DIR = os.path.join(BRAND_DIR, "qr")


# ── Asset loading ────────────────────────────────────────────────────────


def load_flag_data_uris():
    """Read each flag SVG and produce base64 data: URIs for inlining."""
    out = {}
    for fn in sorted(os.listdir(FLAGS_DIR)):
        if not fn.endswith(".svg"):
            continue
        cc = fn[:-4]
        with open(os.path.join(FLAGS_DIR, fn), "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        out[cc] = "data:image/svg+xml;base64," + b64
    return out


def load_qr_path():
    """Extract the single path-data string from the regknot QR SVG."""
    src = os.path.join(QR_DIR, "regknot.svg")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'<path d="([^"]+)"', content)
    if not m:
        raise RuntimeError("No path found in regknot QR SVG")
    return m.group(1)


# ── Color schemes ────────────────────────────────────────────────────────


# Tokens lifted from the brand spec (apps/web/src/app/brand/page.tsx).
NAVY = "#0a0e1a"
BONE = "#f0ece4"
TEAL = "#2dd4bf"
TAGLINE_GRAY = "#94a3b8"
INK_DARK = "#0a0e1a"  # dark text on bone
INK_LIGHT = "#f0ece4"  # light text on navy
SUB_DARK = "#5b6478"  # secondary dark text
SUB_LIGHT = "#6b7594"  # secondary light text


# ── Reusable SVG fragments ───────────────────────────────────────────────


def compass_grid_backdrop(stroke, opacity=0.10):
    """Right-side compass-rose pattern used as backdrop on the front."""
    return f"""  <g stroke="{stroke}" stroke-width="0.6" fill="none" opacity="{opacity}">
    <circle cx="850" cy="300" r="220"/>
    <circle cx="850" cy="300" r="155"/>
    <circle cx="850" cy="300" r="90"/>
    <line x1="630" y1="300" x2="1070" y2="300"/>
    <line x1="850" y1="80"  x2="850" y2="520"/>
    <line x1="694" y1="144" x2="1006" y2="456"/>
    <line x1="694" y1="456" x2="1006" y2="144"/>
  </g>"""


def brand_mark(stroke, fill):
    """The compass logo at translate(720,170) scale(2.2)."""
    return f"""  <g transform="translate(720,170) scale(2.2)" stroke="{stroke}" fill="none">
    <circle cx="60" cy="60" r="56" stroke-width="0.5" stroke-dasharray="3 7"/>
    <circle cx="60" cy="60" r="34" stroke-width="0.5"/>
    <line x1="60" y1="4" x2="60" y2="116" stroke-width="0.5"/>
    <line x1="4" y1="60" x2="116" y2="60" stroke-width="0.5"/>
    <line x1="20" y1="20" x2="100" y2="100" stroke-width="0.3"/>
    <line x1="100" y1="20" x2="20" y2="100" stroke-width="0.3"/>
    <path d="M60 6 L65 52 L60 57 L55 52 Z" fill="{fill}" stroke="none"/>
    <path d="M60 114 L65 68 L60 63 L55 68 Z" fill="{fill}" fill-opacity="0.45" stroke="none"/>
    <path d="M114 60 L68 65 L63 60 L68 55 Z" fill="{fill}" fill-opacity="0.45" stroke="none"/>
    <path d="M6 60 L52 65 L57 60 L52 55 Z" fill="{fill}" fill-opacity="0.45" stroke="none"/>
    <circle cx="60" cy="60" r="4" fill="{fill}" stroke="none"/>
    <circle cx="60" cy="60" r="9" stroke-width="0.8"/>
  </g>"""


def front_template(bg, text_main, text_sub, accent, grid_stroke, grid_opacity):
    """Render a complete front-card SVG with the given color scheme."""
    return f"""<!-- RegKnot business card front (3.5\" x 2\" @ 300 DPI = 1050 x 600 px). -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 600" width="1050" height="600">
  <rect width="1050" height="600" fill="{bg}"/>
{compass_grid_backdrop(grid_stroke, grid_opacity)}

{brand_mark(accent, accent)}

  <!-- Wordmark + tagline -->
  <g font-family="&apos;Barlow Condensed&apos;, &apos;Barlow Semi Condensed&apos;, &apos;Oswald&apos;, &apos;Arial Narrow&apos;, Impact, sans-serif">
    <text x="80" y="240" font-size="92" font-weight="800" letter-spacing="2" fill="{text_main}">RegKnot</text>
    <text x="80" y="290" font-size="22" font-weight="500" letter-spacing="6" fill="{text_sub}">MARITIME COMPLIANCE CO-PILOT</text>
  </g>

  <!-- Divider stripe -->
  <rect x="80" y="320" width="60" height="3" fill="{accent}"/>

  <!-- Name + role -->
  <g font-family="&apos;Barlow Condensed&apos;, &apos;Oswald&apos;, &apos;Arial Narrow&apos;, Impact, sans-serif">
    <text x="80" y="378" font-size="38" font-weight="700" fill="{text_main}" letter-spacing="0.5">Karynn Marchal</text>
    <text x="80" y="410" font-size="18" font-weight="500" fill="{text_sub}" letter-spacing="3">CO-FOUNDER &#183; MASTER UNLIMITED</text>
  </g>

  <!-- Contact -->
  <g font-family="&apos;IBM Plex Mono&apos;, &apos;Courier New&apos;, monospace" font-size="16" fill="{text_main}">
    <text x="80" y="480">captain@regknots.com</text>
    <text x="80" y="510">regknots.com</text>
  </g>
</svg>
"""


# ── Coverage strip variants ──────────────────────────────────────────────


def coverage_none():
    return ""


def coverage_flags(flags, dark_text, sub_text):
    """The original wide flag strip - used by the legacy default card."""
    rows = []
    for i, cc in enumerate(["us", "gb", "au", "no", "sg", "hk", "bs", "lr", "mh"]):
        x = i * 48
        rows.append(
            f'      <image x="{x}" y="0" width="42" height="30" href="{flags[cc]}"/>'
        )
    return f"""
  <g transform="translate(345 520)">
    <text x="0" y="14" font-family="&apos;IBM Plex Mono&apos;, monospace" font-size="10" letter-spacing="2" fill="{sub_text}">COVERAGE</text>
    <g transform="translate(110 0)">
{chr(10).join(rows)}
    </g>
    <text x="588" y="20" font-size="11" font-weight="700" letter-spacing="1.5" fill="{dark_text}">+ IMO</text>
  </g>"""


def coverage_titles(dark_text, sub_text, accent):
    """Coverage as a row of regulation title pills.

    Pills: CFR | SOLAS | STCW | MARPOL | IMDG | ISM | NVIC | + 12 more
    Sized to fit comfortably in the bottom band (y=485-555) without
    crowding the URL line above.
    """
    titles = ["CFR", "SOLAS", "STCW", "MARPOL", "IMDG", "ISM", "NVIC"]
    pills = []
    pad = 10
    gap = 6
    # Approximate widths so we lay the row out manually rather than rely
    # on text-anchor arithmetic. Each pill = title_width + 2*pad.
    widths = [38, 56, 48, 64, 50, 38, 46]
    x = 0
    for title, w in zip(titles, widths):
        pills.append(
            f'<rect x="{x}" y="0" width="{w}" height="22" rx="11" '
            f'fill="none" stroke="{accent}" stroke-width="1"/>'
            f'<text x="{x + w/2}" y="15" font-family="&apos;IBM Plex Mono&apos;, monospace" '
            f'font-size="10" font-weight="700" letter-spacing="1" '
            f'text-anchor="middle" fill="{dark_text}">{title}</text>'
        )
        x += w + gap
    total_width = x - gap
    plus_more = (
        f'<text x="{x}" y="15" font-family="&apos;IBM Plex Mono&apos;, monospace" '
        f'font-size="10" font-weight="500" fill="{sub_text}">+ 12 more</text>'
    )
    full_width = total_width + 70
    start_x = (1050 - full_width) // 2
    return f"""
  <g transform="translate({start_x} 510)">
    <text x="0" y="-10" font-family="&apos;IBM Plex Mono&apos;, monospace" font-size="10" letter-spacing="2" fill="{sub_text}">SOURCES</text>
    {''.join(pills)}{plus_more}
  </g>"""


def coverage_flag_chips(flags, dark_text, sub_text, accent):
    """Coverage as flag+country-code chips matching CorpusBadges style.

    Each chip = 14x10 flag icon + 2-letter code, rounded pill, accent
    border. Used in CorpusBadges on the "what we know" landing section
    so the card and the website carry the same visual language.
    """
    items = [("us", "US"), ("gb", "UK"), ("au", "AU"), ("no", "NO"),
              ("sg", "SG"), ("hk", "HK"), ("bs", "BS"), ("lr", "LR"),
              ("mh", "MH")]
    chip_w = 50
    gap = 6
    chips = []
    for i, (cc, code) in enumerate(items):
        x = i * (chip_w + gap)
        chips.append(
            f'<g transform="translate({x} 0)">'
            f'<rect x="0" y="0" width="{chip_w}" height="22" rx="11" '
            f'fill="none" stroke="{accent}" stroke-width="1"/>'
            f'<image x="6" y="6" width="14" height="10" href="{flags[cc]}"/>'
            f'<text x="34" y="15" font-family="&apos;IBM Plex Mono&apos;, monospace" '
            f'font-size="10" font-weight="700" letter-spacing="0.5" '
            f'text-anchor="middle" fill="{dark_text}">{code}</text>'
            f'</g>'
        )
    full_width = len(items) * (chip_w + gap) - gap
    start_x = (1050 - full_width) // 2
    return f"""
  <g transform="translate({start_x} 510)">
    <text x="0" y="-10" font-family="&apos;IBM Plex Mono&apos;, monospace" font-size="10" letter-spacing="2" fill="{sub_text}">FLAG STATES</text>
    {''.join(chips)}
  </g>"""


# ── Back template ────────────────────────────────────────────────────────


def back_template(bg, dark_text, sub_text, accent, qr_card_fill,
                   qr_card_stroke, qr_path, coverage_svg):
    """Render a complete back-card SVG with the given color scheme + coverage."""
    return f"""<!-- RegKnot business card back (3.5\" x 2\" @ 300 DPI = 1050 x 600 px). -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 600" width="1050" height="600">
  <rect width="1050" height="600" fill="{bg}"/>

  <!-- Tagline -->
  <g font-family="&apos;Barlow Condensed&apos;, &apos;Oswald&apos;, &apos;Arial Narrow&apos;, Impact, sans-serif" fill="{dark_text}">
    <text x="525" y="80" font-size="32" font-weight="800" text-anchor="middle" letter-spacing="2">SCAN TO START</text>
    <text x="525" y="115" font-size="16" font-weight="500" text-anchor="middle" letter-spacing="6" fill="{sub_text}">7-DAY FREE TRIAL &#183; NO CARD</text>
  </g>

  <!-- QR card -->
  <rect x="375" y="155" width="300" height="300" rx="14" fill="{qr_card_fill}" stroke="{qr_card_stroke}" stroke-width="2"/>
  <g transform="translate(395 175) scale(7.879)">
    <path d="{qr_path}" fill="{dark_text}"/>
  </g>

  <!-- URL line -->
  <g font-family="&apos;IBM Plex Mono&apos;, &apos;Courier New&apos;, monospace" font-size="14" fill="{dark_text}">
    <text x="525" y="487" text-anchor="middle" font-weight="700">regknots.com</text>
  </g>
{coverage_svg}
</svg>
"""


# ── Variant definitions ──────────────────────────────────────────────────


# (slug, front_kwargs, back_kwargs, coverage_fn_name)
def make_variants(flags, qr_path):
    return [
        # 1. Clean — current scheme, no coverage strip
        {
            "slug": "clean",
            "label": "Clean (no coverage)",
            "desc": "Navy front, bone back. Just QR + URL.",
            "front": dict(bg=NAVY, text_main=BONE, text_sub=TAGLINE_GRAY,
                          accent=TEAL, grid_stroke=TEAL, grid_opacity=0.10),
            "back": dict(bg=BONE, dark_text=INK_DARK, sub_text=SUB_DARK,
                         accent=NAVY, qr_card_fill="#fff",
                         qr_card_stroke=NAVY, qr_path=qr_path,
                         coverage_svg=coverage_none()),
        },
        # 2. Titles — reg title pills
        {
            "slug": "titles",
            "label": "Reg titles",
            "desc": "Navy front, bone back. Coverage as regulation title pills.",
            "front": dict(bg=NAVY, text_main=BONE, text_sub=TAGLINE_GRAY,
                          accent=TEAL, grid_stroke=TEAL, grid_opacity=0.10),
            "back": dict(bg=BONE, dark_text=INK_DARK, sub_text=SUB_DARK,
                         accent=NAVY, qr_card_fill="#fff",
                         qr_card_stroke=NAVY, qr_path=qr_path,
                         coverage_svg=coverage_titles(INK_DARK, SUB_DARK, NAVY)),
        },
        # 3. Flag chips — small flag + code chips, CorpusBadges style
        {
            "slug": "flag-chips",
            "label": "Flag chips",
            "desc": "Navy front, bone back. Coverage as flag+code chips.",
            "front": dict(bg=NAVY, text_main=BONE, text_sub=TAGLINE_GRAY,
                          accent=TEAL, grid_stroke=TEAL, grid_opacity=0.10),
            "back": dict(bg=BONE, dark_text=INK_DARK, sub_text=SUB_DARK,
                         accent=NAVY, qr_card_fill="#fff",
                         qr_card_stroke=NAVY, qr_path=qr_path,
                         coverage_svg=coverage_flag_chips(flags, INK_DARK, SUB_DARK, NAVY)),
        },
        # 4. All-Navy — premium dark scheme, no coverage
        {
            "slug": "all-navy",
            "label": "All Navy",
            "desc": "Navy front + Navy back. Premium dark, no coverage.",
            "front": dict(bg=NAVY, text_main=BONE, text_sub=TAGLINE_GRAY,
                          accent=TEAL, grid_stroke=TEAL, grid_opacity=0.10),
            "back": dict(bg=NAVY, dark_text=BONE, sub_text=TAGLINE_GRAY,
                         accent=TEAL, qr_card_fill=BONE,
                         qr_card_stroke=TEAL, qr_path=qr_path,
                         coverage_svg=coverage_none()),
        },
        # 5. All-Bone — minimalist light scheme, no coverage
        {
            "slug": "all-bone",
            "label": "All Bone",
            "desc": "Bone front (navy text) + Bone back. Minimalist light.",
            "front": dict(bg=BONE, text_main=INK_DARK, text_sub=SUB_DARK,
                          accent=NAVY, grid_stroke=NAVY, grid_opacity=0.08),
            "back": dict(bg=BONE, dark_text=INK_DARK, sub_text=SUB_DARK,
                         accent=NAVY, qr_card_fill="#fff",
                         qr_card_stroke=NAVY, qr_path=qr_path,
                         coverage_svg=coverage_none()),
        },
    ]


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    flags = load_flag_data_uris()
    qr_path = load_qr_path()
    variants = make_variants(flags, qr_path)
    written = []
    for v in variants:
        slug = v["slug"]
        front_path = os.path.join(BRAND_DIR, f"business-card-{slug}-front.svg")
        back_path = os.path.join(BRAND_DIR, f"business-card-{slug}-back.svg")
        with open(front_path, "w", encoding="utf-8") as f:
            f.write(front_template(**v["front"]))
        with open(back_path, "w", encoding="utf-8") as f:
            f.write(back_template(**v["back"]))
        written.append((slug, front_path, back_path))
        print(f"  {slug:14s} -> {os.path.basename(front_path)} + {os.path.basename(back_path)}")
    print(f"Done. {len(written)} variants ({2*len(written)} files) in {BRAND_DIR}")


if __name__ == "__main__":
    main()
