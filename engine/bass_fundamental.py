"""Low-cost monophonic fundamental prior aligned to model frame times."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class FundamentalTrack:
    midi: tuple[float, ...]
    confidence: tuple[float, ...]


@dataclass(frozen=True)
class PyinFundamentalSettings:
    sample_rate: int = 22_050
    hop_length: int = 256
    frame_length: int = 4_096
    resolution: float = 0.2
    minimum_voiced_probability: float = 0.35


def estimate_pyin_fundamental(
    audio_path: Path,
    frame_times: Sequence[float],
    minimum_midi_pitch: int,
    maximum_midi_pitch: int,
    settings: PyinFundamentalSettings | None = None,
) -> FundamentalTrack:
    """Estimate pYIN once and align its voiced frames to Basic Pitch times."""

    import librosa

    config = settings or PyinFundamentalSettings()
    times = np.asarray(frame_times, dtype=np.float64)
    if len(times) == 0:
        return FundamentalTrack((), ())
    audio, _sample_rate = librosa.load(
        str(audio_path),
        sr=config.sample_rate,
        mono=True,
    )
    frequencies, _voiced, voiced_probabilities = librosa.pyin(
        audio,
        fmin=_midi_frequency(minimum_midi_pitch),
        fmax=_midi_frequency(maximum_midi_pitch),
        sr=config.sample_rate,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
        resolution=config.resolution,
        center=True,
    )
    if frequencies is None or voiced_probabilities is None or len(frequencies) == 0:
        return _empty_track(len(times))

    source_times = librosa.times_like(
        frequencies,
        sr=config.sample_rate,
        hop_length=config.hop_length,
    )
    indices = np.searchsorted(source_times, times, side="left")
    indices = np.clip(indices, 0, len(source_times) - 1)
    previous = np.maximum(0, indices - 1)
    choose_previous = np.abs(source_times[previous] - times) < np.abs(source_times[indices] - times)
    indices = np.where(choose_previous, previous, indices)

    aligned_midi = np.full(len(times), np.nan, dtype=np.float64)
    aligned_confidence = np.zeros(len(times), dtype=np.float64)
    for target, source in enumerate(indices):
        frequency = float(frequencies[source])
        confidence = float(voiced_probabilities[source])
        if (
            math.isfinite(frequency)
            and frequency > 0
            and math.isfinite(confidence)
            and confidence >= config.minimum_voiced_probability
        ):
            aligned_midi[target] = _frequency_to_midi(frequency)
            aligned_confidence[target] = min(1.0, max(0.0, confidence))
    return FundamentalTrack(
        tuple(float(value) for value in aligned_midi),
        tuple(float(value) for value in aligned_confidence),
    )


def _empty_track(frame_count: int) -> FundamentalTrack:
    return FundamentalTrack(
        tuple(math.nan for _ in range(frame_count)),
        tuple(0.0 for _ in range(frame_count)),
    )


def _midi_frequency(midi_pitch: int) -> float:
    return 440.0 * math.pow(2.0, (midi_pitch - 69) / 12.0)


def _frequency_to_midi(frequency: float) -> float:
    return 69 + 12 * math.log2(frequency / 440.0)
