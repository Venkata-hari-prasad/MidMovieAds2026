"""Look up the timeline item and media seek point for the current local time.

Run from the project root with ``python source/tools/recover.py``. This tool
reads the newest saved timeline directly and does not invoke the application
or recalculate the schedule.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_ROOT.parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reporting.terminal_ui import TerminalUI  # noqa: E402


class RecoveryError(ValueError):
    """Raised when a saved timeline cannot support a recovery lookup."""


def _parse_clock(value: str, field_name: str) -> int:
    try:
        parts = [int(part) for part in value.split(":")]
        if len(parts) != 3:
            raise ValueError
        hours, minutes, seconds = parts
        if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
            raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise RecoveryError(f"Invalid {field_name} clock value: {value!r}.") from exc
    return hours * 3600 + minutes * 60 + seconds


def _format_duration(seconds: float) -> str:
    millis = round(seconds * 1000)
    whole, fraction = divmod(millis, 1000)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{fraction:03d}"


def latest_timeline(timeline_directory: str | Path | None = None) -> Path:
    """Find the most recently generated timeline in the output convention."""
    folder = Path(timeline_directory) if timeline_directory else SOURCE_ROOT / "videos" / "output" / "timelines"
    folder = folder.expanduser().resolve()
    candidates = list(folder.glob("timeline_*.json")) if folder.is_dir() else []
    if not candidates:
        raise RecoveryError(f"No saved timeline_*.json files were found in {folder}.")

    def sort_key(path: Path) -> tuple[float, float]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            generated_at = datetime.fromisoformat(document["generated_at"])
            return generated_at.timestamp(), path.stat().st_mtime
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return float("-inf"), path.stat().st_mtime

    return max(candidates, key=sort_key).resolve()


def load_timeline(path: str | Path) -> dict[str, Any]:
    """Load the timeline JSON object used by the recovery lookup."""
    timeline_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"Unable to read timeline JSON {timeline_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"Timeline JSON root must be an object: {timeline_path}")
    if not isinstance(value.get("items"), list) or not value["items"]:
        raise RecoveryError(f"Timeline has no scheduled items: {timeline_path}")
    if not isinstance(value.get("broadcast_start_timestamp"), str):
        raise RecoveryError("Timeline is missing broadcast_start_timestamp.")
    _parse_clock(value["broadcast_start_timestamp"], "broadcast_start_timestamp")
    return value


def resolve_recovery_position(
    timeline: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve the current local wall-clock time to a saved item and source seek.

    ``now`` is injectable for callers that want to inspect a known point; the
    CLI uses the actual system clock. Timeline item elapsed positions are used
    to locate the item, while wall-clock stamps remain the displayed schedule.
    """
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    current_seconds = current.hour * 3600 + current.minute * 60 + current.second + current.microsecond / 1_000_000
    start_seconds = _parse_clock(timeline["broadcast_start_timestamp"], "broadcast_start_timestamp")
    items = timeline["items"]
    try:
        item_ends = [float(item["elapsed_broadcast_end_seconds"]) for item in items]
        total_seconds = float(timeline.get("summary", {}).get("total_elapsed_broadcast_duration_seconds", max(item_ends)))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("Timeline items are missing usable elapsed broadcast positions.") from exc
    if total_seconds < 0:
        raise RecoveryError("Timeline total duration cannot be negative.")

    elapsed = current_seconds - start_seconds
    # Account for a schedule that crosses midnight without mistaking an early
    # pre-start time for a completed previous day's schedule.
    crosses_midnight = total_seconds > (24 * 3600 - start_seconds)
    if elapsed < 0 and crosses_midnight:
        elapsed += 24 * 3600
    base = {
        "current_time": current.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "broadcast_start_time": timeline["broadcast_start_timestamp"],
        "timeline_path": timeline.get("timeline_file") or "",
        "simulation_only": bool(timeline.get("simulation_only", False)),
    }
    if elapsed < 0:
        return {**base, "status": "before_start"}
    if elapsed >= total_seconds:
        return {
            **base,
            "status": "finished",
            "final_wall_clock_time": timeline.get("summary", {}).get("final_wall_clock_timestamp", "unknown"),
        }

    for item in items:
        try:
            item_start = float(item["elapsed_broadcast_start_seconds"])
            item_end = float(item["elapsed_broadcast_end_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("A timeline item is missing usable elapsed broadcast positions.") from exc
        if item_start <= elapsed < item_end:
            resolved = dict(item)
            source_start = item.get("actual_playback_source_start_seconds")
            if source_start is not None and item.get("source_path"):
                seek_seconds = float(source_start) + (elapsed - item_start)
                resolved["seek_position_seconds"] = seek_seconds
                resolved["seek_position_timestamp"] = _format_duration(seek_seconds)
                guidance = None
            else:
                resolved["seek_position_seconds"] = None
                resolved["seek_position_timestamp"] = None
                if item.get("media_type") == "black_video_placeholder":
                    guidance = "This is a planned black-video placeholder; no physical black-video file is assigned yet."
                elif item.get("media_type") == "empty_gap":
                    guidance = "This is an empty timeline gap; no media is scheduled during this interval."
                else:
                    guidance = "This timeline item has no source seek position."
            return {**base, "status": "playing", "item": resolved, "playback_guidance": guidance}

    return {
        **base,
        "status": "unavailable",
        "message": f"no item covers elapsed broadcast position {_format_duration(elapsed)}.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Find what the saved broadcast timeline should play now.")
    parser.add_argument(
        "--timeline",
        type=Path,
        help="Use this timeline JSON instead of automatically selecting the latest one.",
    )
    args = parser.parse_args()
    ui = TerminalUI()
    try:
        path = args.timeline.expanduser().resolve() if args.timeline else latest_timeline()
        timeline = load_timeline(path)
        result = resolve_recovery_position(timeline)
        result["timeline_path"] = str(path)
    except RecoveryError as exc:
        ui.error(f"RECOVERY-001 - {exc}")
        return 2
    ui.recovery_result(result)
    return 1 if result["status"] in {"finished", "unavailable"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
