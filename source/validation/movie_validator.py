"""Movie-only structural and duration checks for simulated JSON inventory."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

MAX_MOVIES = 6
MIN_MOVIE_DURATION_SECONDS = 30 * 60
MAX_MOVIE_DURATION_SECONDS = 4 * 60 * 60
ALLOWED_MOVIE_EXTENSIONS = {".mp4", ".mkv"}

# The current normalized inventory calls folders m1, m2, etc. The verbose
# movie1 form is also accepted for inventory producers using the brief's names.
_FOLDER_NAME = re.compile(r"(?:m|movie)([1-9][0-9]*)\Z")
_MOVIES_METADATA_KEYS = {"exists", "path", "folders", "files"}
_FOLDER_METADATA_KEYS = {"folder_id", "exists", "path", "files"}


def _error(code: int, message: str) -> str:
    return f"MEDIAMOVIE-{code:03d}: {message}"


def _duration_description(value: int | float) -> str:
    if float(value).is_integer():
        seconds = int(value)
        if seconds % 3600 == 0:
            hours = seconds // 3600
            return f"{hours} hour" + ("s" if hours != 1 else "")
        if seconds % 60 == 0:
            minutes = seconds // 60
            return f"{minutes} minute" + ("s" if minutes != 1 else "")
        return f"{seconds} seconds"
    return f"{value:g} seconds"


def _movie_collection(inventory: Any) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(inventory, dict):
        return None, [_error(1, "Media inventory must be a JSON object.")]
    categories = inventory.get("categories", inventory)
    if not isinstance(categories, dict):
        return None, [_error(2, "Media inventory categories must be a JSON object.")]
    movies = categories.get("movies")
    if not isinstance(movies, dict):
        return None, [_error(3, "MOVIES collection is missing or is not an object.")]
    return movies, errors


def validate_movies(inventory: Any) -> list[str]:
    """Return fatal movie inventory errors; an empty list means validation passed.

    This inspects JSON values only. It never opens referenced media paths.
    The input may be the stored inventory JSON object or the normalized
    provider result, since both use a categories/movies/folders structure.
    """
    movies, errors = _movie_collection(inventory)
    if movies is None:
        return errors

    unexpected_collection_keys = set(movies) - _MOVIES_METADATA_KEYS
    for key in sorted(unexpected_collection_keys):
        errors.append(_error(4, f"Unexpected entry {key!r} directly inside the MOVIES collection."))

    direct_files = movies.get("files", [])
    if direct_files not in (None, []):
        errors.append(_error(5, "MOVIES collection contains a file directly; movie files must be inside a numbered movie folder."))

    raw_folders = movies.get("folders", [])
    if not isinstance(raw_folders, list):
        errors.append(_error(6, "MOVIES collection 'folders' must be a list of numbered movie folders."))
        return errors
    if not raw_folders:
        errors.append(_error(7, "MOVIES collection is empty; at least one occupied numbered movie folder is required."))
        return errors

    folder_entries: dict[int, tuple[str, list[Any]]] = {}
    occupied_numbers: set[int] = set()

    for index, folder in enumerate(raw_folders):
        if not isinstance(folder, dict):
            errors.append(_error(8, f"MOVIES entry {index + 1} is not a numbered movie folder."))
            continue
        folder_name = folder.get("folder_id")
        if not isinstance(folder_name, str):
            errors.append(_error(9, f"MOVIES entry {index + 1} has no valid folder identifier; expected m1 or movie1 format."))
            continue
        match = _FOLDER_NAME.fullmatch(folder_name)
        if not match:
            errors.append(_error(10, f"Unexpected movie folder name {folder_name!r}; expected lowercase m1 through m{MAX_MOVIES} (or movie1 through movie{MAX_MOVIES})."))
            continue

        number = int(match.group(1))
        display_name = f"MOVIE{number}"
        if number > MAX_MOVIES:
            errors.append(_error(11, f"{display_name} exceeds the maximum permitted movie folder number, MOVIE{MAX_MOVIES}."))
            continue
        if number in folder_entries:
            errors.append(_error(12, f"Duplicate movie folder number {display_name}; each numbered folder may appear only once."))
            continue

        unknown_folder_keys = set(folder) - _FOLDER_METADATA_KEYS - {"folders"}
        for key in sorted(unknown_folder_keys):
            errors.append(_error(13, f"Unexpected entry {key!r} inside {display_name}."))
        nested = folder.get("folders", [])
        if nested:
            errors.append(_error(14, f"Nested folders are not permitted inside {display_name}."))

        files = folder.get("files", [])
        if not isinstance(files, list):
            errors.append(_error(15, f"{display_name} contents must be a list of files."))
            files = []
        folder_entries[number] = (display_name, files)
        if files:
            occupied_numbers.add(number)
        if len(files) > 1:
            errors.append(_error(16, f"{display_name} contains {len(files)} movie files; exactly one file is allowed in an occupied folder."))

        for file_index, media_file in enumerate(files):
            if not isinstance(media_file, dict):
                errors.append(_error(17, f"Entry {file_index + 1} inside {display_name} is not a movie file record."))
                continue
            filename = media_file.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                errors.append(_error(18, f"A file inside {display_name} has no valid filename."))
                filename = f"file {file_index + 1}"
            suffix = PureWindowsPath(filename).suffix.lower() or PurePosixPath(filename).suffix.lower()
            if suffix not in ALLOWED_MOVIE_EXTENSIONS:
                errors.append(_error(19,
                    f"Unsupported file format: {filename} in {display_name}; expected .mp4 or .mkv."
                ))
            if media_file.get("folders") or media_file.get("children"):
                errors.append(_error(20, f"{filename} in {display_name} contains nested entries; nested folders are not permitted."))

            if "duration_seconds" not in media_file:
                errors.append(_error(21, f"Duration metadata is missing for {filename} in {display_name}."))
                continue
            duration = media_file["duration_seconds"]
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration <= 0
            ):
                errors.append(_error(22, f"Duration metadata for {filename} in {display_name} is invalid; it must be a positive number of seconds."))
                continue
            if duration < MIN_MOVIE_DURATION_SECONDS:
                errors.append(_error(23,
                    f"{filename} in {display_name} duration is {_duration_description(duration)}; "
                    f"minimum allowed is {_duration_description(MIN_MOVIE_DURATION_SECONDS)}."
                ))
            elif duration > MAX_MOVIE_DURATION_SECONDS:
                errors.append(_error(24,
                    f"{filename} in {display_name} duration is {_duration_description(duration)}; "
                    f"maximum allowed is {_duration_description(MAX_MOVIE_DURATION_SECONDS)}."
                ))

    if not occupied_numbers:
        errors.append(_error(25, "MOVIES collection contains no movie files; at least one occupied movie folder is required."))

    encountered_empty: int | None = None
    for number in range(1, MAX_MOVIES + 1):
        if number not in occupied_numbers:
            if encountered_empty is None:
                encountered_empty = number
        elif encountered_empty is not None:
            errors.append(_error(26,
                f"MOVIE{encountered_empty} is empty but MOVIE{number} contains a movie; "
                "occupied movie folders must be sequential with no empty folder before them."
            ))
            break

    return errors
