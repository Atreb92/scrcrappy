import argparse
import shutil
import sys
from pathlib import Path

from . import app, video

BUNDLED_QVH = Path(__file__).resolve().parent.parent / "bin" / "qvh"  # from scripts/build-qvh.sh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scrcrappy", description="Mirror an iPhone screen over USB.")
    parser.add_argument("--qvh", default=str(BUNDLED_QVH) if BUNDLED_QVH.exists() else "qvh",
                        help="path to the patched qvh binary (default: bin/qvh, else PATH)")
    args = parser.parse_args(argv)

    qvh = shutil.which(args.qvh)
    if not qvh:
        print(f"error: qvh not found at '{args.qvh}', build it with scripts/build-qvh.sh", file=sys.stderr)
        return 1
    dev = video.find_iphone()
    if not dev:
        print("error: no iPhone connected over USB", file=sys.stderr)
        return 1
    video.reset_if_stuck(dev)

    frames = video.LatestFrame()
    with video.capture(qvh, frames) as proc:
        closed_by_user = app.run(frames, alive=lambda: proc.poll() is None)
    if not closed_by_user:
        print(f"error: video capture stopped (phone unplugged?), qvh log: {proc.log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
