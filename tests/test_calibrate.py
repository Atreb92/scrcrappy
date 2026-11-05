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
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, pace=None, cancel=None: {"x": {12: 2.5}, "y": {12: 2.5}})
    c.cancel()
    c.begin()  # the app calls this on its own thread before starting the worker
    c.run()
    assert calibrate.load("abc").x(12) == 2.5


def test_a_cancel_during_the_final_measurement_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = calibrate.Calibrator("abc", send=lambda *a: None, frames=None)
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, pace=None, cancel=None: (c.cancel(), {"x": {12: 2.5}, "y": {12: 2.5}})[1])
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


import numpy as np

from scrcrappy.mouse import HOME_REPORTS, TICK, Gain, Gains

LIGHT, RADIUS = 244, 18  # the Settings background; iOS blends the cursor over it as calibrate.BLEND says


class SimPhone:
    """The phone as calibration sees it: reports move a virtual cursor by gains.x / gains.y of their length
    (clamped to the screen); peek() serves a light screen with the cursor disk drawn there; time only passes
    through sleep()."""

    def __init__(self, gains, size=(750, 1334), hidden_until=0.0, decoy=None, video=True, drop_every=0,
                 drop_in_sample=0, band=None):
        self.gains, self.size, self.hidden_until, self.decoy, self.video = gains, size, hidden_until, decoy, video
        self.band = band  # (y0, y1, grey): a darker field across the screen, like Settings' search field
        self.drop_every, self.drop_in_sample = drop_every, drop_in_sample
        self.pos, self.clock, self.log = [size[0] / 2, size[1] / 2], 0.0, []
        self.max_x = self.max_y = 0.0
        self.runs: list[list] = []  # [report, count] for each run of identical reports
        self.report_sleeps, self.just_sent = set(), False
        self.peeks, self.looks_before_found = 0, None

    def send(self, dx, dy, buttons, wheel):
        if not self.runs or self.runs[-1][0] != (dx, dy):
            self.runs.append([(dx, dy), 0])
        self.runs[-1][1] += 1
        self.just_sent = True
        nth_run = sum(1 for r, _ in self.runs if r == (dx, dy))
        if self.drop_every and nth_run == self.drop_in_sample and self.runs[-1][1] % self.drop_every == 0:
            return  # lost on the way
        length = (dx * dx + dy * dy) ** 0.5
        w, h = self.size
        self.pos = [min(max(self.pos[0] + self.gains.x(length) * dx, 0), w - 1),
                    min(max(self.pos[1] + self.gains.y(length) * dy, 0), h - 1)]
        self.max_x, self.max_y = max(self.max_x, self.pos[0]), max(self.max_y, self.pos[1])

    def sleep(self, seconds):
        if self.just_sent:
            self.report_sleeps.add(round(seconds, 6))
            self.just_sent = False
        self.clock += seconds

    def peek(self):
        if not self.video:
            return None
        self.peeks += 1
        w, h = self.size
        img = np.full((h, w, 3), LIGHT, np.uint8)
        if self.band:
            img[self.band[0]:self.band[1]] = self.band[2]
        yy, xx = np.ogrid[:h, :w]
        if self.decoy:  # a grey disk that is part of the screen (an avatar, an icon)
            img[(xx - self.decoy[0]) ** 2 + (yy - self.decoy[1]) ** 2 <= RADIUS * RADIUS] = (150, 148, 152)
        visible = self.clock >= self.hidden_until
        if visible:
            disk = (xx - self.pos[0]) ** 2 + (yy - self.pos[1]) ** 2 <= RADIUS * RADIUS
            gain, offset = calibrate.BLEND
            img[disk] = (img[disk] * gain + offset).round().astype(np.uint8)
        if visible and self.looks_before_found is None:
            self.looks_before_found = self.peeks
        return img.tobytes(), (w, h), w * 3

    @property
    def halved(self):
        """A measuring run redone right away with half the reports (the edge guard)."""
        moves = [(r, n) for r, n in self.runs if r not in ((-127, -127), (4, 4))]
        return any(r1 == r2 and n2 == max(3, n1 // 2) < n1 for (r1, n1), (r2, n2) in zip(moves, moves[1:]))


def sim_gains(fx=2.0, fy=1.9):
    return Gains(Gain({k: v * fx for k, v in DEFAULT_GAIN.items()}), Gain({k: v * fy for k, v in DEFAULT_GAIN.items()}))


def run_cal(phone, tmp_path, **kw):
    return calibrate.calibrate(phone.send, phone, sleep=phone.sleep, miss=tmp_path / "miss.png", log=phone.log.append, **kw)


def test_measures_both_axes_of_a_fast_phone_without_hitting_the_edge(tmp_path):
    phone = SimPhone(sim_gains())
    table = run_cal(phone, tmp_path)
    for axis, gain in (("x", phone.gains.x), ("y", phone.gains.y)):
        for length in calibrate.LENGTHS:
            assert table[axis][length] == pytest.approx(gain(length), rel=0.03)
    assert phone.max_x < 750 - calibrate.EDGE and phone.max_y < 1334 - calibrate.EDGE


def test_sample_that_reaches_the_edge_is_redone_with_half_the_reports(tmp_path):
    jump = {1: 0.8, 2: 0.83, 3: 3.2, 4: 3.3, 6: 3.4, 8: 3.5, 12: 3.6, 16: 3.7, 24: 3.8}  # 3 far faster than 2 predicts
    phone = SimPhone(Gains(Gain(jump), Gain(jump)))
    table = run_cal(phone, tmp_path)
    assert table["x"][3] == pytest.approx(3.2, rel=0.03)
    assert phone.halved


def test_median_and_spread():
    assert calibrate.median_gain([1.0, 1.02, 0.5]) == (1.0, pytest.approx(0.52))


def test_spread_above_five_percent_is_warned(tmp_path):
    phone = SimPhone(sim_gains(), drop_every=7, drop_in_sample=2)  # loses reports in a 2nd sample
    table = run_cal(phone, tmp_path)
    assert any("spread" in line for line in phone.log)
    assert table["x"][12] == pytest.approx(phone.gains.x(12), rel=0.03)  # the median ignores the bad one


def test_gains_that_go_down_fail_and_save_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    down = {**{k: v * 2 for k, v in DEFAULT_GAIN.items()}, 8: DEFAULT_GAIN[6] * 2 * 0.8}
    phone = SimPhone(Gains(Gain(down), Gain(DEFAULT_GAIN)))
    real = calibrate.calibrate
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, pace, cancel: real(
        send, frames, pace, sleep=phone.sleep, cancel=cancel, miss=tmp_path / "miss.png", log=phone.log.append))
    with pytest.raises(RuntimeError, match="went down from length 6 to 8 on x"):
        calibrate.Calibrator("abc", phone.send, phone).run()
    assert not calibrate.gain_path("abc").exists()


def test_cursor_that_shows_up_late_is_still_found(tmp_path):
    # the first look comes at ~0.76 s simulated (home + nudge + 0.35 s settle): 1.2 s needs the retries
    phone = SimPhone(sim_gains(), hidden_until=1.2)
    run_cal(phone, tmp_path)
    assert phone.looks_before_found > 1


def test_cursor_never_seen_saves_the_frame_and_names_it(tmp_path):
    phone = SimPhone(sim_gains(), hidden_until=1e9)
    with pytest.raises(RuntimeError, match="miss.png"):
        run_cal(phone, tmp_path)
    assert (tmp_path / "miss.png").exists()


def test_gray_decoy_off_the_path_is_ignored(tmp_path):
    phone = SimPhone(sim_gains(), decoy=(600, 900))
    assert run_cal(phone, tmp_path)["x"][12] == pytest.approx(phone.gains.x(12), rel=0.03)


def test_landscape_frame(tmp_path):
    phone = SimPhone(sim_gains(), size=(1334, 750))
    table = run_cal(phone, tmp_path)
    assert phone.max_y < 750 - calibrate.EDGE and table["y"][24] == pytest.approx(phone.gains.y(24), rel=0.03)


def test_video_gone_is_a_clean_error(tmp_path):
    phone = SimPhone(sim_gains(), video=False)
    with pytest.raises(RuntimeError, match="can't see the cursor"):
        run_cal(phone, tmp_path)


def test_reports_are_sent_at_the_given_pace(tmp_path):
    phone = SimPhone(sim_gains())
    run_cal(phone, tmp_path, pace=0.03)
    assert phone.report_sleeps == {0.03}


def test_cursor_over_a_grey_field_is_still_found(tmp_path):
    # Settings: the vertical samples end on the grey search field / avatar row, where the cursor reads ~139, not 150
    phone = SimPhone(sim_gains(), band=(330, 460, 224))
    table = run_cal(phone, tmp_path)
    assert table["y"][12] == pytest.approx(phone.gains.y(12), rel=0.03)


def test_cursor_over_black_text_is_still_found(tmp_path):
    # the big black "Settings" title under the vertical path: the cursor reads ~28 there
    phone = SimPhone(sim_gains(), band=(330, 460, 0))
    table = run_cal(phone, tmp_path)
    assert table["y"][12] == pytest.approx(phone.gains.y(12), rel=0.03)


def test_find_cursor_on_ignores_a_screen_without_it():
    ref = np.full((300, 300, 3), LIGHT, np.uint8)
    ref[100:200, 50:250] = 0  # text, an avatar, whatever: it's in the reference too
    assert calibrate.find_cursor_on(ref, ref) is None
    assert calibrate.find_cursor_on(np.roll(ref, 3, 0), ref) is None  # nor in a screen that moved a little
