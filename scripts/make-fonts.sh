#!/bin/sh
# Regenerates scrcrappy/fonts/*: Inter (SIL OFL 1.1) as two static, Latin-only subsets (Regular, SemiBold) plus its
# licence. Dev-only; needs: curl, python3 with fonttools (same as make-icons.sh).
set -eu
COMMIT=0b58fb370093f9a9f4ff785d94405710b79de67c  # google/fonts
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/scrcrappy/fonts"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

BASE="https://raw.githubusercontent.com/google/fonts/$COMMIT/ofl/inter"
mkdir -p "$OUT"
curl -sfL "$BASE/Inter%5Bopsz%2Cwght%5D.ttf" -o "$TMP/var.ttf"
curl -sfL "$BASE/OFL.txt" -o "$OUT/OFL.txt"

# Basic Latin, Latin-1 + Extended-A, general punctuation (dashes, quotes, bullet, ellipsis, ‹ ›), arrows
UNICODES="U+0020-007E,U+00A0-017F,U+2010-2027,U+2039-203A,U+2190-2193"
for spec in Regular:400 SemiBold:600; do
  name=${spec%:*}
  python3 -m fontTools.varLib.instancer "$TMP/var.ttf" opsz=14 wght=${spec#*:} -o "$TMP/$name.ttf" -q
  python3 -m fontTools.subset "$TMP/$name.ttf" --unicodes="$UNICODES" --layout-features='kern,liga,calt' \
    --output-file="$OUT/Inter-$name.ttf"
done
ls -l "$OUT"
