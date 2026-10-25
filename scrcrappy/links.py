"""Connections to the device that plays BLE mouse for the phone. All speak one line protocol:

host -> device: "dx dy buttons wheel" (mouse report), "k modifiers k1..k6" (keyboard report: modifier
                bits + up to 6 held key usages, 0 = none), "?" (status query); reports are sent at once
device -> host: "ready" (advertising), "connected" (phone subscribed to reports)
ESP32 firmware only: "?" answers a snapshot ("ready", "unpaired" | "paired <id>", while connected "connected" and
"peer <id> <name>"), "p" forgets the phone ("pairing"), "disconnected" when the phone goes
"""
import contextlib
import fcntl
import logging
import os
import select
import subprocess
import termios
import threading
import time
import tty
from pathlib import Path
from typing import Callable


log = logging.getLogger("scrcrappy.links")
REPLY_WINDOW = 0.5  # seconds after a quiet "?" in which snapshot lines count as its answer
COUNT_EVERY = 1.0  # seconds between the "sent N reports" log lines
CONTROL = {"ready", "connected", "disconnected", "unpaired", "paired", "peer", "pairing", "dbg", "fw"}  # lines worth logging
SNAPSHOT = {"ready", "fw", "unpaired", "paired", "connected", "peer"}  # the board's answer to "?": logged only when it changes


class Link:
    def __init__(self, write: Callable[[bytes], object], read: Callable[[], bytes],
                 close: Callable[[], object] = lambda: None, on_pairing: Callable[[], None] | None = None) -> None:
        self.ready, self.connected = threading.Event(), threading.Event()
        self._write, self.close, self.on_pairing = write, close, on_pairing
        self.paired: bool | None = None  # ESP32 firmware's last snapshot; None = unknown (old firmware, or not yet answered)
        self.peer: tuple[str, str] | None = None  # (id, name) of the connected phone
        self.last_seen = 0.0  # time.monotonic() of the last line from the device
        self.firmware = ""  # "<normal|debug> <build date>" from the board's `fw` line; "" on older firmware
        self._sent, self._count_at, self._odd = [0, 0], time.monotonic(), 0  # reports sent (mouse, keys), for the log
        self._prev, self._cur, self._same = [], [], False  # the last snapshot and the one arriving, for the log
        self._asked_at = -1.0  # when query() last asked; replies arriving soon after are the quiet kind
        self._write_failing = False  # inside a streak of failed writes (an unplugged board fails every 15 ms)

        def reader() -> None:
            buf = b""
            try:
                while chunk := read():
                    *lines, buf = (buf + chunk).split(b"\n")
                    for line in lines:
                        self._line_in(line.strip().decode(errors="replace"))
            except OSError:
                pass  # port closed / device unplugged

        threading.Thread(target=reader, daemon=True).start()

    def _line_in(self, line: str) -> None:
        self.last_seen = time.monotonic()
        word, _, rest = line.partition(" ")
        if word in CONTROL:  # what the board says about itself; never the phone's name or any input
            quiet = False
            if word in SNAPSHOT and time.monotonic() - self._asked_at < REPLY_WINDOW:
                # the Settings panel asks every second: log an answer to it only when it differs. Lines that
                # arrive on their own (a phone reconnecting, the board restarting) are always logged.
                if word == "ready":
                    self._prev, self._cur, self._same, self._odd = self._cur, [], True, 0  # (a reboot's text is news again)
                i = len(self._cur)
                self._cur.append(line)
                quiet = self._same and self._prev[i:i + 1] == [line]
                self._same = quiet
            if not quiet:
                log.debug("board: %s", f"peer {rest.partition(' ')[0]}" if word == "peer" else line)
        elif self._odd < 20 and line:  # e.g. the ROM's boot text at a wrong baud rate: useful, so shown, but capped
            self._odd += 1
            log.debug("board (unrecognised): %r", line[:80])
        if word == "ready":  # also the first line of every "?" snapshot: the lines after it fill the state again
            self.paired, self.peer = None, None
            self.connected.clear()
            self.ready.set()
        elif word == "connected":
            self.connected.set()
        elif word == "disconnected":
            self.connected.clear()
        elif word in ("paired", "unpaired"):
            self.paired = word == "paired"
        elif word == "fw":
            self.firmware = rest
        elif word == "peer":
            id_, _, name = rest.partition(" ")
            self.peer = (id_, name.strip())
        elif word == "pairing" and self.on_pairing:
            self.on_pairing()

    def query(self) -> None:
        self._asked_at = time.monotonic()
        self._line("?", quiet=True)  # polled every second while Settings is open: not worth a log line

    def forget(self) -> None:
        self._line("p")

    def send(self, dx: int, dy: int, buttons: int, wheel: int) -> None:
        self._line(f"{dx} {dy} {buttons} {wheel}")

    def send_keys(self, modifiers: int, keys: list[int]) -> None:
        self._line(" ".join(map(str, ["k", modifiers, *(keys + [0] * 6)[:6]])))

    def _line(self, line: str, quiet: bool = False) -> None:
        try:
            self._write(f"{line}\n".encode())  # one write per line: lines from two threads never interleave
        except OSError as e:
            if not self._write_failing:  # one line per streak, not one per report
                log.warning("write failed: %s (further failures are not logged until a write works)", e)
                self._write_failing = True
            return  # device gone; the window loop keeps running video-only
        if self._write_failing:
            log.info("writes work again")
            self._write_failing = False
        if line[:1] == "k" or line[:1] == "-" or line[:1].isdigit():  # reports: counted, never recorded
            self._sent[line[:1] == "k"] += 1
            if time.monotonic() - self._count_at >= COUNT_EVERY:
                log.debug("sent %d mouse and %d key reports", *self._sent)
                self._sent, self._count_at = [0, 0], time.monotonic()
        elif not quiet:
            log.debug("sent %r", line)


def ble(python: str) -> Link:
    """This computer's Bluetooth adapter (Linux), via blemouse.py under the system python."""
    log.info("starting the Bluetooth helper with %s", python)
    proc = subprocess.Popen([python, "-I", str(Path(__file__).with_name("blemouse.py"))],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)

    def close() -> None:
        log.info("closing the Bluetooth helper")  # the helper quits on EOF; without this it stays advertised (and connected) after a mode switch
        with contextlib.suppress(OSError):
            proc.stdin.close()
        try:
            proc.wait(2)
        except subprocess.TimeoutExpired:
            proc.kill()

    link = Link(proc.stdin.write, lambda: proc.stdout.read(4096), close)
    if not link.ready.wait(10):  # the helper prints its reason on stderr
        proc.kill()
        log.error("the Bluetooth helper did not report ready within 10 s")
        raise RuntimeError("Bluetooth mouse helper failed to start")
    log.info("the Bluetooth helper is ready")
    return link


def open_serial(port: str, baud: int = 115200) -> int:
    """The serial port as a raw file descriptor at `baud` (what the ESP32 link and `--diagnose-esp32` both open)."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)  # macOS tty.* ports wait for a carrier line otherwise
    try:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)  # then ordinary blocking I/O
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[2] |= termios.CLOCAL  # a USB-serial board has no carrier line
        attrs[4] = attrs[5] = getattr(termios, f"B{baud}")
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (termios.error, AttributeError) as e:  # not an OSError: a port that opens but isn't a serial line
        os.close(fd)
        raise OSError(f"cannot configure {port} as a {baud} baud serial line: {e}") from e
    return fd


def esp32(port: str, baud: int = 115200, wait: float = 10) -> Link:
    """ESP32 running firmware/esp32-mouse, on a USB serial port."""
    log.info("opening %s at %d baud", port, baud)
    try:
        fd = open_serial(port, baud)
    except OSError as e:
        log.error("cannot open %s: %s", port, e)
        raise
    closing, reader_gone = threading.Event(), threading.Event()

    def read() -> bytes:  # poll, so closing the port never waits on a blocked read (macOS hangs there)
        while not closing.is_set():
            if select.select([fd], [], [], 0.2)[0]:
                return os.read(fd, 4096)
        reader_gone.set()
        return b""

    def close() -> None:
        closing.set()
        reader_gone.wait(1)  # the reader must be out of select/read before the fd goes
        os.close(fd)

    link = Link(lambda b: os.write(fd, b), read, close)
    for attempt in range(int(wait / 0.5)):  # opening the port may reboot the board: ask until it answers
        log.debug("handshake attempt %d", attempt + 1)
        link._asked_at = time.monotonic()  # its answer is the first snapshot the quiet polls are compared with
        os.write(fd, b"?\n")
        if link.ready.wait(0.5):
            log.info("the board answered on %s", port)
            return link
    link.close()
    log.error("no firmware answered on %s within %.0f s", port, wait)
    raise RuntimeError(f"no scrcrappy ESP32 firmware answering on {port}")
