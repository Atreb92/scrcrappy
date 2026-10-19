#!/bin/sh
# Builds the patched qvh (QuickTime USB screen capture) into bin/qvh.
# Needs: go, libusb, gstreamer dev headers (qvh links them even though we don't use them).
set -eu
COMMIT=d81396e2e7758d98c2a594853b64f98b54a8a871
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=$(mktemp -d)
trap 'rm -rf "$SRC"' EXIT

git clone -q https://github.com/danielpaulus/quicktime_video_hack "$SRC"
git -C "$SRC" checkout -q "$COMMIT"
git -C "$SRC" apply "$ROOT/third_party/qvh.patch"
mkdir -p "$ROOT/bin"
(cd "$SRC" && go build -o "$ROOT/bin/qvh" .)
echo "built $ROOT/bin/qvh"
