"""Advertisement inventory checks for simulated JSON inventory only."""

from __future__ import annotations

import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

MIN_AD_DURATION_SECONDS = 5
MAX_AD_DURATION_SECONDS = 5 * 60
WARNING_LOAD_PERCENT = 15
MAX_LOAD_PERCENT = 30
ALLOWED_AD_EXTENSIONS = {".mp4", ".mkv"}


def _error(code: int, message: str) -> str:
    return f"MEDIAAD-{code:03d}: {message}"


def validate_advertisements(inventory: Any, settings: Any) -> dict[str, Any]:
    """Return ad errors and load details without touching referenced media paths.

    Warning-range load is returned separately so startup can request explicit
    operator confirmation before discovery or simulation proceeds.
    """
    errors: list[str] = []
    categories = inventory.get("categories", inventory) if isinstance(inventory, dict) else None
    if not isinstance(categories, dict):
        return {"errors": [_error(1, "Media inventory categories must be a JSON object.")], "warning": None}
    ads = categories.get("ads", {"files": []})
    if not isinstance(ads, dict):
        return {"errors": [_error(2, "ADVERTISEMENT collection is not an object.")], "warning": None}

    # JSON inventory uses folders for any simulated subdirectories. Files are
    # validated in place; folder contents are never followed or opened.
    folders = ads.get("folders", ads.get("subfolders", []))
    if not isinstance(folders, list):
        errors.append(_error(3, "ADVERTISEMENT collection subfolders metadata must be a list."))
    elif folders:
        for folder in folders:
            name = folder.get("folder_id", folder.get("name", "unnamed")) if isinstance(folder, dict) else str(folder)
            errors.append(_error(4, f"Advertisement collection contains a subfolder named {name}."))

    files = ads.get("files", [])
    if not isinstance(files, list):
        errors.append(_error(5, "ADVERTISEMENT collection files metadata must be a list."))
        files = []

    total_seconds: int | float = 0
    valid_duration_total = True
    for index, ad in enumerate(files, 1):
        if not isinstance(ad, dict):
            errors.append(_error(6, f"Advertisement entry {index} is not a file record."))
            valid_duration_total = False
            continue
        filename = ad.get("filename")
        label = filename if isinstance(filename, str) and filename.strip() else f"advertisement entry {index}"
        if not isinstance(filename, str) or not filename.strip():
            errors.append(_error(7, f"{label} has no valid filename."))
        else:
            suffix = PureWindowsPath(filename).suffix.lower() or PurePosixPath(filename).suffix.lower()
            if suffix not in ALLOWED_AD_EXTENSIONS:
                errors.append(_error(8, f"{filename} has an unsupported file format. Allowed formats: MP4, MKV."))
        if ad.get("folders") or ad.get("children"):
            errors.append(_error(9, f"{label} contains a nested directory; advertisements must be directly inside the collection."))
        if "duration_seconds" not in ad:
            errors.append(_error(10, f"{label} is missing duration metadata."))
            valid_duration_total = False
            continue
        duration = ad["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            errors.append(_error(11, f"{label} has invalid duration metadata; duration must be a positive number of seconds."))
            valid_duration_total = False
            continue
        if duration < MIN_AD_DURATION_SECONDS:
            errors.append(_error(12, f"{label} duration is {duration:g} seconds. Minimum allowed duration is {MIN_AD_DURATION_SECONDS} seconds."))
        elif duration > MAX_AD_DURATION_SECONDS:
            errors.append(_error(13, f"{label} duration is {duration:g} seconds. Maximum allowed duration is {MAX_AD_DURATION_SECONDS // 60} minutes."))
        total_seconds += duration

    ad_settings = settings.get("ads", settings.get("advertisement", {})) if isinstance(settings, dict) else {}
    movie_settings = settings.get("movie", {}) if isinstance(settings, dict) else {}
    if not isinstance(ad_settings, dict) or not isinstance(movie_settings, dict):
        return {"errors": errors + [_error(14, "Advertisement and movie settings must be JSON objects.")], "warning": None}
    repeat_count = ad_settings.get("repeat_count")
    segment_minutes = movie_settings.get("segment_duration_minutes")
    if isinstance(repeat_count, bool) or not isinstance(repeat_count, (int, float)) or not math.isfinite(repeat_count) or repeat_count < 0:
        errors.append(_error(15, "Advertisement repeat_count setting is missing or invalid."))
    if isinstance(segment_minutes, bool) or not isinstance(segment_minutes, (int, float)) or not math.isfinite(segment_minutes) or segment_minutes <= 0:
        errors.append(_error(16, "Movie segment_duration_minutes setting is missing or invalid."))
    if errors or not valid_duration_total:
        return {"errors": errors, "warning": None}

    playback_seconds = total_seconds * repeat_count
    load_percent = playback_seconds / (segment_minutes * 60) * 100
    details = {
        "total_ad_duration_seconds": total_seconds,
        "repeat_count": repeat_count,
        "total_playback_duration_seconds": playback_seconds,
        "movie_segment_duration_seconds": segment_minutes * 60,
        "load_percent": load_percent,
    }
    if load_percent > MAX_LOAD_PERCENT:
        errors.append(_error(17, f"Advertisement load is {load_percent:.2f}%, exceeding the maximum permitted 30%."))
        return {"errors": errors, "warning": None, "details": details}
    warning = details if load_percent >= WARNING_LOAD_PERCENT else None
    return {"errors": errors, "warning": warning, "details": details}
