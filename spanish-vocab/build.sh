#!/usr/bin/env bash
# Assembles paste-ready output for each note type.
#
# Usage:  ./build.sh        then paste dist/* into Anki

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p dist

for NOTETYPE in reconocimiento produccion; do
  OUT="dist/${NOTETYPE}.styling.css"
  cp shared/styling.css "$OUT"
  echo "wrote $OUT"
done

# Front templates embed the script directly in a <script> tag - Anki always
# runs a literal <script> in a template field, so this doesn't depend on the
# Styling-tab injection trick. Back templates that use {{FrontSide}} inherit
# the front's script that way; produccion/2-produccion's back deliberately
# doesn't use {{FrontSide}} (see its own comment), so it needs its own copy.
embed_script() {
  cat "$1"
  printf '\n<script>\n'
  cat shared/script.js
  printf '</script>\n'
}

embed_script reconocimiento/reconocimiento.front.html > dist/reconocimiento.front.html
cp reconocimiento/reconocimiento.back.html dist/

embed_script produccion/1-reconocimiento.front.html \
  > dist/produccion-1-reconocimiento.front.html
cp produccion/1-reconocimiento.back.html \
  dist/produccion-1-reconocimiento.back.html

embed_script produccion/2-produccion.front.html \
  > dist/produccion-2-produccion.front.html
embed_script produccion/2-produccion.back.html \
  > dist/produccion-2-produccion.back.html

echo
echo "Paste into Anki:"
echo "  Styling tab      <- dist/<notetype>.styling.css  (CSS only)"
echo "  Front/Back tabs  <- the matching .front.html / .back.html"
echo "                      (front templates carry the script inline)"
