import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from . import app, calibrate, links, mouse, video
from .keyqueue import KeyQueue

BUNDLED_QVH = Path(__file__).resolve().parent.parent / "bin" / "qvh"  # from scripts/build-qvh.sh


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "linux" and os.environ.get("DISPLAY"):
        # X11 (XWayland on Wayland desktops): the toolbar window must be placed next to the phone
        # window, which native Wayland doesn't allow. SDL3-based pygame would otherwise pick Wayland.
        os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    parser = argparse.ArgumentParser(prog="scrcrappy", description="Mirror and control an iPhone over USB.")
    parser.add_argument("--qvh", default=str(BUNDLED_QVH) if BUNDLED_QVH.exists() else "qvh",
                        help="path to the patched qvh binary (default: bin/qvh, else PATH)")
    parser.add_argument("--mouse", choices=["none", "ble", "esp32"], default="none",
                        help="drive the AssistiveTouch cursor through a BLE mouse: ble = this computer's "
                             "Bluetooth (Linux), esp32 = ESP32 with firmware/esp32-mouse on --port")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="ESP32 serial port (default: /dev/ttyUSB0)")
    parser.add_argument("--ble-python", default="/usr/bin/python3",
                        help="python with python3-dbus and python3-gobject, runs the Bluetooth helper")
    parser.add_argument("--natural-scroll", action="store_true",
                        help="invert the wheel: content follows the wheel like a finger (as on a touchpad)")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure the pointer gain (needs --mouse; open a plain light screen first)")
    args = parser.parse_args(argv)

    qvh = shutil.which(args.qvh)
    if not qvh:
        print(f"error: qvh not found at '{args.qvh}', build it with scripts/build-qvh.sh", file=sys.stderr)
        return 1
    if args.calibrate and args.mouse == "none":
        print("error: --calibrate needs --mouse ble or esp32", file=sys.stderr)
        return 1
    dev = video.find_iphone()
    if not dev:
        print("error: no iPhone connected over USB", file=sys.stderr)
        return 1
    serial = dev.serial_number
    video.reset_if_stuck(dev)

    make_pointer, keys = None, None
    if args.mouse != "none":
        try:
            link = links.ble(args.ble_python) if args.mouse == "ble" else links.esp32(args.port)
        except (OSError, RuntimeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        send, connected, keys = link.send, link.connected, KeyQueue(link.send_keys)
        keys.start()
        if not connected.wait(5):
            print("waiting for the iPhone to connect to 'scrcrappy PC' / 'scrcrappy ESP32' "
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
        closed_by_user = app.run(frames, alive=lambda: proc.poll() is None, make_pointer=make_pointer,
                                 natural_scroll=args.natural_scroll, keys=keys)
    if not closed_by_user:
        print(f"error: video capture stopped (phone unplugged?), qvh log: {proc.log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
