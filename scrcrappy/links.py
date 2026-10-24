"""Connections to the device that plays BLE mouse for the phone. All speak one line protocol:

host -> device: "dx dy buttons wheel" (mouse report), "k modifiers k1..k6" (keyboard report: modifier
                bits + up to 6 held key usages, 0 = none), "?" (status query); reports are sent at once
device -> host: "ready" (advertising), "connected" (phone subscribed to reports)
ESP32 firmware only: "?" answers a snapshot ("ready", "unpaired" | "paired <id>", while connected "connected" and
"peer <id> <name>"), "p" forgets the phone ("pairing"), "disconnected" when the phone goes
"""
import os
import select
import subprocess
import termios
import threading
import time
import tty
from pathlib import Path
from typing import Callable


class Link:
    def __init__(self, write: Callable[[bytes], object], read: Callable[[], bytes],
                 close: Callable[[], object] = lambda: None, on_pairing: Callable[[], None] | None = None) -> None:
        self.ready, self.connected = threading.Event(), threading.Event()
        self._write, self.close, self.on_pairing = write, close, on_pairing
        self.paired: bool | None = None  # ESP32 firmware's last snapshot; None = unknown (old firmware, or not yet answered)
        self.peer: tuple[str, str] | None = None  # (id, name) of the connected phone
        self.last_seen = 0.0  # time.monotonic() of the last line from the device

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
        elif word == "peer":
            id_, _, name = rest.partition(" ")
            self.peer = (id_, name.strip())
        elif word == "pairing" and self.on_pairing:
            self.on_pairing()

    def query(self) -> None:
        self._line("?")

    def forget(self) -> None:
        self._line("p")

    def send(self, dx: int, dy: int, buttons: int, wheel: int) -> None:
        self._line(f"{dx} {dy} {buttons} {wheel}")

    def send_keys(self, modifiers: int, keys: list[int]) -> None:
        self._line(" ".join(map(str, ["k", modifiers, *(keys + [0] * 6)[:6]])))

    def _line(self, line: str) -> None:
        try:
            self._write(f"{line}\n".encode())  # one write per line: lines from two threads never interleave
        except OSError:
            pass  # device gone; the window loop keeps running video-only


def ble(python: str) -> Link:
    """This computer's Bluetooth adapter (Linux), via blemouse.py under the system python."""
    proc = subprocess.Popen([python, "-I", str(Path(__file__).with_name("blemouse.py"))],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
    link = Link(proc.stdin.write, lambda: proc.stdout.read(4096))
    if not link.ready.wait(10):  # the helper prints its reason on stderr
        proc.kill()
        raise RuntimeError("Bluetooth mouse helper failed to start")
    return link


def esp32(port: str, baud: int = 115200, wait: float = 10) -> Link:
    """ESP32 running firmware/esp32-mouse, on a USB serial port."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    attrs[4] = attrs[5] = getattr(termios, f"B{baud}")
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
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
    for _ in range(int(wait / 0.5)):  # opening the port may reboot the board: ask until it answers
        os.write(fd, b"?\n")
        if link.ready.wait(0.5):
            return link
    link.close()
    raise RuntimeError(f"no scrcrappy ESP32 firmware answering on {port}")
