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
echo "built $ROOT/scrcrappy/bin/qvh"
