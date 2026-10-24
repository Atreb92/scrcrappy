import os
import threading
import time
from types import SimpleNamespace

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy import agent as agent_mod, app as app_module, modes
from scrcrappy.config import Config, Custom
from scrcrappy.dialog import Settings
from scrcrappy.toolbar import Bar
from scrcrappy.video import LatestFrame


class FakePointer:
    def __getattr__(self, name):
        return lambda *a: None


EVENTS = []


class FakeKeys:
    def wait_idle(self, timeout=1.0): EVENTS.append("wait_idle")
    def report(self, *a): pass
    def type_text(self, text): return 0
    def stop(self): pass


class FakeLink:
    paired, peer, on_pairing = True, None, None

    def __init__(self):
        self.connected = threading.Event()
        self.connected.set()

    @property
    def last_seen(self):
        return time.monotonic()

    def query(self): pass
    def forget(self): pass
    def send(self, *a): pass
    def send_keys(self, *a): pass
    def close(self): pass


class FakeSession:
    orientation = 1

    def close(self): pass
    def touch(self, *a): pass


class FakeCalibrator:
    def __init__(self):
        self.gate = threading.Event()

    def begin(self): self.gate.clear()
    def cancel(self): self.gate.set()
    def value(self): return 1.5

    def run(self):
        self.gate.wait(3)


def make(name, **kw):
    """A Mode with fake resources; `.closes` counts close() calls."""
    if name in ("ble", "esp32"):
        kw = {"make_pointer": lambda size: FakePointer(), "keys": FakeKeys(), "link": FakeLink(),
              "calibrator": FakeCalibrator(), **kw}
    if name == "agent":
        kw = {"session": FakeSession(), **kw}
    m = modes.Mode(name, device_name="scrcrappy ESP32" if name == "esp32" else "scrcrappy PC", **kw)
    m.closes, real = [], m.close
    m.close = lambda: ((not m.closed) and m.closes.append(1), real())  # counts real closes only
    return m


@pytest.fixture
def harness(monkeypatch):
    EVENTS.clear()
    ctx = SimpleNamespace(bar=None, settings=None, saved=[], log=[])
    orig_bar, orig_settings = Bar.__init__, Settings.__init__

    def bar_init(self, *a, **kw):
        orig_bar(self, *a, **kw)
        ctx.bar = self

    def settings_init(self, *a, **kw):
        orig_settings(self, *a, **kw)
        ctx.settings = self

    monkeypatch.setattr(Bar, "__init__", bar_init)
    monkeypatch.setattr(Settings, "__init__", settings_init)
    monkeypatch.setattr(app_module.ai_mod.AiControl, "locked", lambda self: ctx.locked() if hasattr(ctx, "locked") else False)

    def run(script, initial, factory, cfg=None, seconds=1.6):
        cfg = cfg or Config()
        cfg.mouse = initial.name
        frames, t0, n = LatestFrame(), time.time(), [0]

        def alive():
            n[0] += 1
            if n[0] <= 3:
                frames.put((bytes(30 * 60 * 3), (30, 60), 90))
            if n[0] == 3:
                ctx.bar.actions["settings"]()
            script(n[0], ctx)
            return time.time() - t0 < seconds

        app_module.run(frames, alive, mode=initial, cfg=cfg,
                       device_key=f"abc/{initial.name}",
                       save=lambda c: ctx.saved.append((c.mouse, c.port)), start_mode=factory, mode_name=initial.name)
        ctx.cfg = cfg
        return ctx

    ctx.run = run
    return ctx


def ids(bar):
    return {b.id for b in bar.items if b}


def test_switch_success_swaps_everything(harness):
    old, new = make("agent"), make("esp32")
    cfg = Config()
    cfg.customs["abc/esp32"] = [Custom(2, "", "Hi")]
    ctx = harness.run(lambda n, c: n == 5 and c.settings._click("mode:2"), old, lambda name, port: new, cfg=cfg)
    assert old.closes == [1] and new.closes == [1]  # the new one is closed on exit
    assert ctx.cfg.mouse == "esp32" and ("esp32", ctx.cfg.port) in ctx.saved
    assert "custom:2" in ids(ctx.bar) and "home" not in ids(ctx.bar) and ctx.bar.toast_text == "Input: ESP32"
    assert {"forget", "calibrate"} <= set(ctx.settings.hits)  # the panel followed the mode


def test_failed_switch_keeps_the_old_mode(harness):
    old = make("esp32")

    def factory(name, port):
        raise modes.ModeError("agent: nobody home")

    def script(n, c):
        if n == 5:
            c.settings._click("mode:3")
        if n == 30:
            c.log.append(list(old.closes))  # the failed switch closed nothing

    ctx = harness.run(script, old, factory)
    assert ctx.log == [[]] and ctx.cfg.mouse == "esp32" and ctx.saved == []
    assert ctx.bar.toast_text == "agent: nobody home" and "forget" in ctx.settings.hits


def test_switching_to_the_active_mode_is_a_noop(harness):
    calls = []
    harness.run(lambda n, c: n == 5 and c.settings.on_mode("esp32"), make("esp32"), lambda *a: calls.append(a))
    assert calls == []


def test_second_click_while_building_is_ignored(harness):
    gate, calls = threading.Event(), []

    def factory(name, port):
        calls.append(name)
        gate.wait(2)
        return make(name)

    def script(n, c):
        if n in (5, 6, 7):
            c.settings.on_mode("agent")
        if n == 20:
            gate.set()

    ctx = harness.run(script, make("esp32"), factory)
    assert calls == ["agent"] and ctx.cfg.mouse == "agent"


def test_refused_while_calibrating(harness):
    calls, old = [], make("esp32")

    def script(n, c):
        if n == 5:
            c.settings._click("calibrate")
        if n == 8:
            c.settings.on_mode("agent")
            c.log.append(c.bar.toast_text)
        if n == 10:
            old.calibrator.cancel()

    ctx = harness.run(script, old, lambda *a: calls.append(a))
    assert calls == [] and ctx.log == ["Not while calibrating"]


def test_refused_while_an_ai_action_runs(harness):
    calls = []
    harness.locked = lambda: True

    def script(n, c):
        if n == 5:
            c.settings.on_mode("agent")
            c.log.append(c.bar.toast_text)

    ctx = harness.run(script, make("esp32"), lambda *a: calls.append(a))
    assert calls == [] and ctx.log == ["Not while an AI action runs"]


def test_swap_waits_for_an_ai_tool_that_started_during_the_build(harness):
    old, state = make("esp32"), {"locked": False}
    harness.locked = lambda: state["locked"]
    gate = threading.Event()

    def factory(name, port):
        gate.wait(2)
        return make(name)

    def script(n, c):
        if n == 5:
            c.settings.on_mode("agent")
        if n == 6:
            state["locked"] = True
            gate.set()
        if n == 25:
            c.log.append(list(old.closes))  # the tool is still running: nothing swapped yet
            state["locked"] = False

    ctx = harness.run(script, old, factory)
    assert ctx.log == [[]] and old.closes == [1] and ctx.cfg.mouse == "agent"


def test_held_input_released_before_the_old_mode_closes(harness, monkeypatch):
    old, new = make("agent"), make("esp32")
    real = agent_mod.Controller.release_all
    monkeypatch.setattr(agent_mod.Controller, "release_all", lambda self: (harness.log.append("release"), real(self))[1])
    old.close = (lambda real_close=old.close: (harness.log.append("close"), real_close()))
    harness.run(lambda n, c: n == 5 and c.settings._click("mode:2"), old, lambda name, port: new)
    assert "release" in harness.log and harness.log.index("release") < harness.log.index("close")


def test_key_repeat_follows_the_mode(harness):
    def script(n, c):
        if n == 5:
            c.settings.on_mode("agent")
        if n == 20:
            c.log.append(pygame.key.get_repeat())
            c.settings.on_mode("esp32")
        if n == 40:
            c.log.append(pygame.key.get_repeat())

    ctx = harness.run(script, make("esp32"), lambda name, port: make(name), seconds=2.5)
    assert ctx.log == [(400, 33), (0, 0)]


def test_port_change_restarts_esp32_and_saves_the_port(harness):
    old, calls = make("esp32"), []

    def factory(name, port):
        calls.append((name, port))
        return make(name)

    ctx = harness.run(lambda n, c: n == 5 and c.settings.on_port("/dev/ttyUSB9"), old, factory)
    assert calls == [("esp32", "/dev/ttyUSB9")] and old.closes == [1] and ctx.cfg.port == "/dev/ttyUSB9"
    assert ("esp32", "/dev/ttyUSB9") in ctx.saved


def test_failed_port_change_rebuilds_the_old_port(harness):
    old, calls, rebuilt = make("esp32"), [], make("esp32")

    def factory(name, port):
        calls.append((name, port))
        if port == "/dev/bad":
            raise modes.ModeError("no scrcrappy ESP32 firmware answering on /dev/bad")
        return rebuilt

    ctx = harness.run(lambda n, c: n == 5 and c.settings.on_port("/dev/bad"), old, factory)
    assert calls == [("esp32", "/dev/bad"), ("esp32", Config().port)]
    assert old.closes == [1] and rebuilt.closes == [1] and ctx.cfg.port == Config().port and ctx.saved == []
    assert "restored" in ctx.bar.toast_text


def test_queued_key_releases_are_sent_before_the_old_mode_closes(harness):
    old = make("esp32")
    real = old.close
    old.close = lambda: (EVENTS.append("close"), real())
    harness.run(lambda n, c: n == 8 and c.settings._click("mode:0"), old, lambda name, port: make(name))
    assert "wait_idle" in EVENTS and EVENTS.index("wait_idle") < EVENTS.index("close")


def test_the_pairing_toast_follows_a_switch_to_esp32(harness):
    new = make("esp32")
    harness.run(lambda n, c: n == 5 and c.settings._click("mode:2"), make("agent"), lambda name, port: new)
    assert new.link.on_pairing is not None
