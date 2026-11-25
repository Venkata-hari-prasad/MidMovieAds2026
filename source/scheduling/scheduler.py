"""Build movie segments, inter-segment ads, wall-clock starts, and waiting gaps."""

from __future__ import annotations

import math
import random
import re
from typing import Any

try:
    from ..core.models import TimelineItem, format_wall_clock
except ImportError:  # source directory used directly on sys.path
    from core.models import TimelineItem, format_wall_clock


def _movie_folder_order(folder_id: str) -> tuple[Any, ...]:
    match = re.fullmatch(r"movie(\d+)", folder_id, flags=re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), folder_id.casefold())
    return (1, folder_id.casefold(), folder_id)


def _parse_wall_clock(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _eligible_times(minutes: list[int], days: int = 3) -> list[int]:
    return [
        day * 86400 + hour * 3600 + minute * 60
        for day in range(days)
        for hour in range(24)
        for minute in minutes
    ]


def choose_movie_start(
    ready_time_seconds: int | float,
    allowed_minutes: list[int],
    tolerance_seconds: int | float,
) -> tuple[int | float, int | float]:
    """Return (actual start, nearest eligible mark) for the next movie.

    If the media is ready within tolerance on either side of an eligible mark,
    start immediately. Otherwise wait for the following mark.
    """
    marks = _eligible_times(allowed_minutes)
    nearest = min(marks, key=lambda mark: (abs(mark - ready_time_seconds), mark))
    if abs(nearest - ready_time_seconds) <= tolerance_seconds:
        return ready_time_seconds, nearest
    following = next((mark for mark in marks if mark > ready_time_seconds), None)
    if following is None:
        raise ValueError("No later eligible movie-start mark is available.")
    return following, following


def maximum_movie_start_wait_seconds(
    allowed_minutes: list[int], tolerance_seconds: int | float
) -> int | float:
    """Return the largest possible positive wait under choose_movie_start().

    A ready time within tolerance of the nearest mark starts immediately. If an
    interval's tolerance windows overlap, no waiting is possible there;
    otherwise the wait approaches ``interval - tolerance`` just after the
    prior mark's tolerance boundary.
    This is the supremum for a strict tolerance boundary, matching the start
    selection rules rather than assuming a rounded hour/half-hour gap.
    """
    if not isinstance(allowed_minutes, list) or not allowed_minutes:
        raise ValueError("allowed_start_minutes must be a non-empty list.")
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 60 for value in allowed_minutes):
        raise ValueError("allowed_start_minutes must contain integer minute marks from 0 through 59.")
    marks = sorted(set(allowed_minutes))
    if len(marks) != len(allowed_minutes):
        raise ValueError("allowed_start_minutes cannot contain duplicates.")
    if isinstance(tolerance_seconds, bool) or not isinstance(tolerance_seconds, (int, float)) or not math.isfinite(tolerance_seconds) or tolerance_seconds < 0:
        raise ValueError("start_time_tolerance_seconds must be a non-negative number.")
    spacings = [
        ((marks[(index + 1) % len(marks)] - mark) % 60 or 60) * 60
        for index, mark in enumerate(marks)
    ]
    return max(
        max(0, spacing - tolerance_seconds) if 2 * tolerance_seconds < spacing else 0
        for spacing in spacings
    )


def _segments(
    duration: int | float,
    cut_seconds: int,
    minimum_final_seconds: int,
) -> list[tuple[int | float, int | float]]:
    """Return contiguous logical ranges, merging a too-short tail backward."""
    ranges: list[tuple[int | float, int | float]] = []
    start: int | float = 0
    while duration - start > cut_seconds:
        end = start + cut_seconds
        ranges.append((start, end))
        start = end
    ranges.append((start, duration))
    if len(ranges) > 1 and ranges[-1][1] - ranges[-1][0] < minimum_final_seconds:
        previous_start, _ = ranges[-2]
        ranges[-2:] = [(previous_start, ranges[-1][1])]
    return ranges


def build_playlist(
    inventory: dict[str, Any],
    settings: dict[str, Any],
    broadcast_start_time: str = "09:00:00",
) -> dict[str, Any]:
    """Construct ordered timeline items and per-movie schedule records."""
    movie_settings = settings["movie"]
    ad_settings = settings["advertisement"]
    cut_seconds = movie_settings["segment_duration_minutes"] * 60
    context_seconds = movie_settings["playback_context_buffer_seconds"]
    minimum_final_seconds = movie_settings["minimum_last_segment_duration_minutes"] * 60
    allowed_minutes = movie_settings["allowed_start_minutes"]
    tolerance_seconds = movie_settings["start_time_tolerance_seconds"]
    repeat_count = ad_settings["repeat_count"]
    broadcast_start_seconds = _parse_wall_clock(broadcast_start_time)

    movie_files: list[tuple[str, dict[str, Any]]] = []
    for folder in sorted(
        inventory["categories"]["movies"].get("folders", []),
        key=lambda entry: _movie_folder_order(entry["folder_id"]),
    ):
        for movie in folder.get("files", []):
            movie_files.append((folder["folder_id"], movie))

    movies: list[dict[str, Any]] = []
    for folder_id, movie in movie_files:
        duration = movie["duration_seconds"]
        if duration is None:
            raise ValueError(f"Simulation needs a known duration for {movie['filename']}.")
        ranges = _segments(duration, cut_seconds, minimum_final_seconds)
        movies.append({
            "folder_id": folder_id,
            "movie": movie,
            "segments": [
                {
                    "segment_number": number,
                    "segment_count": len(ranges),
                    "logical_start": start,
                    "logical_end": end,
                }
                for number, (start, end) in enumerate(ranges, 1)
            ],
        })

    ads = inventory["categories"]["ads"].get("files", [])
    selected_ads = list(ads)
    if ad_settings["playback_order"] == "random":
        random.shuffle(selected_ads)
    ad_sequence = selected_ads * repeat_count

    items: list[TimelineItem] = []
    breaks: list[dict[str, Any]] = []
    movie_schedule: list[dict[str, Any]] = []
    elapsed_cursor: int | float = 0
    sequence = 0
    gap_counter = 0
    gap_duration_total: int | float = 0

    def append_item(
        *,
        media_type: str,
        duration: int | float,
        source_filename: str | None = None,
        source_path: str | None = None,
        movie_folder: str | None = None,
        segment_number: int | None = None,
        segment_count: int | None = None,
        logical_start: int | float | None = None,
        logical_end: int | float | None = None,
        actual_start: int | float | None = None,
        actual_end: int | float | None = None,
        source_duration: int | float | None = None,
        ad_break_number: int | None = None,
        reason: str | None = None,
        gap_id: str | None = None,
    ) -> TimelineItem:
        nonlocal elapsed_cursor, sequence
        sequence += 1
        item = TimelineItem(
            sequence=sequence,
            media_type=media_type,
            source_filename=source_filename,
            source_path=source_path,
            movie_folder=movie_folder,
            segment_number=segment_number,
            segment_count=segment_count,
            logical_source_start_seconds=logical_start,
            logical_source_end_seconds=logical_end,
            actual_playback_source_start_seconds=actual_start,
            actual_playback_source_end_seconds=actual_end,
            source_duration_seconds=source_duration,
            elapsed_broadcast_start_seconds=elapsed_cursor,
            elapsed_broadcast_end_seconds=elapsed_cursor + duration,
            broadcast_duration_seconds=duration,
            wall_clock_start_timestamp=format_wall_clock(broadcast_start_seconds + elapsed_cursor),
            wall_clock_end_timestamp=format_wall_clock(broadcast_start_seconds + elapsed_cursor + duration),
            ad_break_number=ad_break_number,
            reason=reason,
            gap_id=gap_id,
        )
        items.append(item)
        elapsed_cursor += duration
        return item

    for movie_index, movie_record in enumerate(movies):
        gap_before: dict[str, Any] | None = None
        if movie_index > 0:
            ready_wall_clock = broadcast_start_seconds + elapsed_cursor
            actual_start, eligible_mark = choose_movie_start(
                ready_wall_clock, allowed_minutes, tolerance_seconds
            )
            gap_duration = actual_start - ready_wall_clock
            if gap_duration > 0:
                gap_counter += 1
                gap_id = f"gap-{gap_counter}"
                gap_item = append_item(
                    media_type="empty_gap",
                    duration=gap_duration,
                    reason="Waiting for the next eligible movie start.",
                    gap_id=gap_id,
                )
                gap_duration_total += gap_duration
                gap_before = {
                    "gap_id": gap_id,
                    "duration_seconds": gap_duration,
                    "wall_clock_start_timestamp": gap_item.wall_clock_start_timestamp,
                    "wall_clock_end_timestamp": gap_item.wall_clock_end_timestamp,
                    "elapsed_broadcast_start_seconds": gap_item.elapsed_broadcast_start_seconds,
                    "elapsed_broadcast_end_seconds": gap_item.elapsed_broadcast_end_seconds,
                    "reason": gap_item.reason,
                }
            # actual_start is either the current ready time (within tolerance)
            # or the following eligible mark (after an explicit gap).
            if gap_duration == 0 and abs(actual_start - eligible_mark) > tolerance_seconds:
                raise RuntimeError("Chosen movie start falls outside the configured tolerance.")

        movie = movie_record["movie"]
        record: dict[str, Any] = {
            "movie_name": movie["filename"],
            "movie_folder": movie_record["folder_id"],
            "source_path": movie["path"],
            "wall_clock_start_timestamp": format_wall_clock(broadcast_start_seconds + elapsed_cursor),
            "wall_clock_finish_timestamp": None,
            "ready_for_next_movie_timestamp": None,
            "segment_count": len(movie_record["segments"]),
            "advertisement_breaks": [],
            "empty_gap_before": gap_before,
        }
        movie_schedule.append(record)

        for segment_index, segment in enumerate(movie_record["segments"]):
            logical_start = segment["logical_start"]
            logical_end = segment["logical_end"]
            actual_start = max(0, logical_start - context_seconds) if segment["segment_number"] > 1 else logical_start
            duration = logical_end - actual_start
            movie_item = append_item(
                media_type="movie_segment",
                duration=duration,
                source_filename=movie["filename"],
                source_path=movie["path"],
                movie_folder=movie_record["folder_id"],
                segment_number=segment["segment_number"],
                segment_count=segment["segment_count"],
                logical_start=logical_start,
                logical_end=logical_end,
                actual_start=actual_start,
                actual_end=logical_end,
                source_duration=logical_end - logical_start,
            )
            if segment_index == len(movie_record["segments"]) - 1:
                record["wall_clock_finish_timestamp"] = movie_item.wall_clock_end_timestamp

            has_next_segment = segment_index < len(movie_record["segments"]) - 1
            has_next_movie = movie_index < len(movies) - 1
            if has_next_segment or has_next_movie:
                break_number = len(breaks) + 1
                break_record = {
                    "break_number": break_number,
                    "movie_folder": movie_record["folder_id"],
                    "movie_name": movie["filename"],
                    "after_segment_sequence": movie_item.sequence,
                    "ads": [],
                }
                for ad in ad_sequence:
                    ad_duration = ad["duration_seconds"]
                    if ad_duration is None:
                        raise ValueError(f"Simulation needs a known duration for advertisement {ad['filename']}.")
                    ad_item = append_item(
                        media_type="ad",
                        duration=ad_duration,
                        source_filename=ad["filename"],
                        source_path=ad["path"],
                        logical_start=0,
                        logical_end=ad_duration,
                        actual_start=0,
                        actual_end=ad_duration,
                        source_duration=ad_duration,
                        ad_break_number=break_number,
                    )
                    break_record["ads"].append({
                        "sequence": ad_item.sequence,
                        "filename": ad["filename"],
                        "source_path": ad["path"],
                        "duration_seconds": ad_duration,
                    })
                breaks.append(break_record)
                record["advertisement_breaks"].append(break_record)

        record["ready_for_next_movie_timestamp"] = format_wall_clock(broadcast_start_seconds + elapsed_cursor)

    return {
        "items": items,
        "ad_breaks": breaks,
        "movies": movie_schedule,
        "movie_count": len(movie_files),
        "movie_segment_count": sum(movie["segment_count"] for movie in movie_schedule),
        "total_broadcast_duration_seconds": elapsed_cursor,
        "total_empty_gap_duration_seconds": gap_duration_total,
        "broadcast_start_time": broadcast_start_time,
    }
