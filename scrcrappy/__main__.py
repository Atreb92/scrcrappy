import argparse
import atexit
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # before pygame loads: `scrcrappy agent` stdout is JSON only

import shutil
import sys
import time
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path

from . import app, calibrate, config, debuglog, diagnose, modes, video

PACKAGED_QVH = Path(__file__).resolve().parent / "bin" / "qvh"  # from scripts/build-qvh.sh, shipped in the package


def find_qvh(flag: str | None, package: Path | None = None) -> str | None:
    """--qvh, else the package's copy (scripts/build-qvh.sh), else PATH."""
    if flag:
        return shutil.which(flag)
    path = package or PACKAGED_QVH
    if path.is_file():
        if not os.access(path, os.X_OK):  # an installer may drop the exec bit
            path.chmod(path.stat().st_mode | 0o100)
        return str(path)
    return shutil.which("qvh")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrcrappy", description="Mirror and control an iPhone over USB.")
    parser.add_argument("--version", action="version", version=f"scrcrappy {version('scrcrappy')}")
    parser.add_argument("--qvh", help="path to the patched qvh binary (default: the one built into scrcrappy, "
                                      "else PATH)")
    parser.add_argument("--mouse", choices=config.MICE, default=None,
                        help="input: drive the AssistiveTouch cursor through a BLE mouse (ble = this computer's "
                             "Bluetooth (Linux), esp32 = ESP32 with firmware/esp32-mouse on --port), or "
                             "agent = crappytouch on a jailbroken phone (touches, keys, clipboard); "
                             "default: the toolbar's Settings")
    parser.add_argument("--port", help="ESP32 serial port (default: the toolbar's Settings, /dev/ttyUSB0)")
    parser.add_argument("--ble-python", default="/usr/bin/python3",
                        help="python with python3-dbus and python3-gobject, runs the Bluetooth helper")
    parser.add_argument("--natural-scroll", action=argparse.BooleanOptionalAction, default=None,
                        help="invert the wheel: content follows the wheel like a finger (as on a touchpad); "
                             "default: last setting from the toolbar")
    parser.add_argument("--mcp", action="store_true",
                        help="allow AI control (MCP server on 127.0.0.1:7331) for this run; see Settings")
    parser.add_argument("--x11", action="store_true",
                        help="use X11 (XWayland on a Wayland desktop) instead of native Wayland, which is the default there")
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, default=None,
                        help="write the debug log for this run (see Settings › Debug log; default: that setting)")
    parser.add_argument("--diagnose-esp32", action="store_true",
                        help="check the serial side of an ESP32 (--port, else every candidate) and exit; needs no phone")
    parser.add_argument("--report", action="store_true",
                        help="print a scrubbed report to paste into a bug report and exit")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure the pointer gain (needs --mouse; open a plain light screen first)")
    return parser


def pick_video_driver(env: Mapping[str, str], platform: str, x11: bool = False) -> str | None:
    """SDL's video driver list for this session, or None to leave it to SDL: on Linux native Wayland when there is
    a Wayland session (X11 if that fails to start), X11 when asked for or when there is no Wayland. A
    SDL_VIDEODRIVER set by the user always wins."""
    if platform != "linux" or env.get("SDL_VIDEODRIVER"):
        return None
    if x11:
        return "x11"  # asked for: if there is no X server SDL says so, instead of quietly using Wayland
    if env.get("WAYLAND_DISPLAY"):
        return "wayland,x11"
    return "x11" if env.get("DISPLAY") else None


def apply_debug(cfg: config.Config, want: bool, argv: list[str]) -> bool:
    """Turn the debug log on or off (the startup flag and the Settings switch both come through here); returns
    whether it is on now."""
    if want:
        if path := debuglog.enable(cfg, argv):
            print(f"debug log: {path}", file=sys.stderr)
    else:
        debuglog.disable()
    return debuglog.is_enabled()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["agent"]:
        from . import agent_cli
        return agent_cli.main(argv[1:])
    args = build_parser().parse_args(argv)
    if driver := pick_video_driver(os.environ, sys.platform, args.x11):
        os.environ["SDL_VIDEODRIVER"] = driver
    for hint in ("SDL_VIDEO_WAYLAND_WMCLASS", "SDL_VIDEO_X11_WMCLASS"):
        os.environ.setdefault(hint, "scrcrappy")  # the app id / WM class a scrcrappy.desktop entry matches
    cfg = config.load()  # flags win over saved settings for this run, without changing them
    debuglog.add_secret(cfg.mcp_token)
    apply_debug(cfg, cfg.debug_log if args.debug is None else args.debug, argv)
    if args.report:  # neither of these needs a phone, qvh or a window
        print(diagnose.build_report(cfg, argv))
        return 0
    if args.diagnose_esp32:
        return diagnose.diagnose_esp32(args.port)
    args.mouse, args.port = args.mouse or cfg.mouse, args.port or cfg.port

    mac = sys.platform == "darwin"  # macOS captures through AVFoundation, no qvh
    qvh = None if mac else find_qvh(args.qvh)
    if not mac and not qvh:
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
    serial = video.serial_number(dev)
    if not mac:
        video.reset_if_stuck(dev, qvh)

    frames = video.LatestFrame()
    try:
        mode = modes.start_mode(args.mouse, args.port, serial, frames, args.ble_python)
    except modes.ModeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    atexit.register(mode.close)
    if mode.error:
        print(f"note: ESP32 not available ({mode.error}); the window opens so you can fix the port in Settings",
              file=sys.stderr)
    connected = mode.link.connected if mode.link else None
    if connected and not connected.wait(1):  # the window opens anyway: with the ESP32, pairing is done from its Settings
        print("note: the iPhone is not connected over Bluetooth yet to 'scrcrappy PC' / 'scrcrappy ESP32' "
              "(AssistiveTouch on; pair it in Settings > Accessibility > Touch > AssistiveTouch > Devices)",
              file=sys.stderr)

    with (video.capture_avf(frames, serial) if mac else video.capture(qvh, frames)) as proc:
        if args.calibrate:
            if not mode.link:
                print(f"error: --calibrate needs the board: {mode.error}", file=sys.stderr)
                return 1
            if not connected.is_set():  # the window no longer waits for the phone, but measuring needs it
                print("waiting for the iPhone to connect over Bluetooth...", file=sys.stderr)
                connected.wait()
            time.sleep(3)  # stream start-up
            try:
                table = calibrate.calibrate(mode.link.send, frames)
            except RuntimeError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"saved {calibrate.save(serial, table)}")
            return 0
        if args.natural_scroll is not None:
            cfg.natural_scroll = args.natural_scroll
        closed_by_user = app.run(frames, alive=lambda: proc.poll() is None, mode=mode, cfg=cfg,
                                 device_key=f"{serial}/{args.mouse}", mcp=args.mcp, port=args.port, mode_name=args.mouse,
                                 start_mode=lambda name, port: modes.start_mode(name, port, serial, frames, args.ble_python),
                                 set_debug=lambda want: apply_debug(cfg, want, argv),
                                 report=lambda: diagnose.build_report(cfg, argv))
    if not closed_by_user:
        print(f"error: video capture stopped (phone unplugged?), {'log' if mac else 'qvh log'}:\n{proc.log}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
