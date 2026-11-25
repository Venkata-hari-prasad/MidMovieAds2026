"""Discover media, run shared validation, and build the broadcast timeline."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import json

SOURCE_ROOT = Path(__file__).resolve().parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from media.media_discovery import discover_media  # noqa: E402
from config.settings_loader import load_settings  # noqa: E402
from reporting.terminal_ui import TerminalUI  # noqa: E402
from simulation.timeline_simulator import run_simulation  # noqa: E402
from validation.movie_validator import validate_movies  # noqa: E402
from validation.ad_validator import validate_advertisements  # noqa: E402
from validation.song_validator import validate_songs  # noqa: E402
from validation.config_validator import validate_morning_schedule  # noqa: E402
from validation.config_validator import validate_broadcast_end_time  # noqa: E402
from scheduling.ending_scheduler import (  # noqa: E402
    EndingSongCapacityError,
    EndingSongConfirmationRejected,
)


# Keep timeline printing controlled by a single switch; timeline generation and
# JSON output continue regardless of this display preference.
PRINT_TIMELINE_TO_TERMINAL = True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Choose a media source, validate its inventory, and build the broadcast timeline."
    )
    parser.add_argument(
        "--mode",
        choices=("json", "filesystem"),
        required=True,
        help="Select simulated JSON inventory or actual filesystem discovery.",
    )
    args = parser.parse_args()
    ui = TerminalUI()
    settings = None
    try:
        settings = load_settings()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        ui.error(f"Unable to load application settings: {exc}")
        return 1
    config_errors = validate_morning_schedule(settings) + validate_broadcast_end_time(settings)
    if config_errors:
        ui.configuration_validation_errors(config_errors)
        return 2
    try:
        inventory = discover_media({"discovery_mode": args.mode})
    except Exception as exc:
        ui.error(str(exc))
        return 1

    # Both providers return the same normalized shape. All business checks run
    # against that common inventory, never against provider-specific input.
    movie_errors = validate_movies(inventory)
    if movie_errors:
        ui.movie_validation_errors(movie_errors)
        return 2
    ui.validation_success("Movie")

    ad_result = validate_advertisements(inventory, settings)
    if ad_result["errors"]:
        ui.advertisement_validation_errors(ad_result["errors"])
        return 2
    if ad_result.get("warning") and not ui.confirm_advertisement_load(ad_result["warning"]):
        ui.status("Advertisement load declined; stopping before discovery and simulation.")
        return 2
    ui.validation_success("Advertisement")

    song_result = validate_songs(inventory, settings)
    if song_result["errors"]:
        ui.song_validation_errors(song_result["errors"])
        return 2
    for warning_number, warning in enumerate(song_result.get("warnings", []), 1):
        details = warning["details"]
        if details["collection"] == "movie-songs":
            confirmed = ui.confirm_movie_song_coverage(details, warning["code"], warning_number)
        else:
            confirmed = ui.confirm_morning_song_coverage(details, warning["code"], warning_number)
        if not confirmed:
            ui.status(f"{details['label']} coverage warning declined; stopping before discovery and simulation.")
            return 2
    if song_result.get("skipped"):
        ui.status("Song pool validation skipped; all song scheduling blocks are disabled.")
    else:
        ui.validation_success("Song")

    ui.discovery_results(inventory)

    try:
        timeline = run_simulation(
            inventory,
            settings if settings is not None else load_settings(),
            ending_song_confirmation=ui.confirm_ending_song_capacity,
        )
    except EndingSongCapacityError as exc:
        ui.ending_song_capacity_error(str(exc))
        return 2
    except EndingSongConfirmationRejected:
        ui.status("Ending-song coverage warning declined; no timeline was saved.")
        return 2
    except Exception as exc:
        ui.error(str(exc))
        return 1
    if PRINT_TIMELINE_TO_TERMINAL:
        ui.simulation_results(timeline)
    ui.broadcast_end_time_report(timeline["ending_schedule"], timeline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
