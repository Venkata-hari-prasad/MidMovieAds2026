from __future__ import annotations

from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from scheduling.ending_scheduler import (  # noqa: E402
    EndingSongCapacityError,
    assess_ending_song_capacity,
    schedule_ending_songs,
)
from validation.config_validator import validate_broadcast_end_time  # noqa: E402
from simulation import timeline_simulator  # noqa: E402
from scheduling.ending_scheduler import EndingSongConfirmationRejected  # noqa: E402


def song(path: str, duration: int) -> dict:
    return {"path": path, "filename": path.rsplit("/", 1)[-1], "duration_seconds": duration}


def sample_settings(end_time: str = "06:01") -> dict:
    return {"broadcast": {"end_time": end_time}, "songs": {"playback_order": "given", "cut_early_seconds": 5}}


class EndingSchedulerTests(unittest.TestCase):
    def test_end_time_format_validation(self) -> None:
        self.assertEqual(validate_broadcast_end_time({"broadcast": {"end_time": "22:00"}}), [])
        self.assertTrue(validate_broadcast_end_time({"broadcast": {"end_time": "24:00"}}))

    def test_capacity_threshold_inputs(self) -> None:
        self.assertEqual(assess_ending_song_capacity([song("a", 36)], 60)["coverage_percentage"], 60)
        self.assertEqual(assess_ending_song_capacity([song("a", 48)], 60)["coverage_percentage"], 80)
        self.assertGreater(assess_ending_song_capacity([song("a", 49)], 60)["coverage_percentage"], 80)

    def test_below_sixty_percent_is_fatal_without_mutating_plan(self) -> None:
        plan = {
            "broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 0,
            "items": [], "movies": [],
        }
        with self.assertRaises(EndingSongCapacityError):
            schedule_ending_songs(plan, {"categories": {"songs": {"files": [song("a", 35)]}}}, sample_settings())
        self.assertEqual(plan["items"], [])

    def test_warning_range_confirmation_and_hard_cut_finish_exactly_at_target(self) -> None:
        plan = {"broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 0, "items": []}
        inventory = {"categories": {"songs": {"files": [song("a", 24), song("b", 24)]}}}
        prompts: list[dict] = []
        report = schedule_ending_songs(plan, inventory, sample_settings(), lambda details: prompts.append(details) or True)
        self.assertEqual(report["status"], "ending_songs_scheduled")
        self.assertEqual(report["warning_code"], "ENDINGSONG-W001")
        self.assertEqual(len(prompts), 1)
        self.assertEqual(plan["total_broadcast_duration_seconds"], 60)
        self.assertEqual(plan["items"][-1].broadcast_duration_seconds, 12)
        self.assertEqual(plan["items"][-1].completion_status, "hard_cut")
        self.assertEqual(plan["items"][-1].wall_clock_end_timestamp, "06:01:00")
        self.assertTrue(all(item.schedule_block == "broadcast-ending" for item in plan["items"]))

    def test_above_eighty_percent_proceeds_without_prompt_and_cycles_without_adjacent_repeat(self) -> None:
        plan = {"broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 0, "items": []}
        inventory = {"categories": {"songs": {"files": [song("a", 55), song("b", 55)]}}}
        settings = sample_settings("06:02")
        report = schedule_ending_songs(
            plan, inventory, settings, lambda _: self.fail("coverage above 80% must not prompt")
        )
        chosen = [item.source_path for item in plan["items"]]
        self.assertGreater(report["coverage_percentage"], 80.0)
        self.assertEqual(plan["items"][-1].wall_clock_end_timestamp, "06:02:00")
        self.assertTrue(all(left.source_path != right.source_path for left, right in zip(plan["items"], plan["items"][1:])))

    def test_exact_finish_skips_capacity_and_overrun_is_informational(self) -> None:
        inventory = {"categories": {"songs": {"files": []}}}
        exact = {"broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 60, "items": []}
        exact_report = schedule_ending_songs(exact, inventory, sample_settings(), lambda _: self.fail("unexpected prompt"))
        self.assertEqual(exact_report["status"], "exact_target")
        overrun = {"broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 120, "items": []}
        overrun_report = schedule_ending_songs(overrun, inventory, sample_settings(), lambda _: self.fail("unexpected prompt"))
        self.assertEqual(overrun_report["status"], "overrun")
        self.assertEqual(overrun_report["overrun_duration_seconds"], 60)

    def test_rejected_capacity_warning_stops_before_timeline_persistence(self) -> None:
        plan = {
            "broadcast_start_time": "06:00:00", "total_broadcast_duration_seconds": 0,
            "items": [], "movies": [],
        }
        inventory = {"categories": {"songs": {"files": [song("a", 24), song("b", 24)]}}}
        settings = sample_settings()
        with TemporaryDirectory() as temporary:
            with patch.object(timeline_simulator, "build_playlist", return_value=plan), \
                 patch.object(timeline_simulator, "fill_waiting_gaps"), \
                 patch.object(timeline_simulator, "_prepend_morning_schedule"), \
                 self.assertRaises(EndingSongConfirmationRejected):
                timeline_simulator.run_simulation(
                    inventory, settings, output_directory=temporary,
                    ending_song_confirmation=lambda _: False,
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
