"""Plan regular-song filler for a configured broadcast end-time target."""

from __future__ import annotations

import math
from typing import Any, Callable

try:
    from ..core.models import TimelineItem, format_wall_clock
    from .song_scheduler import SongSelectionState
except ImportError:  # source directory used directly on sys.path
    from core.models import TimelineItem, format_wall_clock
    from scheduling.song_scheduler import SongSelectionState

MIN_ENDING_SONG_COVERAGE_PERCENT = 60
MAX_ENDING_SONG_WARNING_COVERAGE_PERCENT = 80


class EndingSongCapacityError(RuntimeError):
    """Raised when the unique regular-song library is too short for ending filler."""

    code = "ENDINGSONG-001"


class EndingSongConfirmationRejected(RuntimeError):
    """Raised when the operator declines an ending-song capacity warning."""


def _clock_seconds(value: str) -> int:
    hours, minutes = (int(part) for part in value.split(":")[:2])
    seconds = int(value.split(":")[2]) if value.count(":") == 2 else 0
    return hours * 3600 + minutes * 60 + seconds


def target_elapsed_seconds(broadcast_start_time: str, end_time: str) -> int:
    """Resolve HH:MM target to its first occurrence after broadcast start."""
    start = _clock_seconds(broadcast_start_time)
    target = _clock_seconds(end_time)
    elapsed = (target - start) % (24 * 60 * 60)
    return elapsed or 24 * 60 * 60


def evaluate_end_time(plan: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Classify a prepared timeline as short, exact, or beyond its target."""
    start_time = plan["broadcast_start_time"]
    target_time = settings["broadcast"]["end_time"]
    target_elapsed = target_elapsed_seconds(start_time, target_time)
    current_elapsed = plan["total_broadcast_duration_seconds"]
    planned_finish = format_wall_clock(_clock_seconds(start_time) + current_elapsed)
    base = {
        "target_finish": target_time,
        "timeline_before_filler_finish": planned_finish,
        "target_elapsed_seconds": target_elapsed,
        "timeline_before_filler_elapsed_seconds": current_elapsed,
        "required_ending_duration_seconds": max(0, target_elapsed - current_elapsed),
        "planned_finish": planned_finish,
    }
    if current_elapsed < target_elapsed:
        base["status"] = "ending_songs_required"
    elif current_elapsed == target_elapsed:
        base["status"] = "exact_target"
    else:
        base["status"] = "overrun"
        base["overrun_duration_seconds"] = current_elapsed - target_elapsed
    return base


def assess_ending_song_capacity(
    songs: list[dict[str, Any]], required_duration_seconds: int | float
) -> dict[str, Any]:
    """Calculate unique regular-song library coverage for ending filler."""
    unique: dict[str, int | float] = {}
    for index, song in enumerate(songs, 1):
        path = song.get("path") or song.get("filename") or f"song-{index}"
        duration = song.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            continue
        unique.setdefault(str(path).replace("\\", "/").casefold(), duration)
    available = sum(unique.values())
    coverage = available / required_duration_seconds * 100
    return {
        "required_ending_duration_seconds": required_duration_seconds,
        "available_unique_song_duration_seconds": available,
        "unique_song_count": len(unique),
        "coverage_percentage": coverage,
    }


def schedule_ending_songs(
    plan: dict[str, Any],
    inventory: dict[str, Any],
    settings: dict[str, Any],
    confirm_warning: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Append regular songs to the target, or report exact/overrun without edits."""
    report = evaluate_end_time(plan, settings)
    if report["status"] != "ending_songs_required":
        plan["ending_schedule"] = report
        return report

    songs = inventory["categories"]["songs"].get("files", [])
    capacity = assess_ending_song_capacity(songs, report["required_ending_duration_seconds"])
    report.update(capacity)
    coverage = capacity["coverage_percentage"]
    if coverage < MIN_ENDING_SONG_COVERAGE_PERCENT:
        raise EndingSongCapacityError(
            f"Regular-song library coverage is {coverage:.2f}%, below the required 60% "
            f"for {capacity['required_ending_duration_seconds']} seconds of ending filler."
        )
    if coverage <= MAX_ENDING_SONG_WARNING_COVERAGE_PERCENT:
        report["warning_code"] = "ENDINGSONG-W001"
        if confirm_warning is None or not confirm_warning(report):
            raise EndingSongConfirmationRejected("Ending-song coverage warning declined.")

    state = SongSelectionState(songs, settings["songs"]["playback_order"])
    start_time_seconds = _clock_seconds(plan["broadcast_start_time"])
    cursor = plan["total_broadcast_duration_seconds"]
    required = report["required_ending_duration_seconds"]
    remaining = required
    ending_items: list[TimelineItem] = []
    while remaining > 0:
        song = state.take_next()
        if song is None:
            raise ValueError("No usable regular songs are available for ending filler.")
        source_duration = song["duration_seconds"]
        played_duration = min(source_duration, remaining)
        completion = "completed_naturally" if played_duration == source_duration else "hard_cut"
        item = TimelineItem(
            sequence=len(plan["items"]) + len(ending_items) + 1,
            media_type="song",
            source_filename=song["filename"],
            source_path=song["path"],
            movie_folder=None,
            segment_number=None,
            segment_count=None,
            logical_source_start_seconds=0,
            logical_source_end_seconds=played_duration,
            actual_playback_source_start_seconds=0,
            actual_playback_source_end_seconds=played_duration,
            source_duration_seconds=source_duration,
            elapsed_broadcast_start_seconds=cursor,
            elapsed_broadcast_end_seconds=cursor + played_duration,
            broadcast_duration_seconds=played_duration,
            wall_clock_start_timestamp=format_wall_clock(start_time_seconds + cursor),
            wall_clock_end_timestamp=format_wall_clock(start_time_seconds + cursor + played_duration),
            reason="Regular-song filler to configured broadcast end time.",
            song_id=song["path"],
            completion_status=completion,
            source_category="songs",
            schedule_block="broadcast-ending",
        )
        ending_items.append(item)
        cursor += played_duration
        remaining -= played_duration

    plan["items"].extend(ending_items)
    plan["total_broadcast_duration_seconds"] += required
    report["status"] = "ending_songs_scheduled"
    report["ending_song_count"] = len(ending_items)
    report["planned_finish"] = format_wall_clock(start_time_seconds + plan["total_broadcast_duration_seconds"])
    report["ending_song_names"] = [item.source_filename for item in ending_items]
    report["schedule_block"] = "broadcast-ending"
    plan["ending_schedule"] = report
    return report
