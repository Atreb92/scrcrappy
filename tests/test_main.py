from scrcrappy import __main__ as cli


def test_missing_qvh_exits_1(capsys):
    assert cli.main(["--qvh", "/nonexistent/qvh"]) == 1
    assert "qvh not found" in capsys.readouterr().err


def test_no_iphone_exits_1(capsys, monkeypatch):
    monkeypatch.setattr(cli.video, "find_iphone", lambda: None)
    assert cli.main(["--qvh", "/bin/true"]) == 1
    assert "no iPhone connected" in capsys.readouterr().err
