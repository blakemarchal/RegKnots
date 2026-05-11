#!/usr/bin/env bash
# Generate apps/web/public/user-guide.pdf from docs/user-guide/user-guide.md.
#
# Uses pandoc + xelatex. Pandoc renders the markdown to a styled PDF
# with proper headers, footers, page numbers, and link colors. The
# generated artifact is committed as a static asset so it's served
# directly by Next.js at regknots.com/user-guide.pdf.
#
# Requirements:
#   - pandoc 2.x or 3.x
#   - xelatex (texlive-xetex)
#   - DejaVu fonts (texlive-fonts-recommended typically includes them)
#
# On the VPS these are already installed (apt-get install pandoc
# texlive-xetex texlive-fonts-recommended texlive-fonts-extra lmodern).
#
# Local development without pandoc: copy the markdown to the VPS via
# scp, run this script there, scp the PDF back.
#
# Usage:
#   ./scripts/generate_user_guide_pdf.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MD_PATH="$REPO_ROOT/docs/user-guide/user-guide.md"
PDF_PATH="$REPO_ROOT/apps/web/public/user-guide.pdf"
HEADER_TEX="$(mktemp --suffix=.tex)"
trap 'rm -f "$HEADER_TEX"' EXIT

if ! command -v pandoc >/dev/null 2>&1; then
    echo "ERROR: pandoc not installed. On Debian/Ubuntu:" >&2
    echo "  apt-get install pandoc texlive-xetex texlive-fonts-recommended texlive-fonts-extra lmodern" >&2
    exit 1
fi

cat > "$HEADER_TEX" <<'EOF'
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\fancyfoot[C]{\thepage}
\fancyhead[L]{\small RegKnots User Guide}
\fancyhead[R]{\small v1.0}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0pt}
EOF

mkdir -p "$(dirname "$PDF_PATH")"

pandoc "$MD_PATH" -o "$PDF_PATH" \
    --pdf-engine=xelatex \
    -V geometry:margin=1in \
    -V fontsize=11pt \
    -V mainfont='DejaVu Serif' \
    -V sansfont='DejaVu Sans' \
    -V monofont='DejaVu Sans Mono' \
    -V colorlinks=true \
    -V linkcolor='Maroon' \
    -V urlcolor='Teal' \
    -V documentclass=article \
    --include-in-header="$HEADER_TEX"

size_kb=$(du -k "$PDF_PATH" | cut -f1)
echo "Generated $(realpath --relative-to="$REPO_ROOT" "$PDF_PATH") (${size_kb} KB)"
