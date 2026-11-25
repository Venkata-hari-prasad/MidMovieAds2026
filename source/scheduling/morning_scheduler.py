"""Build the configured 06:00–09:00 devotional and regular song sequence."""

from __future__ import annotations

from typing import Any

try:
    from ..core.models import TimelineItem, format_wall_clock
    from .song_scheduler import SongSelectionState
except ImportError:  # source directory used directly on sys.path
    from core.models import TimelineItem, format_wall_clock
    from scheduling.song_scheduler import SongSelectionState


def _parse_time(value: str) -> int:
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60


def build_morning_schedule(
    inventory: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Create sequential song sections with configured black placeholders."""
    morning = settings["morning_schedule"]
    start_seconds = _parse_time(morning["start_time"])
    transition_seconds = morning["transition_black_duration_seconds"]
    elapsed_cursor: int | float = 0
    items: list[TimelineItem] = []
    sections: list[dict[str, Any]] = []

    for collection, duration_key, label in (
        ("dev-songs", "dev_songs_duration_minutes", "Devotional songs"),
        ("songs", "songs_duration_minutes", "Regular songs"),
    ):
        block_duration_seconds = morning[duration_key] * 60
        section_start_elapsed = elapsed_cursor
        section_start_wall = start_seconds + elapsed_cursor
        if block_duration_seconds == 0:
            sections.append({
                "collection": collection,
                "label": label,
                "configured_duration_minutes": 0,
                "song_playback_duration_seconds": 0,
                "transition_black_duration_seconds": 0,
                "wall_clock_start_timestamp": format_wall_clock(section_start_wall),
                "wall_clock_end_timestamp": format_wall_clock(section_start_wall),
                "elapsed_broadcast_start_seconds": section_start_elapsed,
                "elapsed_broadcast_end_seconds": elapsed_cursor,
                "song_play_count": 0,
            })
            continue
        song_duration_seconds = block_duration_seconds - transition_seconds
        state = SongSelectionState(
            inventory["categories"][collection].get("files", []),
            settings["songs"]["playback_order"],
        )
        song_end_elapsed = section_start_elapsed + song_duration_seconds
        section_end_elapsed = section_start_elapsed + block_duration_seconds
        while elapsed_cursor < song_end_elapsed:
            song = state.take_next()
            if song is None:
                raise ValueError(f"Morning schedule has no usable {label.lower()} entries.")
            remaining = song_end_elapsed - elapsed_cursor
            source_duration = song["duration_seconds"]
            playback_duration = min(source_duration, remaining)
            if playback_duration <= 0:
                break
            completion = "completed_naturally" if playback_duration == source_duration else "hard_cut"
            items.append(TimelineItem(
                sequence=len(items) + 1,
                media_type="song",
                source_filename=song["filename"],
                source_path=song["path"],
                movie_folder=None,
                segment_number=None,
                segment_count=None,
                logical_source_start_seconds=0,
                logical_source_end_seconds=playback_duration,
                actual_playback_source_start_seconds=0,
                actual_playback_source_end_seconds=playback_duration,
                source_duration_seconds=source_duration,
                elapsed_broadcast_start_seconds=elapsed_cursor,
                elapsed_broadcast_end_seconds=elapsed_cursor + playback_duration,
                broadcast_duration_seconds=playback_duration,
                wall_clock_start_timestamp=format_wall_clock(start_seconds + elapsed_cursor),
                wall_clock_end_timestamp=format_wall_clock(start_seconds + elapsed_cursor + playback_duration),
                song_id=song["path"],
                completion_status=completion,
                source_category=collection,
                schedule_block="morning",
            ))
            elapsed_cursor += playback_duration

        if transition_seconds:
            transition_start = elapsed_cursor
            items.append(TimelineItem(
                sequence=len(items) + 1,
                media_type="black_video_placeholder",
                source_filename=None,
                source_path=None,
                movie_folder=None,
                segment_number=None,
                segment_count=None,
                logical_source_start_seconds=None,
                logical_source_end_seconds=None,
                actual_playback_source_start_seconds=None,
                actual_playback_source_end_seconds=None,
                source_duration_seconds=None,
                elapsed_broadcast_start_seconds=transition_start,
                elapsed_broadcast_end_seconds=transition_start + transition_seconds,
                broadcast_duration_seconds=transition_seconds,
                wall_clock_start_timestamp=format_wall_clock(start_seconds + transition_start),
                wall_clock_end_timestamp=format_wall_clock(start_seconds + transition_start + transition_seconds),
                reason=f"Black video placeholder after {label.lower()}.",
                source_category=collection,
                schedule_block="morning",
            ))
            elapsed_cursor += transition_seconds

        sections.append({
            "collection": collection,
            "label": label,
            "configured_duration_minutes": morning[duration_key],
            "song_playback_duration_seconds": song_duration_seconds,
            "transition_black_duration_seconds": transition_seconds,
            "wall_clock_start_timestamp": format_wall_clock(section_start_wall),
            "wall_clock_end_timestamp": format_wall_clock(start_seconds + elapsed_cursor),
            "elapsed_broadcast_start_seconds": section_start_elapsed,
            "elapsed_broadcast_end_seconds": elapsed_cursor,
            "song_play_count": sum(1 for item in items if item.source_category == collection and item.media_type == "song"),
        })

    return {
        "start_timestamp": format_wall_clock(start_seconds),
        "end_timestamp": format_wall_clock(start_seconds + elapsed_cursor),
        "duration_seconds": elapsed_cursor,
        "transition_black_duration_seconds": transition_seconds,
        "sections": sections,
        "items": items,
    }
