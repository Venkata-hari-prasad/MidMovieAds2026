from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

import main as app_main  # noqa: E402
from reporting.terminal_ui import TerminalUI  # noqa: E402
from validation.ad_validator import (  # noqa: E402
    MAX_AD_DURATION_SECONDS,
    MIN_AD_DURATION_SECONDS,
    validate_advertisements,
)


def ad(name: str = "ad.mp4", duration: object = 10) -> dict:
    record = {"filename": name, "path": f"videos/ads/{name}"}
    if duration is not MISSING:
        record["duration_seconds"] = duration
    return record


class _Missing:
    pass


MISSING = _Missing()


def fixture(files: list | None = None, *, folders: list | None = None) -> dict:
    return {"categories": {"ads": {"exists": True, "path": "videos/ads", "files": files or [], "folders": folders or []}}}


def settings(repeat: int = 1, segment_minutes: int = 25) -> dict:
    return {"movie": {"segment_duration_minutes": segment_minutes}, "advertisement": {"repeat_count": repeat}}


class AdvertisementValidatorTests(unittest.TestCase):
    def result(self, files: list, repeat: int = 1, segment: int = 25, folders: list | None = None) -> dict:
        return validate_advertisements(fixture(files, folders=folders), settings(repeat, segment))

    def test_valid_mp4_and_mkv(self) -> None:
        for record in (ad("spot.mp4", 5), ad("spot.mkv", 300)):
            with self.subTest(filename=record["filename"]):
                self.assertEqual(self.result([record])["errors"], [])

    def test_unsupported_extension_is_fatal(self) -> None:
        self.assertIn("MEDIAAD-008", self.result([ad("spot.avi")])["errors"][0])

    def test_uppercase_extension_is_allowed(self) -> None:
        self.assertEqual(self.result([ad("SPOT.MKV", 5)])["errors"], [])

    def test_duration_shorter_than_five_seconds_is_fatal(self) -> None:
        self.assertIn("MEDIAAD-012", self.result([ad(duration=4.99)])["errors"][0])

    def test_exact_minimum_and_maximum_duration_are_valid(self) -> None:
        self.assertEqual(self.result([ad(duration=MIN_AD_DURATION_SECONDS)])["errors"], [])
        self.assertEqual(self.result([ad(duration=MAX_AD_DURATION_SECONDS)])["errors"], [])

    def test_duration_over_five_minutes_is_fatal(self) -> None:
        self.assertIn("MEDIAAD-013", self.result([ad(duration=301)])["errors"][0])

    def test_missing_duration_is_fatal(self) -> None:
        self.assertIn("MEDIAAD-010", self.result([ad(duration=MISSING)])["errors"][0])

    def test_invalid_durations_are_fatal(self) -> None:
        for value in ("10", 0, -1, True, float("inf"), float("nan")):
            with self.subTest(duration=value):
                self.assertIn("MEDIAAD-011", self.result([ad(duration=value)])["errors"][0])

    def test_subfolder_is_fatal(self) -> None:
        self.assertIn("MEDIAAD-004", self.result([ad()], folders=[{"folder_id": "archive"}])["errors"][0])

    def test_nested_directory_in_ad_record_is_fatal(self) -> None:
        nested = ad()
        nested["folders"] = [{"name": "archive"}]
        self.assertIn("MEDIAAD-009", self.result([nested])["errors"][0])

    def test_load_below_15_percent_passes(self) -> None:
        result = self.result([ad(duration=60)])
        self.assertIsNone(result["warning"])
        self.assertAlmostEqual(result["details"]["load_percent"], 4)

    def test_load_exactly_15_percent_warns(self) -> None:
        result = self.result([ad(duration=225)])
        self.assertAlmostEqual(result["warning"]["load_percent"], 15)

    def test_load_between_15_and_30_percent_warns(self) -> None:
        result = self.result([ad(duration=300)], repeat=1, segment=20)
        self.assertAlmostEqual(result["warning"]["load_percent"], 25)

    def test_load_exactly_30_percent_warns(self) -> None:
        result = self.result([ad(duration=300)], repeat=3, segment=50)
        self.assertAlmostEqual(result["warning"]["load_percent"], 30)

    def test_load_above_30_percent_is_fatal(self) -> None:
        result = self.result([ad(duration=300)], repeat=2, segment=25)
        self.assertIn("MEDIAAD-017", result["errors"][0])
        self.assertIsNone(result["warning"])

    def test_repeat_count_changes_load_as_expected(self) -> None:
        one = self.result([ad(duration=60)], repeat=1)["details"]["load_percent"]
        two = self.result([ad(duration=60)], repeat=2)["details"]["load_percent"]
        self.assertEqual(two, one * 2)

    def test_ads_settings_alias_is_supported(self) -> None:
        self.assertAlmostEqual(self.result([ad(duration=225)])["warning"]["load_percent"], 15)
        alias = {"movie": {"segment_duration_minutes": 25}, "ads": {"repeat_count": 1}}
        self.assertEqual(validate_advertisements(fixture([ad(duration=5)]), alias)["errors"], [])

    def test_warning_accepts_yes(self) -> None:
        ui = TerminalUI(stream=io.StringIO(), color=False)
        with patch("builtins.input", side_effect=["y"]):
            self.assertTrue(ui.confirm_advertisement_load({"total_ad_duration_seconds": 225, "repeat_count": 1, "total_playback_duration_seconds": 225, "movie_segment_duration_seconds": 1500, "load_percent": 15}))

    def test_warning_rejects_no(self) -> None:
        ui = TerminalUI(stream=io.StringIO(), color=False)
        with patch("builtins.input", side_effect=["n"]):
            self.assertFalse(ui.confirm_advertisement_load({"total_ad_duration_seconds": 225, "repeat_count": 1, "total_playback_duration_seconds": 225, "movie_segment_duration_seconds": 1500, "load_percent": 15}))

    def test_invalid_confirmation_reprompts(self) -> None:
        ui = TerminalUI(stream=io.StringIO(), color=False)
        with patch("builtins.input", side_effect=["maybe", "Y"]):
            self.assertTrue(ui.confirm_advertisement_load({"total_ad_duration_seconds": 225, "repeat_count": 1, "total_playback_duration_seconds": 225, "movie_segment_duration_seconds": 1500, "load_percent": 15}))
        self.assertIn("Please enter y or n", ui.stream.getvalue())

    def test_fatal_ad_error_stops_before_discovery_and_simulation(self) -> None:
        raw = {"categories": {"movies": {"folders": [{"folder_id": "m1", "files": [
            {"filename": "movie.mp4", "path": "movie.mp4", "duration_seconds": 3600}]}]},
            "ads": {"files": [ad("bad.avi")]}}}
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json", "--simulate"]), \
             patch.object(app_main, "_load_raw_json_inventory", return_value=raw), \
             patch.object(app_main, "load_settings", return_value={
                 "movie": {"segment_duration_minutes": 25, "allowed_start_minutes": [0, 30], "start_time_tolerance_seconds": 60},
                 "advertisement": {"repeat_count": 1},
                 "morning_schedule": {"start_time": "06:00", "dev_songs_duration_minutes": 120, "songs_duration_minutes": 60, "transition_black_duration_seconds": 10},
                 "broadcast": {"end_time": "22:00"},
             }), \
             patch.object(app_main, "discover_media") as discover, \
             patch.object(app_main, "run_simulation") as simulate, \
             contextlib.redirect_stdout(output):
            code = app_main.main()
        self.assertEqual(code, 2)
        discover.assert_not_called()
        simulate.assert_not_called()
        self.assertIn("ADVERTISEMENT error", output.getvalue())
        self.assertIn("MEDIAAD-008", output.getvalue())

    def test_warning_rejection_stops_before_discovery(self) -> None:
        raw = {"categories": {"movies": {"folders": [{"folder_id": "m1", "files": [
            {"filename": "movie.mp4", "path": "movie.mp4", "duration_seconds": 3600}]}]},
            "ads": {"files": [ad("spot.mp4", 225)]}}}
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "_load_raw_json_inventory", return_value=raw), \
             patch.object(app_main, "load_settings", return_value={
                 "movie": {"segment_duration_minutes": 25, "allowed_start_minutes": [0, 30], "start_time_tolerance_seconds": 60},
                 "advertisement": {"repeat_count": 1},
                 "morning_schedule": {"start_time": "06:00", "dev_songs_duration_minutes": 120, "songs_duration_minutes": 60, "transition_black_duration_seconds": 10},
                 "broadcast": {"end_time": "22:00"},
             }), \
             patch.object(app_main, "discover_media") as discover, \
             patch("builtins.input", return_value="n"), contextlib.redirect_stdout(output):
            code = app_main.main()
        self.assertEqual(code, 2)
        discover.assert_not_called()
        self.assertIn("15.00%", output.getvalue())


if __name__ == "__main__":
    unittest.main()
