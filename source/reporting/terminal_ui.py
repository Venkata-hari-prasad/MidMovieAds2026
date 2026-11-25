"""Formatted terminal output for application status and discovery inventories."""

from __future__ import annotations

import sys
from typing import Any, TextIO

try:
    from ..core.models import format_clock
except ImportError:  # source directory used directly on sys.path
    from core.models import format_clock


class TerminalUI:
    """Owns user-facing terminal messages; it does not discover or validate media."""

    def __init__(self, stream: TextIO | None = None, color: bool | None = None) -> None:
        self.stream = stream or sys.stdout
        self.color = self.stream.isatty() if color is None else color

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    @staticmethod
    def _short_filename(filename: str, max_width: int = 25) -> str:
        """Keep render rows compact while retaining the generated prefix and file suffix."""
        if len(filename) <= max_width:
            return filename
        stem, dot, suffix = filename.rpartition(".")
        extension = f"{dot}{suffix}" if dot else ""
        prefix = filename[: min(12, max_width // 3)]
        tail_width = max(1, max_width - len(prefix) - len(extension) - 1)
        return f"{prefix}…{stem[-tail_width:]}{extension}"

    def status(self, message: str) -> None:
        print(self._paint(message, "36"), file=self.stream)

    def license_check_result(self, result: Any) -> None:
        """Show the activation result and the machine fingerprint when action is needed."""
        if result.valid:
            print(self._paint("LICENSE CHECK PASSED", "1;32"), file=self.stream)
            return
        print(self._paint(f"LICENSE ERROR {result.code}: {result.message}", "1;31"), file=self.stream)
        if result.fingerprint:
            print(self._paint(f"  Machine fingerprint: {result.fingerprint}", "1;33"), file=self.stream)

    def render_started(self, timeline_path: str, item_count: int, output_directory: str) -> None:
        """Show the input blueprint and isolated render destination."""
        print(self._paint("\nMIDMOVIEADS-2026  |  RENDER", "1;36"), file=self.stream)
        print("STREAM COPY ONLY - source streams are not re-encoded.", file=self.stream)
        print(f"  Timeline      : {timeline_path}", file=self.stream)
        print(f"  Output files  : {item_count}", file=self.stream)
        print(f"  Output folder : {output_directory}", file=self.stream)

    def render_progress(self, sequence: int, total: int, filename: str) -> None:
        """Display one output file as it is rendered."""
        print(
            f"  [{sequence:0{3 if total < 1000 else 4}d}/{total}] {self._short_filename(filename)}",
            file=self.stream,
        )

    def render_item_drift(
        self,
        filename: str,
        planned_duration: float,
        actual_duration: float,
        drift_seconds: float,
        drift_limit: float,
    ) -> None:
        """Show the planned and measured duration for every rendered item."""
        label = "WARNING" if abs(drift_seconds) > 0.001 else "OK"
        color = "1;33" if label == "WARNING" else "32"
        print(self._paint(
            f"    {label} {self._short_filename(filename)} | expected {planned_duration:.3f}s | "
            f"actual {actual_duration:.3f}s | drift {drift_seconds:+.3f}s (limit ±{drift_limit:g}s)",
            color,
        ), file=self.stream)

    @staticmethod
    def _clock_after(timestamp: str, elapsed_seconds: float) -> str:
        hour, minute, second = (int(part) for part in timestamp.split(":"))
        total = (hour * 3600 + minute * 60 + second + int(round(elapsed_seconds))) % 86400
        hour, remainder = divmod(total, 3600)
        minute, second = divmod(remainder, 60)
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    def render_timing_report(
        self,
        timeline: dict[str, Any],
        rendered_items: list[dict[str, Any]],
        final_drift: float,
        worst_cumulative_drift: float,
    ) -> None:
        """Compare the planned broadcast clock with measured sequential render times."""
        if not rendered_items:
            return
        broadcast_start = timeline["broadcast_start_timestamp"]
        actual_elapsed = 0.0
        for rendered in rendered_items:
            rendered["actual_elapsed_start"] = actual_elapsed
            actual_elapsed += rendered["actual_duration"]
            rendered["actual_elapsed_end"] = actual_elapsed

        print(self._paint("\nCOMPLETE BROADCAST TIMELINE — EXPECTED VS ACTUAL", "1;34"), file=self.stream)
        for rendered in rendered_items:
            actual_start = self._clock_after(broadcast_start, rendered["actual_elapsed_start"])
            actual_end = self._clock_after(broadcast_start, rendered["actual_elapsed_end"])
            delta = rendered["drift"]
            label = (
                f"  {rendered['sequence']:03d} {rendered['media_type']} — "
                f"{self._short_filename(rendered['filename'])}"
            )
            detail = (
                f"      Expected {rendered['expected_start']}–{rendered['expected_end']}"
                f" | Actual {actual_start}–{actual_end}"
                f" | Drift {delta:+.3f}s (limit ±{rendered['drift_limit']:g}s)"
            )
            color = "1;33" if abs(delta) > 0.001 else "0"
            print(self._paint(label, color), file=self.stream)
            print(self._paint(detail, color), file=self.stream)

        expected_finish = timeline["summary"].get("final_wall_clock_timestamp")
        actual_finish = self._clock_after(broadcast_start, actual_elapsed)
        print(self._paint("\nBROADCAST TIMING SUMMARY", "1;36"), file=self.stream)
        print(f"  Expected broadcast finish : {expected_finish}", file=self.stream)
        print(
            f"  Actual rendered finish    : {self._paint(actual_finish, '32')}",
            file=self.stream,
        )
        print(f"  Final runtime difference  : {final_drift:+.3f}s", file=self.stream)
        print(f"  Worst cumulative drift    : {worst_cumulative_drift:+.3f}s", file=self.stream)

        planned_duration = sum(row["expected_duration"] for row in rendered_items)
        rendered_duration = sum(row["actual_duration"] for row in rendered_items)
        print(self._paint("\nRENDER TIMING REVIEW", "1;33"), file=self.stream)
        print(f"  Planned runtime          : {self._duration(planned_duration)}", file=self.stream)
        print(
            f"  Rendered runtime         : {self._paint(self._duration(rendered_duration), '32')}",
            file=self.stream,
        )
        print(f"  Final runtime difference : {final_drift:+.3f}s", file=self.stream)
        print(f"  Worst cumulative drift   : {worst_cumulative_drift:+.3f}s", file=self.stream)

        print(self._paint("\nMOVIE START / FINISH COMPARISON", "1;34"), file=self.stream)
        for movie_number, movie in enumerate(timeline.get("movies", []), 1):
            movie_items = [
                row for row in rendered_items
                if row["media_type"] == "movie_segment"
                and row["movie_folder"] == movie.get("movie_folder")
                and row["source_path"] == movie.get("source_path")
            ]
            if not movie_items:
                continue
            first, last = movie_items[0], movie_items[-1]
            actual_movie_start = self._clock_after(broadcast_start, first["actual_elapsed_start"])
            actual_movie_finish = self._clock_after(broadcast_start, last["actual_elapsed_end"])
            movie_drift = sum(row["drift"] for row in movie_items)
            label = f"MOVIE {movie_number} — {movie.get('movie_folder', '')} " \
                f"{self._short_filename(movie.get('movie_name', 'movie'))}"
            print(f"  {label}", file=self.stream)
            print(
                f"    Start  | expected {self._paint(movie['wall_clock_start_timestamp'], '33')} "
                f"| actual {self._paint(actual_movie_start, '35')}",
                file=self.stream,
            )
            print(
                f"    Finish | expected {self._paint(movie['wall_clock_finish_timestamp'], '33')} "
                f"| actual {self._paint(actual_movie_finish, '35')} "
                f"| segment drift {self._paint(f'{movie_drift:+.3f}s', '36')}",
                file=self.stream,
            )

    def confirm_render_drift(self) -> bool:
        """Ask before publishing after the complete timing report is displayed."""
        while True:
            try:
                answer = input("Publish these clips with the reported timing drift? (y/n): ").strip().lower()
            except EOFError:
                return False
            if answer in {"y", "n"}:
                return answer == "y"
            self.warning("Please enter y or n.")

    def render_completed(
        self,
        output_directory: str,
        file_count: int,
        planned_duration: float,
        rendered_duration: float,
        worst_cumulative_drift: float,
    ) -> None:
        """Report the successfully published render folder."""
        print(self._paint("\nRENDER COMPLETE", "1;32"), file=self.stream)
        print(f"  Individual clips : {file_count}", file=self.stream)
        print(f"  Timeline runtime : {self._duration(planned_duration)}", file=self.stream)
        print(f"  Clip runtime     : {self._duration(rendered_duration)}", file=self.stream)
        delta = rendered_duration - planned_duration
        print(f"  Final drift      : {delta:+.3f}s", file=self.stream)
        print(f"  Worst cumulative : {worst_cumulative_drift:+.3f}s", file=self.stream)
        print(f"  VMix folder      : {output_directory}", file=self.stream)

    def render_error(self, message: str) -> None:
        """Display a coded render failure."""
        self.error(f"RENDER-001 - {message}")

    def recovery_result(self, result: dict[str, Any]) -> None:
        """Display a wall-clock recovery lookup without doing timeline logic."""
        print(self._paint("\nBROADCAST RECOVERY LOOKUP", "1;36"), file=self.stream)
        print("=" * 72, file=self.stream)
        print(f"  Current system time : {result['current_time']}", file=self.stream)
        print(f"  Timeline            : {result['timeline_path']}", file=self.stream)
        if result.get("simulation_only"):
            print(self._paint(
                "  SIMULATION TIMELINE: media paths are references; file existence is not confirmed.",
                "1;33",
            ), file=self.stream)

        status = result["status"]
        if status == "finished":
            print(self._paint("\n  TIMELINE FINISHED — current time is past its final scheduled item.", "1;31"), file=self.stream)
            print(f"  Scheduled finish    : {result['final_wall_clock_time']}", file=self.stream)
            return
        if status == "before_start":
            print(self._paint("\n  TIMELINE NOT STARTED — current time is before its broadcast start.", "1;33"), file=self.stream)
            print(f"  Scheduled start     : {result['broadcast_start_time']}", file=self.stream)
            return
        if status == "unavailable":
            print(self._paint(f"\n  RECOVERY POSITION UNAVAILABLE — {result['message']}", "1;31"), file=self.stream)
            return

        item = result["item"]
        print(self._paint("\n  PLAY THIS TIMELINE ITEM NOW", "1;32"), file=self.stream)
        print(self._paint(
            f"  TIMELINE ITEM       : #{item.get('sequence', '—')}",
            "1;35",
        ), file=self.stream)
        print(f"  Media type          : {item.get('media_type', '—')}", file=self.stream)
        if item.get("movie_folder"):
            print(f"  Movie folder        : {item['movie_folder']}", file=self.stream)
        if item.get("segment_number") is not None:
            segment = str(item["segment_number"])
            if item.get("segment_count") is not None:
                segment += f" / {item['segment_count']}"
            print(f"  Segment             : {segment}", file=self.stream)
        print(f"  Media filename      : {item.get('source_filename') or '—'}", file=self.stream)
        print(f"  Media path          : {item.get('source_path') or '—'}", file=self.stream)
        print(f"  Scheduled interval : {item.get('wall_clock_start_timestamp', '—')} – "
              f"{item.get('wall_clock_end_timestamp', '—')}", file=self.stream)
        if item.get("seek_position_seconds") is not None:
            print(self._paint(
                f"  SEEK POSITION       : {item['seek_position_timestamp']} "
                f"({item['seek_position_seconds']:.3f} seconds)",
                "1;34",
            ), file=self.stream)
            print("  Resume guidance     : Start this source at the seek position; follow the saved timeline from here.", file=self.stream)
        else:
            print(f"  Playback guidance   : {result.get('playback_guidance', 'No source seek position applies.')}", file=self.stream)

    def error(self, message: str) -> None:
        print(self._paint(f"ERROR  {message}", "1;31"), file=self.stream)

    def warning(self, message: str) -> None:
        print(self._paint(f"WARNING  {message}", "1;33"), file=self.stream)

    def validation_success(self, category: str) -> None:
        print(self._paint(f"{category} media validation succeeded.", "1;32"), file=self.stream)

    def movie_validation_errors(self, errors: list[str]) -> None:
        """Print fatal movie inventory errors with stable sequential numbering."""
        for number, message in enumerate(errors, 1):
            code, separator, description = message.partition(": ")
            if not separator or not code.startswith("MEDIAMOVIE-"):
                code, description = "MEDIAMOVIE-000", message
            line = f"ERROR {number} - {code} - MOVIE error - {description}"
            print(self._paint(line, "1;31"), file=self.stream)

    def advertisement_validation_errors(self, errors: list[str]) -> None:
        """Print fatal advertisement errors with unique stable codes."""
        for number, message in enumerate(errors, 1):
            code, separator, description = message.partition(": ")
            if not separator or not code.startswith("MEDIAAD-"):
                code, description = "MEDIAAD-000", message
            line = f"ERROR {number} - {code} - ADVERTISEMENT error - {description}"
            print(self._paint(line, "1;31"), file=self.stream)

    def song_validation_errors(self, errors: list[str]) -> None:
        """Print devotional and movie-song fatal errors with stable codes."""
        for number, message in enumerate(errors, 1):
            code, separator, description = message.partition(": ")
            if not separator or not code.startswith(("MEDIADEVSONG-", "MEDIAMOVIESONG-")):
                code, description = "MEDIASONG-000", message
            category = "DEVOTIONAL SONG" if code.startswith("MEDIADEVSONG-") else "MOVIE SONG"
            line = f"ERROR {number} - {code} - {category} error - {description}"
            print(self._paint(line, "1;31"), file=self.stream)

    def configuration_validation_errors(self, errors: list[str]) -> None:
        """Print coded configuration failures in the shared fatal-error style."""
        for number, message in enumerate(errors, 1):
            code, separator, description = message.partition(": ")
            if not separator or not code.startswith(("MORNING_", "BROADCAST_", "SCHEDULE_")):
                code, description = "CONFIG-000", message
            line = f"ERROR {number} - {code} - CONFIGURATION error - {description}"
            print(self._paint(line, "1;31"), file=self.stream)

    def confirm_movie_song_coverage(self, details: dict[str, int | float], code: str, number: int = 1) -> bool:
        """Display the one capacity warning and require explicit y/n consent."""
        line = f"WARNING {number} - {code} - MOVIE SONG warning - Movie-song coverage is below the recommended 80%."
        print(self._paint(line, "1;33"), file=self.stream)
        print(f"  Maximum possible filler gap       : {self._duration(details['maximum_filler_gap_seconds'])}", file=self.stream)
        print(f"  Total unique movie-song duration  : {self._duration(details['total_unique_movie_song_duration_seconds'])}", file=self.stream)
        print(f"  Coverage                          : {details['coverage_percentage']:.2f}%", file=self.stream)
        print("  Songs may repeat after the unique collection is exhausted.", file=self.stream)
        while True:
            answer = input("Do you want to continue with this movie-song library? (y/n): ").strip().lower()
            if answer in {"y", "n"}:
                return answer == "y"
            self.warning("Please enter y or n.")

    def confirm_morning_song_coverage(self, details: dict[str, str | int | float], code: str, number: int = 1) -> bool:
        """Display and confirm one devotional or regular song coverage warning."""
        label = str(details["label"])
        line = f"WARNING {number} - {code} - {label.upper()} warning - Collection coverage is between 60% and 80%."
        print(self._paint(line, "1;33"), file=self.stream)
        print(f"  Required duration        : {self._duration(details['required_duration_seconds'])}", file=self.stream)
        print(f"  Available unique duration: {self._duration(details['available_unique_duration_seconds'])}", file=self.stream)
        print(f"  Coverage                 : {details['coverage_percentage']:.2f}%", file=self.stream)
        while True:
            answer = input(f"Continue with this {label.lower()} collection? (y/n): ").strip().lower()
            if answer in {"y", "n"}:
                return answer == "y"
            self.warning("Please enter y or n.")

    def confirm_ending_song_capacity(self, details: dict[str, int | float | str]) -> bool:
        """Show dynamic ending-song capacity warning and ask the operator."""
        code = str(details.get("warning_code", "ENDINGSONG-W001"))
        print(self._paint(
            f"WARNING 1 - {code} - REGULAR SONG warning - Ending-song coverage is between 60% and 80%.",
            "1;33",
        ), file=self.stream)
        print(f"  Required ending duration : {self._duration(details['required_ending_duration_seconds'])}", file=self.stream)
        print(f"  Unique song duration     : {self._duration(details['available_unique_song_duration_seconds'])}", file=self.stream)
        print(f"  Coverage                 : {details['coverage_percentage']:.2f}%", file=self.stream)
        while True:
            answer = input("Continue with this regular-song collection for ending filler? (y/n): ").strip().lower()
            if answer in {"y", "n"}:
                return answer == "y"
            self.warning("Please enter y or n.")

    def ending_song_capacity_error(self, description: str) -> None:
        """Display the fatal dynamic capacity error."""
        print(self._paint(f"ERROR 1 - ENDINGSONG-001 - REGULAR SONG error - {description}", "1;31"), file=self.stream)

    def broadcast_end_time_report(
        self, report: dict[str, Any], timeline: dict[str, Any] | None = None
    ) -> None:
        """Print the final wall-clock schedule and configured finish outcome."""
        print(self._paint("\nBROADCAST TIME SUMMARY", "1;36"), file=self.stream)
        print("-" * 72, file=self.stream)
        if timeline is not None:
            settings = timeline.get("settings_used", {})
            target = settings.get("broadcast", {}).get("end_time", report["target_finish"])
            summary = timeline["summary"]
            print(f"  Broadcast start          : {timeline['broadcast_start_timestamp']}", file=self.stream)
            print(f"  Configured till time     : {target}", file=self.stream)
            print(f"  Actual final finish      : {summary['final_wall_clock_timestamp']}", file=self.stream)
            print(f"  Total elapsed broadcast  : {self._duration(summary['total_elapsed_broadcast_duration_seconds'])}", file=self.stream)

            toggles = settings.get("schedule_toggles", {})
            print(file=self.stream)
            print(self._paint("  SCHEDULE TOGGLES", "1;34"), file=self.stream)
            print(f"    Morning 06:00–09:00 block : {'Enabled' if toggles.get('morning_block_enabled', True) else 'Disabled'}", file=self.stream)
            print(f"    Movie-gap song filler     : {'Enabled' if toggles.get('movie_gap_song_filler_enabled', True) else 'Disabled'}", file=self.stream)
            print(f"    Broadcast-end song filler : {'Enabled' if toggles.get('broadcast_ending_song_filler_enabled', True) else 'Disabled'}", file=self.stream)

            morning = timeline.get("morning_schedule") or {}
            sections = morning.get("sections", [])
            if sections:
                print(file=self.stream)
                print(self._paint("  MORNING SONG BLOCKS", "1;34"), file=self.stream)
                for section in sections:
                    songs = [
                        item for item in timeline["items"]
                        if item.get("schedule_block") == "morning"
                        and item.get("source_category") == section["collection"]
                        and item.get("media_type") == "song"
                    ]
                    label = section["label"]
                    if songs:
                        print(
                            f"    {label}: {songs[0]['wall_clock_start_timestamp']}–{songs[-1]['wall_clock_end_timestamp']} "
                            f"| {len(songs)} song plays",
                            file=self.stream,
                        )
                    else:
                        print(f"    {label}: no songs played", file=self.stream)
                    transition = next((
                        item for item in timeline["items"]
                        if item.get("schedule_block") == "morning"
                        and item.get("source_category") == section["collection"]
                        and item.get("media_type") == "black_video_placeholder"
                    ), None)
                    if transition:
                        print(
                            f"      Black transition: {transition['wall_clock_start_timestamp']}–{transition['wall_clock_end_timestamp']}",
                            file=self.stream,
                        )

            if timeline.get("movies"):
                print(file=self.stream)
                print(self._paint("  MOVIES", "1;34"), file=self.stream)
                for movie in timeline["movies"]:
                    print(
                        f"    {movie['movie_folder']} — {movie['movie_name']}: "
                        f"{movie['wall_clock_start_timestamp']}–{movie['wall_clock_finish_timestamp']} "
                        f"(content; {movie['segment_count']} segments)",
                        file=self.stream,
                    )
                    ready_time = movie.get("ready_for_next_movie_timestamp")
                    if ready_time and ready_time != movie["wall_clock_finish_timestamp"]:
                        print(f"      Ads finish / ready for next movie: {ready_time}", file=self.stream)

            items = timeline["items"]
            for block, label in (("movie-gap", "MOVIE-GAP SONGS"), ("broadcast-ending", "ENDING SONGS")):
                print(file=self.stream)
                songs = [
                    item for item in items
                    if item.get("schedule_block") == block and item.get("media_type") == "song"
                ]
                print(self._paint(f"  {label}", "1;34"), file=self.stream)
                if songs:
                    groups: dict[str, list[dict[str, Any]]] = {}
                    for song in songs:
                        group_key = song.get("waiting_gap_id") or block
                        groups.setdefault(group_key, []).append(song)
                    for group_key, group_songs in groups.items():
                        print(
                            f"    {group_key}: {group_songs[0]['wall_clock_start_timestamp']}–"
                            f"{group_songs[-1]['wall_clock_end_timestamp']} | {len(group_songs)} song plays",
                            file=self.stream,
                        )
                else:
                    if block == "movie-gap" and not toggles.get("movie_gap_song_filler_enabled", True):
                        print("    Disabled; these waits remain empty black intervals.", file=self.stream)
                    elif block == "broadcast-ending" and not toggles.get("broadcast_ending_song_filler_enabled", True):
                        print("    Disabled.", file=self.stream)
                    else:
                        print("    No songs played.", file=self.stream)

        print(file=self.stream)
        print(self._paint("  END-TIME RESULT", "1;34"), file=self.stream)
        status = report["status"]
        if status == "overrun":
            print(self._paint(
                "    Target exceeded; no ending filler songs added.", "1;34"
            ), file=self.stream)
            print(f"    Configured target     : {report['target_finish']}", file=self.stream)
            print(f"    Actual planned finish : {report['planned_finish']}", file=self.stream)
            print(f"    Amount over target    : {self._duration(report['overrun_duration_seconds'])}", file=self.stream)
            print("    Ending filler         : Not required", file=self.stream)
        elif status == "exact_target":
            print(self._paint(
                "    Target met exactly; no ending filler songs needed.", "1;34"
            ), file=self.stream)
            print(f"    Configured target     : {report['target_finish']}", file=self.stream)
            print(f"    Actual planned finish : {report['planned_finish']}", file=self.stream)
            print("    Ending filler         : Not required", file=self.stream)
        elif status == "ending_filler_disabled":
            print(self._paint(
                "    Target not reached; ending-song filler is disabled.", "1;33"
            ), file=self.stream)
            print(f"    Configured target     : {report['target_finish']}", file=self.stream)
            print(f"    Actual planned finish : {report['planned_finish']}", file=self.stream)
            print(f"    Unfilled time         : {self._duration(report['required_ending_duration_seconds'])}", file=self.stream)
            print("    Ending filler         : Disabled by schedule toggle", file=self.stream)
        else:
            print(self._paint(
                "    Target met with regular-song ending filler.", "1;34"
            ), file=self.stream)
            print(f"    Configured target     : {report['target_finish']}", file=self.stream)
            print(f"    Actual planned finish : {report['planned_finish']}", file=self.stream)
            print(f"    Filler duration       : {self._duration(report['required_ending_duration_seconds'])}", file=self.stream)
            print(f"    Unique song duration  : {self._duration(report['available_unique_song_duration_seconds'])}", file=self.stream)
            print(f"    Song coverage         : {report['coverage_percentage']:.2f}%", file=self.stream)
            print(f"    Ending song plays     : {report['ending_song_count']}", file=self.stream)

    def confirm_advertisement_load(self, details: dict[str, int | float]) -> bool:
        """Show the aggregate yellow load warning and require y/n confirmation."""
        print(self._paint("WARNING 1 - MEDIAAD-W001 - ADVERTISEMENT error - Advertisement load is in the 15%–30% confirmation range.", "1;33"), file=self.stream)
        print(f"  Total advertisement duration          : {self._duration(details['total_ad_duration_seconds'])}", file=self.stream)
        print(f"  Repeat count                          : {details['repeat_count']}", file=self.stream)
        print(f"  Total advertisement playback duration : {self._duration(details['total_playback_duration_seconds'])}", file=self.stream)
        print(f"  Movie segment duration                : {self._duration(details['movie_segment_duration_seconds'])}", file=self.stream)
        print(f"  Calculated advertisement load         : {details['load_percent']:.2f}%", file=self.stream)
        print("  Recommended threshold                 : below 15%", file=self.stream)
        while True:
            answer = input("Do you want to continue with this advertisement load? (y/n): ").strip().lower()
            if answer in {"y", "n"}:
                return answer == "y"
            self.warning("Please enter y or n.")

    @staticmethod
    def _duration(seconds: int | float | None) -> str:
        if seconds is None:
            return "unknown"
        whole_seconds = int(round(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _items(inventory: dict[str, Any], category: str) -> list[tuple[str, str, int | float | None]]:
        category_data = inventory["categories"][category]
        if category == "movies":
            return [
                (folder.get("folder_id", ""), item.get("filename", ""), item.get("duration_seconds"))
                for folder in category_data.get("folders", [])
                for item in folder.get("files", [])
            ]
        return [
            ("", item.get("filename", ""), item.get("duration_seconds"))
            for item in category_data.get("files", [])
        ]

    def _section(self, title: str, category: str, inventory: dict[str, Any]) -> tuple[int, int | float, int]:
        category_data = inventory["categories"][category]
        items = self._items(inventory, category)
        folders = category_data.get("folders", []) if category == "movies" else []
        known = [duration for _, _, duration in items if duration is not None]
        total = sum(known)
        print(file=self.stream)
        print(self._paint(f"{title}", "1;34"), file=self.stream)
        if category == "movies":
            print(f"  Movie folders: {len(folders)}   Movie files: {len(items)}", file=self.stream)
        if not category_data.get("exists", False):
            print(self._paint("  Source category is missing.", "33"), file=self.stream)
        elif not items:
            print(self._paint("  No media files found.", "33"), file=self.stream)
        else:
            rows = [("Folder", "Filename", "Duration")]
            rows.extend(
                (folder, self._short_filename(filename), self._duration(duration))
                for folder, filename, duration in items
            )
            widths = [max(len(row[i]) for row in rows) for i in range(3)]
            for index, row in enumerate(rows):
                rendered = "  " + "  ".join(value.ljust(widths[i]) for i, value in enumerate(row))
                print(self._paint(rendered, "1;37" if index == 0 else "0"), file=self.stream)
        known_label = self._duration(total)
        suffix = f" ({len(known)}/{len(items)} durations known)" if len(known) != len(items) else ""
        print(f"  Total: {len(items)} file(s) | known duration {known_label}{suffix}", file=self.stream)
        return len(items), total, len(known)

    def discovery_results(self, inventory: dict[str, Any]) -> None:
        """Print a readable summary from provider-neutral normalized inventory."""
        mode = inventory.get("source_type", "unknown")
        source = inventory.get("source", {})
        source_kind = source.get("kind", mode)
        source_path = source.get("path", "unknown")
        mode_label = "JSON" if source_kind == "json" else "Filesystem" if source_kind == "filesystem" else str(source_kind)

        print(self._paint("MIDMOVIEADS-2026  |  MEDIA DISCOVERY", "1;36"), file=self.stream)
        print("=" * 66, file=self.stream)
        print(f"Status          : {self._paint('SUCCESS', '1;32')}", file=self.stream)
        print(f"Discovery mode  : {mode_label}", file=self.stream)
        print(f"Inventory source: {source_path}", file=self.stream)
        if source_kind == "json":
            print(self._paint("                  Simulated inventory; media files are not opened or required.", "33"), file=self.stream)
        else:
            print("                  Actual directory contents were enumerated.", file=self.stream)

        totals: dict[str, tuple[int, int | float, int]] = {}
        for title, category in (
            ("MOVIES", "movies"),
            ("ADVERTISEMENT", "ads"),
            ("DEVOTIONAL SONGS", "dev-songs"),
            ("MOVIE SONGS", "movie-songs"),
            ("REGULAR SONGS", "songs"),
        ):
            totals[category] = self._section(title, category, inventory)

        file_count = sum(value[0] for value in totals.values())
        known_duration = sum(value[1] for value in totals.values())
        known_count = sum(value[2] for value in totals.values())
        print(self._paint("\nOVERALL SUMMARY", "1;36"), file=self.stream)
        print("-" * 66, file=self.stream)
        print(f"  Discovered media files : {file_count}", file=self.stream)
        print(f"  Known total duration   : {self._duration(known_duration)} ({known_count}/{file_count} durations known)", file=self.stream)

    def simulation_results(self, timeline: dict[str, Any]) -> None:
        """Display schedule grouped by movie and the complete cumulative timeline."""
        summary = timeline["summary"]
        items = timeline["items"]
        print(self._paint("\nMIDMOVIEADS-2026  |  WALL-CLOCK MOVIE SIMULATION", "1;36"), file=self.stream)
        print("SIMULATION ONLY - no media files were cut, rendered, or concatenated.", file=self.stream)

        morning = timeline.get("morning_schedule")
        if morning:
            print(self._paint(
                f"\nMORNING SONG BLOCK - {morning['start_timestamp']} to {morning['end_timestamp']}", "1;34"
            ), file=self.stream)
            for section in morning["sections"]:
                print(
                    f"  {section['label']}: {section['wall_clock_start_timestamp']}–{section['wall_clock_end_timestamp']} "
                    f"({section['configured_duration_minutes']} minutes; {section['song_play_count']} plays)",
                    file=self.stream,
                )
                for item in items:
                    if item.get("schedule_block") == "morning" and item.get("source_category") == section["collection"]:
                        if item["media_type"] == "black_video_placeholder":
                            print(
                                f"    BLACK VIDEO PLACEHOLDER {self._duration(item['broadcast_duration_seconds'])} "
                                f"({item['wall_clock_start_timestamp']}–{item['wall_clock_end_timestamp']})",
                                file=self.stream,
                            )
                        else:
                            print(
                                f"    {self._short_filename(item['source_filename'])} "
                                f"{self._duration(item['broadcast_duration_seconds'])} "
                                f"({item['wall_clock_start_timestamp']}–{item['wall_clock_end_timestamp']}, {item['completion_status']})",
                                file=self.stream,
                            )

        for movie_number, movie in enumerate(timeline["movies"], 1):
            movie_items = [
                item for item in items
                if item["media_type"] == "movie_segment"
                and item["movie_folder"] == movie["movie_folder"]
                and item["source_path"] == movie["source_path"]
            ]
            print(self._paint(
                f"\nMOVIE {movie_number} - {self._short_filename(movie['movie_name'])} "
                f"({movie['movie_folder']})", "1;34"
            ), file=self.stream)
            gap = movie["empty_gap_before"]
            if gap:
                print(
                    f"  Waiting interval: {self._duration(gap['duration_seconds'])} "
                    f"({gap['wall_clock_start_timestamp']}–{gap['wall_clock_end_timestamp']}); "
                    f"songs {self._duration(gap.get('song_playback_duration_seconds', 0))}; "
                    f"empty {self._duration(gap.get('remaining_empty_duration_seconds', gap['duration_seconds']))}",
                    file=self.stream,
                )
            print(f"  Starts: {movie['wall_clock_start_timestamp']}", file=self.stream)
            print(f"  Finishes: {movie['wall_clock_finish_timestamp']} (movie content)", file=self.stream)
            print(f"  Segments: {movie['segment_count']}", file=self.stream)
            print(
                f"  Ads: {sum(len(block['ads']) for block in movie['advertisement_breaks'])} "
                f"across {len(movie['advertisement_breaks'])} break(s); "
                f"ready for next movie at {movie['ready_for_next_movie_timestamp']}",
                file=self.stream,
            )
            if gap:
                for song in gap.get("songs", []):
                    print(
                        f"    Song {self._short_filename(song['filename'])} ({gap['gap_id']}): "
                        f"{self._duration(song['played_duration_seconds'])}, {song['completion_status']}",
                        file=self.stream,
                    )
            for item in movie_items:
                logical = f"{item['logical_source_start_timestamp']}–{item['logical_source_end_timestamp']}"
                actual = f"{item['actual_playback_source_start_timestamp']}–{item['actual_playback_source_end_timestamp']}"
                print(
                    f"    Segment {item['segment_number']}: source {logical}; playback {actual}; "
                    f"wall {item['wall_clock_start_timestamp']}–{item['wall_clock_end_timestamp']} "
                    f"({self._duration(item['broadcast_duration_seconds'])})",
                    file=self.stream,
                )
            for block in movie["advertisement_breaks"]:
                print(f"    Ad break {block['break_number']}:", file=self.stream)
                for ad in block["ads"]:
                    ad_item = next(item for item in items if item["sequence"] == ad["sequence"])
                    print(
                        f"      {self._short_filename(ad['filename'])} "
                        f"{self._duration(ad['duration_seconds'])} "
                        f"({ad_item['wall_clock_start_timestamp']}–{ad_item['wall_clock_end_timestamp']})",
                        file=self.stream,
                    )

        print(self._paint("\nCOMPLETE BROADCAST TIMELINE", "1;34"), file=self.stream)
        rows = [("#", "Type", "Source", "Movie / segment", "Source range", "Wall-clock start–end", "Elapsed start–end", "Duration")]
        for item in items:
            if item["media_type"] == "movie_segment":
                identity = f"{item['movie_folder']} {item['segment_number']}/{item['segment_count']}"
                source_range = f"{item['actual_playback_source_start_timestamp']}–{item['actual_playback_source_end_timestamp']}"
            elif item["media_type"] == "ad":
                identity = f"ad break {item['ad_break_number']}"
                source_range = f"{item['actual_playback_source_start_timestamp']}–{item['actual_playback_source_end_timestamp']}"
            elif item["media_type"] == "song":
                if item.get("schedule_block") == "morning":
                    identity = f"morning {item['source_category']}"
                elif item.get("schedule_block") == "broadcast-ending":
                    identity = "broadcast ending"
                else:
                    identity = item["waiting_gap_id"] or "waiting"
                source_range = f"{item['actual_playback_source_start_timestamp']}–{item['actual_playback_source_end_timestamp']} ({item['completion_status']})"
            elif item["media_type"] == "black_video_placeholder":
                identity = f"transition after {item['source_category']}"
                source_range = item["reason"] or "black video placeholder"
            else:
                identity = "waiting"
                source_range = "—"
            rows.append((
                str(item["sequence"]), item["media_type"],
                self._short_filename(item["source_filename"] or "—"), identity,
                source_range,
                f"{item['wall_clock_start_timestamp']}–{item['wall_clock_end_timestamp']}",
                f"{item['elapsed_broadcast_start']}–{item['elapsed_broadcast_end']}",
                self._duration(item["broadcast_duration_seconds"]),
            ))
        widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
        for row_index, row in enumerate(rows):
            line = "  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
            print(self._paint(line, "1;37" if row_index == 0 else "0"), file=self.stream)

        print(self._paint("\nOVERALL SUMMARY", "1;36"), file=self.stream)
        print("-" * 82, file=self.stream)
        print(f"  Broadcast start          : {timeline['broadcast_start_timestamp']}", file=self.stream)
        print(f"  Final broadcast finish   : {summary['final_wall_clock_timestamp']}", file=self.stream)
        print(f"  Total elapsed duration   : {self._duration(summary['total_elapsed_broadcast_duration_seconds'])}", file=self.stream)
        print(f"  Movie segments           : {summary['movie_segment_count']}", file=self.stream)
        print(f"  Advertisement breaks     : {summary['advertisement_break_count']}", file=self.stream)
        print(f"  Advertisement plays      : {summary['advertisement_play_count']}", file=self.stream)
        print(f"  Songs played             : {summary['song_play_count']}", file=self.stream)
        if morning:
            print(f"  Morning songs played     : {summary['morning_song_play_count']}", file=self.stream)
            print(f"  Morning song duration    : {self._duration(summary['morning_song_playback_duration_seconds'])}", file=self.stream)
            print(f"  Morning black intervals : {self._duration(summary['morning_transition_black_duration_seconds'])}", file=self.stream)
        print(f"  Song playback duration   : {self._duration(summary['total_song_playback_duration_seconds'])}", file=self.stream)
        print(f"  Songs unused             : {summary['songs_unused_count']}", file=self.stream)
        print(f"  Song collection exhausted: {summary['song_collection_exhausted']}", file=self.stream)
        print(f"  Total empty-gap duration : {self._duration(summary['total_empty_gap_duration_seconds'])}", file=self.stream)
        print(f"  Timeline JSON            : {timeline['timeline_file']}", file=self.stream)
        checks = timeline["consistency_checks"]
        print(
            f"  Consistency checks       : {'PASS' if all(checks.values()) else 'FAIL'} "
            f"({sum(checks.values())}/{len(checks)})",
            file=self.stream,
        )
        for check_name, passed in checks.items():
            mark = self._paint("PASS", "32") if passed else self._paint("FAIL", "1;31")
            print(f"    {mark}  {check_name.replace('_', ' ')}", file=self.stream)
        if summary["songs_unused"]:
            print("  Unused songs: " + ", ".join(song["filename"] for song in summary["songs_unused"]), file=self.stream)


def display_discovery(inventory: dict[str, Any], stream: TextIO | None = None) -> None:
    """Convenience function for displaying one completed discovery result."""
    TerminalUI(stream=stream).discovery_results(inventory)
