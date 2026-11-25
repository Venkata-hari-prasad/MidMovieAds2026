from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

import main as app_main  # noqa: E402
from validation.movie_validator import (  # noqa: E402
    MAX_MOVIE_DURATION_SECONDS,
    MIN_MOVIE_DURATION_SECONDS,
    validate_movies,
)


def movie_file(name: str = "movie1.mp4", duration: object = 3600) -> dict:
    record = {"filename": name, "path": f"videos/movies/movie1/{name}"}
    if duration is not MISSING:
        record["duration_seconds"] = duration
    return record


class _Missing:
    pass


MISSING = _Missing()


def folder(number: int, files: list[dict] | None = None, name: str | None = None) -> dict:
    return {
        "folder_id": name or f"movie{number}",
        "exists": True,
        "path": f"videos/movies/movie{number}",
        "files": files or [],
    }


def inventory(folders: list[dict] | None = None, **movie_fields: object) -> dict:
    movies = {"exists": True, "path": "videos/movies", "folders": folders or []}
    movies.update(movie_fields)
    return {"categories": {"movies": movies}}


class MovieValidatorTests(unittest.TestCase):
    def test_valid_sequential_folders_and_empty_trailing_folders(self) -> None:
        data = inventory([folder(1, [movie_file()]), folder(2, [movie_file("movie2.mkv")]), folder(3), folder(4), folder(5), folder(6)])
        self.assertEqual(validate_movies(data), [])

    def test_missing_trailing_folder_entries_are_empty(self) -> None:
        self.assertEqual(validate_movies(inventory([folder(1, [movie_file()])])), [])

    def test_empty_folder_followed_by_occupied_folder_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file()]), folder(2), folder(3, [movie_file("movie3.mp4")])]))
        self.assertTrue(any("MOVIE2 is empty but MOVIE3 contains a movie" in error for error in errors))

    def test_unexpected_direct_entry_in_movies_collection_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file()])], notes=["loose.mp4"]))
        self.assertTrue(any("Unexpected entry 'notes' directly" in error for error in errors))

    def test_direct_file_inside_movies_collection_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file()])], files=[movie_file("loose.mp4")]))
        self.assertTrue(any("file directly" in error for error in errors))

    def test_unexpected_folder_name_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file()], name="extra")]))
        self.assertTrue(any("Unexpected movie folder name" in error for error in errors))

    def test_folder_number_above_maximum_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file()]), folder(7, [movie_file("movie7.mp4")])]))
        self.assertTrue(any("MEDIAMOVIE-011" in error for error in errors))

    def test_empty_movies_collection_is_invalid(self) -> None:
        errors = validate_movies(inventory([]))
        self.assertTrue(any("MOVIES collection is empty" in error for error in errors))

    def test_multiple_movie_files_in_folder_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file(), movie_file("backup.mp4")])]))
        self.assertTrue(any("MEDIAMOVIE-016" in error for error in errors))

    def test_unsupported_movie_extension_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file("notes.txt")])]))
        self.assertTrue(any("MEDIAMOVIE-019" in error for error in errors))

    def test_missing_duration_metadata_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file(duration=MISSING)])]))
        self.assertTrue(any("MEDIAMOVIE-021" in error for error in errors))

    def test_zero_negative_and_non_numeric_durations_are_invalid(self) -> None:
        for duration in (0, -1, "3600", True, float("inf"), float("nan")):
            with self.subTest(duration=duration):
                errors = validate_movies(inventory([folder(1, [movie_file(duration=duration)])]))
                self.assertTrue(any("MEDIAMOVIE-022" in error for error in errors))

    def test_duration_below_minimum_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file(duration=MIN_MOVIE_DURATION_SECONDS - 1)])]))
        self.assertTrue(any("MEDIAMOVIE-023" in error for error in errors))

    def test_exact_minimum_duration_is_valid(self) -> None:
        self.assertEqual(validate_movies(inventory([folder(1, [movie_file(duration=MIN_MOVIE_DURATION_SECONDS)])])), [])

    def test_exact_maximum_duration_is_valid(self) -> None:
        self.assertEqual(validate_movies(inventory([folder(1, [movie_file(duration=MAX_MOVIE_DURATION_SECONDS)])])), [])

    def test_duration_above_maximum_is_invalid(self) -> None:
        errors = validate_movies(inventory([folder(1, [movie_file(duration=MAX_MOVIE_DURATION_SECONDS + 1)])]))
        self.assertTrue(any("MEDIAMOVIE-024" in error for error in errors))

    def test_nested_folders_are_invalid(self) -> None:
        nested = folder(1, [movie_file()])
        nested["folders"] = [{"folder_id": "movie1-part"}]
        errors = validate_movies(inventory([nested]))
        self.assertTrue(any("nested folders are not permitted" in error.lower() for error in errors))

    def test_validation_failure_stops_before_simulation(self) -> None:
        bad = inventory([folder(1, [movie_file(duration=1)])])
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "discover_media", return_value=bad) as discover, \
             patch.object(app_main, "run_simulation") as simulate, \
             contextlib.redirect_stdout(output):
            code = app_main.main()
        self.assertEqual(code, 2)
        discover.assert_called_once_with({"discovery_mode": "json"})
        simulate.assert_not_called()
        self.assertNotIn("MEDIA DISCOVERY", output.getvalue())
        self.assertIn("ERROR 1 - MEDIAMOVIE-023 - MOVIE error", output.getvalue())

    def test_successful_json_mode_prints_discovery_and_keeps_timeline_toggle(self) -> None:
        good = inventory([folder(1, [movie_file()])])
        normalized = {
            "source_type": "json",
            "source": {"kind": "json", "path": "fixture.json"},
            "categories": {
                "movies": {"exists": True, "folders": [folder(1, [movie_file()])]},
                "ads": {"exists": True, "files": []},
                "dev-songs": {"exists": True, "files": []},
                "movie-songs": {"exists": True, "files": []},
                "songs": {"exists": True, "files": []},
            },
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "discover_media", return_value=normalized), \
             patch.object(app_main, "validate_advertisements", return_value={"errors": [], "warning": None}), \
             patch.object(app_main, "validate_songs", return_value={"errors": [], "warnings": [], "skipped": False}), \
             patch.object(app_main, "load_settings", return_value={
                 "movie": {"segment_duration_minutes": 25, "allowed_start_minutes": [0, 30], "start_time_tolerance_seconds": 60},
                 "advertisement": {"repeat_count": 1},
                 "morning_schedule": {"start_time": "06:00", "dev_songs_duration_minutes": 120, "songs_duration_minutes": 60, "transition_black_duration_seconds": 10},
                 "broadcast": {"end_time": "22:00"},
             }), \
             patch.object(app_main, "run_simulation", return_value={
                 "ending_schedule": {
                     "target_finish": "22:00", "timeline_before_filler_finish": "20:00:00",
                     "status": "exact_target", "planned_finish": "22:00:00",
                 },
                 "settings_used": {"broadcast": {"end_time": "22:00"}},
                 "summary": {"final_wall_clock_timestamp": "22:00:00", "total_elapsed_broadcast_duration_seconds": 57600},
                 "broadcast_start_timestamp": "06:00:00", "movies": [], "items": [],
             }) as simulate, \
             patch.object(app_main.TerminalUI, "simulation_results") as timeline_display, \
             contextlib.redirect_stdout(output):
            code = app_main.main()
        self.assertEqual(code, 0)
        simulate.assert_called_once()
        self.assertIn("Movie media validation succeeded", output.getvalue())
        self.assertIn("MEDIA DISCOVERY", output.getvalue())
        timeline_display.assert_called_once()
        self.assertTrue(app_main.PRINT_TIMELINE_TO_TERMINAL)


if __name__ == "__main__":
    unittest.main()
