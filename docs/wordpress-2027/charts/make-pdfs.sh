#!/usr/bin/env bash
# Render every chart HTML in this folder to a one-page landscape PDF.
# Usage:  ./make-pdfs.sh            (all charts)
#         ./make-pdfs.sh foo.html   (one chart)
set -euo pipefail
cd "$(dirname "$0")"
shopt -s nullglob
files=( "${@:-}" ); [ -z "${files[0]:-}" ] && files=( *.html )
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  out="${f%.html}.pdf"
  tmp="/tmp/$(basename "$f")"
  cp "$f" "$tmp"
  google-chrome --headless --disable-gpu --no-sandbox \
    --print-to-pdf="$out" --no-pdf-header-footer "$tmp" 2>/dev/null
  pages=$(python3 -c "import fitz;print(fitz.open('$out').page_count)")
  echo "  $f -> $out  (${pages}p)"
  if [ "$pages" != "1" ]; then echo "     ^ WARNING: not one page - trim rows or shrink the callout"; fi
done
