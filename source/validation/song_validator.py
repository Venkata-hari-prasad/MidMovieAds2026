"""Validation for morning and movie-filler pools in normalized inventories."""

from __future__ import annotations

import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

try:
    from ..scheduling.scheduler import maximum_movie_start_wait_seconds
except ImportError:  # source directory used directly on sys.path
    from scheduling.scheduler import maximum_movie_start_wait_seconds

MIN_SONG_DURATION_SECONDS = 30
MAX_SONG_DURATION_SECONDS = 30 * 60
MIN_MOVIE_SONG_COVERAGE_PERCENT = 60
WARNING_MOVIE_SONG_COVERAGE_PERCENT = 80
MIN_MORNING_SONG_COVERAGE_PERCENT = 60
MAX_MORNING_SONG_WARNING_COVERAGE_PERCENT = 80
ALLOWED_SONG_EXTENSIONS = {".mp4", ".mkv"}

_COLLECTIONS = (
    ("dev-songs", "MEDIADEVSONG", "DEVOTIONAL SONG"),
    ("songs", "MEDIAMORNINGSONG", "REGULAR SONG"),
    ("movie-songs", "MEDIAMOVIESONG", "MOVIE SONG"),
)


def _error(prefix: str, code: int, message: str) -> str:
    return f"{prefix}-{code:03d}: {message}"


def _collection_records(inventory: Any, collection: str, prefix: str, label: str,
                        errors: list[str]) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
    categories = inventory.get("categories", inventory) if isinstance(inventory, dict) else None
    category = categories.get(collection) if isinstance(categories, dict) else None
    if not isinstance(category, dict):
        errors.append(_error(prefix, 1, f"{label} collection is missing or is not an object."))
        return [], {}
    if category.get("exists", True) is False:
        errors.append(_error(prefix, 2, f"{label} collection directory is missing."))
    nested = category.get("folders", category.get("subfolders", []))
    if not isinstance(nested, list):
        errors.append(_error(prefix, 3, f"{label} collection subfolder metadata must be a list."))
    elif nested:
        errors.append(_error(prefix, 3, f"{label} collection must contain song files directly, not subfolders."))
    files = category.get("files")
    if not isinstance(files, list):
        errors.append(_error(prefix, 4, f"{label} collection files metadata must be a list."))
        return [], {}

    seen: set[str] = set()
    unique_durations: dict[str, int | float] = {}
    for index, record in enumerate(files, 1):
        if not isinstance(record, dict):
            errors.append(_error(prefix, 5, f"Entry {index} in {label} is not a song file record."))
            continue
        filename = record.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            errors.append(_error(prefix, 6, f"Song entry {index} in {label} has no valid filename."))
            continue
        extension = PureWindowsPath(filename).suffix.lower() or PurePosixPath(filename).suffix.lower()
        if extension not in ALLOWED_SONG_EXTENSIONS:
            errors.append(_error(prefix, 7, f"{filename} has an unsupported format; allowed formats are MP4 and MKV."))

        path = record.get("path", filename)
        if not isinstance(path, str) or not path.strip():
            errors.append(_error(prefix, 8, f"{filename} has an invalid media path."))
            identity = filename.casefold()
        else:
            identity = path.replace("\\", "/").casefold()
        filename_identity = filename.replace("\\", "/").casefold()
        if identity in seen or filename_identity in seen:
            errors.append(_error(prefix, 9, f"Duplicate song entry {filename} in {label}; entries must refer to unique media."))
        seen.update((identity, filename_identity))
        if record.get("folders") or record.get("children"):
            errors.append(_error(prefix, 10, f"{filename} contains nested entries; song collections must be flat."))
        if "duration_seconds" not in record:
            errors.append(_error(prefix, 11, f"{filename} is missing duration metadata."))
            continue
        duration = record["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            errors.append(_error(prefix, 12, f"{filename} has invalid duration metadata; expected a positive number of seconds."))
            continue
        if duration < MIN_SONG_DURATION_SECONDS:
            errors.append(_error(prefix, 13, f"{filename} duration is {duration:g} seconds; minimum allowed is {MIN_SONG_DURATION_SECONDS} seconds."))
        elif duration > MAX_SONG_DURATION_SECONDS:
            errors.append(_error(prefix, 14, f"{filename} duration is {duration:g} seconds; maximum allowed is 30 minutes."))
        # Only count a repeated media identity once in capacity totals.
        unique_durations.setdefault(identity, duration)
    return files, unique_durations


def validate_songs(inventory: Any, settings: Any) -> dict[str, Any]:
    """Validate only song pools used by the enabled schedule blocks."""
    errors: list[str] = []
    categories = inventory.get("categories", inventory) if isinstance(inventory, dict) else None
    if not isinstance(categories, dict):
        return {"errors": [
            _error("MEDIADEVSONG", 1, "Media inventory categories must be a JSON object."),
            _error("MEDIAMORNINGSONG", 1, "Media inventory categories must be a JSON object."),
            _error("MEDIAMOVIESONG", 1, "Media inventory categories must be a JSON object."),
        ], "warnings": [], "warning": None}

    toggles = settings.get("schedule_toggles", {}) if isinstance(settings, dict) else {}
    if not isinstance(toggles, dict):
        return {"errors": [_error("MEDIASONG", 17, "Schedule toggles must be a JSON object.")], "warnings": [], "warning": None}
    morning_enabled = toggles.get("morning_block_enabled", True)
    movie_gap_enabled = toggles.get("movie_gap_song_filler_enabled", True)
    ending_enabled = toggles.get("broadcast_ending_song_filler_enabled", True)

    collections_to_check: set[str] = set()
    if morning_enabled:
        collections_to_check.update(("dev-songs", "songs"))
    elif ending_enabled:
        collections_to_check.add("songs")
    if movie_gap_enabled:
        collections_to_check.add("movie-songs")

    collections: dict[str, dict[str, int | float]] = {}
    for collection, prefix, label in _COLLECTIONS:
        if collection in collections_to_check:
            _, collections[collection] = _collection_records(inventory, collection, prefix, label, errors)
    if errors:
        return {"errors": errors, "warnings": [], "warning": None}
    if not collections_to_check:
        return {
            "errors": [], "warnings": [], "warning": None,
            "warning_code": None, "details": None, "skipped": True,
        }

    warnings: list[dict[str, Any]] = []
    movie_details: dict[str, Any] | None = None
    if morning_enabled:
        morning = settings.get("morning_schedule") if isinstance(settings, dict) else None
        if not isinstance(morning, dict):
            return {"errors": [_error("MEDIAMORNINGSONG", 15, "Morning schedule settings are missing; cannot calculate song capacity.")], "warnings": [], "warning": None}
        transition_seconds = morning.get("transition_black_duration_seconds")
        if isinstance(transition_seconds, bool) or not isinstance(transition_seconds, (int, float)) or not math.isfinite(transition_seconds) or transition_seconds < 0:
            return {"errors": [_error("MEDIAMORNINGSONG", 15, "Morning transition black duration is missing or invalid; cannot calculate song capacity.")], "warnings": [], "warning": None}

        for collection, prefix, setting_key, label in (
            ("dev-songs", "MEDIADEVSONG", "dev_songs_duration_minutes", "Devotional songs"),
            ("songs", "MEDIAMORNINGSONG", "songs_duration_minutes", "Regular songs"),
        ):
            configured_minutes = morning.get(setting_key)
            if isinstance(configured_minutes, bool) or not isinstance(configured_minutes, (int, float)) or not math.isfinite(configured_minutes) or configured_minutes <= 0:
                errors.append(_error(prefix, 15, f"Configured {label.lower()} duration is missing or invalid."))
                continue
            required = configured_minutes * 60 - transition_seconds
            available = sum(collections[collection].values())
            coverage = available / required * 100
            details = {
                "collection": collection,
                "label": label,
                "required_duration_seconds": required,
                "available_unique_duration_seconds": available,
                "coverage_percentage": coverage,
            }
            if coverage < MIN_MORNING_SONG_COVERAGE_PERCENT:
                errors.append(_error(prefix, 16, f"{label} library coverage is {coverage:.2f}%, below the required minimum of 60% of its configured {configured_minutes:g}-minute block."))
            elif coverage <= MAX_MORNING_SONG_WARNING_COVERAGE_PERCENT:
                warnings.append({"code": f"{prefix}-W001", "details": details})

    if movie_gap_enabled:
        movie_settings = settings.get("movie") if isinstance(settings, dict) else None
        if not isinstance(movie_settings, dict):
            errors.append(_error("MEDIAMOVIESONG", 15, "Movie scheduling settings are missing; cannot calculate movie-song capacity."))
        else:
            try:
                max_gap = maximum_movie_start_wait_seconds(
                    movie_settings["allowed_start_minutes"],
                    movie_settings["start_time_tolerance_seconds"],
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append(_error("MEDIAMOVIESONG", 15, "Movie start settings are missing or invalid; cannot calculate movie-song capacity reliably."))
            else:
                available = sum(collections["movie-songs"].values())
                coverage = 100.0 if max_gap == 0 else available / max_gap * 100
                movie_details = {
                    "collection": "movie-songs",
                    "label": "Movie songs",
                    "maximum_filler_gap_seconds": max_gap,
                    "total_unique_movie_song_duration_seconds": available,
                    "coverage_percentage": coverage,
                }
                if coverage < MIN_MOVIE_SONG_COVERAGE_PERCENT:
                    errors.append(_error("MEDIAMOVIESONG", 16, f"Movie-song library coverage is {coverage:.2f}%, below the required minimum of 60% of the maximum filler gap."))
                elif coverage < WARNING_MOVIE_SONG_COVERAGE_PERCENT:
                    warnings.append({"code": "MEDIAMOVIESONG-W001", "details": movie_details})

    if errors:
        warnings = []
    movie_warning = next((warning for warning in warnings if warning["details"]["collection"] == "movie-songs"), None)
    return {
        "errors": errors,
        "warnings": warnings,
        # Retained for current callers/tests that consume the movie-song result.
        "warning": movie_warning["details"] if movie_warning else None,
        "warning_code": movie_warning["code"] if movie_warning else None,
        "details": movie_details,
    }
