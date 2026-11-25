"""Read media duration metadata with FFprobe for filesystem discovery."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path


class MediaProbeUnavailableError(RuntimeError):
    """Raised when FFprobe is needed but is not available on PATH."""


def probe_duration_seconds(media_path: str | Path) -> float | None:
    """Return a media file's duration in seconds, or ``None`` if unreadable.

    A missing FFprobe installation is an environment-level failure and is
    reported clearly. A file-specific probe failure is represented as unknown
    duration so the shared media validators can report it with other inventory
    issues.
    """
    executable = shutil.which("ffprobe")
    if executable is None:
        raise MediaProbeUnavailableError(
            "FFprobe was not found on PATH. Install FFmpeg (including ffprobe) "
            "or add its bin directory to PATH to discover filesystem durations."
        )

    try:
        result = subprocess.run(
            [
                executable,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        duration = float(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None

    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration
