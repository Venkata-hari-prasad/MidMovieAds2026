from __future__ import annotations

from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from validation.config_validator import validate_morning_schedule  # noqa: E402
import main as app_main  # noqa: E402


class MorningConfigurationTests(unittest.TestCase):
    @staticmethod
    def settings(dev_minutes: int, regular_minutes: int) -> dict:
        return {"morning_schedule": {
            "start_time": "06:00",
            "dev_songs_duration_minutes": dev_minutes,
            "songs_duration_minutes": regular_minutes,
            "transition_black_duration_seconds": 10,
        }}

    def test_exact_180_minute_schedule_passes(self) -> None:
        self.assertEqual(validate_morning_schedule(self.settings(120, 60)), [])

    def test_different_valid_split_passes(self) -> None:
        self.assertEqual(validate_morning_schedule(self.settings(150, 30)), [])

    def test_179_minutes_fails_with_specific_code(self) -> None:
        errors = validate_morning_schedule(self.settings(120, 59))
        self.assertTrue(any("MORNING_DURATION_TOTAL_INVALID" in error for error in errors))

    def test_181_minutes_fails_with_specific_code(self) -> None:
        errors = validate_morning_schedule(self.settings(120, 61))
        self.assertTrue(any("MORNING_DURATION_TOTAL_INVALID" in error for error in errors))

    def test_block_must_end_at_the_existing_movie_start(self) -> None:
        data = self.settings(120, 60)
        data["morning_schedule"]["start_time"] = "05:00"
        self.assertTrue(any("MORNING_BLOCK_END_INVALID" in error for error in validate_morning_schedule(data)))

    def test_invalid_morning_total_stops_before_discovery_or_simulation(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--mode", "json"]), \
             patch.object(app_main, "check_license", return_value=SimpleNamespace(valid=True)), \
             patch.object(app_main, "load_settings", return_value=self.settings(120, 59)), \
             patch.object(app_main, "discover_media") as discover, \
             patch.object(app_main, "run_simulation") as simulate, \
             contextlib.redirect_stdout(output):
            result = app_main.main()
        self.assertEqual(result, 2)
        discover.assert_not_called()
        simulate.assert_not_called()
        self.assertIn("MORNING_DURATION_TOTAL_INVALID", output.getvalue())


if __name__ == "__main__":
    unittest.main()
