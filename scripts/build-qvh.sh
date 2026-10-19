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
(cd "$SRC" && git apply "$ROOT/third_party/qvh.patch")  # not `patch`: may be a different tool on PATH
mkdir -p "$ROOT/scrcrappy/bin"
(cd "$SRC" && go build -o "$ROOT/scrcrappy/bin/qvh" .)
echo "built $ROOT/scrcrappy/bin/qvh"
