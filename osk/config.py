"""User settings, persisted next to the personal language model."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .prediction.userstore import data_dir


@dataclass
class Settings:
    # -- window -----------------------------------------------------------
    docked: bool = True
    opacity: float = 1.0
    faded_opacity: float = 0.45
    x: int = -1
    y: int = -1
    width: int = 1080
    height: int = 460
    always_on_top: bool = True
    nav_visible: bool = True
    #: "dark" or "light". A light keyboard over a white document is easier to
    #: read past, and the higher contrast suits some users with low vision.
    theme: str = "dark"
    #: Marks hover, press and dwell progress. Offered as a choice because those
    #: are load-bearing signals, and a user with colour vision deficiency may not
    #: distinguish the default from the key beneath it.
    accent: str = "blue"

    # -- typing -----------------------------------------------------------
    key_font_scale: float = 1.0
    hold_to_repeat: bool = True
    repeat_delay_ms: int = 500
    repeat_rate_ms: int = 60
    click_sound: bool = False

    # -- accessibility ----------------------------------------------------
    #: Dwell selection activates a key by resting the pointer on it, for users
    #: who can aim a pointer (head mouse, eye tracker, joystick) but cannot
    #: reliably click.
    dwell_enabled: bool = False
    dwell_ms: int = 900

    # -- prediction -------------------------------------------------------
    prediction_enabled: bool = True
    #: Suggestions per row, and how many rows of them. Two rows is the default:
    #: the model's confidence drops away after the first few guesses, so a second
    #: row catches most of what the first one misses, while a third costs screen
    #: space and a longer visual search for a smaller return.
    suggestion_count: int = 7
    suggestion_rows: int = 2
    auto_space: bool = True
    learn_from_typing: bool = True

    def clamp(self) -> "Settings":
        self.opacity = min(1.0, max(0.25, self.opacity))
        self.faded_opacity = min(1.0, max(0.15, self.faded_opacity))
        self.suggestion_count = min(10, max(3, self.suggestion_count))
        self.suggestion_rows = min(3, max(1, self.suggestion_rows))
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        self.dwell_ms = min(4000, max(300, self.dwell_ms))
        self.key_font_scale = min(2.0, max(0.6, self.key_font_scale))
        self.repeat_delay_ms = min(2000, max(150, self.repeat_delay_ms))
        self.repeat_rate_ms = min(500, max(20, self.repeat_rate_ms))
        return self


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    path = settings_path()
    try:
        # utf-8-sig, not utf-8: a settings file edited by hand in Notepad comes
        # back with a byte-order mark, and a plain utf-8 read would reject it and
        # silently discard every setting the user had chosen.
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known}).clamp()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
