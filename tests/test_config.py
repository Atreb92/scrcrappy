import json
import os

import pytest

from scrcrappy import config
from scrcrappy.config import Config, Custom

HOME = "\ue9b2"


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "nope.json") == Config()


def test_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    cfg = Config(natural_scroll=True, pinned=False, customs={"abc/ble": [Custom(2, HOME, "Home")]})
    config.save(cfg, p)
    assert json.loads(p.read_text())["customs"]["abc/ble"][0]["icon"] == "e9b2"  # readable hex in the file
    assert config.load(p) == cfg


def test_corrupt_json_gives_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    assert config.load(p) == Config()


def test_invalid_customs_dropped(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"natural_scroll": True, "customs": {"k": [
        {"button": 2, "icon": "e9b2", "name": "Home"},
        {"button": 2, "icon": "e8eb", "name": "dup"},      # duplicate number
        {"button": 7, "icon": "e8eb", "name": "range"},    # outside 2..5
        {"button": 3, "icon": "ffff", "name": "icon"},     # not a picker icon
        {"button": "x"},                                   # garbage
    ]}}))
    cfg = config.load(p)
    assert cfg.natural_scroll is True
    assert cfg.customs == {"k": [Custom(2, HOME, "Home")]}


def test_save_is_atomic(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    config.save(Config(natural_scroll=True), p)
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        config.save(Config(natural_scroll=False), p)
    assert config.load(p).natural_scroll is True


def test_power_icon_offered():
    assert ("\uf8c7", "Power / Lock") in config.ICON_CHOICES


def test_settings_roundtrip_and_bad_mouse(tmp_path):
    p = tmp_path / "c.json"
    cfg = Config(mouse="agent", port="/dev/ttyACM0", screenshots="~/shots")
    config.save(cfg, p)
    assert config.load(p) == cfg
    p.write_text(json.dumps({"mouse": "wifi"}))
    assert config.load(p).mouse == "none"
