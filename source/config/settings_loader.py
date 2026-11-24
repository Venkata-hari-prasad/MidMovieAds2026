"""Load the application's JSON settings without applying validation rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS_PATH = Path(__file__).with_name("settings.json")


def load_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    """Load and return settings from JSON.

    If no path is supplied, reads the adjacent ``settings.json`` file.
    This loader only parses JSON; it does not validate setting values.
    """
    path = Path(settings_path) if settings_path is not None else DEFAULT_SETTINGS_PATH
    with path.open("r", encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    if not isinstance(settings, dict):
        raise ValueError(f"Settings JSON must contain an object: {path}")
    return settings
