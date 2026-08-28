"""Backend-independent contracts for stem separation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, runtime_checkable

StemName = Literal["vocals", "drums", "bass", "other"]
STEM_NAMES: tuple[StemName, ...] = ("vocals", "drums", "bass", "other")


@dataclass(frozen=True)
class ProgressUpdate:
    progress: float
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "progress", min(1.0, max(0.0, self.progress)))
        if not self.message.strip():
            raise ValueError("A progress update must include a message.")


@runtime_checkable
class ProgressReporter(Protocol):
    def report(self, progress: float, message: str) -> None:
        """Report a normalized progress value and a user-facing message."""


class CallbackProgressReporter:
    def __init__(self, callback: Callable[[ProgressUpdate], None]) -> None:
        self._callback = callback

    def report(self, progress: float, message: str) -> None:
        self._callback(ProgressUpdate(progress=progress, message=message))


@dataclass(frozen=True)
class StemResult:
    stems: Mapping[StemName, Path]
    sample_rate: int
    channels: int
    duration_seconds: float
    backend_id: str
    model_id: str
    device: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = set(self.stems)
        expected = set(STEM_NAMES)
        if names != expected:
            missing = sorted(expected - names)
            extra = sorted(names - expected)
            raise ValueError(f"Invalid stem result; missing={missing}, extra={extra}")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive.")
        if self.channels <= 0:
            raise ValueError("channels must be positive.")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive.")
        if not self.backend_id or not self.model_id or not self.device:
            raise ValueError("backend_id, model_id, and device are required.")

    def stems_payload(self) -> dict[StemName, str]:
        return {name: str(self.stems[name]) for name in STEM_NAMES}

    def metadata_payload(self) -> dict[str, object]:
        return {
            "backendId": self.backend_id,
            "modelId": self.model_id,
            "device": self.device,
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "durationSeconds": self.duration_seconds,
            "warnings": list(self.warnings),
        }


@runtime_checkable
class StemSeparator(Protocol):
    backend_id: str
    model_id: str

    def separate(
        self,
        input_path: Path,
        output_dir: Path,
        progress: ProgressReporter,
    ) -> StemResult:
        """Separate one source file into the standard four-stem result."""

