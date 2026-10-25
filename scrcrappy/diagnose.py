"""`--diagnose-esp32` and `--report`: what is on the serial line, and a scrubbed block to paste into a bug report."""
import errno
import glob
import logging
import os
import select
import sys
import time
from typing import Callable

from . import debuglog, links
from .config import Config

log = logging.getLogger("scrcrappy.diagnose")
HINTS = {errno.EACCES: "permission denied (Linux: add your user to the dialout / uucp group and log in again; "
                       "macOS: another program may own the port)",
         errno.ENOENT: "no such device (is the board plugged in? on macOS use the cu.* name)",
         errno.EBUSY: "busy: another program (scrcrappy, a serial monitor) has the port open"}
NOISE = ("Bluetooth-Incoming-Port", "debug-console")  # macOS built-ins, not boards


def list_ports(platform: str | None = None, globber: Callable[[str], list[str]] = glob.glob) -> list[tuple[str, str]]:
    """Serial port candidates with a one-line hint."""
    if (platform or sys.platform) == "darwin":
        cu = [(p, "use this one: cu.* opens at once") for p in sorted(globber("/dev/cu.*")) if not any(n in p for n in NOISE)]
        tty = [(p, "prefer the cu.* name: tty.* can block on open") for p in sorted(globber("/dev/tty.*"))
               if not any(n in p for n in NOISE)]
        return cu + tty
    return [(p, "USB serial") for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*") for p in sorted(globber(pattern))]


def _read(fd: int, seconds: float, until: bytes = b"") -> bytes:
    """Whatever arrives in `seconds` (sooner once `until` has been seen)."""
    data, end = b"", time.monotonic() + seconds
    while time.monotonic() < end and not (until and until in data):
        if select.select([fd], [], [], 0.05)[0]:
            try:
                data += os.read(fd, 4096)
            except OSError:
                break
    return data


def _show(data: bytes) -> str:
    return f"{len(data)} bytes: {data[:200].hex(' ')} | {data[:200].decode(errors='replace')!r}"


def diagnose_esp32(port: str | None, write: Callable[[str], None] = print, boot_wait: float = 3.0, tries: int = 5,
                   reply_wait: float = 1.0) -> int:
    """Open the port the way the app does and show what the board does; returns 0 if it answered, else 1.
    Sends nothing but `?`."""
    def say(text: str) -> None:
        line = debuglog.scrub(text)
        log.info("diagnose: %s", line)
        write(line)

    if port:
        ports = [port]
    else:
        found = list_ports()
        if not found:
            say("no serial ports found: is the board plugged in (with a data cable)?")
            return 1
        say("serial port candidates:")
        for path, hint in found:
            say(f"  {path}  ({hint})")
        ports = [path for path, _ in found]
    answered = False
    for path in ports:
        t0 = time.monotonic()
        say(f"== {path}")
        try:
            fd = links.open_serial(path)
        except OSError as e:
            say(f"cannot open: {HINTS.get(e.errno, '')} {e}".replace("  ", " "))
            continue
        try:
            say(f"[{time.monotonic() - t0:.2f}s] opened, raw mode, 115200 baud; listening {boot_wait:g} s (opening may reboot the board)")
            boot = _read(fd, boot_wait)
            say(f"[{time.monotonic() - t0:.2f}s] boot output: {_show(boot) if boot else 'nothing'}")
            reply = b""
            for attempt in range(tries):
                os.write(fd, b"?\n")
                reply = _read(fd, reply_wait, until=b"ready")
                say(f"[{time.monotonic() - t0:.2f}s] sent '?' (try {attempt + 1}): {_show(reply) if reply else 'no reply'}")
                if b"ready" in reply:
                    break
        finally:
            os.close(fd)
        if b"ready" in reply:
            say(f"{path}: board answered (firmware ok)")
            answered = True
        elif boot:
            say(f"{path}: board silent: it printed text but did not answer '?': a different firmware or baud rate? "
                "(wrong port, board not flashed with firmware/esp32-mouse, or the port blocks on open: try the cu.* name)")
        else:
            say(f"{path}: board silent: wrong port, board not flashed with firmware/esp32-mouse, or the port blocks "
                "on open (try the cu.* name)")
    return 0 if answered else 1


def build_report(cfg: Config, args: list[str], log_lines: int = 200) -> str:
    """A markdown block for a bug report; everything in it has been scrubbed."""
    out = ["# scrcrappy debug report", "",
           "_Review before posting: it is scrubbed of tokens, home folders, account names and serial numbers, "
           "but you know your machine best._", "", "## Facts", *(f"- {line}" for line in debuglog.startup_facts(cfg, args)),
           "", "## Serial ports"]
    ports = list_ports()
    out += [f"- {path} ({hint})" for path, hint in ports] or ["- none found"]
    out += ["", "## Log"]
    path = debuglog.log_path()
    try:
        lines = path.read_text(errors="replace").splitlines()[-log_lines:]
        out += ["```", *lines, "```"]
    except OSError:
        out.append("The debug log is off (or empty). Turn it on with `--debug` or Settings › Debug log, reproduce the "
                   "problem, and run `scrcrappy --report` again.")
    return debuglog.scrub("\n".join(out))
