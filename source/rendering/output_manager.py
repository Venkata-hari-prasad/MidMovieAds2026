"""Safe output-directory lifecycle for an individual render run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import time


class RenderOutputError(RuntimeError):
    """Raised when a render output directory cannot be prepared or published."""


@dataclass
class RenderSession:
    """Temporary render directory that is published only after full success."""

    staging_directory: Path
    final_directory: Path
    _finished: bool = False
    _preserve_staging: bool = False

    def publish(self) -> Path:
        """Publish completed clips, with a copy fallback for locked Windows folders."""
        if self._finished:
            raise RenderOutputError("Render session is already closed.")
        if self.final_directory.exists():
            self._preserve_staging = True
            raise RenderOutputError(
                f"Render destination already exists; refusing to overwrite: {self.final_directory}. "
                f"Completed clips are retained in {self.staging_directory}."
            )

        last_error: OSError | None = None
        for attempt in range(3):
            try:
                self.staging_directory.replace(self.final_directory)
                self._finished = True
                return self.final_directory
            except OSError as exc:
                last_error = exc
                if self.final_directory.exists() and not self.staging_directory.exists():
                    self._finished = True
                    return self.final_directory
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))

        # Windows sync providers can temporarily deny directory renames. Copy
        # the completed output as a fallback, while retaining staging on error.
        if self.final_directory.exists():
            self._preserve_staging = True
            raise RenderOutputError(
                f"Unable to publish render output after retries: {last_error}. "
                f"Completed clips are retained in {self.staging_directory}; "
                f"destination already exists: {self.final_directory}."
            ) from last_error
        try:
            shutil.copytree(self.staging_directory, self.final_directory)
        except OSError as exc:
            partial_destination = False
            if self.final_directory.exists():
                try:
                    shutil.rmtree(self.final_directory)
                except OSError:
                    partial_destination = True
            self._preserve_staging = True
            detail = (
                f" A partial destination may remain at {self.final_directory}."
                if partial_destination else ""
            )
            raise RenderOutputError(
                f"Unable to publish render output by rename or copy: {exc}. "
                f"Completed clips are retained in {self.staging_directory}.{detail}"
            ) from exc

        self._finished = True
        try:
            shutil.rmtree(self.staging_directory)
        except OSError:
            # The final copy is complete; a leftover hidden staging folder is
            # harmless and can be removed later.
            pass
        return self.final_directory

    def discard(self) -> None:
        """Remove only this session's incomplete staging directory."""
        if self._finished:
            return
        if self.staging_directory.exists() and not self._preserve_staging:
            shutil.rmtree(self.staging_directory)
        self._finished = True


class OutputManager:
    """Create isolated render runs without touching source or prior output."""

    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).expanduser().resolve()

    def create_session(self, timeline_path: str | Path) -> RenderSession:
        """Prepare a private staging folder and a timeline-specific destination."""
        timeline_name = Path(timeline_path).stem
        final_directory = self.output_root / f"{timeline_name}_rendered"
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
            if final_directory.exists():
                raise RenderOutputError(
                    f"Render destination already exists; refusing to overwrite: {final_directory}"
                )
            staging_directory = Path(tempfile.mkdtemp(
                prefix=f".{timeline_name}.rendering-",
                dir=self.output_root,
            ))
        except RenderOutputError:
            raise
        except OSError as exc:
            raise RenderOutputError(f"Unable to prepare render output directory: {exc}") from exc
        return RenderSession(staging_directory, final_directory)
