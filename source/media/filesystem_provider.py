"""Filesystem-backed media discovery. No media probing or validation is done."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

CATEGORIES = ("movies", "dev-songs", "movie-songs", "songs", "ads")


def _folder_sort_key(path: Path) -> tuple[Any, ...]:
    """Put numbered movie folders in numeric order while retaining other names."""
    match = re.fullmatch(r"m(\d+)", path.name, flags=re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), path.name.casefold())
    return (1, path.name.casefold(), path.name)


def _media_file(path: Path, category: str) -> dict[str, Any]:
    return {
        "filename": path.name,
        "path": str(path.resolve()),
        "duration_seconds": None,
        "category": category,
        "source_type": "filesystem",
    }


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
            if category_exists:
                for folder_path in sorted(
                    (p for p in category_path.iterdir() if p.is_dir()),
                    key=_folder_sort_key,
                ):
                    files = [
                        _media_file(p, category)
                        for p in sorted(folder_path.iterdir(), key=lambda p: (p.name.casefold(), p.name))
                        if p.is_file()
                    ]
                    folders.append({
                        "folder_id": folder_path.name,
                        "exists": True,
                        "path": str(folder_path.resolve()),
                        "files": files,
                    })
            entry["folders"] = folders
        else:
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
