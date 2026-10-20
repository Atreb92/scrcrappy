#!/bin/sh
# Regenerates scrcrappy/fonts/*: Roboto (SIL OFL 1.1) as two static, Latin-only subsets (Regular, SemiBold) plus its
# licence. Dev-only (the result is committed and ships in the wheel); needs: curl, python3 with fonttools.
set -eu
COMMIT=1c627bfa375fc51cf86fabeca4f6e08a95f0aa5c  # google/fonts
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/scrcrappy/fonts"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

BASE="https://raw.githubusercontent.com/google/fonts/$COMMIT/ofl/roboto"
mkdir -p "$OUT"
rm -f "$OUT"/*.ttf
curl -sfL "$BASE/Roboto%5Bwdth%2Cwght%5D.ttf" -o "$TMP/var.ttf"
curl -sfL "$BASE/OFL.txt" -o "$OUT/OFL.txt"

# Basic Latin, Latin-1 + Extended-A, general punctuation (dashes, quotes, bullet, ellipsis, ‹ ›), arrows
UNICODES="U+0020-007E,U+00A0-017F,U+2010-2027,U+2039-203A,U+2190-2193"
for spec in Regular:400 SemiBold:600; do
  name=${spec%:*}
  python3 -m fontTools.varLib.instancer "$TMP/var.ttf" wdth=100 wght=${spec#*:} -o "$TMP/$name.ttf" -q
  python3 -m fontTools.subset "$TMP/$name.ttf" --unicodes="$UNICODES" --layout-features='kern,liga,calt' \
    --output-file="$OUT/Roboto-$name.ttf"
done
ls -l "$OUT"
