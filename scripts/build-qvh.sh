#!/bin/sh
# Builds the patched qvh (QuickTime USB screen capture) into scrcrappy/bin/qvh, shipped inside the package.
# Needs: go, libusb (+ pkg-config). Usage: build-qvh.sh [qvh checkout at COMMIT]  (default: clone it)
set -eu
COMMIT=d81396e2e7758d98c2a594853b64f98b54a8a871
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ $# -ge 1 ]; then
  SRC=$1  # e.g. Homebrew's staged resource
else
  SRC=$(mktemp -d)
  trap 'rm -rf "$SRC"' EXIT
  git clone -q https://github.com/danielpaulus/quicktime_video_hack "$SRC"
  git -C "$SRC" checkout -q "$COMMIT"
fi
SRC=$(cd "$SRC" && pwd)
# git apply, not `patch` (may be a different tool on PATH). The ceiling stops git from treating SRC as part of
# an enclosing repo, where it skips every file silently; the grep catches any other silent no-op.
(cd "$SRC" && GIT_CEILING_DIRECTORIES=$(dirname "$SRC") git apply "$ROOT/third_party/qvh.patch")
grep -q "built without GStreamer" "$SRC/main.go" || { echo "error: qvh.patch did not apply in $SRC" >&2; exit 1; }
mkdir -p "$ROOT/scrcrappy/bin"
(cd "$SRC" && go build -o "$ROOT/scrcrappy/bin/qvh" .)

# Licences of qvh and every Go module compiled into it, shipped next to the binary. Copyleft must not get in:
# scrcrappy is MIT (the patch already drops go-ios, which is AGPL-3.0).
NOTICE="$ROOT/scrcrappy/bin/qvh-LICENSES.txt"
MODCACHE=$(go env GOMODCACHE)
{
  echo "scrcrappy/bin/qvh is built from github.com/danielpaulus/quicktime_video_hack@$COMMIT"
  echo "with scrcrappy's third_party/qvh.patch. Licences of it and of the Go modules compiled into it follow."
  printf '\n==== quicktime_video_hack ====\n\n'
  cat "$SRC/LICENSE"
  go version -m "$ROOT/scrcrappy/bin/qvh" | awk '$1 == "dep" { print $2 "@" $3 }' | while read -r mod; do
    dir="$MODCACHE/$(echo "$mod" | sed 's/[A-Z]/!&/g' | tr 'A-Z' 'a-z')"  # module cache escapes capitals
    printf '\n==== %s ====\n\n' "$mod"
    cat "$dir"/LICENSE* 2>/dev/null || { echo "error: no licence file for $mod" >&2; exit 1; }
  done
} > "$NOTICE"
if grep -qiE "affero|gnu general public" "$NOTICE"; then
  echo "error: copyleft licence among qvh's modules, see $NOTICE" >&2
  exit 1
fi
echo "built $ROOT/scrcrappy/bin/qvh"
