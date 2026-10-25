import logging
import os
import socket
import stat
import threading
import time

import pytest

from scrcrappy import agent, debuglog, links, modes, video
from scrcrappy.config import Config
from scrcrappy.video import LatestFrame


@pytest.fixture
def logfile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(debuglog.getpass, "getuser", lambda: "alice")
    debuglog.disable()
    path = debuglog.enable(Config(), [], tmp_path / "logs" / "scrcrappy.log")

    def text():
        for h in logging.getLogger("scrcrappy").handlers:
            h.flush()
        return path.read_text()

    yield text
    debuglog.disable()
    debuglog._secrets.clear()


def board(master, replies: bytes):
    """A fake ESP32 on a pty: answers every '?' with `replies`."""
    def run():
        buf = b""
        while True:
            try:
                buf += os.read(master, 1024)
            except OSError:
                return
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if line == b"?":
                    os.write(master, replies)

    threading.Thread(target=run, daemon=True).start()


def esp32_link(replies: bytes):
    master, slave = os.openpty()
    board(master, replies)
    link = links.esp32(os.ttyname(slave))
    time.sleep(0.2)
    return link, master


def test_esp32_handshake_logs_control_lines_only(logfile):
    link, _ = esp32_link(b"ready\nconnected\npeer 3F:A2 Alice's iPhone\ndbg connect aa:bb:cc:dd:ee:ff bonds=0\n")
    text = logfile()
    assert "handshake attempt 1" in text and "peer 3F:A2" in text and "…:ee:ff" in text
    assert "Alice" not in text and "aa:bb:cc:dd" not in text
    link.close()


def test_reports_are_counted_never_recorded(logfile, monkeypatch):
    monkeypatch.setattr(links, "COUNT_EVERY", 0.0)
    link, _ = esp32_link(b"ready\n")
    link.send(55, 77, 1, 0)
    link.send(55, 77, 1, 0)
    link.send_keys(0, [4, 5])
    link.send_keys(0, [])
    text = logfile()
    assert "mouse" in text and "key reports" in text
    assert "55 77" not in text and "k 0 4 5" not in text
    link.close()


def test_unrecognised_board_output_is_logged_truncated_and_capped(logfile):
    link, _ = esp32_link(b"ready\n" + b"".join(b"garbage%d " % i + b"x" * 300 + b"\n" for i in range(40)))
    text = logfile()
    assert text.count("unrecognised") == 20 and "x" * 100 not in text
    link.close()


def test_mode_failure_is_logged_with_traceback(logfile, monkeypatch):
    def boom(python):
        raise OSError("no such helper /dev/ttyUSB9")

    monkeypatch.setattr(modes.links, "ble", boom)
    monkeypatch.setattr(modes, "selectable", lambda name, platform=None: True)
    with pytest.raises(modes.ModeError):
        modes.start_mode("ble", "/dev/ttyUSB9", "abc", None)
    text = logfile()
    assert "no such helper" in text and "Traceback" in text


def test_an_unavailable_esp32_is_logged_with_traceback_and_does_not_raise(logfile, monkeypatch):
    monkeypatch.setattr(modes.links, "esp32", lambda port: (_ for _ in ()).throw(OSError(2, "No such file")))
    mode = modes.start_mode("esp32", "/dev/ttyUSB9", "abc", None)
    text = logfile()
    assert mode.error and "mode esp32 failed to start" in text and "Traceback" in text


def test_canary_secrets_never_reach_the_log_file(logfile, tmp_path, monkeypatch):
    token, code = "tok-canary-777", "123456"
    debuglog.add_secret(token)
    debuglog.add_secret(code)
    udid, mac = "da9c13bc2d479e8e130e156fe1eddf99b7e3eef8", "aa:bb:cc:dd:ee:ff"
    home = str(tmp_path / "home")
    # the board speaks canaries: control lines, a peer name, odd output
    link, _ = esp32_link(f"ready\npeer 3F:A2 alice-iphone\ndbg connect {mac} {token} {home}\nnoise {udid} {code}\n".encode())
    # keys and mouse go through the link: counted only
    link.send_keys(0, [4, 5, 6])
    link.send(55, 77, 1, 0)
    # a failing mode start whose message carries canaries
    monkeypatch.setattr(modes.links, "ble", lambda python: (_ for _ in ()).throw(OSError(f"{home}/x {udid} {token}")))
    monkeypatch.setattr(modes, "selectable", lambda name, platform=None: True)
    with pytest.raises(modes.ModeError):
        modes.start_mode("ble", "/dev/x", udid, None)
    monkeypatch.setattr(modes.links, "esp32", lambda port: (_ for _ in ()).throw(OSError(f"{home}/y {udid} {token}")))
    assert modes.start_mode("esp32", "/dev/x", udid, None).error  # unavailable, and its text is scrubbed in the log
    # an agent session that loses its connection
    ours, phone = socket.socketpair()
    session = agent.Session(ours, post=lambda fn: fn(), reopen=lambda: socket.socketpair()[0])
    phone.close()
    session.request({"cmd": "key", "usage": 4})
    time.sleep(0.3)
    session.close()
    # qvh output with the UDID and the home folder
    script = tmp_path / "fakeqvh"
    script.write_text(f"#!/bin/sh\necho 'using device {udid} in {home}'\n")
    script.chmod(0o755)
    with video.capture(str(script), LatestFrame()) as proc:
        proc.wait()
    logging.getLogger("scrcrappy.test").info("clipboard-canary typed-canary should only appear if someone logs them")
    text = logfile()
    for leaked in (token, code, home, "alice", udid, mac, "aa:bb:cc:dd", "55 77", "k 0 4 5 6"):
        assert leaked not in text, leaked
    assert stat.S_IMODE(os.stat(tmp_path / "logs" / "scrcrappy.log").st_mode) == 0o600
    link.close()


def test_status_polls_do_not_flood_the_log(logfile):
    link, _ = esp32_link(b"ready\npaired 6F:BF\nconnected\npeer 6F:BF x\n")
    for _ in range(6):
        link.query()
        time.sleep(0.05)
    text = logfile()
    assert text.count("handshake attempt") >= 1
    assert text.count("sent '?'") == 0  # polls are not logged
    assert text.count("board: ready") == 1 and text.count("board: paired 6F:BF") == 1
    link.close()


def test_a_changed_board_state_is_logged_again(logfile):
    master, slave = os.openpty()
    state = [b"ready\npaired 6F:BF\nconnected\n"]
    received = []

    def run():
        buf = b""
        while True:
            try:
                buf += os.read(master, 1024)
            except OSError:
                return
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if line == b"?":
                    os.write(master, state[0])

    threading.Thread(target=run, daemon=True).start()
    link = links.esp32(os.ttyname(slave))
    time.sleep(0.2)
    state[0] = b"ready\nunpaired\n"
    link.query()
    time.sleep(0.2)
    text = logfile()
    assert "board: paired 6F:BF" in text and "board: unpaired" in text and text.count("board: ready") == 1
    link.close()


def test_forget_is_logged(logfile):
    link, _ = esp32_link(b"ready\n")
    link.forget()
    assert "sent 'p'" in logfile()
    link.close()


def test_a_dead_link_logs_one_failure_per_streak(logfile):
    state = {"fail": True}

    def write(b):
        if state["fail"]:
            raise OSError(5, "Input/output error")
        return len(b)

    link = links.Link(write, lambda: b"")
    for _ in range(50):
        link.send(1, 2, 0, 0)
    state["fail"] = False
    link.send(1, 2, 0, 0)
    state["fail"] = True
    link.send(1, 2, 0, 0)
    text = logfile()
    assert text.count("write failed") == 2 and text.count("writes work again") == 1


def test_firmware_line_is_logged_once_across_polls(logfile):
    link, _ = esp32_link(b"ready\nfw debug Oct 25 2026 21:00:00\nunpaired\n")
    for _ in range(4):
        link.query()
        time.sleep(0.05)
    text = logfile()
    assert text.count("board: fw debug Oct 25 2026 21:00:00") == 1 and "unrecognised" not in text
    link.close()


def test_boot_text_after_a_restart_is_logged_even_when_the_cap_was_used_up(logfile):
    master, slave = os.openpty()
    board(master, b"ready\n")
    link = links.esp32(os.ttyname(slave))
    os.write(master, b"".join(b"noise %d\n" % i for i in range(30)))  # uses up the 20 unrecognised lines
    time.sleep(0.2)
    os.write(master, b"ready\nafter-restart-text\n")  # the board restarted: its text is news again
    time.sleep(0.2)
    assert "after-restart-text" in logfile()
    link.close()


def test_a_reconnect_after_a_disconnect_is_never_swallowed_by_the_dedupe(logfile):
    link = links.Link(lambda b: None, lambda: b"")
    snapshot = ["ready", "fw normal x", "paired 3F:A2", "connected", "peer 3F:A2 n"]

    def poll(lines):
        link._asked_at = time.monotonic()  # lines arriving right after our own '?'
        for line in lines:
            link._line_in(line)

    poll(snapshot)
    poll(snapshot)
    link._asked_at = -1.0  # unsolicited lines, long after any '?'
    link._line_in("disconnected")
    poll(snapshot[:3])  # the poll while the phone is away
    link._asked_at = -1.0
    link._line_in("connected")  # the phone comes back, unasked
    link._line_in("ready")  # the board restarted, unasked
    text = logfile()
    assert text.count("board: connected") == 2 and text.count("board: ready") == 2 and "board: disconnected" in text
