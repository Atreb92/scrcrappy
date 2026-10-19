"""State the user changes in the toolbar, saved to ~/.config/scrcrappy/config.json after each change."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PATH = Path.home() / ".config" / "scrcrappy" / "config.json"
BUTTONS = range(2, 6)  # mouse buttons free for custom actions (1 is the tap)

# icon picker for custom buttons: Material Symbols codepoint, label
ICON_CHOICES = [
    ("\ue9b2", "Home"), ("\ue8eb", "App switcher"), ("\uf8c7", "Power / Lock"), ("\ue899", "Lock screen"), ("\ue429", "Control Centre"),
    ("\ue7f5", "Notification Centre"), ("\uec08", "Screenshot"), ("\ue31d", "Siri"), ("\ue050", "Volume up"),
    ("\ue04d", "Volume down"), ("\ue04f", "Mute"), ("\uf2d5", "Rotate"), ("\uef7a", "Spotlight"),
    ("\ue412", "Camera"), ("\uf2cb", "Shake"), ("\ue92c", "Accessibility"), ("\uf09a", "Star"),
]
_ICONS = {c for c, _ in ICON_CHOICES}


@dataclass
class Custom:
    button: int  # mouse button 2..5
    icon: str  # one of ICON_CHOICES
    name: str


@dataclass
class Config:
    natural_scroll: bool = False
    pinned: bool = True
    customs: dict[str, list[Custom]] = field(default_factory=dict)  # "<phone serial>/<ble|esp32>" -> buttons


def load(path: Path = PATH) -> Config:
    """Missing or unreadable file -> defaults; invalid custom buttons are dropped."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    customs = {}
    for key, items in (raw.get("customs") or {}).items():
        seen, kept = set(), []
        for item in items if isinstance(items, list) else []:
            try:
                c = Custom(int(item["button"]), chr(int(item["icon"], 16)), str(item.get("name", "")))
            except (KeyError, TypeError, ValueError):
                continue
            if c.button in BUTTONS and c.button not in seen and c.icon in _ICONS:
                seen.add(c.button)
                kept.append(c)
        customs[str(key)] = kept
    return Config(bool(raw.get("natural_scroll", False)), bool(raw.get("pinned", True)), customs)


def save(cfg: Config, path: Path = PATH) -> None:
    """Write via a temp file + rename, so an interrupted save leaves the old file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"natural_scroll": cfg.natural_scroll, "pinned": cfg.pinned,
            "customs": {k: [{"button": c.button, "icon": f"{ord(c.icon):x}", "name": c.name} for c in v]
                        for k, v in cfg.customs.items()}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
