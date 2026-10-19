"""Connections to the device that plays BLE mouse for the phone. All speak one line protocol:

host -> device: "dx dy buttons wheel" (mouse report), "k modifiers k1..k6" (keyboard report: modifier
                bits + up to 6 held key usages, 0 = none), "?" (status query); reports are sent at once
device -> host: "ready" (advertising), "connected" (phone subscribed to reports)
"""
import os
import subprocess
import termios
import threading
import tty
from pathlib import Path
from typing import Callable


class Link:
    def __init__(self, write: Callable[[bytes], object], read: Callable[[], bytes]) -> None:
        self.ready, self.connected = threading.Event(), threading.Event()
        self._write = write

        def reader() -> None:
            buf = b""
            try:
                while chunk := read():
                    *lines, buf = (buf + chunk).split(b"\n")
                    for line in lines:
                        {b"ready": self.ready, b"connected": self.connected}.get(line.strip(), threading.Event()).set()
            except OSError:
                pass  # port closed / device unplugged

        threading.Thread(target=reader, daemon=True).start()

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
    link = Link(lambda b: os.write(fd, b), lambda: os.read(fd, 4096))
    for _ in range(int(wait / 0.5)):  # opening the port may reboot the board: ask until it answers
        os.write(fd, b"?\n")
        if link.ready.wait(0.5):
            return link
    os.close(fd)
    raise RuntimeError(f"no scrcrappy mouse firmware answering on {port}")
