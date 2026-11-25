"""Render a saved timeline into ordered, independent VMix media clips."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_ROOT.parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reporting.terminal_ui import TerminalUI  # noqa: E402
from rendering.output_manager import OutputManager, RenderOutputError, RenderSession  # noqa: E402
from security.license_manager import check_license  # noqa: E402


class RenderingError(RuntimeError):
    """Raised when a timeline cannot be rendered safely."""


class RenderConfirmationRejected(RuntimeError):
    """Raised when the operator declines a nonzero cumulative drift report."""


MOVIE_FOLDER = re.compile(r"movie([1-9][0-9]*)\Z", re.IGNORECASE)
MAX_MOVIE_SEGMENT_DRIFT_SECONDS = 20.0
MAX_AD_SONG_DRIFT_SECONDS = 5.0
MAX_BLACK_CLIP_DRIFT_SECONDS = 1.0
MAX_CUMULATIVE_DRIFT_SECONDS = 2 * 60.0
MAX_MOVIE_DRIFT_SECONDS = 2 * 60.0
BLACK_WIDTH = 1920
BLACK_HEIGHT = 1080
BLACK_FRAME_RATE = 30


def latest_timeline(timeline_directory: str | Path | None = None) -> Path:
    """Find the latest timeline by the project's timestamped filename convention."""
    directory = Path(timeline_directory) if timeline_directory else PROJECT_ROOT / "videos" / "output" / "timelines"
    directory = directory.expanduser().resolve()
    candidates = sorted(directory.glob("timeline_*.json")) if directory.is_dir() else []
    if not candidates:
        raise RenderingError(f"No timeline_*.json files were found in {directory}.")
    return candidates[-1].resolve()


def _load_timeline(path: str | Path) -> tuple[Path, dict[str, Any]]:
    timeline_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderingError(f"Unable to read timeline JSON {timeline_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RenderingError("Timeline JSON root must be an object.")
    if value.get("simulation_only") is not True:
        raise RenderingError("Timeline must be a completed simulation blueprint.")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise RenderingError("Timeline contains no media items to render.")
    checks = value.get("consistency_checks")
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        raise RenderingError("Timeline is missing successful consistency checks; refusing to render it.")
    for expected_sequence, item in enumerate(items, 1):
        if (not isinstance(item, dict)
                or isinstance(item.get("sequence"), bool)
                or not isinstance(item.get("sequence"), int)
                or item["sequence"] != expected_sequence):
            raise RenderingError("Timeline item sequence is malformed or not contiguous.")
    return timeline_path, value


def _number(value: Any, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RenderingError(f"{description} must be a finite number of seconds.")
    return float(value)


def _item_drift_limit(item: dict[str, Any]) -> float:
    """Return the allowed stream-copy duration deviation for this timeline item."""
    if item.get("media_type") == "movie_segment":
        return MAX_MOVIE_SEGMENT_DRIFT_SECONDS
    if item.get("media_type") in {"ad", "song"}:
        return MAX_AD_SONG_DRIFT_SECONDS
    return MAX_BLACK_CLIP_DRIFT_SECONDS


def _source_path(raw_path: Any, filename: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise RenderingError(f"Timeline source path is missing for {filename}.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise RenderingError(f"Source media file does not exist: {path}")
    return path


def _tag_for(item: dict[str, Any]) -> str:
    media_type = item.get("media_type")
    if media_type == "movie_segment":
        folder = item.get("movie_folder")
        match = MOVIE_FOLDER.fullmatch(folder) if isinstance(folder, str) else None
        if not match:
            raise RenderingError(f"Invalid movie folder on timeline item {item['sequence']}: {folder!r}")
        return f"M{int(match.group(1))}"
    if media_type == "ad":
        return "AD"
    if media_type == "song":
        category = item.get("source_category")
        if category == "movie-songs" or item.get("schedule_block") == "movie-gap":
            return "MS"
        if category == "dev-songs":
            return "DS"
        if category == "songs":
            return "S"
        raise RenderingError(f"Unknown song collection on timeline item {item['sequence']}: {category!r}")
    if media_type in {"empty_gap", "black_video_placeholder"}:
        return "BLK"
    raise RenderingError(f"Unsupported media type on timeline item {item['sequence']}: {media_type!r}")


def _output_name(item: dict[str, Any], total_items: int) -> str:
    sequence = item["sequence"]
    width = 3 if total_items < 1000 else 4
    serial = str(sequence).zfill(width)
    tag = _tag_for(item)
    if item["media_type"] in {"empty_gap", "black_video_placeholder"}:
        return f"{serial}_{tag}_black_{sequence:04d}.mp4"

    source_name = item.get("source_filename")
    if not isinstance(source_name, str) or not source_name.strip():
        raise RenderingError(f"Source filename is missing on timeline item {sequence}.")
    basename = Path(source_name).name
    suffix = Path(item.get("source_path", basename)).suffix.lower()
    if suffix not in {".mp4", ".mkv"}:
        raise RenderingError(f"Unsupported output container for {source_name}; expected MP4 or MKV.")
    return f"{serial}_{tag}_{basename}"


def _ffprobe_json(ffprobe: str, media_path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,codec_name,profile,level,pix_fmt,width,height,avg_frame_rate",
                "-of", "json", str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        document = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None)
        raise RenderingError(f"FFprobe could not inspect {media_path}: {detail or exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("streams"), list):
        raise RenderingError(f"FFprobe returned invalid stream metadata for {media_path}.")
    return document


def _media_duration(document: dict[str, Any], media_path: Path) -> float:
    try:
        duration = float(document["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RenderingError(f"FFprobe did not report a duration for {media_path}.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RenderingError(f"FFprobe reported an invalid duration for {media_path}.")
    return duration


def _stream_signature(document: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(stream.get("codec_type", "")), str(stream.get("codec_name", "")))
        for stream in document["streams"]
    ]


def _source_interval(item: dict[str, Any], source_path: Path, source_duration: float) -> tuple[float, float]:
    start = _number(item.get("actual_playback_source_start_seconds"),
                    f"Timeline item {item['sequence']} source start")
    end = _number(item.get("actual_playback_source_end_seconds"),
                  f"Timeline item {item['sequence']} source end")
    if start < 0 or end <= start:
        raise RenderingError(f"Timeline item {item['sequence']} has an empty or negative source interval.")
    if end > source_duration + _item_drift_limit(item):
        raise RenderingError(
            f"Timeline item {item['sequence']} ends beyond the probed source duration: "
            f"{end:.3f}s > {source_duration:.3f}s ({source_path})."
        )
    return start, end


def _ffmpeg_run(ffmpeg: str, command: list[str], purpose: str) -> None:
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *command],
            capture_output=True,
            text=True,
            check=True,
            timeout=2 * 60 * 60,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RenderingError(f"FFmpeg failed while {purpose}: {detail}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderingError(f"FFmpeg failed while {purpose}: {exc}") from exc


def _render_source_clip(
    item: dict[str, Any],
    source_path: Path,
    source_metadata: dict[str, Any],
    destination: Path,
    ffmpeg: str,
    ffprobe: str,
) -> float:
    source_duration = _media_duration(source_metadata, source_path)
    start, end = _source_interval(item, source_path, source_duration)
    if not any(stream.get("codec_type") == "video" for stream in source_metadata["streams"]):
        raise RenderingError(f"Source has no video stream: {source_path}")

    command = [
        "-ss", f"{start:.6f}",
        "-i", str(source_path),
        "-t", f"{end - start:.6f}",
        "-map", "0",
        "-c", "copy",
        "-map_metadata", "0",
        "-map_chapters", "0",
        "-avoid_negative_ts", "make_zero",
    ]
    if destination.suffix.lower() == ".mp4":
        command.extend(["-movflags", "+faststart"])
    command.extend(["-n", str(destination)])
    _ffmpeg_run(ffmpeg, command, f"cutting timeline item {item['sequence']}")

    if not destination.is_file() or destination.stat().st_size == 0:
        raise RenderingError(f"FFmpeg produced an empty clip for timeline item {item['sequence']}.")
    rendered_metadata = _ffprobe_json(ffprobe, destination)
    rendered_duration = _media_duration(rendered_metadata, destination)
    expected_duration = end - start
    drift_limit = _item_drift_limit(item)
    if abs(rendered_duration - expected_duration) > drift_limit:
        raise RenderingError(
            f"Clip duration for timeline item {item['sequence']} differs from the requested cut by "
            f"more than {drift_limit:g}s (requested {expected_duration:.3f}s, "
            f"rendered {rendered_duration:.3f}s)."
        )
    if _stream_signature(rendered_metadata) != _stream_signature(source_metadata):
        raise RenderingError(f"Stream-copy verification failed for timeline item {item['sequence']}.")

    try:
        packet_result = subprocess.run(
            [
                ffprobe, "-v", "error", "-select_streams", "v:0",
                "-read_intervals", "%+#1", "-show_packets",
                "-show_entries", "packet=flags", "-of", "default=noprint_wrappers=1:nokey=1",
                str(destination),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderingError(f"Unable to verify the first video packet in {destination}: {exc}") from exc
    first_packet = next((line.strip() for line in packet_result.stdout.splitlines() if line.strip()), "")
    if packet_result.returncode != 0 or "K" not in first_packet:
        raise RenderingError(
            f"The first video packet in timeline item {item['sequence']} is not a keyframe; "
            "refusing a clip that may begin with a frozen or undecodable picture."
        )
    return rendered_duration


def _render_black_clip(item: dict[str, Any], destination: Path, ffmpeg: str, ffprobe: str) -> float:
    duration = _number(item.get("broadcast_duration_seconds"),
                       f"Timeline item {item['sequence']} black duration")
    if duration <= 0:
        raise RenderingError(f"Black interval {item['sequence']} must have a positive duration.")
    command = [
        "-f", "lavfi",
        "-i", f"color=c=black:s={BLACK_WIDTH}x{BLACK_HEIGHT}:r={BLACK_FRAME_RATE}",
        "-t", f"{duration:.6f}",
        "-map", "0:v:0",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "baseline",
        "-level:v", "4.0",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-n", str(destination),
    ]
    _ffmpeg_run(ffmpeg, command, f"generating black interval {item['sequence']}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RenderingError(f"FFmpeg produced an empty black clip for timeline item {item['sequence']}.")
    metadata = _ffprobe_json(ffprobe, destination)
    rendered_duration = _media_duration(metadata, destination)
    if abs(rendered_duration - duration) > MAX_BLACK_CLIP_DRIFT_SECONDS:
        raise RenderingError(
            f"Generated black clip {item['sequence']} differs from the timeline by more than "
            f"{MAX_BLACK_CLIP_DRIFT_SECONDS:g}s."
        )
    video_streams = [stream for stream in metadata["streams"] if stream.get("codec_type") == "video"]
    if (len(video_streams) != 1
            or video_streams[0].get("codec_name") != "h264"
            or video_streams[0].get("profile") not in {"Baseline", "Constrained Baseline"}
            or video_streams[0].get("level") != 40
            or video_streams[0].get("pix_fmt") != "yuv420p"
            or video_streams[0].get("width") != BLACK_WIDTH
            or video_streams[0].get("height") != BLACK_HEIGHT
            or video_streams[0].get("avg_frame_rate") != f"{BLACK_FRAME_RATE}/1"
            or any(stream.get("codec_type") == "audio" for stream in metadata["streams"])):
        raise RenderingError(f"Generated black clip {item['sequence']} failed format verification.")
    return rendered_duration


def render_timeline(
    timeline_path: str | Path | None = None,
    output_directory: str | Path | None = None,
    ui: TerminalUI | None = None,
) -> dict[str, Any]:
    """Render each timeline item to its own prefixed clip, without concatenation."""
    terminal = ui or TerminalUI()
    selected_timeline = Path(timeline_path).expanduser().resolve() if timeline_path else latest_timeline()
    timeline_path, timeline = _load_timeline(selected_timeline)
    items = timeline["items"]

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None:
        raise RenderingError("FFmpeg was not found on PATH.")
    if ffprobe is None:
        raise RenderingError("FFprobe was not found on PATH; it is required to verify rendered clips.")

    # Preflight every input before creating any output, so a missing path or
    # unreadable source cannot leave a partial VMix folder.
    source_info: dict[str, tuple[Path, dict[str, Any]]] = {}
    prepared: list[tuple[dict[str, Any], Path | None, dict[str, Any] | None, str]] = []
    for item in items:
        _tag_for(item)  # reject unsupported item types before creating output
        if item["media_type"] in {"empty_gap", "black_video_placeholder"}:
            name = _output_name(item, len(items))
            prepared.append((item, None, None, name))
            continue
        filename = str(item.get("source_filename") or "unnamed media")
        source_path = _source_path(item.get("source_path"), filename)
        cache_key = str(source_path)
        if cache_key not in source_info:
            metadata = _ffprobe_json(ffprobe, source_path)
            source_info[cache_key] = (source_path, metadata)
        _, metadata = source_info[cache_key]
        source_duration = _media_duration(metadata, source_path)
        _source_interval(item, source_path, source_duration)
        if not any(stream.get("codec_type") == "video" for stream in metadata["streams"]):
            raise RenderingError(f"Source has no video stream: {source_path}")
        source_name_suffix = Path(filename).suffix.lower()
        path_suffix = source_path.suffix.lower()
        if source_name_suffix != path_suffix:
            raise RenderingError(
                f"Timeline filename and source path extensions disagree for {source_path}."
            )
        prepared.append((item, source_path, metadata, _output_name(item, len(items))))

    root = Path(output_directory).expanduser() if output_directory else PROJECT_ROOT / "videos" / "output" / "renders"
    planned_duration_total = sum(
        _number(item.get("broadcast_duration_seconds"), f"Timeline item {item['sequence']} duration")
        for item, _, _, _ in prepared
    )
    session: RenderSession | None = None
    try:
        session = OutputManager(root).create_session(timeline_path)
        terminal.render_started(str(timeline_path), len(prepared), str(session.final_directory))
        rendered_duration_total = 0.0
        cumulative_drift = 0.0
        worst_cumulative_drift = 0.0
        movie_drifts: dict[tuple[str, str], float] = {}
        rendered_items: list[dict[str, Any]] = []
        for index, (item, source_path, metadata, filename) in enumerate(prepared, 1):
            terminal.render_progress(index, len(prepared), filename)
            target = session.staging_directory / filename
            if source_path is None:
                item_rendered_duration = _render_black_clip(item, target, ffmpeg, ffprobe)
            else:
                assert metadata is not None
                item_rendered_duration = _render_source_clip(item, source_path, metadata, target, ffmpeg, ffprobe)
            item_planned_duration = _number(
                item.get("broadcast_duration_seconds"), f"Timeline item {item['sequence']} duration"
            )
            item_drift = item_rendered_duration - item_planned_duration
            drift_limit = _item_drift_limit(item)
            terminal.render_item_drift(
                filename,
                item_planned_duration,
                item_rendered_duration,
                item_drift,
                drift_limit,
            )
            if abs(item_drift) > drift_limit:
                raise RenderingError(
                    f"Rendered timeline item {item['sequence']} differs from its planned duration by "
                    f"{item_drift:+.3f}s, exceeding the {drift_limit:g}s limit."
                )
            cumulative_drift += item_drift
            worst_cumulative_drift = max(worst_cumulative_drift, abs(cumulative_drift))
            rendered_duration_total += item_rendered_duration
            if item.get("media_type") == "movie_segment":
                movie_key = (str(item.get("movie_folder") or ""), str(item.get("source_path") or ""))
                movie_drifts[movie_key] = movie_drifts.get(movie_key, 0.0) + item_drift
                if abs(movie_drifts[movie_key]) > MAX_MOVIE_DRIFT_SECONDS:
                    raise RenderingError(
                        f"Movie {movie_key[0]} accumulated {movie_drifts[movie_key]:+.3f}s of segment drift, "
                        f"exceeding its {MAX_MOVIE_DRIFT_SECONDS:g}s whole-movie limit."
                    )
            rendered_items.append({
                "sequence": item["sequence"],
                "filename": filename,
                "media_type": item.get("media_type"),
                "movie_folder": item.get("movie_folder"),
                "source_path": item.get("source_path"),
                "expected_start": item.get("wall_clock_start_timestamp"),
                "expected_end": item.get("wall_clock_end_timestamp"),
                "expected_duration": item_planned_duration,
                "actual_duration": item_rendered_duration,
                "drift": item_drift,
                "drift_limit": drift_limit,
            })
            if worst_cumulative_drift > MAX_CUMULATIVE_DRIFT_SECONDS:
                raise RenderingError(
                    f"Cumulative render drift exceeded {MAX_CUMULATIVE_DRIFT_SECONDS:g}s "
                    f"at timeline item {item['sequence']} ({cumulative_drift:+.3f}s)."
                )
        terminal.render_timing_report(timeline, rendered_items, cumulative_drift, worst_cumulative_drift)
        if worst_cumulative_drift > 0.001 and not terminal.confirm_render_drift():
            raise RenderConfirmationRejected("Operator declined to publish clips with timing drift.")
        final_directory = session.publish()
    except BaseException:
        if session is not None:
            session.discard()
        raise

    terminal.render_completed(
        str(final_directory),
        len(prepared),
        planned_duration_total,
        rendered_duration_total,
        worst_cumulative_drift,
    )
    return {
        "timeline_path": str(timeline_path),
        "output_directory": str(final_directory),
        "file_count": len(prepared),
        "planned_duration_seconds": planned_duration_total,
        "rendered_duration_seconds": rendered_duration_total,
        "duration_delta_seconds": rendered_duration_total - planned_duration_total,
        "files": [filename for _, _, _, filename in prepared],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a saved timeline into individually prefixed VMix clips."
    )
    parser.add_argument(
        "--timeline",
        type=Path,
        help="Timeline JSON to render; defaults to the latest saved timeline.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Root directory for this render run; defaults to videos/output/renders at the project root.",
    )
    args = parser.parse_args()
    terminal = TerminalUI()
    license_result = check_license()
    terminal.license_check_result(license_result)
    if not license_result.valid:
        return 3
    try:
        render_timeline(args.timeline, args.output_directory, terminal)
    except RenderConfirmationRejected as exc:
        terminal.status(f"{exc} Incomplete render files were discarded.")
        return 2
    except (RenderingError, RenderOutputError, OSError) as exc:
        terminal.render_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
