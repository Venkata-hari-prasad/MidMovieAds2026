"""Run the movie/ad schedule simulation, check it, and save its JSON blueprint."""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace
import json
import math
from pathlib import Path
from typing import Any, Callable

try:
    from ..core.models import format_clock
    from ..scheduling.scheduler import build_playlist, choose_movie_start
    from ..scheduling.morning_scheduler import build_morning_schedule
    from ..scheduling.song_scheduler import fill_waiting_gaps
    from ..scheduling.ending_scheduler import schedule_ending_songs, target_elapsed_seconds
except ImportError:  # source directory used directly on sys.path
    from core.models import format_clock
    from scheduling.scheduler import build_playlist, choose_movie_start
    from scheduling.morning_scheduler import build_morning_schedule
    from scheduling.song_scheduler import fill_waiting_gaps
    from scheduling.ending_scheduler import schedule_ending_songs, target_elapsed_seconds

BROADCAST_START_TIME = "09:00:00"


class SimulationConsistencyError(RuntimeError):
    """Raised when a generated simulation timeline fails its checks."""


def _same(left: int | float, right: int | float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _clock_seconds(value: str) -> int:
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def _clock_rounding_drift(actual_timestamp: str, expected_seconds: int | float) -> float:
    """Return circular wall-clock difference, accounting for midnight wrap."""
    actual = _clock_seconds(actual_timestamp)
    expected = expected_seconds % 86400
    difference = abs(actual - expected) % 86400
    return min(difference, 86400 - difference)


def _movie_sources(inventory: dict[str, Any]) -> list[tuple[str, str, int | float]]:
    result = []
    for folder in inventory["categories"]["movies"].get("folders", []):
        for movie in folder.get("files", []):
            if movie.get("duration_seconds") is None:
                raise ValueError(f"Simulation needs a known duration for {movie.get('filename', 'movie')}.")
            result.append((folder["folder_id"], movie["path"], movie["duration_seconds"]))
    return result


def check_timeline(
    inventory: dict[str, Any],
    plan: dict[str, Any],
    settings: dict[str, Any],
    original_movie_starts: list[str],
) -> dict[str, bool]:
    """Run simulation-specific source, placement, alignment, and continuity checks."""
    items = plan["items"]
    movie_items = [item for item in items if item.media_type == "movie_segment"]
    ad_items = [item for item in items if item.media_type == "ad"]
    gap_items = [item for item in items if item.media_type == "empty_gap"]
    song_items = [item for item in items if item.media_type == "song"]
    movie_song_items = [item for item in song_items if item.schedule_block == "movie-gap"]
    morning_items = [item for item in song_items if item.schedule_block == "morning"]
    ending_items = [item for item in song_items if item.schedule_block == "broadcast-ending"]
    morning_block_items = [
        item for item in items
        if item.schedule_block == "morning"
        and item.media_type in ("song", "black_video_placeholder")
    ]
    sources = _movie_sources(inventory)
    source_keys = {(folder, path) for folder, path, _ in sources}
    handled_keys = {(item.movie_folder, item.source_path) for item in movie_items}
    every_movie_processed = len(sources) == len(handled_keys) and source_keys == handled_keys

    expected_durations = {(folder, path): duration for folder, path, duration in sources}
    segments_by_movie: dict[tuple[str | None, str], list[Any]] = {}
    for item in movie_items:
        segments_by_movie.setdefault((item.movie_folder, item.source_path), []).append(item)
    source_continuity = True
    for key, segments in segments_by_movie.items():
        segments.sort(key=lambda item: item.segment_number or 0)
        source_continuity &= _same(segments[0].logical_source_start_seconds, 0)
        for previous, current in zip(segments, segments[1:]):
            source_continuity &= _same(previous.logical_source_end_seconds, current.logical_source_start_seconds)
        source_continuity &= _same(segments[-1].logical_source_end_seconds, expected_durations[key])
        source_continuity &= _same(sum(item.source_duration_seconds for item in segments), expected_durations[key])

    # Each adjacent pair of movie segments has one ad break. A gap is only
    # permitted after the ads at a movie boundary, before the next movie.
    movie_positions = [index for index, item in enumerate(items) if item.media_type == "movie_segment"]
    ad_breaks_correct = len(plan["ad_breaks"]) == max(0, len(movie_items) - 1)
    ad_breaks_correct &= not items or items[-1].media_type != "ad"
    same_movie_transitions_immediate = True
    for left_index, right_index in zip(movie_positions, movie_positions[1:]):
        left, right = items[left_index], items[right_index]
        between = items[left_index + 1:right_index]
        ads_between = [item for item in between if item.media_type == "ad"]
        gaps_between = [item for item in between if item.media_type == "empty_gap"]
        ad_breaks_correct &= bool(ads_between) and all(
            item.media_type in ("ad", "song", "empty_gap") for item in between
        )
        ad_breaks_correct &= len({item.ad_break_number for item in ads_between}) == 1
        if left.movie_folder == right.movie_folder and left.source_path == right.source_path:
            same_movie_transitions_immediate &= (
                not gaps_between
                and not any(item.media_type == "song" for item in between)
                and len(ads_between) > 0
                and all(item.media_type == "ad" for item in between)
            )
        else:
            first_gap_content = next((i for i, item in enumerate(between) if item.media_type in ("song", "empty_gap")), len(between))
            ad_breaks_correct &= all(item.media_type == "ad" for item in between[:first_gap_content])
            ad_breaks_correct &= all(item.media_type in ("song", "empty_gap") for item in between[first_gap_content:])
            ad_breaks_correct &= len({item.waiting_gap_id for item in between[first_gap_content:]}) <= 1

    inventory_ads = inventory["categories"]["ads"].get("files", [])
    ads_by_path = {ad["path"]: ad.get("duration_seconds") for ad in inventory_ads}
    ads_full = all(
        item.source_path in ads_by_path
        and ads_by_path[item.source_path] is not None
        and _same(item.source_duration_seconds, ads_by_path[item.source_path])
        and _same(item.actual_playback_source_start_seconds, 0)
        and _same(item.actual_playback_source_end_seconds, ads_by_path[item.source_path])
        and _same(item.broadcast_duration_seconds, ads_by_path[item.source_path])
        for item in ad_items
    )

    context_seconds = settings["movie"]["playback_context_buffer_seconds"]
    context_correct = all(
        _same(
            item.actual_playback_source_start_seconds,
            max(0, item.logical_source_start_seconds - context_seconds)
            if item.segment_number and item.segment_number > 1
            else item.logical_source_start_seconds,
        )
        and _same(item.actual_playback_source_end_seconds, item.logical_source_end_seconds)
        and _same(
            item.broadcast_duration_seconds,
            item.actual_playback_source_end_seconds - item.actual_playback_source_start_seconds,
        )
        for item in movie_items
    )

    gaps_correct = all(
        item.reason is not None
        and _same(item.broadcast_duration_seconds, item.elapsed_broadcast_end_seconds - item.elapsed_broadcast_start_seconds)
        and item.broadcast_duration_seconds > 0
        for item in gap_items
    )
    linked_gap_count = 0
    for movie_index, movie_record in enumerate(plan["movies"]):
        gap = movie_record["empty_gap_before"]
        if gap:
            linked_gap_count += 1
            block_items = [item for item in items if item.waiting_gap_id == gap["gap_id"]]
            gaps_correct &= bool(block_items)
            gaps_correct &= all(item.media_type in ("song", "empty_gap") for item in block_items)
            if block_items:
                gaps_correct &= _same(block_items[0].elapsed_broadcast_start_seconds, gap["elapsed_broadcast_start_seconds"])
                gaps_correct &= _same(block_items[-1].elapsed_broadcast_end_seconds, gap["elapsed_broadcast_end_seconds"])
                gaps_correct &= _same(
                    sum(item.broadcast_duration_seconds for item in block_items), gap["duration_seconds"]
                )
                for previous, current in zip(block_items, block_items[1:]):
                    gaps_correct &= _same(previous.elapsed_broadcast_end_seconds, current.elapsed_broadcast_start_seconds)
                gaps_correct &= block_items[0].wall_clock_start_timestamp == gap["wall_clock_start_timestamp"]
                gaps_correct &= block_items[-1].wall_clock_end_timestamp == gap["wall_clock_end_timestamp"]
                gaps_correct &= block_items[-1].wall_clock_end_timestamp == movie_record["wall_clock_start_timestamp"]
            previous_movie = plan["movies"][movie_index - 1]
            gaps_correct &= gap["wall_clock_start_timestamp"] == previous_movie["ready_for_next_movie_timestamp"]
        elif movie_index > 0:
            previous_movie = plan["movies"][movie_index - 1]
            gaps_correct &= previous_movie["ready_for_next_movie_timestamp"] == movie_record["wall_clock_start_timestamp"]

    song_ids = [item.song_id for item in movie_song_items]
    movie_song_count = len(inventory["categories"]["movie-songs"].get("files", []))
    songs_no_repeat = True
    for movie_record in plan["movies"]:
        gap = movie_record["empty_gap_before"]
        if not gap:
            continue
        cycle_ids: set[str] = set()
        gap_song_ids = [item.song_id for item in movie_song_items if item.waiting_gap_id == gap["gap_id"]]
        for song_id in gap_song_ids:
            if song_id in cycle_ids:
                songs_no_repeat &= len(cycle_ids) == movie_song_count
                cycle_ids.clear()
            cycle_ids.add(song_id)
    songs_inventory_by_path = {
        song["path"]: song for song in inventory["categories"]["movie-songs"].get("files", [])
    }
    songs_only_in_gaps = all(
        item.song_id == item.source_path
        and item.source_path in songs_inventory_by_path
        and item.waiting_gap_id in {movie["empty_gap_before"]["gap_id"] for movie in plan["movies"] if movie["empty_gap_before"]}
        and item.logical_source_start_seconds == 0
        and item.actual_playback_source_start_seconds == 0
        and item.actual_playback_source_end_seconds == item.broadcast_duration_seconds
        and item.broadcast_duration_seconds <= songs_inventory_by_path[item.source_path]["duration_seconds"]
        for item in movie_song_items
    )
    songs_completed_or_cut_correctly = all(
        (item.completion_status == "completed_naturally" and _same(item.broadcast_duration_seconds, item.source_duration_seconds))
        or (item.completion_status == "hard_cut" and item.broadcast_duration_seconds < item.source_duration_seconds)
        for item in movie_song_items
    )
    no_ads_between_songs = True
    for movie_record in plan["movies"]:
        gap = movie_record["empty_gap_before"]
        if not gap:
            continue
        block_items = [item for item in items if item.waiting_gap_id == gap["gap_id"]]
        no_ads_between_songs &= all(item.media_type != "ad" for item in block_items)
        block_songs = [item for item in block_items if item.media_type == "song"]
        positions = [items.index(item) for item in block_songs]
        for left, right in zip(positions, positions[1:]):
            no_ads_between_songs &= all(items[index].media_type == "song" for index in range(left, right + 1))

    songs_stay_before_movie = True
    for movie_record in plan["movies"]:
        gap = movie_record["empty_gap_before"]
        if not gap:
            continue
        deadline = _clock_seconds(movie_record["wall_clock_start_timestamp"]) - settings["songs"]["cut_early_seconds"]
        block_songs = [item for item in movie_song_items if item.waiting_gap_id == gap["gap_id"]]
        if block_songs:
            songs_stay_before_movie &= _clock_seconds(block_songs[-1].wall_clock_end_timestamp) <= deadline
    song_duration_matches = _same(
        sum(item.broadcast_duration_seconds for item in movie_song_items),
        plan["song_selection"]["total_song_playback_duration_seconds"],
    )
    unused_song_ids = [song["song_id"] for song in plan["song_selection"]["songs_unused"]]
    selected_or_unused = set(song_ids).isdisjoint(unused_song_ids)
    selected_or_unused &= set(song_ids) | set(unused_song_ids) == set(songs_inventory_by_path)

    movie_settings = settings["movie"]
    alignment_checks = plan["movies"]
    first_movie_starts_on_time = bool(alignment_checks) and (
        alignment_checks[0]["wall_clock_start_timestamp"] == BROADCAST_START_TIME
    )
    subsequent_movies_aligned = True
    tolerance_respected = True
    for movie_index, movie_record in enumerate(alignment_checks[1:], 1):
        actual_start = _clock_seconds(movie_record["wall_clock_start_timestamp"])
        selected_start, eligible_mark = choose_movie_start(
            _clock_seconds(alignment_checks[movie_index - 1]["ready_for_next_movie_timestamp"]),
            movie_settings["allowed_start_minutes"],
            movie_settings["start_time_tolerance_seconds"],
        )
        subsequent_movies_aligned &= (
            _clock_rounding_drift(movie_record["wall_clock_start_timestamp"], selected_start) <= 1
        )
        # The serialized wall-clock timestamp is rounded to a whole second.
        # Allow that representation's rounding when checking the scheduler's
        # exact fractional start against its configured tolerance.
        tolerance_respected &= (
            abs(actual_start - eligible_mark)
            <= movie_settings["start_time_tolerance_seconds"] + 1
        )
    movie_starts_unchanged = [movie["wall_clock_start_timestamp"] for movie in plan["movies"]] == original_movie_starts

    toggles = settings.get("schedule_toggles", {})
    morning_enabled = toggles.get("morning_block_enabled", True)
    morning = plan.get("morning_schedule")
    morning_prefix = [item for item in items if item.schedule_block == "morning"]
    transition_items = [item for item in morning_prefix if item.media_type == "black_video_placeholder"]
    if morning_enabled and isinstance(morning, dict):
        morning_sections = morning["sections"]
        transition_seconds = settings["morning_schedule"]["transition_black_duration_seconds"]
        morning_timing_correct = bool(morning_sections) and morning["start_timestamp"] == settings["morning_schedule"]["start_time"] + ":00"
        morning_timing_correct &= morning["end_timestamp"] == BROADCAST_START_TIME
        morning_timing_correct &= len(morning_prefix) == len(morning_block_items)
        morning_timing_correct &= all(item.media_type in ("song", "black_video_placeholder") for item in morning_prefix)
        morning_timing_correct &= bool(morning_block_items) and morning_block_items[0].wall_clock_start_timestamp == morning["start_timestamp"]
        morning_timing_correct &= morning_block_items[-1].wall_clock_end_timestamp == morning["end_timestamp"]
        morning_timing_correct &= _same(sum(item.broadcast_duration_seconds for item in morning_block_items), 180 * 60)
        active_sections = [section for section in morning_sections if section["configured_duration_minutes"] > 0]
        morning_timing_correct &= len(transition_items) == (len(active_sections) if transition_seconds else 0)
        for left, right in zip(morning_block_items, morning_block_items[1:]):
            morning_timing_correct &= left.elapsed_broadcast_end_seconds == right.elapsed_broadcast_start_seconds
            morning_timing_correct &= left.wall_clock_end_timestamp == right.wall_clock_start_timestamp
        devotional_items = [item for item in morning_items if item.source_category == "dev-songs"]
        regular_morning_items = [item for item in morning_items if item.source_category == "songs"]
        morning_timing_correct &= bool(devotional_items) == (settings["morning_schedule"]["dev_songs_duration_minutes"] > 0)
        morning_timing_correct &= bool(regular_morning_items) == (settings["morning_schedule"]["songs_duration_minutes"] > 0)
        if morning_sections:
            for section in morning_sections:
                section_items = [item for item in morning_block_items if item.source_category == section["collection"]]
                section_songs = [item for item in section_items if item.media_type == "song"]
                section_transitions = [item for item in section_items if item.media_type == "black_video_placeholder"]
                required_block_duration = section["configured_duration_minutes"] * 60
                morning_timing_correct &= _same(sum(item.broadcast_duration_seconds for item in section_items), required_block_duration)
                if required_block_duration == 0:
                    morning_timing_correct &= _same(sum(item.broadcast_duration_seconds for item in section_songs), 0)
                    morning_timing_correct &= not section_items and not section_songs and not section_transitions
                    morning_timing_correct &= section["wall_clock_start_timestamp"] == section["wall_clock_end_timestamp"]
                    continue
                morning_timing_correct &= _same(sum(item.broadcast_duration_seconds for item in section_songs), required_block_duration - transition_seconds)
                morning_timing_correct &= bool(section_songs)
                morning_timing_correct &= bool(section_items) and section_items[0].wall_clock_start_timestamp == section["wall_clock_start_timestamp"]
                morning_timing_correct &= section_items[-1].wall_clock_end_timestamp == section["wall_clock_end_timestamp"]
                morning_timing_correct &= len(section_transitions) == (1 if transition_seconds else 0)
                if section_transitions:
                    transition = section_transitions[0]
                    morning_timing_correct &= transition.broadcast_duration_seconds == transition_seconds
                    morning_timing_correct &= transition.source_path is None and transition.reason is not None
                    morning_timing_correct &= section_songs[-1].wall_clock_end_timestamp == transition.wall_clock_start_timestamp
            morning_timing_correct &= morning_sections[0]["wall_clock_end_timestamp"] == morning_sections[1]["wall_clock_start_timestamp"]
            if transition_seconds:
                expected_transition_categories = [section["collection"] for section in active_sections]
                morning_timing_correct &= [item.source_category for item in transition_items] == expected_transition_categories
        morning_sources_correct = all(
            item.source_path in {song["path"] for song in inventory["categories"][item.source_category].get("files", [])}
            for item in morning_items
        )
        morning_sources_correct &= all(item.source_category != "movie-songs" for item in morning_items)
        morning_sources_correct &= all(
            (item.completion_status == "completed_naturally" and _same(item.broadcast_duration_seconds, item.source_duration_seconds))
            or (item.completion_status == "hard_cut" and item.broadcast_duration_seconds < item.source_duration_seconds)
            for item in morning_items
        )
    else:
        morning_timing_correct = not morning_prefix and not morning_block_items
        morning_sources_correct = not morning_items and not transition_items

    elapsed_continuity = True
    wall_clock_continuity = True
    previous_elapsed_end: int | float = 0
    timeline_start = plan["broadcast_start_time"]
    previous_wall_end = timeline_start
    for item in items:
        elapsed_continuity &= _same(item.elapsed_broadcast_start_seconds, previous_elapsed_end)
        elapsed_continuity &= _same(
            item.elapsed_broadcast_end_seconds - item.elapsed_broadcast_start_seconds,
            item.broadcast_duration_seconds,
        )
        wall_clock_continuity &= item.wall_clock_start_timestamp == previous_wall_end
        expected_start = _clock_seconds(timeline_start) + item.elapsed_broadcast_start_seconds
        expected_end = _clock_seconds(timeline_start) + item.elapsed_broadcast_end_seconds
        wall_clock_continuity &= _clock_rounding_drift(item.wall_clock_start_timestamp, expected_start) <= 1
        wall_clock_continuity &= _clock_rounding_drift(item.wall_clock_end_timestamp, expected_end) <= 1
        previous_elapsed_end = item.elapsed_broadcast_end_seconds
        previous_wall_end = item.wall_clock_end_timestamp
    total_sum_matches = _same(previous_elapsed_end, sum(item.broadcast_duration_seconds for item in items))
    total_sum_matches &= _same(previous_elapsed_end, plan["total_broadcast_duration_seconds"])
    total_sum_matches &= _same(previous_elapsed_end, sum(item.elapsed_broadcast_end_seconds - item.elapsed_broadcast_start_seconds for item in items))

    end_report = plan["ending_schedule"]
    target_elapsed = target_elapsed_seconds(plan["broadcast_start_time"], settings["broadcast"]["end_time"])
    ending_schedule_correct = True
    if end_report["status"] == "ending_songs_scheduled":
        ending_schedule_correct &= bool(ending_items)
        ending_schedule_correct &= all(item.source_category == "songs" for item in ending_items)
        ending_schedule_correct &= len(ending_items) == end_report["ending_song_count"]
        ending_schedule_correct &= _same(sum(item.broadcast_duration_seconds for item in ending_items), end_report["required_ending_duration_seconds"])
        ending_schedule_correct &= _same(plan["total_broadcast_duration_seconds"], target_elapsed)
        ending_schedule_correct &= _same(ending_items[0].elapsed_broadcast_start_seconds, end_report["timeline_before_filler_elapsed_seconds"])
        ending_schedule_correct &= ending_items[-1].wall_clock_end_timestamp == settings["broadcast"]["end_time"] + ":00"
        ending_schedule_correct &= all(item.media_type == "song" for item in items[items.index(ending_items[0]):])
    elif end_report["status"] == "exact_target":
        ending_schedule_correct &= not ending_items and _same(plan["total_broadcast_duration_seconds"], target_elapsed)
    elif end_report["status"] == "overrun":
        ending_schedule_correct &= not ending_items and plan["total_broadcast_duration_seconds"] > target_elapsed
    elif end_report["status"] == "ending_filler_disabled":
        ending_schedule_correct &= not ending_items
        ending_schedule_correct &= plan["total_broadcast_duration_seconds"] < target_elapsed
        ending_schedule_correct &= _same(
            plan["total_broadcast_duration_seconds"],
            end_report["timeline_before_filler_elapsed_seconds"],
        )
        ending_schedule_correct &= (
            end_report["planned_finish"] == end_report["timeline_before_filler_finish"]
        )
    else:
        ending_schedule_correct = False

    return {
        "movie_1_starts_at_09_00": first_movie_starts_on_time,
        "subsequent_movies_follow_eligible_start_selection": subsequent_movies_aligned,
        "early_late_start_tolerance_respected": tolerance_respected,
        "same_movie_segments_have_no_alignment_wait": same_movie_transitions_immediate,
        "advertisements_remain_between_movie_segments": ad_breaks_correct,
        "movie_and_ad_content_is_not_truncated_or_logically_duplicated": source_continuity and ads_full,
        "empty_gaps_are_explicit_and_consistent": gaps_correct,
        "movie_songs_repeat_only_after_cycle_exhaustion": songs_no_repeat and songs_only_in_gaps,
        "songs_are_contiguous_without_ad_breaks": no_ads_between_songs,
        "song_playback_completion_and_cut_boundaries_are_correct": songs_completed_or_cut_correctly and songs_stay_before_movie,
        "song_selection_state_has_no_lost_or_duplicate_inventory": selected_or_unused,
        "song_playback_duration_summary_matches_timeline": song_duration_matches,
        "morning_sections_run_sequentially_from_configured_start_to_09_00": morning_timing_correct,
        "morning_songs_use_only_devotional_and_regular_collections": morning_sources_correct,
        "movie_wall_clock_starts_are_unchanged": movie_starts_unchanged,
        "wall_clock_timestamps_are_continuous": wall_clock_continuity,
        "elapsed_broadcast_positions_are_continuous": elapsed_continuity,
        "final_duration_matches_complete_timeline": total_sum_matches,
        "broadcast_end_time_filler_matches_target_or_overrun": ending_schedule_correct,
    }


def _prepend_morning_schedule(
    plan: dict[str, Any],
    inventory: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Prefix the 06:00 morning block while retaining all 09:00 movie times."""
    toggles = settings.get("schedule_toggles", {})
    if not toggles.get("morning_block_enabled", True):
        plan["morning_schedule"] = None
        return plan

    morning = build_morning_schedule(inventory, settings)
    offset = morning["duration_seconds"]
    morning_count = len(morning["items"])

    shifted_items = [
        replace(
            item,
            sequence=item.sequence + morning_count,
            elapsed_broadcast_start_seconds=item.elapsed_broadcast_start_seconds + offset,
            elapsed_broadcast_end_seconds=item.elapsed_broadcast_end_seconds + offset,
        )
        for item in plan["items"]
    ]
    for block in plan["ad_breaks"]:
        block["after_segment_sequence"] += morning_count
        for ad in block["ads"]:
            ad["sequence"] += morning_count
    for movie in plan["movies"]:
        gap = movie.get("empty_gap_before")
        if gap:
            gap["elapsed_broadcast_start_seconds"] += offset
            gap["elapsed_broadcast_end_seconds"] += offset

    plan["items"] = morning["items"] + shifted_items
    plan["total_broadcast_duration_seconds"] += offset
    plan["broadcast_start_time"] = morning["start_timestamp"]
    plan["morning_schedule"] = {key: value for key, value in morning.items() if key != "items"}
    return plan


def run_simulation(
    inventory: dict[str, Any],
    settings: dict[str, Any],
    output_directory: str | Path | None = None,
    broadcast_start_time: str = BROADCAST_START_TIME,
    ending_song_confirmation: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Build, verify, and save the complete execution blueprint as JSON."""
    plan = build_playlist(inventory, settings, broadcast_start_time)
    original_movie_starts = [movie["wall_clock_start_timestamp"] for movie in plan["movies"]]
    toggles = settings.get("schedule_toggles", {})
    fill_waiting_gaps(
        plan,
        inventory,
        settings["songs"],
        enabled=toggles.get("movie_gap_song_filler_enabled", True),
    )
    _prepend_morning_schedule(plan, inventory, settings)
    schedule_ending_songs(
        plan,
        inventory,
        settings,
        ending_song_confirmation,
        enabled=toggles.get("broadcast_ending_song_filler_enabled", True),
    )
    movie_sources = _movie_sources(inventory)
    original_movie_duration = sum(duration for _, _, duration in movie_sources)
    actual_movie_duration = sum(item.broadcast_duration_seconds for item in plan["items"] if item.media_type == "movie_segment")
    context_duration = actual_movie_duration - original_movie_duration
    ad_plays = sum(1 for item in plan["items"] if item.media_type == "ad")
    generated_at = datetime.now().astimezone()

    timeline: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "simulation_only": True,
        "broadcast_start_timestamp": plan["broadcast_start_time"],
        "media_source": inventory.get("source", {"kind": inventory.get("source_type")}),
        "settings_used": {
            "movie": settings["movie"],
            "advertisement": settings["advertisement"],
            "songs": settings["songs"],
            "morning_schedule": settings["morning_schedule"],
            "broadcast": settings["broadcast"],
            "schedule_toggles": {
                "morning_block_enabled": toggles.get("morning_block_enabled", True),
                "movie_gap_song_filler_enabled": toggles.get("movie_gap_song_filler_enabled", True),
                "broadcast_ending_song_filler_enabled": toggles.get("broadcast_ending_song_filler_enabled", True),
            },
        },
        "morning_schedule": plan["morning_schedule"],
        "ending_schedule": plan["ending_schedule"],
        "song_selection": plan["song_selection"],
        "summary": {
            "movie_count": plan["movie_count"],
            "movie_segment_count": plan["movie_segment_count"],
            "advertisement_break_count": len(plan["ad_breaks"]),
            "advertisement_play_count": ad_plays,
            "song_play_count": sum(1 for item in plan["items"] if item.media_type == "song"),
            "morning_song_play_count": sum(1 for item in plan["items"] if item.media_type == "song" and item.schedule_block == "morning"),
            "morning_song_playback_duration_seconds": sum(item.broadcast_duration_seconds for item in plan["items"] if item.media_type == "song" and item.schedule_block == "morning"),
            "morning_transition_black_duration_seconds": sum(item.broadcast_duration_seconds for item in plan["items"] if item.media_type == "black_video_placeholder" and item.schedule_block == "morning"),
            "ending_song_play_count": sum(1 for item in plan["items"] if item.media_type == "song" and item.schedule_block == "broadcast-ending"),
            "movie_gap_song_play_count": plan["song_selection"]["songs_played_count"],
            "total_song_playback_duration_seconds": sum(item.broadcast_duration_seconds for item in plan["items"] if item.media_type == "song"),
            "songs_unused_count": len(plan["song_selection"]["songs_unused"]),
            "songs_unused": plan["song_selection"]["songs_unused"],
            "song_collection_exhausted": plan["song_selection"]["song_collection_exhausted"],
            "original_movie_duration_seconds": original_movie_duration,
            "additional_context_buffer_duration_seconds": context_duration,
            "total_empty_gap_duration_seconds": plan["song_selection"]["total_remaining_empty_gap_duration_seconds"],
            "total_elapsed_broadcast_duration_seconds": plan["total_broadcast_duration_seconds"],
            "final_wall_clock_timestamp": plan["items"][-1].wall_clock_end_timestamp if plan["items"] else broadcast_start_time,
        },
        "movies": plan["movies"],
        "advertisement_breaks": plan["ad_breaks"],
        "items": [item.to_dict() for item in plan["items"]],
    }
    checks = check_timeline(inventory, plan, settings, original_movie_starts)
    timeline["consistency_checks"] = checks
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SimulationConsistencyError("Simulation consistency checks failed: " + ", ".join(failed))

    project_root = Path(__file__).resolve().parents[2]
    destination = Path(output_directory) if output_directory is not None else project_root / "videos" / "output" / "timelines"
    destination.mkdir(parents=True, exist_ok=True)
    timeline_path = destination / f"timeline_{generated_at.strftime('%Y%m%d_%H%M%S')}.json"
    temporary_path = timeline_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    temporary_path.replace(timeline_path)
    timeline["timeline_file"] = str(timeline_path.resolve())
    return timeline
