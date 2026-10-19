#!/bin/sh
# Regenerates scrcrappy/icons/*.ttf: the few Material Symbols Rounded glyphs the toolbar uses,
# as two static fonts (outline and filled). Dev-only; needs: curl, python3 with fonttools.
set -eu
COMMIT=49d4db35df873165d6bd6ba09b063c7dafbac2f4
NAMES="content_paste content_copy swap_vert chevron_left chevron_right add power_settings_new home view_carousel lock tune notifications screenshot_monitor mic volume_up volume_down volume_off screen_rotation search photo_camera vibration accessibility_new star"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/scrcrappy/icons"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

BASE="https://raw.githubusercontent.com/google/material-design-icons/$COMMIT/variablefont"
curl -sfL "$BASE/MaterialSymbolsRounded%5BFILL,GRAD,opsz,wght%5D.ttf" -o "$TMP/var.ttf"
curl -sfL "$BASE/MaterialSymbolsRounded%5BFILL,GRAD,opsz,wght%5D.codepoints" -o "$TMP/codepoints"
curl -sfL "https://raw.githubusercontent.com/google/material-design-icons/$COMMIT/LICENSE" -o "$OUT/LICENSE"

UNICODES=$(for n in $NAMES; do awk -v n="$n" '$1 == n { printf "U+%s,", $2 }' "$TMP/codepoints"; done)
echo "glyphs: $NAMES -> $UNICODES"
mkdir -p "$OUT"
for fill in 0 1; do
  python3 -m fontTools.varLib.instancer "$TMP/var.ttf" FILL=$fill GRAD=0 opsz=24 wght=400 -o "$TMP/static$fill.ttf" -q
  name=$([ $fill = 0 ] && echo outline || echo filled)
  python3 -m fontTools.subset "$TMP/static$fill.ttf" --unicodes="$UNICODES" --no-layout-closure \
    --output-file="$OUT/MaterialSymbolsRounded-$name.ttf"
done
ls -l "$OUT"
