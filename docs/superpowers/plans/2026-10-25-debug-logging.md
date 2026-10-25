# Opt-in debug log, ESP32 diagnostic and debug report: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An opt-in, privacy-scrubbed debug log (`--debug` / saved Settings switch), `scrcrappy --diagnose-esp32` (serial-level diagnostic, no window or phone) and `scrcrappy --report` (+ Settings "Copy debug report"), so ESP32 problems on macOS (and anywhere) can be debugged from a pasted report.

**Architecture:** stdlib `logging` loggers `scrcrappy.<module>` with no handler by default. `debuglog.py` owns enabling/disabling (rotating file handler, scrub filter, startup facts, exception hooks) and the scrubbing rules. `links.py` gets `open_serial()` shared by `esp32()` and `diagnose.py`. `diagnose.py` builds the diagnostic and the report as plain text.

**Tech Stack:** Python 3 standard library (`logging`, `logging.handlers`, `platform`, `glob`, `getpass`), pygame (Settings, clipboard via `pygame.scrap`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-debug-logging-design.md` (read it first, including "Settled").

## Global Constraints

- Branch `debug-logging` (exists, from `main`, spec committed). Commit per task; do not merge.
- No new dependency. Logging off = no handler installed, no hooks installed, no behaviour change.
- Privacy rules are binding (spec §2): never log MCP token / `Authorization`, agent pairing code or secret, clipboard text, typed text, key usages, pasted text, screenshots / frames, custom button names, hostname, IPs, account names; mask `$HOME` -> `~`, OS user name, MAC addresses to last 2 bytes (`…:3F:A2`), phone serial / UDID to first 4 characters + `…`; config and environment views are allowlists; mouse / key reports are counted, never recorded.
- Log files: dir mode 700, file mode 600; `RotatingFileHandler(maxBytes=1_000_000, backupCount=2)`; macOS `~/Library/Logs/scrcrappy/scrcrappy.log`, Linux `$XDG_STATE_HOME` or `~/.local/state` + `/scrcrappy/scrcrappy.log`.
- Log line format: `%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s`; level DEBUG when on.
- Texts, exactly: stderr line `debug log: <path>`; Settings switch label `Debug log`; button `Copy debug report`; toasts `Debug report copied` and `Debug report saved: <path>`; diagnostic verdicts `board answered (firmware ok)`, `board silent: wrong port, board not flashed with firmware/esp32-mouse, or the port blocks on open (try the cu.* name)`, `cannot open: <reason>`.
- Existing stderr `print`s stay. Match surrounding code style (terse comments).

## Review Focus

- Canary secrets (token, pairing code, `$HOME`, OS user name, UDID, MAC, clipboard, typed text) never reach the log file, the report or the diagnostic output.
- Logging switched on and off repeatedly at runtime: no duplicate handlers, hooks restored, no leaked file handles.
- Mouse and key reports to the board are never recorded as values, only counted.
- `--diagnose-esp32` with no board, a silent port, a missing port, and a permission error: each ends with a clear verdict line and exit code, never a traceback.
- `--report` with the log off, with no log file, and with a huge log: bounded output (last 200 lines).
- Log directory unwritable (read-only home): enabling fails soft (stderr warning, app keeps running).
- `Config` files without `debug_log` still load; `--debug` / `--no-debug` precedence over the saved switch.

---

### Task 1: `debuglog.py` (paths, scrubbing, enable/disable, facts)

**Files:**
- Create: `scrcrappy/debuglog.py`
- Test: `tests/test_debuglog.py`

**Interfaces:**
- Produces:
  - `log_path(platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None) -> Path` (rules in Global Constraints; arguments default to the real platform / environment / home, read at call time).
  - `add_secret(value: str) -> None` (registers a runtime secret; empty and 1-2 character values ignored); `scrub(text: str) -> str` (home -> `~`, OS user name, every registered secret -> `<secret>`, `Bearer \S+` -> `Bearer <secret>`, 40-hex and 25-char UDID-like tokens -> first 4 characters + `…`, MAC addresses `aa:bb:cc:dd:ee:ff` -> `…:ee:ff`).
  - `mask_serial(serial: str) -> str` (first 4 characters + `…`).
  - `enable(cfg: Config, args: list[str], path: Path | None = None) -> Path | None`: creates the directory / file with the modes above, installs the rotating handler with the scrub `logging.Filter` on logger `scrcrappy` (level DEBUG, `propagate=False`), installs the two exception hooks (chaining), writes the startup facts block via `startup_facts(cfg, args)`, returns the path; on `OSError` prints `warning: debug log: <reason>` to stderr and returns None. Calling it when already enabled does nothing (returns the path).
  - `disable() -> None` (removes and closes the handler, restores both hooks); `is_enabled() -> bool`.
  - `startup_facts(cfg: Config, args: list[str]) -> list[str]`: scrcrappy / Python / pygame / SDL versions, `platform.platform()` and machine, `SDL_VIDEODRIVER`, `XDG_SESSION_TYPE`, whether `WAYLAND_DISPLAY` / `DISPLAY` are set, `args`, and `config_view(cfg)`.
  - `config_view(cfg: Config) -> dict` (only `mouse`, `port`, `natural_scroll`, `ai_control` as bool, `debug_log`, `screenshots` as `~`-relative text, `customs` as the total number of custom buttons).

- [ ] **Step 1: Write failing tests** in `tests/test_debuglog.py`: `test_log_path_macos_and_linux_xdg_default` (explicit `platform`, `env`, `home`); `test_scrub_masks_each_sensitive_shape` (home, OS user name via monkeypatched `getpass.getuser`, a registered secret, `Bearer abc`, a 40-hex UDID, a 25-char serial, a MAC); `test_scrub_leaves_ordinary_text`; `test_config_view_is_an_allowlist` (token, custom names, screenshots under home never appear); `test_enable_writes_facts_and_scrubs_records` (tmp path; log a message containing a canary secret via `logging.getLogger("scrcrappy.x")`; the file has facts, not the canary; file mode `0o600`, dir `0o700`); `test_enable_twice_adds_one_handler`; `test_disable_removes_handler_and_restores_hooks`; `test_unwritable_directory_warns_and_returns_none` (capsys); `test_threading_excepthook_logs_the_traceback_scrubbed`; `test_rotation_caps_the_file` (tiny maxBytes via a module constant monkeypatched).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_debuglog.py -q` -> FAIL (module missing).
- [ ] **Step 3: Implement** `debuglog.py` per the interface (module constants `MAX_BYTES`, `BACKUPS` so the test can shrink them).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` -> PASS.
- [ ] **Step 5: Commit** `debuglog: opt-in rotating log with scrubbing`.

### Task 2: Config field and CLI flags

**Files:**
- Modify: `scrcrappy/config.py` (`Config.debug_log: bool = False`, `load`, `save`), `scrcrappy/__main__.py` (`--debug` / `--no-debug` as `argparse.BooleanOptionalAction`, `--diagnose-esp32`, `--report` declared here; handled in Task 4), logging start in `main`
- Test: `tests/test_config.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `debuglog.enable`, `debuglog.add_secret` (Task 1).
- Produces: `Config.debug_log`; in `main`, right after the config is loaded: `want = args.debug if args.debug is not None else cfg.debug_log`; if `want`, `path = debuglog.enable(cfg, argv)` and print `debug log: <path>` to stderr; `cfg.mcp_token` registered with `add_secret` when non-empty. Helper `apply_debug(cfg, want: bool, argv) -> None` (module-level in `__main__.py`, also used by Settings in Task 5 through a callback) so enabling/disabling has one implementation.

- [ ] **Step 1: Write failing tests**: `test_config_debug_log_roundtrips_and_old_files_load` (a file without the key loads False); `test_debug_flag_beats_saved_switch` (saved True + `--no-debug` -> not enabled; saved False + `--debug` -> enabled; monkeypatch `debuglog.enable` to record); `test_debug_prints_the_log_path` (capsys); `test_token_is_registered_as_a_secret`.
- [ ] **Step 2: Run** the two test files -> FAIL.
- [ ] **Step 3: Implement** config field + load/save (keep `save`'s mode-600 write), parser entries, `apply_debug`, and the call in `main`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` -> PASS.
- [ ] **Step 5: Commit** `--debug flag and saved debug_log setting`.

### Task 3: Instrumentation (call sites)

**Files:**
- Modify: `scrcrappy/links.py` (`open_serial` extraction + logging), `scrcrappy/modes.py`, `scrcrappy/agent.py`, `scrcrappy/video.py`, `scrcrappy/app.py` (mode switch events), `scrcrappy/__main__.py`
- Test: `tests/test_links.py`, `tests/test_instrumentation.py`

**Interfaces:**
- Produces: `links.open_serial(port: str, baud: int = 115200) -> int` (the `os.open(O_RDWR | O_NOCTTY)`, `tty.setraw`, termios baud code currently inline in `esp32()`; `esp32()` calls it; behaviour unchanged). Loggers `scrcrappy.links`, `.modes`, `.agent`, `.video`, `.app`.
- Log points (messages free-form, content rules binding): `links.esp32`: port path, baud, open result / errno, each handshake attempt number, each received **control line** (`ready`, `connected`, `disconnected`, `unpaired`, `paired <id>`, `peer <id> <name>` with the name omitted, `pairing`, `dbg …`), and once per second a count of mouse / key reports sent (counted in `Link.send` / `send_keys`, never their values); `links.ble`: helper start, ready, close, its non-protocol output; `modes.start_mode`: requested mode, success, `ModeError` with traceback (`exc_info`), `Mode.close`; `agent`: connect, connection lost, reconnect; `video`: capture start / stop and the qvh log tail (scrubbed by the filter); `app`: mode switch requested / built / swapped / failed, calibration start / end / cancel; `__main__`: nothing beyond `debuglog`'s facts.

- [ ] **Step 1: Write failing tests**: in `tests/test_links.py` `test_open_serial_sets_raw_mode_and_baud` (pty slave; `termios.tcgetattr` shows the speed; fd closes cleanly) and `test_esp32_still_handshakes_through_open_serial`; in `tests/test_instrumentation.py` with `caplog`-style capture on logger `scrcrappy`: `test_esp32_handshake_logs_control_lines_only` (fake board on a pty answers `ready\nconnected\npeer 3F:A2 Alice's iPhone\n`; assert control lines logged, the name `Alice` not, and no cursor values after `link.send(5, 7, 1, 0)`), `test_report_counts_not_values` (send 3 reports, assert a count record and no `5 7`), `test_mode_failure_is_logged_with_traceback` (fake factory raising), `test_canary_secrets_never_reach_the_log_file` (enable a real file log in tmp; register token and pairing-code canaries; drive `links.esp32` (pty), `modes.start_mode` (fakes), `agent.Session` reconnect (socketpair), `video` qvh-log tail (fake text containing a UDID and the home path), and a `Link` receiving `peer` lines; read the file; assert none of: token, pairing code, `$HOME`, OS user, UDID, MAC, `clipboard-canary`, `typed-canary`).
- [ ] **Step 2: Run** the new tests -> FAIL.
- [ ] **Step 3: Implement** `open_serial` and the log points.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` -> PASS.
- [ ] **Step 5: Commit** `Log the ESP32 handshake, mode changes, agent and video events`.

### Task 4: `--diagnose-esp32` and `--report`

**Files:**
- Create: `scrcrappy/diagnose.py`
- Modify: `scrcrappy/__main__.py` (dispatch before any phone / qvh checks: both commands need neither)
- Test: `tests/test_diagnose.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `links.open_serial`, `debuglog.scrub`, `debuglog.config_view`, `debuglog.startup_facts`, `debuglog.log_path`.
- Produces in `diagnose.py`:
  - `list_ports(platform: str | None = None, glob=glob.glob) -> list[tuple[str, str]]` (path, hint; macOS `/dev/cu.*` and `/dev/tty.*` with the hint that `cu.*` is the one to use, Linux `/dev/ttyUSB*` and `/dev/ttyACM*`).
  - `diagnose_esp32(port: str | None, write: Callable[[str], None] = print, boot_wait: float = 3.0, tries: int = 5, reply_wait: float = 1.0) -> int`: writes the step-by-step output (timings in seconds, boot bytes as hex and text, every reply) and returns the exit code (0 answered, 1 otherwise); with `port=None` it lists candidates and diagnoses each; sends only `?\n`; verdict lines exactly as in Global Constraints; all output passes through `scrub`.
  - `build_report(cfg: Config, args: list[str], log_lines: int = 200) -> str`: markdown with a "review before posting" note, facts, config / environment views, the port list, the log tail (or the line saying the log is off and how to turn it on), all scrubbed.
- `__main__`: `--diagnose-esp32` uses `--port` (else the saved port is NOT assumed: no port means "all candidates"), `--report` prints `build_report`; both return before `video.find_iphone`.

- [ ] **Step 1: Write failing tests** with a pty fake board (reuse `fake_board` from `tests/test_links.py` style): `test_diagnose_answered` (exit 0, output has the `board answered (firmware ok)` verdict, shows the reply lines, sent only `?`); `test_diagnose_silent_port` (a pty that never answers, `boot_wait`/`reply_wait` tiny -> exit 1 and the silent verdict); `test_diagnose_missing_port` (`cannot open:` with the reason, no traceback); `test_diagnose_without_port_lists_candidates` (patched `list_ports`); `test_list_ports_macos_prefers_cu` (injected glob + platform); `test_output_is_scrubbed` (a port path containing `$HOME`... or a board line with a MAC); `test_report_with_log_off` / `test_report_tail_is_bounded` (1000-line log -> 200) / `test_report_contains_no_canary_secrets`; in `tests/test_main.py` `test_report_and_diagnose_need_no_phone` (`main(["--report"])` and `main(["--diagnose-esp32", "--port", "/nonexistent"])` return without touching `video.find_iphone`, which is patched to fail the test).
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** `diagnose.py` and the dispatch.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` -> PASS.
- [ ] **Step 5: Commit** `--diagnose-esp32 and --report`.

### Task 5: Settings switch, report button, docs

**Files:**
- Modify: `scrcrappy/dialog.py` (`Settings`), `scrcrappy/app.py` (wire callbacks), `README.md` (a "Reporting a problem" section: `--debug`, log location, `--diagnose-esp32`, `--report`, what is never logged), `TODO.md`, `CLAUDE.md` Map (`debuglog.py`, `diagnose.py`)
- Test: `tests/test_dialog.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `apply_debug`-style callback (Task 2), `diagnose.build_report`, `debuglog.log_path`.
- Produces: `Settings.__init__(..., on_debug: Callable[[], None] | None = None, on_report: Callable[[], None] | None = None, debug_path: Callable[[], str] = lambda: "")`: a `Debug log` switch (hit `"debug"`, bound to `cfg.debug_log`, drawn like the AI switch) with the log path as a small muted line under it when on, and a `Copy debug report` button (hit `"report"`); the section is hidden when `on_debug` is None. In `app.run`: `on_debug` flips `cfg.debug_log`, enables / disables the log, saves; `on_report` builds the report and writes it with `pygame.scrap.put_text` (falling back to `report.txt` next to the log, toast `Debug report saved: <path>`), toast `Debug report copied` on success.

- [ ] **Step 1: Write failing tests**: `test_debug_switch_toggles_cfg_and_calls_back`; `test_debug_path_line_only_when_on`; `test_report_button_calls_back`; `test_debug_section_hidden_without_callbacks`; in `tests/test_app.py` `test_report_button_copies_or_falls_back` (monkeypatch `pygame.scrap.put_text` to succeed / raise `pygame.error`; assert the toast text and, in the fallback, the file's existence) and `test_debug_switch_enables_and_disables_the_log` (monkeypatched `debuglog.enable` / `disable`).
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** the Settings section (follow the layout and `_switch` pattern of the AI switch), the app wiring, and the docs.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` -> PASS; run `scrcrappy --diagnose-esp32 --port /dev/ttyUSB0` against the real board with the user (expect `board answered (firmware ok)`), then `--debug` once and read the resulting log with the user to confirm it holds no token, home path or typed text.
- [ ] **Step 5: Commit** `Settings: Debug log switch and Copy debug report; docs`, then one fresh reviewer on the whole branch (`superpowers:requesting-code-review`) and fix what it finds. Leave merging to the user.
