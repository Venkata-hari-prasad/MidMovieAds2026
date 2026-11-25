"""Select and place movie songs only inside existing movie-start waiting gaps."""

from __future__ import annotations

from dataclasses import replace
import random
from typing import Any

try:
    from ..core.models import TimelineItem, format_wall_clock
except ImportError:  # source directory used directly on sys.path
    from core.models import TimelineItem, format_wall_clock


def _wall_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


class SongSelectionState:
    """Track unique inventory usage plus repeat cycles within a waiting gap."""

    def __init__(self, songs: list[dict[str, Any]], playback_order: str) -> None:
        self._songs = list(songs)
        if playback_order == "random":
            random.shuffle(self._songs)
        self._index = 0
        self._selected_ids: set[str] = set()
        self._cycle_used: set[str] = set()
        self._playback_order = playback_order
        self._last_song_id: str | None = None
        self._selection_order: list[dict[str, Any]] = []

    @staticmethod
    def _id(song: dict[str, Any]) -> str:
        return str(song["path"])

    def take_next(self) -> dict[str, Any] | None:
        if not self._songs:
            return None
        if len(self._cycle_used) == len(self._songs):
            self._start_cycle(avoid_immediate_repeat=True)
        while self._index < len(self._songs):
            song = self._songs[self._index]
            self._index += 1
            song_id = self._id(song)
            if song_id in self._cycle_used:
                continue
            self._cycle_used.add(song_id)
            self._selected_ids.add(song_id)
            self._selection_order.append(song)
            self._last_song_id = song_id
            return song
        return None

    def _start_cycle(self, *, avoid_immediate_repeat: bool) -> None:
        self._cycle_used.clear()
        self._songs = list(self._songs)
        if self._playback_order == "random":
            random.shuffle(self._songs)
        if avoid_immediate_repeat and len(self._songs) > 1 and self._id(self._songs[0]) == self._last_song_id:
            swap_index = next(index for index, song in enumerate(self._songs[1:], 1) if self._id(song) != self._last_song_id)
            self._songs[0], self._songs[swap_index] = self._songs[swap_index], self._songs[0]
        self._index = 0

    def reset_for_gap(self) -> None:
        """Start a fresh no-repeat cycle for a new movie waiting gap."""
        self._last_song_id = None
        self._start_cycle(avoid_immediate_repeat=False)

    @property
    def selected_songs(self) -> list[dict[str, Any]]:
        return list(self._selection_order)

    @property
    def unused_songs(self) -> list[dict[str, Any]]:
        return [song for song in self._songs if self._id(song) not in self._selected_ids]

    @property
    def exhausted(self) -> bool:
        return not self.unused_songs


def fill_one_gap(
    gap: TimelineItem,
    state: SongSelectionState,
    cut_early_seconds: int,
) -> tuple[list[TimelineItem], list[dict[str, Any]]]:
    """Fill a single gap to its usable boundary and return items plus song records."""
    gap_id = gap.gap_id or f"gap-before-{gap.wall_clock_end_timestamp}"
    gap_duration = gap.broadcast_duration_seconds
    usable_duration = max(0, gap_duration - cut_early_seconds)
    consumed = 0
    sequence_items: list[TimelineItem] = []
    song_records: list[dict[str, Any]] = []

    while consumed < usable_duration:
        song = state.take_next()
        if song is None:
            break
        full_duration = song["duration_seconds"]
        available = usable_duration - consumed
        played_duration = min(full_duration, available)
        if played_duration <= 0:
            continue
        start_elapsed = gap.elapsed_broadcast_start_seconds + consumed
        end_elapsed = start_elapsed + played_duration
        start_wall = _wall_seconds(gap.wall_clock_start_timestamp) + consumed
        end_wall = start_wall + played_duration
        song_id = SongSelectionState._id(song)
        completion = "completed_naturally" if played_duration == full_duration else "hard_cut"
        item = TimelineItem(
            sequence=0,
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
            source_duration_seconds=full_duration,
            elapsed_broadcast_start_seconds=start_elapsed,
            elapsed_broadcast_end_seconds=end_elapsed,
            broadcast_duration_seconds=played_duration,
            wall_clock_start_timestamp=format_wall_clock(start_wall),
            wall_clock_end_timestamp=format_wall_clock(end_wall),
            song_id=song_id,
            waiting_gap_id=gap_id,
            completion_status=completion,
            source_category="movie-songs",
            schedule_block="movie-gap",
        )
        sequence_items.append(item)
        song_records.append({
            "song_id": song_id,
            "filename": song["filename"],
            "waiting_gap_id": gap_id,
            "played_duration_seconds": played_duration,
            "source_duration_seconds": full_duration,
            "completion_status": completion,
        })
        consumed += played_duration

    remaining = gap_duration - consumed
    if remaining > 0:
        gap_start_elapsed = gap.elapsed_broadcast_start_seconds + consumed
        gap_end_elapsed = gap.elapsed_broadcast_end_seconds
        gap_start_wall = _wall_seconds(gap.wall_clock_start_timestamp) + consumed
        reserved_only = consumed >= usable_duration and remaining == min(cut_early_seconds, gap_duration)
        if reserved_only:
            reason = "Reserved before the next movie start (cut-early buffer)."
        elif consumed == 0 and state.exhausted:
            reason = "No unused songs remain; waiting for the next eligible movie start."
        else:
            reason = "Unfilled waiting time before the next eligible movie start."
        sequence_items.append(TimelineItem(
            sequence=0,
            media_type="empty_gap",
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
            elapsed_broadcast_start_seconds=gap_start_elapsed,
            elapsed_broadcast_end_seconds=gap_end_elapsed,
            broadcast_duration_seconds=remaining,
            wall_clock_start_timestamp=format_wall_clock(gap_start_wall),
            wall_clock_end_timestamp=gap.wall_clock_end_timestamp,
            reason=reason,
            gap_id=gap_id,
            waiting_gap_id=gap_id,
        ))

    return sequence_items, song_records


def fill_waiting_gaps(
    plan: dict[str, Any],
    inventory: dict[str, Any],
    song_settings: dict[str, Any],
    enabled: bool = True,
) -> dict[str, Any]:
    """Insert movie-songs in planned gaps, or keep gaps explicitly empty."""
    songs = inventory["categories"]["movie-songs"].get("files", [])
    state = SongSelectionState(songs, song_settings["playback_order"])
    cut_early = song_settings["cut_early_seconds"]
    new_items: list[TimelineItem] = []
    old_to_new_sequence: dict[int, int] = {}
    songs_by_gap: dict[str, list[dict[str, Any]]] = {}

    for item in plan["items"]:
        if item.media_type != "empty_gap":
            new_items.append(item)
            old_to_new_sequence[item.sequence] = 0  # final sequence assigned below
            continue
        gap_id = item.gap_id or f"gap-{len(songs_by_gap) + 1}"
        item = replace(item, gap_id=gap_id, waiting_gap_id=gap_id)
        state.reset_for_gap()
        if enabled:
            fill_items, records = fill_one_gap(item, state, cut_early)
        else:
            fill_items = [replace(
                item,
                reason="Movie-gap song filler is disabled; waiting for the next eligible movie start.",
            )]
            records = []
        new_items.extend(fill_items)
        songs_by_gap[gap_id] = records

    # Re-number the flattened timeline and update ad-break references for the
    # renderer. The order, timings, and movie starts remain fixed.
    for index, item in enumerate(new_items, 1):
        new_items[index - 1] = replace(item, sequence=index)
        if item.sequence in old_to_new_sequence:
            old_to_new_sequence[item.sequence] = index
    for block in plan["ad_breaks"]:
        block["after_segment_sequence"] = old_to_new_sequence[block["after_segment_sequence"]]
        for ad in block["ads"]:
            ad["sequence"] = old_to_new_sequence[ad["sequence"]]

    for movie in plan["movies"]:
        gap = movie["empty_gap_before"]
        if gap:
            records = songs_by_gap.get(gap["gap_id"], [])
            gap["songs"] = records
            gap["song_playback_duration_seconds"] = sum(r["played_duration_seconds"] for r in records)
            gap["remaining_empty_duration_seconds"] = gap["duration_seconds"] - gap["song_playback_duration_seconds"]

    plan["items"] = new_items
    plan["song_selection"] = {
        "songs_played": [
            {
                "song_id": song["path"],
                "filename": song["filename"],
                "source_duration_seconds": song["duration_seconds"],
            }
            for song in state.selected_songs
        ],
        "songs_unused": [
            {
                "song_id": song["path"],
                "filename": song["filename"],
                "source_duration_seconds": song["duration_seconds"],
            }
            for song in state.unused_songs
        ],
        "songs_played_count": sum(1 for item in new_items if item.media_type == "song"),
        "total_song_playback_duration_seconds": sum(
            item.broadcast_duration_seconds for item in new_items if item.media_type == "song"
        ),
        "total_remaining_empty_gap_duration_seconds": sum(
            item.broadcast_duration_seconds for item in new_items if item.media_type == "empty_gap"
        ),
        "song_collection_exhausted": state.exhausted,
    }
    plan["total_empty_gap_duration_seconds"] = plan["song_selection"]["total_remaining_empty_gap_duration_seconds"]
    return plan
