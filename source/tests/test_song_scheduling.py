from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from config.settings_loader import load_settings  # noqa: E402
from core.models import TimelineItem  # noqa: E402
from media.media_discovery import discover_media  # noqa: E402
from scheduling.song_scheduler import SongSelectionState, fill_one_gap  # noqa: E402
from scheduling.morning_scheduler import build_morning_schedule  # noqa: E402
from simulation.timeline_simulator import run_simulation  # noqa: E402


def make_gap(duration: int, gap_id: str = "gap-test") -> TimelineItem:
    return TimelineItem(
        sequence=1,
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
        elapsed_broadcast_start_seconds=0,
        elapsed_broadcast_end_seconds=duration,
        broadcast_duration_seconds=duration,
        wall_clock_start_timestamp="10:00:00",
        wall_clock_end_timestamp=f"10:{duration // 60:02d}:{duration % 60:02d}",
        reason="Waiting for the next eligible movie start.",
        gap_id=gap_id,
        waiting_gap_id=gap_id,
    )


def songs_with_durations(*durations: int) -> list[dict[str, object]]:
    return [
        {
            "filename": f"song{index}.mp4",
            "path": f"simulated/song{index}.mp4",
            "duration_seconds": duration,
            "category": "songs",
            "source_type": "json",
        }
        for index, duration in enumerate(durations, 1)
    ]


class SongSelectionTests(unittest.TestCase):
    def test_morning_schedule_has_sequential_devotional_and_regular_blocks(self) -> None:
        inventory = discover_media({"discovery_mode": "json"})
        morning = build_morning_schedule(inventory, load_settings())
        self.assertEqual(morning["start_timestamp"], "06:00:00")
        self.assertEqual(morning["end_timestamp"], "09:00:00")
        self.assertEqual(
            [(section["collection"], section["wall_clock_start_timestamp"], section["wall_clock_end_timestamp"])
             for section in morning["sections"]],
            [("dev-songs", "06:00:00", "08:00:00"), ("songs", "08:00:00", "09:00:00")],
        )
        categories = [item.source_category for item in morning["items"]]
        first_regular = categories.index("songs")
        self.assertTrue(all(category == "dev-songs" for category in categories[:first_regular]))
        self.assertTrue(all(category == "songs" for category in categories[first_regular:]))
        self.assertEqual(sum(item.media_type == "black_video_placeholder" for item in morning["items"]), 2)
        self.assertEqual(
            [(item.wall_clock_start_timestamp, item.wall_clock_end_timestamp)
             for item in morning["items"] if item.media_type == "black_video_placeholder"],
            [("07:59:50", "08:00:00"), ("08:59:50", "09:00:00")],
        )

    def test_morning_schedule_reuses_short_pools_until_boundaries(self) -> None:
        inventory = {"categories": {
            "dev-songs": {"files": [{"filename": "dev.mp4", "path": "dev.mp4", "duration_seconds": 1800}]},
            "songs": {"files": [{"filename": "regular.mp4", "path": "regular.mp4", "duration_seconds": 1800}]},
        }}
        settings = load_settings()
        settings["songs"]["playback_order"] = "given"
        morning = build_morning_schedule(inventory, settings)
        dev_items = [item for item in morning["items"] if item.source_category == "dev-songs" and item.media_type == "song"]
        regular_items = [item for item in morning["items"] if item.source_category == "songs" and item.media_type == "song"]
        self.assertEqual(len(dev_items), 4)
        self.assertEqual(len(regular_items), 2)
        self.assertEqual(len({item.source_path for item in dev_items}), 1)
        self.assertEqual(len({item.source_path for item in regular_items}), 1)

    def test_morning_schedule_hard_cuts_final_song_at_collection_boundary(self) -> None:
        inventory = {"categories": {
            "dev-songs": {"files":[
                {"filename": f"dev{i}.mkv", "path": f"dev{i}.mkv", "duration_seconds": duration}
                for i, duration in enumerate([1200, 1200, 1200, 1200, 1200, 1300], 1)
            ]},
            "songs": {"files": [
                {"filename": f"regular{i}.mp4", "path": f"regular{i}.mp4", "duration_seconds": 1800}
                for i in range(2)
            ]},
        }}
        settings = load_settings()
        settings["songs"]["playback_order"] = "given"
        morning = build_morning_schedule(inventory, settings)
        last_dev = [item for item in morning["items"] if item.source_category == "dev-songs" and item.media_type == "song"][-1]
        self.assertEqual(last_dev.broadcast_duration_seconds, 1190)
        self.assertEqual(last_dev.source_duration_seconds, 1300)
        self.assertEqual(last_dev.completion_status, "hard_cut")
        self.assertEqual(last_dev.wall_clock_end_timestamp, "07:59:50")

    def test_selection_cycle_resets_for_each_gap(self) -> None:
        songs = songs_with_durations(100, 100, 100)
        state = SongSelectionState(songs, "given")
        first, _ = fill_one_gap(make_gap(150, "gap-1"), state, 0)
        state.reset_for_gap()
        second, _ = fill_one_gap(
            TimelineItem(**{**make_gap(100, "gap-2").__dict__,
                           "elapsed_broadcast_start_seconds": 150,
                           "elapsed_broadcast_end_seconds": 250,
                           "wall_clock_start_timestamp": "10:02:30",
                           "wall_clock_end_timestamp": "10:04:10"}),
            state,
            0,
        )
        played = [item.source_filename for item in first + second if item.media_type == "song"]
        self.assertEqual(played, ["song1.mp4", "song2.mp4", "song1.mp4"])

    def test_random_shuffles_once_then_consumes_that_order(self) -> None:
        songs = songs_with_durations(10, 10, 10)
        with patch("scheduling.song_scheduler.random.shuffle", side_effect=lambda values: values.reverse()) as shuffle:
            state = SongSelectionState(songs, "random")
            order = [state.take_next()["filename"] for _ in songs]
        shuffle.assert_called_once()
        self.assertEqual(order, ["song3.mp4", "song2.mp4", "song1.mp4"])

    def test_song_exactly_fits_usable_window_and_reserve_remains(self) -> None:
        state = SongSelectionState(songs_with_durations(300), "given")
        items, records = fill_one_gap(make_gap(305), state, 5)
        self.assertEqual([i.media_type for i in items], ["song", "empty_gap"])
        self.assertEqual(items[0].completion_status, "completed_naturally")
        self.assertEqual(items[1].broadcast_duration_seconds, 5)
        self.assertEqual(records[0]["played_duration_seconds"], 300)

    def test_song_is_hard_cut_at_usable_boundary(self) -> None:
        state = SongSelectionState(songs_with_durations(300), "given")
        items, _ = fill_one_gap(make_gap(200), state, 5)
        self.assertEqual(items[0].completion_status, "hard_cut")
        self.assertEqual(items[0].broadcast_duration_seconds, 195)
        self.assertEqual(items[0].wall_clock_end_timestamp, "10:03:15")
        self.assertEqual(items[-1].broadcast_duration_seconds, 5)

    def test_no_song_selected_when_gap_has_only_reserved_time(self) -> None:
        state = SongSelectionState(songs_with_durations(10), "given")
        items, records = fill_one_gap(make_gap(5), state, 15)
        self.assertEqual(records, [])
        self.assertEqual([item.media_type for item in items], ["empty_gap"])
        self.assertEqual(items[0].broadcast_duration_seconds, 5)
        self.assertEqual(state.unused_songs[0]["filename"], "song1.mp4")

    def test_cut_early_zero_exact_fit_leaves_no_gap(self) -> None:
        state = SongSelectionState(songs_with_durations(300), "given")
        items, _ = fill_one_gap(make_gap(300), state, 0)
        self.assertEqual([item.media_type for item in items], ["song"])
        self.assertEqual(items[0].completion_status, "completed_naturally")

    def test_cut_early_fifteen_reserves_fifteen_seconds(self) -> None:
        state = SongSelectionState(songs_with_durations(300), "given")
        items, _ = fill_one_gap(make_gap(315), state, 15)
        self.assertEqual(items[0].broadcast_duration_seconds, 300)
        self.assertEqual(items[1].broadcast_duration_seconds, 15)

    def test_inventory_exhaustion_restarts_cycle_to_fill_gap(self) -> None:
        state = SongSelectionState(songs_with_durations(100), "given")
        items, _ = fill_one_gap(make_gap(500), state, 15)
        self.assertTrue(state.exhausted)
        self.assertEqual(sum(item.media_type == "song" for item in items), 5)
        self.assertEqual(items[-1].media_type, "empty_gap")
        self.assertEqual(items[-1].broadcast_duration_seconds, 15)

    def test_cycle_boundary_avoids_immediate_repeat_when_possible(self) -> None:
        state = SongSelectionState(songs_with_durations(100, 100), "given")
        items, _ = fill_one_gap(make_gap(500), state, 0)
        names = [item.source_filename for item in items if item.media_type == "song"]
        self.assertEqual(names, ["song1.mp4", "song2.mp4", "song1.mp4", "song2.mp4", "song1.mp4"])

    def test_full_simulation_preserves_movie_starts_ads_and_no_repeat(self) -> None:
        inventory = discover_media({"discovery_mode": "json"})
        # Keep the scheduling regression fixture independent from the shared
        # inventory, which may deliberately be edited for validation testing.
        inventory["categories"]["movies"]["folders"] = [
            {
                "folder_id": f"m{index}",
                "exists": True,
                "path": f"videos/movies/m{index}",
                "files": [{
                    "filename": f"movie{index}.mp4",
                    "path": f"videos/movies/m{index}/movie{index}.mp4",
                    "duration_seconds": duration,
                    "category": "movies",
                    "source_type": "json",
                }],
            }
            for index, duration in enumerate((8142, 8725, 7938, 8964), 1)
        ]
        # Preserve this regression's original two-ad schedule while the shared
        # JSON fixture is used for separate advertisement-validation testing.
        inventory["categories"]["ads"]["files"] = [
            {"filename": "ad1.mp4", "path": "videos/ads/ad1.mp4", "duration_seconds": 11},
            {"filename": "ad2.mp4", "path": "videos/ads/ad2.mp4", "duration_seconds": 9},
        ]
        settings = load_settings()
        settings["movie"]["segment_duration_minutes"] = 25
        settings["advertisement"]["repeat_count"] = 1
        settings["songs"]["playback_order"] = "given"
        # This fixture's existing timeline runs past 18:00, exercising the
        # informational overrun path without requiring ending-song capacity.
        settings["broadcast"]["end_time"] = "18:00"
        with tempfile.TemporaryDirectory() as temporary:
            timeline = run_simulation(inventory, settings, output_directory=temporary)
            self.assertTrue(Path(timeline["timeline_file"]).is_file())
            json.loads(Path(timeline["timeline_file"]).read_text(encoding="utf-8"))

        self.assertEqual(
            [movie["wall_clock_start_timestamp"] for movie in timeline["movies"]],
            ["09:00:00", "11:30:00", "13:59:05", "16:30:00"],
        )
        self.assertEqual(timeline["summary"]["movie_segment_count"], 23)
        self.assertEqual(timeline["summary"]["advertisement_break_count"], 22)
        self.assertEqual(timeline["summary"]["advertisement_play_count"], 44)
        self.assertEqual(timeline["broadcast_start_timestamp"], "06:00:00")
        self.assertEqual(
            [(section["collection"], section["wall_clock_start_timestamp"], section["wall_clock_end_timestamp"])
             for section in timeline["morning_schedule"]["sections"]],
            [("dev-songs", "06:00:00", "08:00:00"), ("songs", "08:00:00", "09:00:00")],
        )
        first_movie_index = next(index for index, item in enumerate(timeline["items"]) if item["media_type"] == "movie_segment")
        morning_prefix = timeline["items"][:first_movie_index]
        self.assertTrue(all(item["media_type"] in ("song", "black_video_placeholder") for item in morning_prefix))
        self.assertEqual(sum(item["media_type"] == "black_video_placeholder" for item in morning_prefix), 2)
        self.assertEqual(timeline["movies"][0]["wall_clock_start_timestamp"], "09:00:00")
        song_items = [item for item in timeline["items"] if item["media_type"] == "song" and item["source_category"] == "movie-songs"]
        self.assertTrue(all(item["source_path"].startswith("videos/movie-songs/") for item in song_items))
        self.assertTrue(all(item["completion_status"] in ("completed_naturally", "hard_cut") for item in song_items))
        self.assertTrue(all(timeline["consistency_checks"].values()))


if __name__ == "__main__":
    unittest.main()
