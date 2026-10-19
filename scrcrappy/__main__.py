import argparse
import os
import shutil
import socket
import sys
import time
from pathlib import Path

from . import agent, app, calibrate, config, links, mouse, video
from .keyqueue import KeyQueue

PACKAGED_QVH = Path(__file__).resolve().parent / "bin" / "qvh"  # from scripts/build-qvh.sh, shipped in the package
REPO_QVH = Path(__file__).resolve().parent.parent / "bin" / "qvh"  # older checkouts built it here


def find_qvh(flag: str | None, package: Path | None = None, repo: Path | None = None) -> str | None:
    """--qvh, else the package's copy, else the repo's, else PATH."""
    if flag:
        return shutil.which(flag)
    for path in (package or PACKAGED_QVH, repo or REPO_QVH):
        if path.is_file():
            if not os.access(path, os.X_OK):  # an installer may drop the exec bit
                path.chmod(path.stat().st_mode | 0o100)
            return str(path)
    return shutil.which("qvh")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrcrappy", description="Mirror and control an iPhone over USB.")
    parser.add_argument("--qvh", help="path to the patched qvh binary (default: the one built into scrcrappy, "
                                      "else PATH)")
    parser.add_argument("--mouse", choices=config.MICE, default=None,
                        help="input: drive the AssistiveTouch cursor through a BLE mouse (ble = this computer's "
                             "Bluetooth (Linux), esp32 = ESP32 with firmware/esp32-mouse on --port), or "
                             "agent = scrcrappy-agent on a jailbroken phone (touches, keys, clipboard); "
                             "default: the toolbar's Settings")
    parser.add_argument("--port", help="ESP32 serial port (default: the toolbar's Settings, /dev/ttyUSB0)")
    parser.add_argument("--ble-python", default="/usr/bin/python3",
                        help="python with python3-dbus and python3-gobject, runs the Bluetooth helper")
    parser.add_argument("--natural-scroll", action=argparse.BooleanOptionalAction, default=None,
                        help="invert the wheel: content follows the wheel like a finger (as on a touchpad); "
                             "default: last setting from the toolbar")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure the pointer gain (needs --mouse; open a plain light screen first)")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "linux" and os.environ.get("DISPLAY"):
        # X11 (XWayland on Wayland desktops): the toolbar window must be placed next to the phone
        # window, which native Wayland doesn't allow. SDL3-based pygame would otherwise pick Wayland.
        os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    args = build_parser().parse_args(argv)
    cfg = config.load()  # flags win over saved settings for this run, without changing them
    args.mouse, args.port = args.mouse or cfg.mouse, args.port or cfg.port

    qvh = find_qvh(args.qvh)
    if not qvh:
        print(f"error: qvh not found{f' at {args.qvh!r}' if args.qvh else ''}, build it with scripts/build-qvh.sh",
              file=sys.stderr)
        return 1
    if args.calibrate and args.mouse not in ("ble", "esp32"):
        print("error: --calibrate needs --mouse ble or esp32", file=sys.stderr)
        return 1
    dev = video.find_iphone()
    if not dev:
        print("error: no iPhone connected over USB", file=sys.stderr)
        return 1
    serial = dev.serial_number
    video.reset_if_stuck(dev)

    make_pointer, keys, session = None, None, None
    if args.mouse == "agent":
        try:
            host = socket.gethostname()
            session = agent.Session(agent.connect(host).sock, reopen=lambda: agent.connect(host, wait=1).sock)
        except (OSError, agent.AgentError) as e:
            print(f"error: agent: {e}", file=sys.stderr)
            return 1
    elif args.mouse != "none":
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
        if args.natural_scroll is not None:
            cfg.natural_scroll = args.natural_scroll
        closed_by_user = app.run(frames, alive=lambda: proc.poll() is None, make_pointer=make_pointer, keys=keys,
                                 cfg=cfg, device_key=f"{serial}/{args.mouse}", agent=session,
                                 device_name="scrcrappy ESP32" if args.mouse == "esp32" else "scrcrappy PC")
    if not closed_by_user:
        print(f"error: video capture stopped (phone unplugged?), qvh log: {proc.log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
