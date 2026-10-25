# Opt-in debug log, ESP32 diagnostic, and a copyable report (design)

Date: 2026-10-25. Decided with the user in chat: logging is **opt-in**, and **no sensitive information** is ever logged.

## Why

The user could not make `--mouse esp32` work on macOS and had nothing to debug with: after finding the right `/dev`
device by hand, there was no output and no hint why. They can't develop on the Mac, and other users who open tickets
will hit the same wall. scrcrappy has no logging (31 `print`s to stderr, nothing recorded). The goal is that someone
on any machine can switch on a log, run a diagnostic, and paste a safe report into a GitHub issue.

## What changes

### 1. Opt-in debug log

- Off by default. On with `--debug` for a run (`--no-debug` forces it off), or with a Settings switch "Debug log"
  (saved as `debug_log` in `config.json`, default false, flags win for that run, applies at once without restart).
  When on, stderr gets one line at start: `debug log: <path>`; the Settings panel shows the path under the switch.
- File: macOS `~/Library/Logs/scrcrappy/scrcrappy.log`; Linux `$XDG_STATE_HOME/scrcrappy/scrcrappy.log`
  (default `~/.local/state/scrcrappy/`). Standard `logging.handlers.RotatingFileHandler` (1 MB x 3 files), directory
  mode 700, files mode 600. Format: `time level thread logger message`. One level (DEBUG) when on.
- Records: the startup facts (scrcrappy / Python / pygame / SDL versions, OS and machine, SDL video driver, which
  display session type, run arguments, an allowlisted view of the config); every input mode start, switch and failure
  with the full traceback; ESP32 serial open (path, baud, termios result) and every handshake `?` attempt with
  the control lines received (`ready`, `connected`, `unpaired`, `paired <id>`, `peer …`, `disconnected`, `pairing`,
  the firmware's `dbg …` lines); BT helper start / exit / its stderr; agent connect, reconnect and errors; video
  capture start / stop and the tail of the qvh log (or AVFoundation device selection); uncaught exceptions in any
  thread (`sys.excepthook`, `threading.excepthook`), logged and then handled as before.
- Instrumentation goes through stdlib `logging` loggers named `scrcrappy.<module>`; with no handler installed they
  cost nothing, and anything expensive to format is guarded by `isEnabledFor`.

### 2. What is never logged (the privacy rules)

- **Never**: the MCP token (or any `Authorization` header), the agent's pairing code or secret, clipboard text, typed
  text, key usages, pasted text, screenshots or video frames, the contents of custom button names, the computer's
  hostname, e-mail or account names, IP addresses.
- **Counted, not recorded**: mouse reports and key reports to the board (counts per second, never values); lines
  from the board that are not control lines.
- **Masked**: the home directory becomes `~` everywhere (paths, tracebacks); the phone's serial / UDID shows its
  first 4 characters and `…` (40-hex and 25-char UDID-like strings found in any message, including qvh output, are
  masked the same way); Bluetooth / MAC addresses show only their last two bytes (`…:3F:A2`); the iPhone's
  device name is not logged (only that one was found).
- **Allowlists, not blocklists**: the config view logs only `mouse`, `port`, `natural_scroll`, `ai_control` (as
  on/off), `debug_log`, the screenshot folder as `~`-relative path, and the number of custom buttons; the environment
  view logs only `SDL_VIDEODRIVER`, `XDG_SESSION_TYPE`, and whether `WAYLAND_DISPLAY` / `DISPLAY` are set.
- **Defense in depth**: a `logging.Filter` on the handler scrubs every record (home directory, MAC addresses,
  UDID-like strings, `Bearer …`, and every secret registered at runtime with `scrub.add_secret(...)` such as the MCP
  token and the pairing code) even if a call site forgot. The scrub is also applied to the report and to the
  diagnostic output.
- A test logs a set of canary secrets (token, pairing code, a home-path, a UDID, a MAC, clipboard and typed text)
  through every instrumented code path and asserts none of them appears in the log file.

### 3. `scrcrappy --diagnose-esp32 [--port P]` (works with no window and no phone)

Prints, with timings, what happens on the serial side: the serial port candidates found (macOS `/dev/cu.*` and
`/dev/tty.*`; Linux `/dev/ttyUSB*`, `/dev/ttyACM*`) with a one-line hint (on macOS prefer `cu.*`); then, for `--port`
(or for each candidate when none is given): opening it (success, or the errno and what it usually means: permission
denied, busy, no such device), setting 115200 raw, waiting 3 s and showing any boot output (hex and text), sending
`?` up to 5 times and showing every reply, and a final verdict line: `board answered (firmware ok)` / `board silent:
wrong port, board not flashed with firmware/esp32-mouse, or the port blocks on open (try the cu.* name)` /
`cannot open: <reason>`. The output goes to stdout and, when the debug log is on, to the log. It uses the same open
code path as `links.esp32` (not a copy), so it shows what the app would experience.

### 4. Debug report

`scrcrappy --report` prints, and Settings › "Copy debug report" copies to the clipboard (toast `Debug report copied`),
a markdown block: "review before posting" note, versions and platform, the allowlisted config and environment, the
serial port candidates, the last 200 lines of the log if it exists (else a line saying the log is off and how to turn
it on), all scrubbed. Nothing is sent anywhere.

## Goals

- Someone on macOS (or anywhere) with a non-working ESP32 can run one command and see exactly where it stops.
- A GitHub issue can carry a report that is safe to post without reading it line by line (still tell them to skim it).

## Non-goals

- Uploading logs or crash reports; telemetry; remote logging; log-level settings beyond on/off.
- Fixing the unknown macOS ESP32 failure blind. The diagnostic exists to find it; a fix is a follow-up once someone has
  a report.
- Windows; logging video content; performance tracing.

## Anti-goals

- Any sensitive value in a file, a report or the diagnostic output.
- Logging slowing the app when it is off, or filling the disk when it is on (rotation is the cap).
- A second code path for opening the serial port just for the diagnostic.

## Constraints

- Standard library only (`logging`, `logging.handlers`, `platform`, `glob`); no new dependency.
- Linux and macOS. The tests need no phone, board or display (`.venv/bin/pytest -q`).
- The existing stderr `print`s stay as they are (user-facing messages); the log is additional.

## Settled (builder-check answers)

- **Toggling at runtime**: turning the log on (switch or flag) emits the startup facts block, so a log started mid-run
  still has versions and platform; turning it off removes the handler. `sys.excepthook` / `threading.excepthook` are
  installed (chaining to the previous hook) when the log is turned on and put back when it is turned off, so nothing
  changes while the log is off.
- **Shared open path**: `links.esp32` is split. A new `links.open_serial(port, baud) -> int` does the `os.open`,
  raw mode and baud setup and is what both `links.esp32` and `--diagnose-esp32` call. The diagnostic then reads and
  writes the file descriptor itself. It sends only `?\n` to the board, nothing else.
- **Firmware**: no firmware change. The host logs the board's `dbg …` lines if the firmware has them (0.4.0 does; an
  older board simply shows none).
- **Masking**: over-masking is fine (a 40-hex git hash being masked is harmless). Serial port names are not masked.
  Besides `$HOME`, the OS user name (`getpass.getuser()`) is registered as a secret and scrubbed wherever it appears.
- **Canary test**: it drives each instrumented call site with fakes (fake serial board on a pty, fake sessions,
  fake qvh output, fake BT helper process) and relies on the scrub filter for the rest; it needs no hardware.
- **Report without a log / without a clipboard**: `--report` works with the log off (facts only, with a line saying how
  to turn the log on). If the pygame clipboard can't be written, "Copy debug report" writes the report to
  `report.txt` next to the log and the toast gives that path.
- The report's "last 200 lines" come from the current log file only.

## Left to the builder

Module layout (suggested: `scrcrappy/debuglog.py` for setup, paths and the scrub filter, `scrcrappy/diagnose.py` for
`--diagnose-esp32` and `--report`), exact logger names and messages, how the Settings switch is laid out (follow the
existing switches), how the clipboard is written (pygame's scrap, as paste already reads it), and the wording of the
hints and verdicts beyond the examples.

## Decided by the assistant, not the user (check these)

- Flag names `--debug` / `--no-debug` / `--diagnose-esp32` / `--report`, and the Settings switch being saved.
- Log locations and rotation (1 MB x 3), file mode 600.
- The phone serial is shown as its first 4 characters; serial port names (e.g. `cu.usbserial-0001`) are not masked.
- The report includes the last 200 log lines.
- Per-second counts for mouse / key reports instead of values.
