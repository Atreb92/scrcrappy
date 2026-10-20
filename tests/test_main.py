import shutil

import pytest

from scrcrappy import __main__ as cli

TRUE = shutil.which("true")  # /bin/true on Linux, /usr/bin/true on macOS


@pytest.fixture(autouse=True)
def linux(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")  # the qvh path; macOS captures through AVFoundation


def test_missing_qvh_exits_1(capsys):
    assert cli.main(["--qvh", "/nonexistent/qvh"]) == 1
    assert "qvh not found" in capsys.readouterr().err


def test_macos_needs_no_qvh(capsys, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)
    assert cli.main(["--qvh", "/nonexistent/qvh"]) == 1
    assert "no iPhone connected" in capsys.readouterr().err


def test_no_iphone_exits_1(capsys, monkeypatch):
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)
    assert cli.main(["--qvh", TRUE]) == 1
    assert "no iPhone connected" in capsys.readouterr().err


def test_video_driver_wayland_first_with_x11_fallback_or_forced():
    pick = cli.pick_video_driver
    assert pick({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "linux") == "wayland,x11"  # x11 if wayland fails
    assert pick({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "linux", x11=True) == "x11"
    assert pick({"DISPLAY": ":0"}, "linux") == "x11"
    assert pick({"WAYLAND_DISPLAY": "wayland-0"}, "linux", x11=True) == "x11"  # asked for X11: say so, even if SDL can't
    assert pick({"WAYLAND_DISPLAY": "wayland-0", "SDL_VIDEODRIVER": ""}, "linux") == "wayland,x11"  # empty = not set
    assert pick({"WAYLAND_DISPLAY": "wayland-0", "SDL_VIDEODRIVER": "x11"}, "linux") is None  # the user's own choice wins
    assert pick({"WAYLAND_DISPLAY": "wayland-0"}, "darwin") is None


def test_x11_flag():
    assert cli.build_parser().parse_args(["--x11"]).x11 is True
    assert cli.build_parser().parse_args([]).x11 is False


def test_natural_scroll_flag_is_tristate():
    # no flag: the saved value is used; --natural-scroll / --no-natural-scroll override it
    p = cli.build_parser()
    assert p.parse_args([]).natural_scroll is None
    assert p.parse_args(["--natural-scroll"]).natural_scroll is True
    assert p.parse_args(["--no-natural-scroll"]).natural_scroll is False


def test_saved_input_mode_used_unless_flag_given(monkeypatch, capsys):
    from scrcrappy.config import Config
    monkeypatch.setattr(cli.config, "load", lambda: Config(mouse="agent"))
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)
    assert cli.main(["--qvh", TRUE, "--calibrate"]) == 1  # saved agent: no calibration
    assert "--calibrate needs" in capsys.readouterr().err
    assert cli.main(["--qvh", TRUE, "--calibrate", "--mouse", "ble"]) == 1  # flag wins: gets past the check
    assert "no iPhone connected" in capsys.readouterr().err


def test_find_qvh_prefers_flag_then_package_then_path(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg" / "qvh"
    pkg.parent.mkdir()
    pkg.write_text("")
    pkg.chmod(0o755)
    assert cli.find_qvh(TRUE, pkg) == TRUE
    assert cli.find_qvh(None, pkg) == str(pkg)
    pkg.unlink()
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.find_qvh(None, pkg) is None


def test_find_qvh_restores_exec_bit(tmp_path):
    import os
    pkg = tmp_path / "qvh"
    pkg.write_text("")
    pkg.chmod(0o644)
    assert cli.find_qvh(None, pkg) == str(pkg)
    assert os.access(pkg, os.X_OK)


def test_missing_qvh_names_build_script(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "PACKAGED_QVH", tmp_path / "a")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)  # never reach a real phone if this regresses
    assert cli.main([]) == 1
    assert "scripts/build-qvh.sh" in capsys.readouterr().err


def test_macos_skips_qvh_and_the_usb_reset(monkeypatch, capsys):
    import contextlib
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.video, "find_iphone", lambda: object())
    monkeypatch.setattr(cli.video, "serial_number", lambda dev: "abc")
    monkeypatch.setattr(cli, "find_qvh", lambda flag: pytest.fail("macOS has no qvh"))
    monkeypatch.setattr(cli.video, "reset_if_stuck", lambda dev: pytest.fail("macOS never enters the QuickTime config"))
    cap = type("Cap", (), {"poll": lambda self: 0, "log": "boom"})()
    monkeypatch.setattr(cli.video, "capture_avf", lambda frames, serial: contextlib.nullcontext(cap))
    monkeypatch.setattr(cli.app, "run", lambda *a, **k: False)
    assert cli.main(["--mouse", "none"]) == 1
    assert "boom" in capsys.readouterr().err
