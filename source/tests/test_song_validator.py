from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import contextlib
from types import SimpleNamespace

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from reporting.terminal_ui import TerminalUI  # noqa: E402
import main as app_main  # noqa: E402
from scheduling.scheduler import maximum_movie_start_wait_seconds  # noqa: E402
from validation.song_validator import validate_songs  # noqa: E402


def song(name: str, duration: object = 300, path: str | None = None) -> dict:
    record = {"filename": name, "path": path or f"videos/{name}"}
    if duration is not MISSING:
        record["duration_seconds"] = duration
    return record


class _Missing:
    pass


MISSING = _Missing()


def _dev_pool() -> list[dict]:
    return [song(f"dev-base-{i}.mp4", 1800, f"videos/dev-songs/dev-base-{i}.mp4") for i in range(1, 5)]


def _regular_pool() -> list[dict]:
    return [song(f"regular-base-{i}.mp4", 1800, f"videos/songs/regular-base-{i}.mp4") for i in range(1, 3)]


def _duration_pool(total_seconds: int, category: str, prefix: str) -> list[dict]:
    durations = []
    remaining = total_seconds
    while remaining:
        duration = min(1800, remaining)
        durations.append(duration)
        remaining -= duration
    return [song(f"{prefix}{i}.mp4", duration, f"videos/{category}/{prefix}{i}.mp4") for i, duration in enumerate(durations, 1)]


def inventory(dev: list | None = None, movie: list | None = None, regular: list | None = None) -> dict:
    return {"categories": {
        "dev-songs": {"exists": True, "path": "videos/dev-songs", "files": _dev_pool() if dev is None else dev},
        "songs": {"exists": True, "path": "videos/songs", "files": _regular_pool() if regular is None else regular},
        "movie-songs": {"exists": True, "path": "videos/movie-songs", "files": movie or []},
    }}


def settings(minutes: list[int] | None = None, tolerance: int = 60) -> dict:
    return {
        "movie": {"allowed_start_minutes": [0, 30] if minutes is None else minutes, "start_time_tolerance_seconds": tolerance},
        "morning_schedule": {"start_time": "06:00", "dev_songs_duration_minutes": 120, "songs_duration_minutes": 60, "transition_black_duration_seconds": 10},
    }


class SongValidatorTests(unittest.TestCase):
    @staticmethod
    def _application_inventory(movie_song_duration: int) -> dict:
        data = inventory(movie=[song("filler.mp4", movie_song_duration)])
        data["categories"]["movies"] = {"exists": True, "folders": [{
            "folder_id": "movie1", "exists": True, "path": "videos/movies/movie1",
            "files": [{"filename": "movie.mp4", "path": "videos/movies/movie1/movie.mp4", "duration_seconds": 3600}],
        }]}
        data["categories"]["ads"] = {"exists": True, "files": []}
        return data

    @staticmethod
    def _application_settings() -> dict:
        return {
            "movie": {"segment_duration_minutes": 25, "allowed_start_minutes": [0, 30], "start_time_tolerance_seconds": 60},
            "advertisement": {"repeat_count": 1},
            "morning_schedule": {"start_time": "06:00", "dev_songs_duration_minutes": 120, "songs_duration_minutes": 60, "transition_black_duration_seconds": 10},
            "broadcast": {"end_time": "22:00"},
        }

    def test_valid_both_collections_and_cross_collection_duplicate(self) -> None:
        dev = _dev_pool() + [song("same.mp4", path="videos/dev-songs/same.mp4")]
        result = validate_songs(inventory(dev, [song("same.mp4", 1800, path="videos/movie-songs/same.mp4")]), settings())
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["warning"])

    def test_missing_collection_directory_is_fatal(self) -> None:
        data = inventory(movie=[song("filler.mp4", 1800)])
        data["categories"]["dev-songs"]["exists"] = False
        result = validate_songs(data, settings())
        self.assertTrue(any("MEDIADEVSONG-002" in error for error in result["errors"]))

    def test_missing_collection_is_fatal(self) -> None:
        data = inventory(movie=[song("filler.mp4", 1800)])
        del data["categories"]["dev-songs"]
        self.assertTrue(any("MEDIADEVSONG-001" in error for error in validate_songs(data, settings())["errors"]))

    def test_unsupported_extension_is_fatal(self) -> None:
        result = validate_songs(inventory([song("bad.avi")], [song("filler.mp4", 1800)]), settings())
        self.assertTrue(any("MEDIADEVSONG-007" in error for error in result["errors"]))

    def test_extension_matching_is_case_insensitive(self) -> None:
        result = validate_songs(inventory(_dev_pool() + [song("DEV.MKV")], [song("fill.MP4", 1800)]), settings())
        self.assertEqual(result["errors"], [])

    def test_duration_boundaries_are_inclusive(self) -> None:
        result = validate_songs(inventory(_dev_pool() + [song("min.mp4", 30), song("max.mkv", 1800)], [song("filler.mp4", 1800)]), settings())
        self.assertEqual(result["errors"], [])

    def test_regular_song_collection_uses_the_same_basic_rules(self) -> None:
        result = validate_songs(inventory(regular=_regular_pool() + [song("bad.avi", 29)]), settings())
        self.assertTrue(any("MEDIAMORNINGSONG-007" in error for error in result["errors"]))

    def test_missing_invalid_and_out_of_range_durations_are_fatal(self) -> None:
        for record in (song("missing.mp4", MISSING), song("zero.mp4", 0), song("negative.mp4", -1), song("text.mp4", "45"), song("short.mp4", 29), song("long.mp4", 1801)):
            with self.subTest(filename=record["filename"]):
                result = validate_songs(inventory([record], [song("filler.mp4", 1800)]), settings())
                self.assertTrue(result["errors"])

    def test_duplicate_within_collection_is_fatal(self) -> None:
        result = validate_songs(inventory([song("same.mp4"), song("same.mp4", path="another/same.mp4")], [song("filler.mp4", 1800)]), settings())
        self.assertTrue(any("MEDIADEVSONG-009" in error for error in result["errors"]))

    def test_coverage_below_sixty_percent_is_fatal(self) -> None:
        result = validate_songs(inventory(movie=[song("a.mp4", 1000)]), settings())
        self.assertTrue(any("MEDIAMOVIESONG-016" in error for error in result["errors"]))
        self.assertAlmostEqual(result["details"]["coverage_percentage"], 1000 / 1740 * 100)

    def test_exactly_sixty_percent_warns(self) -> None:
        result = validate_songs(inventory(movie=[song("a.mp4", 522), song("b.mp4", 522)]), settings())
        self.assertAlmostEqual(result["warning"]["coverage_percentage"], 60)
        self.assertEqual(result["warning_code"], "MEDIAMOVIESONG-W001")

    def test_between_sixty_and_eighty_warns(self) -> None:
        result = validate_songs(inventory(movie=[song("a.mp4", 1200)]), settings())
        self.assertGreater(result["warning"]["coverage_percentage"], 60)
        self.assertLess(result["warning"]["coverage_percentage"], 80)

    def test_exactly_eighty_percent_and_above_pass(self) -> None:
        exact = validate_songs(inventory(movie=[song("a.mp4", 696), song("b.mp4", 696)]), settings())
        above = validate_songs(inventory(movie=[song("a.mp4", 1500)]), settings())
        self.assertIsNone(exact["warning"])
        self.assertAlmostEqual(exact["details"]["coverage_percentage"], 80)
        self.assertIsNone(above["warning"])

    def test_maximum_gap_matches_scheduler_tolerance_semantics(self) -> None:
        self.assertEqual(maximum_movie_start_wait_seconds([0], 60), 3540)
        self.assertEqual(maximum_movie_start_wait_seconds([0, 30], 60), 1740)
        self.assertEqual(maximum_movie_start_wait_seconds([0, 15, 30, 45], 60), 840)
        self.assertEqual(maximum_movie_start_wait_seconds([0, 10, 40], 500), 1300)

    def test_coverage_uses_changed_allowed_start_marks(self) -> None:
        result = validate_songs(inventory(movie=[song("filler.mp4", 1800)]), settings([0], 60))
        self.assertEqual(result["details"]["maximum_filler_gap_seconds"], 3540)

    def test_morning_collection_coverage_boundaries_are_inclusive(self) -> None:
        cases = (
            (4314, "MEDIADEVSONG-W001", True),   # exactly 60% after the transition holdback
            (5752, "MEDIADEVSONG-W001", True),   # exactly 80%: still a warning
            (6000, "MEDIADEVSONG-W001", False),  # above 80%: pass
        )
        for available, warning_code, expected_warning in cases:
            with self.subTest(available=available):
                result = validate_songs(
                    inventory(dev=_duration_pool(available, "dev-songs", "coverage"), movie=[song("filler.mp4", 1800)]),
                    settings(),
                )
                has_warning = any(warning["code"] == warning_code for warning in result["warnings"])
                self.assertEqual(has_warning, expected_warning)
                self.assertFalse(result["errors"])

    def test_morning_collection_below_sixty_percent_is_fatal(self) -> None:
        result = validate_songs(
            inventory(dev=_duration_pool(4313, "dev-songs", "low"), movie=[song("filler.mp4", 1800)]),
            settings(),
        )
        self.assertTrue(any("MEDIADEVSONG-016" in error for error in result["errors"]))

    def test_regular_song_coverage_uses_its_configured_duration(self) -> None:
        config = settings()
        config["morning_schedule"].update({"dev_songs_duration_minutes": 150, "songs_duration_minutes": 30})
        result = validate_songs(inventory(
            dev=_duration_pool(9000, "dev-songs", "dev"),
            regular=_duration_pool(1074, "songs", "regular"),
            movie=[song("filler.mp4", 1800)],
        ), config)
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["MEDIAMORNINGSONG-W001"])
        self.assertEqual(result["warnings"][0]["details"]["collection"], "songs")
        self.assertEqual(result["warnings"][0]["details"]["required_duration_seconds"], 1790)

    def test_invalid_alignment_settings_do_not_assume_a_gap(self) -> None:
        result = validate_songs(inventory(movie=[song("filler.mp4", 1800)]), settings([]))
        self.assertTrue(any("MEDIAMOVIESONG-015" in error for error in result["errors"]))

    def test_confirmation_accepts_rejects_and_retries_invalid_input(self) -> None:
        details = {"maximum_filler_gap_seconds": 1740, "total_unique_movie_song_duration_seconds": 1200, "coverage_percentage": 68.97}
        ui = TerminalUI(stream=io.StringIO(), color=False)
        with patch("builtins.input", side_effect=["what", "y"]):
            self.assertTrue(ui.confirm_movie_song_coverage(details, "MEDIAMOVIESONG-W001"))
        self.assertIn("Please enter y or n", ui.stream.getvalue())
        with patch("builtins.input", return_value="n"):
            self.assertFalse(ui.confirm_movie_song_coverage(details, "MEDIAMOVIESONG-W001"))

    def test_morning_coverage_warning_prompts_again_and_uses_code(self) -> None:
        details = {"label": "Devotional songs", "required_duration_seconds": 7200,
                   "available_unique_duration_seconds": 5400, "coverage_percentage": 75}
        ui = TerminalUI(stream=io.StringIO(), color=False)
        with patch("builtins.input", side_effect=["invalid", "y"]):
            self.assertTrue(ui.confirm_morning_song_coverage(details, "MEDIADEVSONG-W001"))
        self.assertIn("MEDIADEVSONG-W001", ui.stream.getvalue())
        self.assertIn("Required duration", ui.stream.getvalue())
        self.assertIn("Available unique duration", ui.stream.getvalue())
        self.assertIn("Please enter y or n", ui.stream.getvalue())

    def test_song_fatal_error_stops_before_discovery_and_simulation(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "discover_media", return_value=self._application_inventory(300)) as discover, \
             patch.object(app_main, "load_settings", return_value=self._application_settings()), \
             patch.object(app_main, "run_simulation") as simulate, \
             contextlib.redirect_stdout(output):
            result = app_main.main()
        self.assertEqual(result, 2)
        discover.assert_called_once_with({"discovery_mode": "json"})
        simulate.assert_not_called()
        self.assertIn("MEDIAMOVIESONG-016", output.getvalue())

    def test_rejected_song_capacity_warning_stops_before_discovery(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "discover_media", return_value=self._application_inventory(1044)) as discover, \
             patch.object(app_main, "load_settings", return_value=self._application_settings()), \
             patch("builtins.input", return_value="n"), contextlib.redirect_stdout(output):
            result = app_main.main()
        self.assertEqual(result, 2)
        discover.assert_called_once_with({"discovery_mode": "json"})
        self.assertIn("MEDIAMOVIESONG-W001", output.getvalue())

    def test_accepted_song_capacity_warning_continues_to_discovery(self) -> None:
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "load_settings", return_value=self._application_settings()), \
             patch.object(app_main, "discover_media", return_value=self._application_inventory(1044)) as discover, \
             patch.object(app_main.TerminalUI, "discovery_results"), \
             patch.object(app_main, "run_simulation", return_value={"ending_schedule": {}}), \
             patch.object(app_main.TerminalUI, "simulation_results"), \
             patch.object(app_main.TerminalUI, "broadcast_end_time_report"), \
             patch("builtins.input", return_value="y"):
            result = app_main.main()
        self.assertEqual(result, 0)
        discover.assert_called_once()


if __name__ == "__main__":
    unittest.main()
