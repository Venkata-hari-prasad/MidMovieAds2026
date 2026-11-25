"""JSON-backed simulated media discovery with a normalized provider result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATEGORIES = ("movies", "dev-songs", "movie-songs", "songs", "ads")


class InventoryFormatError(ValueError):
    """Raised when the inventory JSON cannot be normalized safely."""


def _duration(value: Any, where: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise InventoryFormatError(f"{where}.duration_seconds must be a non-negative number or null.")
    return value


def _file_record(raw: Any, category: str, source_type: str, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InventoryFormatError(f"{where} must be an object.")
    filename = raw.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise InventoryFormatError(f"{where}.filename must be a non-empty string.")
    path = raw.get("path", filename)
    if not isinstance(path, str) or not path.strip():
        raise InventoryFormatError(f"{where}.path must be a non-empty string.")
    record = {
        "filename": filename,
        "path": path,
        "duration_seconds": _duration(raw.get("duration_seconds"), where),
        "category": category,
        "source_type": source_type,
    }
    # Preserve structural metadata consumed by the shared validators.
    for key in ("folders", "children"):
        if key in raw:
            record[key] = raw[key]
    return record


def discover_json(inventory_path: str | Path) -> dict[str, Any]:
    """Load and normalize an inventory file without checking simulated paths."""
    path = Path(inventory_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Media inventory JSON not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryFormatError(f"Malformed inventory JSON at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise InventoryFormatError("Inventory root must be a JSON object.")
    raw_categories = raw.get("categories", raw)
    if not isinstance(raw_categories, dict):
        raise InventoryFormatError("Inventory 'categories' must be a JSON object.")

    categories: dict[str, Any] = {}
    source_type = "json"
    for category in CATEGORIES:
        if category not in raw_categories:
            categories[category] = {"exists": False, "path": None, "folders": [], "files": []}
            continue
        raw_category = raw_categories[category]
        if not isinstance(raw_category, dict):
            raise InventoryFormatError(f"Category {category!r} must be an object.")
        category_exists = raw_category.get("exists", True)
        if not isinstance(category_exists, bool):
            raise InventoryFormatError(f"Category {category!r}.exists must be a boolean.")
        entry: dict[str, Any] = {"exists": category_exists, "path": raw_category.get("path")}

        if category == "movies":
            raw_folders = raw_category.get("folders", [])
            if not isinstance(raw_folders, list):
                raise InventoryFormatError("Category 'movies'.folders must be a list.")
            folders = []
            for index, folder in enumerate(raw_folders):
                where = f"movies.folders[{index}]"
                if not isinstance(folder, dict):
                    raise InventoryFormatError(f"{where} must be an object.")
                folder_id = folder.get("folder_id")
                if not isinstance(folder_id, str) or not folder_id.strip():
                    raise InventoryFormatError(f"{where}.folder_id must be a non-empty string.")
                folder_exists = folder.get("exists", True)
                if not isinstance(folder_exists, bool):
                    raise InventoryFormatError(f"{where}.exists must be a boolean.")
                raw_files = folder.get("files", [])
                if not isinstance(raw_files, list):
                    raise InventoryFormatError(f"{where}.files must be a list.")
                folders.append({
                    "folder_id": folder_id,
                    "exists": folder_exists,
                    "path": folder.get("path", folder_id),
                    "files": [_file_record(item, category, source_type, f"{where}.files[{i}]")
                              for i, item in enumerate(raw_files)],
                    **({"folders": folder["folders"]} if "folders" in folder else {}),
                })
            raw_direct_files = raw_category.get("files", [])
            if not isinstance(raw_direct_files, list):
                raise InventoryFormatError("Category 'movies'.files must be a list.")
            entry["folders"] = folders
            entry["files"] = [_file_record(item, category, source_type, f"movies.files[{i}]")
                              for i, item in enumerate(raw_direct_files)]
        else:
            raw_files = raw_category.get("files", [])
            if not isinstance(raw_files, list):
                raise InventoryFormatError(f"Category {category!r}.files must be a list.")
            entry["files"] = [_file_record(item, category, source_type, f"{category}.files[{i}]")
                              for i, item in enumerate(raw_files)]
            entry["folders"] = raw_category.get("folders", raw_category.get("subfolders", []))
        categories[category] = entry

    return {"source_type": source_type, "categories": categories}
