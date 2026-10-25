"""Opt-in debug log: a rotating file under the OS's log folder, every line scrubbed of anything sensitive.

Loggers are `scrcrappy.<module>` and cost nothing while no handler is installed (the default). `enable()` installs
the handler and the exception hooks, `disable()` takes them out again."""
import getpass
import logging
import os
import platform
import re
import sys
import threading
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from .config import Config

MAX_BYTES, BACKUPS = 1_000_000, 2
FORMAT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
_secrets: set[str] = set()
_handler: RotatingFileHandler | None = None
_hooks: tuple | None = None  # (sys.excepthook, threading.excepthook) as they were before enable()

_UDID = re.compile(r"\b(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16})\b")
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){4}([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})\b")
_BEARER = re.compile(r"Bearer\s+\S+")


def log_path(platform_name: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Where the log goes: ~/Library/Logs on macOS, the XDG state folder elsewhere."""
    platform_name = platform_name or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform_name == "darwin":
        return home / "Library" / "Logs" / "scrcrappy" / "scrcrappy.log"
    base = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else home / ".local" / "state"
    return base / "scrcrappy" / "scrcrappy.log"


def add_secret(value: str) -> None:
    """Never let `value` (the MCP token, a pairing code, …) reach the log, the report or the diagnostic."""
    if value and len(value) > 2:
        _secrets.add(value)


def mask_serial(serial: str) -> str:
    return serial[:4] + "…"


def scrub(text: str) -> str:
    """`text` without the home folder, the account name, registered secrets, phone serials or full MAC addresses."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, "<secret>")
    text = _BEARER.sub("Bearer <secret>", text)
    for home in {str(Path.home()), str(Path.home().resolve())}:
        text = text.replace(home, "~")
    user = getpass.getuser()
    if len(user) > 2:
        text = re.sub(rf"\b{re.escape(user)}\b", "<user>", text)
    text = _UDID.sub(lambda m: mask_serial(m.group(0)), text)
    return _MAC.sub(lambda m: f"…:{m.group(1)}:{m.group(2)}", text)


def config_view(cfg: Config) -> dict:
    """The few settings worth knowing when debugging (an allowlist: no token, no button names)."""
    shots = scrub(cfg.screenshots)
    return {"mouse": cfg.mouse, "port": cfg.port, "natural_scroll": cfg.natural_scroll,
            "ai_control": bool(cfg.ai_control), "debug_log": cfg.debug_log, "screenshots": shots,
            "customs": sum(len(v) for v in cfg.customs.values())}


def startup_facts(cfg: Config, args: list[str]) -> list[str]:
    import pygame
    from importlib.metadata import PackageNotFoundError, version
    try:
        ours = version("scrcrappy")
    except PackageNotFoundError:
        ours = "unknown"
    env = os.environ
    return [f"scrcrappy {ours}, python {platform.python_version()}, pygame {pygame.version.ver} "
            f"(SDL {'.'.join(map(str, pygame.get_sdl_version()))})",
            f"platform {platform.platform()} {platform.machine()}",
            f"video driver {env.get('SDL_VIDEODRIVER', '-')}, session {env.get('XDG_SESSION_TYPE', '-')}, "
            f"WAYLAND_DISPLAY {'set' if env.get('WAYLAND_DISPLAY') else 'unset'}, "
            f"DISPLAY {'set' if env.get('DISPLAY') else 'unset'}",
            f"args {args}", f"config {config_view(cfg)}"]


class _Handler(RotatingFileHandler):
    def _open(self):  # rotated files too: private
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))  # the message, the traceback, everything


def _log_uncaught(kind: str, exc_type, exc, tb) -> None:
    logging.getLogger("scrcrappy.crash").critical("uncaught exception in %s", kind, exc_info=(exc_type, exc, tb))


def is_enabled() -> bool:
    return _handler is not None


def current_path() -> Path | None:
    return Path(_handler.baseFilename) if _handler else None


def enable(cfg: Config, args: list[str], path: Path | None = None) -> Path | None:
    """Start logging to `path` (default `log_path()`); None, with a warning, when the file can't be written."""
    global _handler, _hooks
    if _handler:
        return Path(_handler.baseFilename)
    path = path or log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        handler = _Handler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    except OSError as e:
        print(f"warning: debug log: {e}", file=sys.stderr)
        return None
    handler.setFormatter(_Formatter(FORMAT))
    log = logging.getLogger("scrcrappy")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    _handler = handler
    previous = (sys.excepthook, threading.excepthook)

    def main_hook(exc_type, exc, tb) -> None:
        _log_uncaught("main thread", exc_type, exc, tb)
        previous[0](exc_type, exc, tb)

    def thread_hook(args) -> None:
        _log_uncaught(f"thread {getattr(args.thread, 'name', '?')}", args.exc_type, args.exc_value, args.exc_traceback)
        previous[1](args)

    _hooks, sys.excepthook, threading.excepthook = previous, main_hook, thread_hook
    for line in startup_facts(cfg, args):
        log.info(line)
    return path


def disable() -> None:
    global _handler, _hooks
    if _hooks:
        sys.excepthook, threading.excepthook = _hooks
        _hooks = None
    if _handler:
        log = logging.getLogger("scrcrappy")
        log.removeHandler(_handler)
        _handler.close()
        _handler = None
        log.propagate = True
