"""Phone screen capture: qvh (QuickTime USB protocol) -> named pipe -> PyAV decode."""
import contextlib
import ctypes.util
import os
import signal
import subprocess
import tempfile
import threading
import time
from typing import BinaryIO, Iterator

import av
import usb.backend.libusb1
import usb.core

APPLE = 0x05AC
Frame = tuple[bytes, tuple[int, int], int]  # RGB pixels, (width, height), bytes per row


class LatestFrame:
    """Hands the newest decoded frame to the UI; older undrawn frames are dropped."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Frame | None = None

    def put(self, frame: Frame) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> Frame | None:
        """Newest frame, or None if nothing new since the last call."""
        with self._lock:
            frame, self._frame = self._frame, None
            return frame


HOMEBREW_LIBS = ("/opt/homebrew/lib", "/usr/local/lib")  # Apple Silicon, Intel


def libusb_path(name: str, find=ctypes.util.find_library, exists=os.path.exists) -> str | None:
    """pyusb's libusb lookup, plus Homebrew's folders, which ctypes doesn't search on macOS."""
    return find(name) or next((p for d in HOMEBREW_LIBS if exists(p := f"{d}/lib{name}.dylib")), None)


def find_iphone() -> usb.core.Device | None:
    return usb.core.find(idVendor=APPLE, backend=usb.backend.libusb1.get_backend(find_library=libusb_path))


def reset_if_stuck(dev: usb.core.Device) -> None:
    """qvh can't switch the phone back out of the QuickTime config on Linux (usbmuxd holds it),
    and the next session then never gets the device's PING. A USB reset re-enumerates it."""
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError:
        return
    if any(i.bInterfaceClass == 0xFF and i.bInterfaceSubClass == 0x2A for i in cfg):
        with contextlib.suppress(usb.core.USBError):  # device vanishes mid-call while resetting
            dev.reset()
        time.sleep(3)


def decode(stream: BinaryIO, out: LatestFrame) -> None:
    """Decode an Annex-B H.264 byte stream until EOF, publishing each frame to `out`."""
    codec = av.CodecContext.create("h264", "r")
    codec.flags |= av.codec.context.Flags.low_delay
    while chunk := stream.read(65536):
        for packet in codec.parse(chunk):
            for frame in codec.decode(packet):
                plane = frame.reformat(format="rgb24").planes[0]
                out.put((bytes(plane), (frame.width, frame.height), plane.line_size))


@contextlib.contextmanager
def capture(qvh: str, out: LatestFrame) -> Iterator[subprocess.Popen]:
    """Run `qvh record` into a named pipe and decode it in a background thread."""
    tmp = tempfile.mkdtemp(prefix="scrcrappy-")
    fifo, log_path = os.path.join(tmp, "video.h264"), os.path.join(tmp, "qvh.log")
    os.mkfifo(fifo)
    with open(log_path, "wb") as log:
        proc = subprocess.Popen([qvh, "record", fifo, os.devnull], stdout=log, stderr=log)
    proc.log_path = log_path

    def reader() -> None:
        with open(fifo, "rb", buffering=0) as f:
            decode(f, out)

    threading.Thread(target=reader, daemon=True).start()
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)  # qvh then tells the phone to stop streaming
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
