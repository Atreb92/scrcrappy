import argparse
import shutil
import sys
import time
from pathlib import Path

from . import app, calibrate, mouse, video

BUNDLED_QVH = Path(__file__).resolve().parent.parent / "bin" / "qvh"  # from scripts/build-qvh.sh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scrcrappy", description="Mirror and control an iPhone over USB.")
    parser.add_argument("--qvh", default=str(BUNDLED_QVH) if BUNDLED_QVH.exists() else "qvh",
                        help="path to the patched qvh binary (default: bin/qvh, else PATH)")
    parser.add_argument("--mouse", choices=["none", "ble"], default="none",
                        help="ble: this computer's Bluetooth acts as a mouse for AssistiveTouch (Linux)")
    parser.add_argument("--ble-python", default="/usr/bin/python3",
                        help="python with python3-dbus and python3-gobject, runs the Bluetooth helper")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure the pointer gain (needs --mouse; open a plain light screen first)")
    args = parser.parse_args(argv)

    qvh = shutil.which(args.qvh)
    if not qvh:
        print(f"error: qvh not found at '{args.qvh}', build it with scripts/build-qvh.sh", file=sys.stderr)
        return 1
    if args.calibrate and args.mouse == "none":
        print("error: --calibrate needs --mouse ble", file=sys.stderr)
        return 1
    dev = video.find_iphone()
    if not dev:
        print("error: no iPhone connected over USB", file=sys.stderr)
        return 1
    serial = dev.serial_number
    video.reset_if_stuck(dev)

    make_pointer = None
    if args.mouse == "ble":
        try:
            send, connected, _helper = mouse.start_ble(args.ble_python)
        except (OSError, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not connected.wait(5):
            print("waiting for the iPhone to connect to 'scrcrappy mouse' "
                  "(AssistiveTouch on; pair it in Settings > Bluetooth the first time)...", file=sys.stderr)
            connected.wait()
        gain = mouse.Gain(calibrate.load(serial))
        make_pointer = lambda size: mouse.Pointer(send, gain, size)  # noqa: E731

    frames = video.LatestFrame()
    with video.capture(qvh, frames) as proc:
        if args.calibrate:
            time.sleep(3)  # stream start-up
            try:
                table = calibrate.calibrate(send, frames)
            except RuntimeError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"saved {calibrate.save(serial, table)}")
            return 0
        closed_by_user = app.run(frames, alive=lambda: proc.poll() is None, make_pointer=make_pointer)
    if not closed_by_user:
        print(f"error: video capture stopped (phone unplugged?), qvh log: {proc.log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
