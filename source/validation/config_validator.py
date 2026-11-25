"""Focused validation for application scheduling configuration."""

from __future__ import annotations

import math
import re
from typing import Any


_TIME_PATTERN = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\Z")
_ELIGIBLE_START_MINUTES = {0, 15, 30, 45}
_MAX_START_TIME_TOLERANCE_SECONDS = 449


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def validate_movie_settings(settings: Any) -> list[str]:
    """Validate movie segmentation and wall-clock alignment settings."""
    if not isinstance(settings, dict) or not isinstance(settings.get("movie"), dict):
        return ["CONFIG-MOVIE-001: movie settings must be a JSON object."]
    movie = settings["movie"]
    errors: list[str] = []

    segment = movie.get("segment_duration_minutes")
    if not _is_number(segment) or not 10 <= segment <= 60:
        errors.append("CONFIG-MOVIE-002: movie.segment_duration_minutes must be between 10 and 60 minutes.")

    buffer_seconds = movie.get("playback_context_buffer_seconds")
    if not _is_number(buffer_seconds) or not 0 <= buffer_seconds <= 60:
        errors.append("CONFIG-MOVIE-003: movie.playback_context_buffer_seconds must be between 0 and 60 seconds.")

    minimum_last = movie.get("minimum_last_segment_duration_minutes")
    if not _is_number(minimum_last) or minimum_last < 10:
        errors.append("CONFIG-MOVIE-004: movie.minimum_last_segment_duration_minutes must be at least 10 minutes.")
    elif _is_number(segment) and minimum_last > segment:
        errors.append("CONFIG-MOVIE-005: movie.minimum_last_segment_duration_minutes cannot exceed segment_duration_minutes.")

    allowed = movie.get("allowed_start_minutes")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(isinstance(value, bool) or not isinstance(value, int) or value not in _ELIGIBLE_START_MINUTES for value in allowed)
        or len(set(allowed)) != len(allowed)
    ):
        errors.append("CONFIG-MOVIE-006: movie.allowed_start_minutes must be a non-empty list of unique values from 0, 15, 30, and 45.")

    tolerance = movie.get("start_time_tolerance_seconds")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, int)
        or not 0 <= tolerance <= _MAX_START_TIME_TOLERANCE_SECONDS
    ):
        errors.append(
            "CONFIG-MOVIE-007: movie.start_time_tolerance_seconds must be an integer from 0 to "
            f"{_MAX_START_TIME_TOLERANCE_SECONDS} seconds."
        )
    return errors


def validate_playback_settings(settings: Any) -> list[str]:
    """Validate ad and song ordering and playback limits."""
    if not isinstance(settings, dict):
        return ["CONFIG-PLAYBACK-001: application settings must be a JSON object."]
    errors: list[str] = []
    advertisement = settings.get("advertisement")
    if not isinstance(advertisement, dict):
        errors.append("CONFIG-AD-001: advertisement settings must be a JSON object.")
    else:
        if not isinstance(advertisement.get("playback_order"), str) or advertisement["playback_order"] not in {"random", "given"}:
            errors.append("CONFIG-AD-002: advertisement.playback_order must be 'random' or 'given'.")
        repeat_count = advertisement.get("repeat_count")
        if isinstance(repeat_count, bool) or not isinstance(repeat_count, int) or not 1 <= repeat_count <= 3:
            errors.append("CONFIG-AD-003: advertisement.repeat_count must be an integer from 1 to 3.")

    songs = settings.get("songs")
    if not isinstance(songs, dict):
        errors.append("CONFIG-SONG-001: songs settings must be a JSON object.")
    else:
        if not isinstance(songs.get("playback_order"), str) or songs["playback_order"] not in {"random", "given"}:
            errors.append("CONFIG-SONG-002: songs.playback_order must be 'random' or 'given'.")
        cut_early = songs.get("cut_early_seconds")
        if not _is_number(cut_early) or not 5 <= cut_early <= 15:
            errors.append("CONFIG-SONG-003: songs.cut_early_seconds must be between 5 and 15 seconds.")
    return errors


def validate_settings(settings: Any) -> list[str]:
    """Run all configuration checks before discovery or scheduling."""
    return (
        validate_movie_settings(settings)
        + validate_playback_settings(settings)
        + validate_morning_schedule(settings)
        + validate_broadcast_end_time(settings)
    )


def validate_morning_schedule(settings: Any) -> list[str]:
    """Validate schedule switches and the morning block when it is enabled."""
    errors: list[str] = []
    if not isinstance(settings, dict):
        return ["MORNING_SETTINGS_MISSING: The application settings object is missing or invalid."]

    toggles = settings.get("schedule_toggles", {})
    if not isinstance(toggles, dict):
        return ["SCHEDULE_TOGGLES_INVALID: schedule_toggles must be a JSON object."]
    for key in (
        "morning_block_enabled",
        "movie_gap_song_filler_enabled",
        "broadcast_ending_song_filler_enabled",
    ):
        if key in toggles and not isinstance(toggles[key], bool):
            errors.append(f"SCHEDULE_TOGGLE_INVALID: schedule_toggles.{key} must be true or false.")
    if errors:
        return errors

    if not isinstance(settings.get("morning_schedule"), dict):
        return ["MORNING_SETTINGS_MISSING: The morning_schedule settings section is missing or invalid."]
    morning = settings["morning_schedule"]
    durations: list[int] = []
    for key, label in (("dev_songs_duration_minutes", "devotional songs"), ("songs_duration_minutes", "regular songs")):
        value = morning.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 180:
            errors.append(f"CONFIG-MORNING-001: {label.title()} duration must be a whole number from 0 to 180 minutes.")
        else:
            durations.append(value)
    if len(durations) == 2 and sum(durations) != 180:
        dev_duration = morning["dev_songs_duration_minutes"]
        regular_duration = morning["songs_duration_minutes"]
        errors.append(
            "MORNING_DURATION_TOTAL_INVALID: "
            f"Devotional songs ({dev_duration:g} min) + regular songs ({regular_duration:g} min) "
            f"= {sum(durations):g} min. Expected exactly 180 min."
        )

    transition_gap = morning.get("transition_black_duration_seconds")
    if (
        isinstance(transition_gap, bool)
        or not isinstance(transition_gap, (int, float))
        or not math.isfinite(transition_gap)
        or not 10 <= transition_gap <= 20
    ):
        errors.append("CONFIG-MORNING-003: morning_schedule.transition_black_duration_seconds must be between 10 and 20 seconds.")
    return errors


def validate_broadcast_end_time(settings: Any) -> list[str]:
    """Validate the single configured 24-hour broadcast finish target."""
    if not isinstance(settings, dict) or not isinstance(settings.get("broadcast"), dict):
        return ["BROADCAST_END_TIME_INVALID: broadcast.end_time is missing; expected 24-hour HH:MM format."]
    end_time = settings["broadcast"].get("end_time")
    if not isinstance(end_time, str) or not _TIME_PATTERN.fullmatch(end_time):
        return [f"CONFIG-BROADCAST-001: broadcast.end_time {end_time!r} must use 24-hour HH:MM format (00:00 through 23:59)."]

    toggles = settings.get("schedule_toggles", {})
    start_time = "09:00"
    if isinstance(toggles, dict) and toggles.get("morning_block_enabled", True):
        morning = settings.get("morning_schedule", {})
        candidate = morning.get("start_time") if isinstance(morning, dict) else None
        # The morning start setting has no format rule yet. Compare it only
        # when it happens to be parseable; other checks leave it untouched.
        if isinstance(candidate, str) and _TIME_PATTERN.fullmatch(candidate):
            start_time = candidate
        else:
            start_time = "06:00"
    end_seconds = int(end_time[:2]) * 3600 + int(end_time[3:]) * 60
    start_seconds = int(start_time[:2]) * 3600 + int(start_time[3:]) * 60
    if end_time != "00:00" and end_seconds <= start_seconds:
        return [
            "CONFIG-BROADCAST-002: broadcast.end_time must be at or after the broadcast start "
            "and no later than midnight (00:00)."
        ]
    return []
