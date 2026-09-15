#!/usr/bin/env bash
# Assembles the paste-ready Styling block for each note type.
#
# Anki's Styling tab holds CSS, but a <script> tag pasted after it is injected
# into both sides of every card — which is how one copy of the script serves
# all four card templates. This just glues the two shared files together so
# there is exactly one place to edit each.
#
# Usage:  ./build.sh        then paste dist/*.styling.css into Anki

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p dist

for NOTETYPE in reconocimiento produccion; do
  OUT="dist/${NOTETYPE}.styling.css"
  {
    cat shared/styling.css
    printf '\n<script>\n'
    cat shared/script.js
    printf '</script>\n'
  } > "$OUT"
  echo "wrote $OUT"
done

# Templates are copied through unchanged, just gathered for convenience.
cp reconocimiento/*.html dist/
for f in produccion/*.html; do
  cp "$f" "dist/produccion-$(basename "$f")"
done

echo
echo "Paste into Anki:"
echo "  Styling tab      <- dist/<notetype>.styling.css  (CSS *and* the script block)"
echo "  Front/Back tabs  <- the matching .front.html / .back.html"
