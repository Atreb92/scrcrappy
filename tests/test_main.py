from scrcrappy import __main__ as cli


def test_missing_qvh_exits_1(capsys):
    assert cli.main(["--qvh", "/nonexistent/qvh"]) == 1
    assert "qvh not found" in capsys.readouterr().err


def test_no_iphone_exits_1(capsys, monkeypatch):
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)
    assert cli.main(["--qvh", "/bin/true"]) == 1
    assert "no iPhone connected" in capsys.readouterr().err


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
    assert cli.main(["--qvh", "/bin/true", "--calibrate"]) == 1  # saved agent: no calibration
    assert "--calibrate needs" in capsys.readouterr().err
    assert cli.main(["--qvh", "/bin/true", "--calibrate", "--mouse", "ble"]) == 1  # flag wins: gets past the check
    assert "no iPhone connected" in capsys.readouterr().err


def test_find_qvh_prefers_flag_then_package_then_repo(tmp_path):
    pkg, repo = tmp_path / "pkg" / "qvh", tmp_path / "repo" / "qvh"
    for p in (pkg, repo):
        p.parent.mkdir()
        p.write_text("")
        p.chmod(0o755)
    assert cli.find_qvh("/bin/true", pkg, repo) == "/bin/true"
    assert cli.find_qvh(None, pkg, repo) == str(pkg)  # package beats an old repo build
    pkg.unlink()
    assert cli.find_qvh(None, pkg, repo) == str(repo)


def test_find_qvh_restores_exec_bit(tmp_path):
    import os
    pkg = tmp_path / "qvh"
    pkg.write_text("")
    pkg.chmod(0o644)
    assert cli.find_qvh(None, pkg, tmp_path / "none") == str(pkg)
    assert os.access(pkg, os.X_OK)


def test_missing_qvh_names_build_script(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "PACKAGED_QVH", tmp_path / "a")
    monkeypatch.setattr(cli, "REPO_QVH", tmp_path / "b")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)  # never reach a real phone if this regresses
    assert cli.main([]) == 1
    assert "scripts/build-qvh.sh" in capsys.readouterr().err
