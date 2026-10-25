import os
import threading

import pytest

from scrcrappy import debuglog, diagnose, links
from scrcrappy.config import Config


def fake_board(master, answer: bytes | None, received: list, boot: bytes = b""):
    if boot:  # a real board prints this after the reset that opening the port causes
        threading.Timer(0.05, os.write, (master, boot)).start()

    def run():
        buf = b""
        while True:
            try:
                buf += os.read(master, 1024)
            except OSError:
                return
            *lines, buf = buf.split(b"\n")
            for line in lines:
                received.append(line)
                if answer and line == b"?":
                    os.write(master, answer)

    threading.Thread(target=run, daemon=True).start()


def run(port, **kw):
    out = []
    rc = diagnose.diagnose_esp32(port, write=out.append, boot_wait=kw.pop("boot_wait", 0.05),
                                 tries=kw.pop("tries", 3), reply_wait=kw.pop("reply_wait", 0.3), **kw)
    return rc, "\n".join(out)


def test_diagnose_answered_sends_only_queries():
    master, slave = os.openpty()
    received = []
    fake_board(master, b"ready\nunpaired\n", received, boot=b"ets Jul 29 2019 boot text\n")
    rc, text = run(os.ttyname(slave), boot_wait=0.4)
    assert rc == 0 and "board answered (firmware ok)" in text and "ready" in text and "boot text" in text
    assert received and set(received) == {b"?"}


def test_diagnose_silent_port():
    master, slave = os.openpty()
    fake_board(master, None, [])
    rc, text = run(os.ttyname(slave))
    assert rc == 1 and "board silent: wrong port, board not flashed with firmware/esp32-mouse" in text
    assert "cu.*" in text


def test_diagnose_missing_port_has_a_reason_and_no_traceback():
    rc, text = run("/nonexistent/ttyUSB9")
    assert rc == 1 and "cannot open: " in text and "Traceback" not in text


def test_diagnose_permission_hint(monkeypatch):
    monkeypatch.setattr(diagnose.links, "open_serial", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")))
    rc, text = run("/dev/ttyUSB0")
    assert rc == 1 and "cannot open: " in text and "permission" in text.lower()


def test_diagnose_without_a_port_lists_and_tries_the_candidates(monkeypatch):
    master, slave = os.openpty()
    fake_board(master, b"ready\n", [])
    monkeypatch.setattr(diagnose, "list_ports", lambda *a, **k: [(os.ttyname(slave), "USB serial")])
    rc, text = run(None)
    assert rc == 0 and os.ttyname(slave) in text and "board answered" in text


def test_diagnose_without_any_port(monkeypatch):
    monkeypatch.setattr(diagnose, "list_ports", lambda *a, **k: [])
    rc, text = run(None)
    assert rc == 1 and "no serial ports found" in text


def test_list_ports_macos_prefers_cu_and_skips_builtin_noise():
    found = ["/dev/cu.usbserial-0001", "/dev/tty.usbserial-0001", "/dev/cu.Bluetooth-Incoming-Port", "/dev/cu.debug-console"]
    ports = dict(diagnose.list_ports("darwin", lambda pattern: [p for p in found if p.startswith(pattern[:-1])]))
    assert set(ports) == {"/dev/cu.usbserial-0001", "/dev/tty.usbserial-0001"}
    assert "use" in ports["/dev/cu.usbserial-0001"].lower() and "cu." in ports["/dev/tty.usbserial-0001"]


def test_list_ports_linux():
    ports = dict(diagnose.list_ports("linux", lambda pattern: ["/dev/ttyUSB0"] if "USB" in pattern else ["/dev/ttyACM0"]))
    assert set(ports) == {"/dev/ttyUSB0", "/dev/ttyACM0"}


def test_diagnose_output_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(diagnose.links, "open_serial", lambda *a, **k: (_ for _ in ()).throw(OSError(f"{tmp_path}/home/secret-dir")))
    rc, text = run("/dev/x")
    assert str(tmp_path / "home") not in text and "~/secret-dir" in text


@pytest.fixture
def logpath(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "scrcrappy.log"
    monkeypatch.setattr(diagnose.debuglog, "log_path", lambda *a, **k: path)
    return path


def test_report_with_the_log_off(logpath):
    text = diagnose.build_report(Config(), ["--report"])
    assert "debug log is off" in text and "--debug" in text and "Review" in text and "python" in text.lower()


def test_report_tail_is_bounded(logpath):
    logpath.parent.mkdir()
    logpath.write_text("".join(f"line {i}\n" for i in range(1000)))
    text = diagnose.build_report(Config(), [])
    assert "line 999" in text and "line 799" not in text and "line 800" in text


def test_report_scrubs_everything_including_old_log_lines(logpath, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    debuglog.add_secret("tok-canary-9")
    logpath.parent.mkdir()
    logpath.write_text(f"old line with tok-canary-9 and {tmp_path}/home/x\n")
    try:
        text = diagnose.build_report(Config(mcp_token="tok-canary-9"), [])
    finally:
        debuglog._secrets.discard("tok-canary-9")
    assert "tok-canary-9" not in text and str(tmp_path / "home") not in text


def test_diagnose_never_shows_the_phone_name_or_a_full_mac_even_in_hex():
    master, slave = os.openpty()
    reply = b"ready\npeer 3F:A2 Alice Smith's iPhone\n"
    fake_board(master, reply, [], boot=b"dbg connect 4c:57:ca:12:3f:a2 bonds=1\n")
    rc, text = run(os.ttyname(slave), boot_wait=0.4)
    assert "Alice" not in text and "Smith" not in text and "4c:57:ca" not in text.lower()
    assert "41 6c 69 63 65" not in text and "34 63 3a 35 37" not in text  # no hex of either
    assert "peer 3F:A2" in text and rc == 0


def test_garbage_is_shown_as_hex_with_readable_bytes_masked():
    shown = diagnose._show(b"\x00\x80x\x80" * 10 + b"4c:57:ca:12:3f:a2")
    assert "mostly not text" in shown and "34 63 3a" not in shown and "4c:57" not in shown


def test_a_failed_write_is_a_verdict_not_a_traceback(monkeypatch):
    master, slave = os.openpty()
    fake_board(master, None, [])
    real_write = os.write
    monkeypatch.setattr(diagnose.os, "write", lambda fd, data: (_ for _ in ()).throw(OSError(5, "Input/output error")))
    rc, text = run(os.ttyname(slave))
    assert rc == 1 and "write failed" in text and "Traceback" not in text
    monkeypatch.setattr(diagnose.os, "write", real_write)
