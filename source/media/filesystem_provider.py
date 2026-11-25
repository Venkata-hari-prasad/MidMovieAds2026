"""Filesystem-backed discovery returning the shared normalized inventory."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

try:  # Supports both `import media...` and `import source.media...`.
    from .media_probe import probe_duration_seconds
except ImportError:  # pragma: no cover - exercised by direct script imports
    from media_probe import probe_duration_seconds

CATEGORIES = ("movies", "dev-songs", "movie-songs", "songs", "ads")


def _folder_sort_key(path: Path) -> tuple[Any, ...]:
    """Put numbered movie folders in numeric order while retaining other names."""
    match = re.fullmatch(r"movie(\d+)", path.name, flags=re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), path.name.casefold())
    return (1, path.name.casefold(), path.name)


def _media_file(path: Path, category: str) -> dict[str, Any]:
    return {
        "filename": path.name,
        "path": str(path.resolve()),
        "duration_seconds": probe_duration_seconds(path),
        "category": category,
        "source_type": "filesystem",
    }


def _directory_record(path: Path) -> dict[str, str]:
    """Represent an unexpected directory so shared validators can inspect it."""
    return {"folder_id": path.name, "path": str(path.resolve())}


def discover_filesystem(media_root: str | Path) -> dict[str, Any]:
    """Return what exists beneath media_root, retaining missing/empty states."""
    root = Path(media_root)
    categories: dict[str, Any] = {}

    for category in CATEGORIES:
        category_path = root / category
        category_exists = category_path.is_dir()
        entry: dict[str, Any] = {
            "exists": category_exists,
            "path": str(category_path.resolve()),
        }
        if category == "movies":
            folders = []
            direct_files = []
            if category_exists:
                entries = list(category_path.iterdir())
                direct_files = [
                    _media_file(p, category)
                    for p in sorted((item for item in entries if item.is_file()),
                                    key=lambda item: (item.name.casefold(), item.name))
                ]
                for folder_path in sorted((p for p in entries if p.is_dir()), key=_folder_sort_key):
                    children = sorted(
                        (p for p in folder_path.iterdir() if p.is_dir()),
                        key=lambda item: (item.name.casefold(), item.name),
                    )
                    files = [
                        _media_file(p, category)
                        for p in sorted(folder_path.iterdir(), key=lambda p: (p.name.casefold(), p.name))
                        if p.is_file()
                    ]
                    folder_record = {
                        "folder_id": folder_path.name,
                        "exists": True,
                        "path": str(folder_path.resolve()),
                        "files": files,
                    }
                    if children:
                        folder_record["folders"] = [_directory_record(child) for child in children]
                    folders.append(folder_record)
            entry["folders"] = folders
            entry["files"] = direct_files
        else:
            child_directories = sorted(
                (p for p in category_path.iterdir() if p.is_dir()),
                key=lambda item: (item.name.casefold(), item.name),
            ) if category_exists else []
            entry["folders"] = [_directory_record(child) for child in child_directories]
            entry["files"] = [
                _media_file(p, category)
                for p in sorted(category_path.iterdir(), key=lambda p: (p.name.casefold(), p.name))
                if p.is_file()
            ] if category_exists else []
        categories[category] = entry

    return {
        "source_type": "filesystem",
        "categories": categories,
    }
