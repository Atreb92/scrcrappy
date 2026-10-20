"""`scrcrappy agent --<action>`: one AI action per call, straight to crappytouch (no window, no video).

Prints exactly one JSON object on stdout ({"ok": true, ...} or {"ok": false, "error": ...}, exit 1);
pairing prompts and hints go to stderr. Coordinates are percent of the upright screenshot.
"""
import argparse
import base64
import json
import socket
import sys
import time
from pathlib import Path

import pygame

from . import actions
from . import agent as agent_mod
from .agent_client import Agent, AgentError

ERRORS = {"clipboard timeout": "the phone is asking Allow Paste for this clipboard, which can't be answered "
                               "remotely; tap it on the phone or set the text from this computer",
          "unknown command": "this crappytouch is too old for that: update it on the phone (apps and open need 0.3.0, open_url 0.5.0)",
          "locked": "the phone is locked: unlock it first",
          "unknown app": "that app is not installed (see the app list)",
          "open failed": "the phone could not open it (nothing handles it, or no answer in 5 s)",
          "bad url": "that is not a URL: it needs a scheme, e.g. https://example.com"}


def listed(apps: list[dict]) -> list[dict]:
    """The agent's app list as name, id and whether it is running."""
    return [{"id": app["id"], "name": app["name"], "running": "pid" in app} for app in apps]


def find_app(apps: list[dict], query: str) -> dict:
    """The app `query` means: a bundle id or a display name (any case), else a name that contains it, if that is one app."""
    q = query.strip().casefold()
    if not q:
        raise ValueError("say which app: a name or a bundle id")
    for matches in ([a for a in apps if a["id"].casefold() == q], [a for a in apps if a["name"].casefold() == q],
                    [a for a in apps if q in a["name"].casefold()]):
        if len(matches) == 1:
            return matches[0]
        if matches:
            names = ", ".join(f"{a['name']} ({a['id']})" for a in matches[:6])
            raise ValueError(f"{query!r} matches more than one app: {names}; use the bundle id")
    raise ValueError(f"no app called {query!r}: see the app list")


def connect() -> Agent:
    return agent_mod.connect(socket.gethostname())


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scrcrappy agent", description="One action on a jailbroken iPhone running "
                                "crappytouch. Coordinates: percent (0-100, decimals ok) of the upright "
                                "screenshot, x left to right, y top to bottom. Prints one JSON object.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--screenshot", metavar="PATH", help="save a PNG (long edge at most 1568 px); "
                   "replies with width, height and orientation")
    g.add_argument("--tap", metavar="X,Y")
    g.add_argument("--long-press", metavar="X,Y[,MS]", help=f"default {actions.LONG_PRESS_MS} ms")
    g.add_argument("--swipe", metavar="X1,Y1,X2,Y2[,MS]", help=f"default {actions.SWIPE_MS} ms")
    g.add_argument("--type", metavar="TEXT", help="type into the focused field: keys when a US layout can "
                   "type it all, else paste (the phone may ask Allow Paste)")
    g.add_argument("--clipboard", action="store_true", help="print the phone's clipboard text")
    g.add_argument("--apps", action="store_true", help="list the apps the phone can open (name, id, running)")
    g.add_argument("--open", metavar="APP", help="open an app by name or bundle id (replies before it has drawn)")
    g.add_argument("--open-url", metavar="URL", help="open a URL or deeplink (https:, tel:, maps:, app schemes…) like "
                   "tapping a link; replies before the app has drawn")
    g.add_argument("--home", action="store_true", help="press the Home button")
    g.add_argument("--switcher", action="store_true", help="open the app switcher (Home pressed twice)")
    g.add_argument("--lock", action="store_true", help="press the Lock button (the phone stays locked until unlocked)")
    return p


def touch(a: Agent, steps: list[actions.Step]) -> dict:
    screen = a.request({"cmd": "screen"})
    if not screen.get("touch_ready", True):
        raise ValueError("touch the phone's screen once (needed after each reboot), then retry")
    for delay, phase, x, y in steps:
        time.sleep(delay)
        fx, fy = actions.to_portrait(x, y, screen["orientation"])
        a.send({"cmd": "touch", "events": [{"finger": 1, "phase": phase, "x": fx, "y": fy}]})
    a.request({"cmd": "screen"})  # replies come in order: every touch above has been handled
    return {}


def run(args: argparse.Namespace, a: Agent) -> dict:
    if args.tap is not None:
        x, y, _ = actions.parse_point(args.tap)
        return touch(a, actions.tap(x, y))
    if args.long_press is not None:
        return touch(a, actions.long_press(*actions.parse_point(args.long_press)))
    if args.swipe is not None:
        return touch(a, actions.swipe(*actions.parse_points(args.swipe)))
    if args.screenshot is not None:
        orientation = a.request({"cmd": "screen"})["orientation"]
        png = base64.b64decode(a.request({"cmd": "screenshot"})["png"])
        data, w, h = actions.upright_png(png, orientation)
        Path(args.screenshot).write_bytes(data)
        return {"path": args.screenshot, "width": w, "height": h,
                "orientation": actions.ORIENTATIONS.get(orientation, "portrait")}
    if args.apps:
        return {"apps": listed(a.apps())}
    if args.open is not None:
        app = find_app(a.apps(), args.open)
        a.open_app(app["id"])
        return {"id": app["id"], "name": app["name"]}
    if args.open_url is not None:
        a.open_url(args.open_url)
        return {"url": args.open_url}
    if args.home or args.switcher or args.lock:
        usages = (agent_mod.LOCK,) if args.lock else (agent_mod.HOME,) * (2 if args.switcher else 1)
        for i, usage in enumerate(usages):
            if i:
                time.sleep(agent_mod.SWITCHER_GAP)
            a.request({"cmd": "key", "page": agent_mod.BUTTONS, "usage": usage})
        return {}
    if args.type is not None:
        kind, strokes = actions.typing_plan(args.type)
        if kind == "keys":
            for modifiers, usage in strokes:
                a.request({"cmd": "key", "usage": usage, "modifiers": modifiers})
        else:
            a.request({"cmd": "text", "text": args.type})
        return {"typed_with": kind}
    return {"text": a.request({"cmd": "clipboard_get"})["text"]}


def main(argv: list[str], out=None) -> int:
    out = out or sys.stdout
    args = parser().parse_args(argv)
    try:
        for value in (args.tap, args.long_press):  # bad input fails before touching the phone
            if value is not None:
                actions.parse_point(value)
        if args.swipe is not None:
            actions.parse_points(args.swipe)
        if args.screenshot == "":
            raise ValueError("--screenshot needs a file path")
        a = connect()
        try:
            result = run(args, a)
        finally:
            a.close()
    except AgentError as e:
        result = {"ok": False, "error": ERRORS.get(str(e), str(e))}
    except (OSError, ValueError, KeyError, pygame.error) as e:
        result = {"ok": False, "error": str(e) or type(e).__name__}
    else:
        result = {"ok": True, **result}
    out.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0 if result["ok"] else 1
