import os
import threading

import pytest

from scrcrappy import links


def fake_board(master: int, received: list[bytes], boot_lines: int = 0) -> None:
    """Pretends to be the firmware on the other end of a pty: ignores the first `boot_lines`
    queries (board rebooting after port open), then answers like the real thing."""
    buf = b""
    while True:
        try:
            buf += os.read(master, 1024)
        except OSError:
            return
        *lines, buf = buf.split(b"\n")
        for line in lines:
            received.append(line)
            if line == b"?":
                if boot_lines:
                    boot_lines -= 1
                else:
                    os.write(master, b"ready\nconnected\n")


def test_esp32_handshake_and_reports():
    master, slave = os.openpty()
    received = []
    threading.Thread(target=fake_board, args=(master, received, 2), daemon=True).start()
    link = links.esp32(os.ttyname(slave))
    assert link.connected.wait(2)
    link.send(-5, 12, 1, 0)
    for _ in range(100):
        if received[-1:] == [b"-5 12 1 0"]:
            break
        threading.Event().wait(0.01)
    assert received[-1] == b"-5 12 1 0"
    assert received.count(b"?") == 3  # retried through the "reboot"


def test_esp32_silent_port_is_an_error():
    master, slave = os.openpty()
    with pytest.raises(RuntimeError, match="no scrcrappy ESP32 firmware"):
        links.esp32(os.ttyname(slave), wait=1)


def test_link_handles_lines_split_across_reads():
    chunks = iter([b"rea", b"dy\ncon", b"nected\n", b""])
    link = links.Link(lambda b: None, lambda: next(chunks))
    assert link.ready.wait(1) and link.connected.wait(1)


def test_send_keys_pads_to_six_slots():
    out = []
    link = links.Link(out.append, lambda: b"")
    link.send_keys(0x02, [0x04, 0x05])
    assert out == [b"k 2 4 5 0 0 0 0\n"]
