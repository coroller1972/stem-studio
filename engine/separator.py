"""Compatibility facade for callers of the original functional API."""

from __future__ import annotations

from pathlib import Path

from audio_io import AudioIO
from domain import ProgressReporter, StemResult
from errors import SeparationError
from factory import create_separator
from registry import STANDARD_PROFILE, SeparationProfile


def separate_audio(
    source: Path,
    output: Path,
    progress: ProgressReporter,
    profile: SeparationProfile = STANDARD_PROFILE,
    audio_io: AudioIO | None = None,
) -> StemResult:
    """Run separation through the backend registry.

    Kept for compatibility; new code should create a StemSeparator through the factory.
    """

    separator = create_separator(profile, audio_io=audio_io)
    return separator.separate(source, output, progress)


__all__ = ["SeparationError", "separate_audio"]
