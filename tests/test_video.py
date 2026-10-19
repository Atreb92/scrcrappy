import io

import av

from scrcrappy.geometry import fit
from scrcrappy.video import LatestFrame, decode


def h264(frames: int, w: int, h: int) -> bytes:
    buf = io.BytesIO()
    with av.open(buf, "w", format="h264") as out:
        stream = out.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        for _ in range(frames):
            out.mux(stream.encode(av.VideoFrame(w, h, "yuv420p")))
        out.mux(stream.encode())
    return buf.getvalue()


def test_latest_frame_drops_old():
    f = LatestFrame()
    f.put((b"a", (1, 1), 3))
    f.put((b"b", (1, 1), 3))
    assert f.get()[0] == b"b"
    assert f.get() is None


def test_decode_publishes_rgb_frames():
    out = LatestFrame()
    decode(io.BytesIO(h264(5, 64, 48)), out)
    pixels, size, pitch = out.get()
    assert size == (64, 48)
    assert pitch >= 64 * 3 and len(pixels) >= pitch * 47 + 64 * 3


def test_fit_letterboxes_tall_frame():
    assert fit((1125, 2436), (1000, 1000)) == (269, 0, 462, 1000)


def test_fit_pillarboxes_wide_window():
    assert fit((750, 1334), (375, 667)) == (0, 0, 375, 667)
    assert fit((1334, 750), (1000, 1000)) == (0, 219, 1000, 562)


def test_libusb_found_in_homebrew_when_the_system_search_misses():
    # macOS: ctypes.util.find_library doesn't look in /opt/homebrew/lib, so pyusb found no backend
    from scrcrappy import video
    assert video.libusb_path("usb-1.0", find=lambda n: None,
                             exists=lambda p: p == "/opt/homebrew/lib/libusb-1.0.dylib") == "/opt/homebrew/lib/libusb-1.0.dylib"
    assert video.libusb_path("usb-1.0", find=lambda n: "/usr/lib/libusb-1.0.so.0", exists=lambda p: False) == "/usr/lib/libusb-1.0.so.0"
    assert video.libusb_path("usb-1.0", find=lambda n: None, exists=lambda p: False) is None
