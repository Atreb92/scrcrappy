import logging
import os
import stat
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrcrappy import debuglog
from scrcrappy.config import Config, Custom


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(debuglog.getpass, "getuser", lambda: "alice")
    debuglog.disable()
    debuglog._secrets.clear()
    yield
    debuglog.disable()
    debuglog._secrets.clear()


def test_log_path_macos_and_linux_xdg_default():
    home = Path("/Users/bob")
    assert debuglog.log_path("darwin", {}, home) == home / "Library/Logs/scrcrappy/scrcrappy.log"
    assert debuglog.log_path("linux", {}, home) == home / ".local/state/scrcrappy/scrcrappy.log"
    assert debuglog.log_path("linux", {"XDG_STATE_HOME": "/s"}, home) == Path("/s/scrcrappy/scrcrappy.log")


def test_scrub_masks_each_sensitive_shape(tmp_path):
    home = str(tmp_path / "home")
    debuglog.add_secret("tok-123456")
    text = (f"open {home}/x as alice with tok-123456 Authorization: Bearer abcdef "
            "udid da9c13bc2d479e8e130e156fe1eddf99b7e3eef8 ser 00008030-001234567890802E mac AA:BB:CC:DD:3F:A2")
    out = debuglog.scrub(text)
    for leaked in (home, "alice", "tok-123456", "abcdef", "da9c13bc2d479e8e130e156fe1eddf99b7e3eef8",
                   "001234567890802E", "AA:BB:CC:DD"):
        assert leaked not in out
    assert "~/x" in out and "da9c…" in out and "…:3F:A2" in out


def test_scrub_leaves_ordinary_text():
    assert debuglog.scrub("handshake attempt 2: ready") == "handshake attempt 2: ready"


def test_short_secrets_are_ignored():
    debuglog.add_secret("a")
    debuglog.add_secret("")
    assert debuglog.scrub("a banana") == "a banana"


def test_config_view_is_an_allowlist(tmp_path):
    cfg = Config(mcp_token="SECRET-TOKEN", screenshots=str(tmp_path / "home" / "Pics"), mouse="esp32", ai_control=True)
    cfg.customs = {"abcd/esp32": [Custom(2, "x", "My private name")]}
    view = debuglog.config_view(cfg)
    assert view == {"mouse": "esp32", "port": cfg.port, "natural_scroll": False, "ai_control": True,
                    "debug_log": False, "screenshots": "~/Pics", "customs": 1}
    assert "SECRET-TOKEN" not in str(view) and "private" not in str(view)


def read(path):
    for h in logging.getLogger("scrcrappy").handlers:
        h.flush()
    return path.read_text()


def test_enable_writes_facts_and_scrubs_records(tmp_path):
    debuglog.add_secret("canary-secret")
    path = debuglog.enable(Config(), ["--debug"], tmp_path / "logs" / "scrcrappy.log")
    logging.getLogger("scrcrappy.x").info("leak canary-secret in %s", tmp_path / "home" / "f")
    text = read(path)
    assert "canary-secret" not in text and "~/f" in text
    assert "scrcrappy" in text and "--debug" in text and "platform" in text.lower()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert debuglog.is_enabled()


def test_enable_twice_adds_one_handler(tmp_path):
    path = tmp_path / "l.log"
    debuglog.enable(Config(), [], path)
    debuglog.enable(Config(), [], path)
    assert len(logging.getLogger("scrcrappy").handlers) == 1


def test_disable_removes_handler_and_restores_hooks(tmp_path):
    before = (sys.excepthook, threading.excepthook)
    debuglog.enable(Config(), [], tmp_path / "l.log")
    assert (sys.excepthook, threading.excepthook) != before
    debuglog.disable()
    assert (sys.excepthook, threading.excepthook) == before
    assert logging.getLogger("scrcrappy").handlers == [] and not debuglog.is_enabled()


def test_unwritable_directory_warns_and_returns_none(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert debuglog.enable(Config(), [], blocker / "sub" / "l.log") is None
    assert "warning: debug log" in capsys.readouterr().err and not debuglog.is_enabled()


def test_threading_excepthook_logs_the_traceback_scrubbed_and_chains(tmp_path, monkeypatch):
    chained = []
    monkeypatch.setattr(threading, "excepthook", lambda args: chained.append(args))
    path = debuglog.enable(Config(), [], tmp_path / "l.log")
    try:
        raise ValueError("boom for alice")
    except ValueError as e:
        args = SimpleNamespace(exc_type=ValueError, exc_value=e, exc_traceback=e.__traceback__,
                               thread=threading.current_thread())
        threading.excepthook(args)
    text = read(path)
    assert "boom for" in text and "alice" not in text and chained == [args]


def test_rotation_caps_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(debuglog, "MAX_BYTES", 2000)
    path = debuglog.enable(Config(), [], tmp_path / "l.log")
    log = logging.getLogger("scrcrappy.r")
    for i in range(200):
        log.info("line %d %s", i, "x" * 50)
    for h in logging.getLogger("scrcrappy").handlers:
        h.flush()
    files = sorted(p.name for p in tmp_path.glob("l.log*"))
    assert files == ["l.log", "l.log.1", "l.log.2"] and all((tmp_path / f).stat().st_size < 4000 for f in files)
    assert all(stat.S_IMODE((tmp_path / f).stat().st_mode) == 0o600 for f in files)


def test_startup_facts_show_the_effective_debug_log_setting(tmp_path):
    path = debuglog.enable(Config(debug_log=False), ["--debug"], tmp_path / "l.log")
    assert "'debug_log': True" in read(path)
