import pytest

from scrcrappy import calibrate
from scrcrappy.mouse import DEFAULT_GAIN


class NoFrames:
    def peek(self):
        return None


def test_cancel_stops_the_measurement_and_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sent = []
    c = calibrate.Calibrator("abc", send=lambda *a: (sent.append(a), len(sent) == 3 and c.cancel()), frames=NoFrames())
    with pytest.raises(calibrate.Cancelled):
        c.run()
    assert len(sent) <= 5  # stopped within a report or two, not after the whole sweep
    assert not calibrate.gain_path("abc").exists()


def test_a_cancel_before_the_run_does_not_leak_into_it(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = calibrate.Calibrator("abc", send=lambda *a: None, frames=None)
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, cancel=None, pace=None: {"x": {12: 2.5}, "y": {12: 2.5}})
    c.cancel()
    c.begin()  # the app calls this on its own thread before starting the worker
    c.run()
    assert calibrate.load("abc").x(12) == 2.5


def test_a_cancel_during_the_final_measurement_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = calibrate.Calibrator("abc", send=lambda *a: None, frames=None)
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, cancel=None, pace=None: (c.cancel(), {"x": {12: 2.5}, "y": {12: 2.5}})[1])
    with pytest.raises(calibrate.Cancelled):
        c.run()
    assert not calibrate.gain_path("abc").exists()


def test_load_reads_both_axes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.save("abc", {"x": {1: 1.0, 24: 3.0}, "y": {1: 0.5, 24: 2.0}})
    g = calibrate.load("abc")
    assert g.x(24) == 3.0 and g.y(24) == 2.0


def test_load_old_flat_file_is_used_for_both_axes(monkeypatch, tmp_path):  # left from an earlier version
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.gain_path("abc").parent.mkdir(parents=True)
    calibrate.gain_path("abc").write_text('{"1": 0.9, "24": 2.8}')
    g = calibrate.load("abc")
    assert g.x(24) == g.y(24) == 2.8


@pytest.mark.parametrize("text", ["garbage", '{"x": {"1": -1}, "y": {"1": 1}}', '{"x": {}}'])
def test_load_falls_back_to_defaults(monkeypatch, tmp_path, text):
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.gain_path("abc").parent.mkdir(parents=True)
    calibrate.gain_path("abc").write_text(text)
    g = calibrate.load("abc")
    assert g.x(12) == g.y(12) == DEFAULT_GAIN[12]
