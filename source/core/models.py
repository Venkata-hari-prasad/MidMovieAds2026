"""Small shared data models used by the movie-playlist simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def format_clock(seconds: int | float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    whole = int(round(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_wall_clock(seconds_since_midnight: int | float) -> str:
    """Format seconds from midnight as a wall-clock HH:MM:SS timestamp."""
    whole = int(round(seconds_since_midnight)) % (24 * 3600)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class TimelineItem:
    sequence: int
    media_type: str
    source_filename: str | None
    source_path: str | None
    movie_folder: str | None
    segment_number: int | None
    segment_count: int | None
    logical_source_start_seconds: int | float | None
    logical_source_end_seconds: int | float | None
    actual_playback_source_start_seconds: int | float | None
    actual_playback_source_end_seconds: int | float | None
    source_duration_seconds: int | float | None
    elapsed_broadcast_start_seconds: int | float
    elapsed_broadcast_end_seconds: int | float
    broadcast_duration_seconds: int | float
    wall_clock_start_timestamp: str
    wall_clock_end_timestamp: str
    ad_break_number: int | None = None
    reason: str | None = None
    gap_id: str | None = None
    song_id: str | None = None
    waiting_gap_id: str | None = None
    completion_status: str | None = None
    source_category: str | None = None
    schedule_block: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["elapsed_broadcast_start"] = format_clock(self.elapsed_broadcast_start_seconds)
        result["elapsed_broadcast_end"] = format_clock(self.elapsed_broadcast_end_seconds)
        for field in (
            "logical_source_start",
            "logical_source_end",
            "actual_playback_source_start",
            "actual_playback_source_end",
        ):
            value = result[f"{field}_seconds"]
            result[f"{field}_timestamp"] = format_clock(value) if value is not None else None
        if self.media_type == "empty_gap":
            result["duration_seconds"] = self.broadcast_duration_seconds
        return result
