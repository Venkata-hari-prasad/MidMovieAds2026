"""Focused validation for application scheduling configuration."""

from __future__ import annotations

import math
import re
from typing import Any


_TIME_PATTERN = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\Z")


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
    if errors or not toggles.get("morning_block_enabled", True):
        return errors

    if not isinstance(settings.get("morning_schedule"), dict):
        return ["MORNING_SETTINGS_MISSING: The morning_schedule settings section is missing or invalid."]
    morning = settings["morning_schedule"]
    durations: list[int | float] = []
    for key, label in (("dev_songs_duration_minutes", "devotional songs"), ("songs_duration_minutes", "regular songs")):
        value = morning.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            errors.append(f"MORNING_DURATION_VALUE_INVALID: {label.title()} duration must be a positive number of minutes.")
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
        or transition_gap < 0
        or (len(durations) == 2 and transition_gap >= min(durations) * 60)
    ):
        errors.append("MORNING_TRANSITION_GAP_INVALID: transition_black_duration_seconds must be non-negative and shorter than both morning sections.")

    start_time = morning.get("start_time")
    match = _TIME_PATTERN.fullmatch(start_time) if isinstance(start_time, str) else None
    if not match:
        errors.append("MORNING_START_TIME_INVALID: start_time must use 24-hour HH:MM format.")
    elif len(durations) == 2:
        start_seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60
        if start_seconds + sum(durations) * 60 != 9 * 3600:
            errors.append("MORNING_BLOCK_END_INVALID: The configured morning block must end at the existing 09:00 movie start.")
    return errors


def validate_broadcast_end_time(settings: Any) -> list[str]:
    """Validate the single configured 24-hour broadcast finish target."""
    if not isinstance(settings, dict) or not isinstance(settings.get("broadcast"), dict):
        return ["BROADCAST_END_TIME_INVALID: broadcast.end_time is missing; expected 24-hour HH:MM format."]
    end_time = settings["broadcast"].get("end_time")
    if not isinstance(end_time, str) or not _TIME_PATTERN.fullmatch(end_time):
        return [f"BROADCAST_END_TIME_INVALID: broadcast.end_time {end_time!r} must use 24-hour HH:MM format."]
    return []
