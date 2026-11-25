"""Provider-neutral entry point for discovering the configured media inventory.

Normalized inventory shape::

    {
        "source_type": "filesystem" | "json",
        "categories": {
            "movies": {"exists": bool, "path": str, "files": [...], "folders": [
                {"folder_id": str, "exists": bool, "path": str,
                 "files": [{"filename": str, "path": str,
                            "duration_seconds": int | float | None,
                            "category": "movies", "source_type": str}],
                 "folders": [...] (only when nested directories exist)}
            ]},
            "dev-songs" | "movie-songs" | "songs" | "ads": {
                "exists": bool, "path": str, "folders": [...],
                "files": [{"filename": str, "path": str,
                           "duration_seconds": int | float | None,
                           "category": str, "source_type": str}]
            }
        }
    }

Existence flags distinguish absent paths/categories from present empty ones.
Directory records are retained so shared validators can identify forbidden
nested folders. Discovery reports facts only; business validation belongs
elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:  # Supports both `import media...` and `import source.media...`.
    from .filesystem_provider import discover_filesystem
    from .json_provider import discover_json
except ImportError:  # pragma: no cover - exercised by direct script imports
    from filesystem_provider import discover_filesystem
    from json_provider import discover_json


class DiscoveryModeError(ValueError):
    """Raised when the configured provider mode is not supported."""


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the application's JSON configuration object."""
    project_root = Path(__file__).resolve().parents[1]
    path = Path(config_path) if config_path else project_root / "config" / "settings.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a JSON object: {path}")
    return value


def discover_media(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Discover media using the configured `filesystem` or `json` provider.

    `media_root` defaults to `videos` relative to the source project directory;
    `inventory_path` defaults to `test_data/media_inventory.json` there.
    """
    settings: dict[str, Any] = load_config()
    if config:
        settings.update(config)

    project_root = Path(__file__).resolve().parents[1]
    configured_mode = settings.get("discovery_mode")
    if configured_mode is None:
        raise DiscoveryModeError(
            "No discovery mode is configured. Select one with discovery_mode or pass it to discover_media()."
        )
    mode = str(configured_mode).strip().lower()
    if mode == "filesystem":
        media_root = Path(settings.get("media_root", "videos"))
        if not media_root.is_absolute():
            media_root = project_root / media_root
        inventory = discover_filesystem(media_root)
        inventory["source"] = {"kind": "filesystem", "path": str(media_root.resolve())}
        return inventory
    if mode == "json":
        inventory_path = Path(settings.get("inventory_path", "test_data/media_inventory.json"))
        if not inventory_path.is_absolute():
            inventory_path = project_root / inventory_path
        inventory = discover_json(inventory_path)
        inventory["source"] = {"kind": "json", "path": str(inventory_path.resolve())}
        return inventory
    raise DiscoveryModeError(
        f"Unsupported discovery_mode {mode!r}; expected 'filesystem' or 'json'."
    )


def discover(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Short alias for :func:`discover_media`."""
    return discover_media(config)
