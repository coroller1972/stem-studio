"""DrumScript adapter returning normalized Stem Studio drum events."""

from __future__ import annotations

import math
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Sequence

from errors import TranscriptionError
from gm_drums import normalize_drum_instrument
from transcription_domain import DrumEvent

DRUMSCRIPT_MODEL_ID = "drumscript-physics-0.2.1"


class DrumScriptTranscriber:
    """Transcribe an isolated drum stem with DrumScript's onset classifier."""

    model_id = DRUMSCRIPT_MODEL_ID

    def transcribe(self, audio_path: Path) -> tuple[DrumEvent, ...]:
        try:
            import numpy as np
            from drumscript.audio_processor.audio_loader import load_audio, normalise_audio
            from drumscript.audio_processor.onset_detector import detect_onsets
            from drumscript.drum_classifier.classify import classify_events
        except ImportError as error:
            raise TranscriptionError(
                "Unable to load the drum transcription engine.",
                "Install DrumScript from engine/requirements.txt.",
            ) from error

        try:
            # DrumScript writes diagnostics to stdout. Stem Studio reserves stdout
            # for its JSON-lines protocol, so keep dependency logs on stderr.
            with redirect_stdout(sys.stderr):
                audio, sample_rate = load_audio(str(audio_path), sr=44_100)
                audio = normalise_audio(audio)
                onsets = detect_onsets(audio, sample_rate)
                classified = classify_events(audio, sample_rate, onsets)
        except Exception as error:
            raise TranscriptionError("Drum transcription failed.", str(error)) from error

        return events_from_drumscript(classified, audio, sample_rate, np)


def events_from_drumscript(
    classified: Sequence[dict[str, Any]],
    audio: Any,
    sample_rate: int,
    np: Any,
) -> tuple[DrumEvent, ...]:
    """Convert DrumScript's polyphonic onset dictionaries to stable events."""

    onset_levels = [
        _onset_level(audio, sample_rate, float(item.get("time_sec", 0)), np)
        for item in classified
    ]
    positive_levels = [level for level in onset_levels if level > 0]
    reference_level = (
        float(np.percentile(positive_levels, 90)) if positive_levels else 1.0
    )

    converted: list[tuple[float, str, int]] = []
    for item, level in zip(classified, onset_levels):
        timestamp = max(0.0, float(item.get("time_sec", 0)))
        velocity = _velocity(level, reference_level)
        instruments = dict.fromkeys(item.get("instruments", ()))
        for raw_instrument in instruments:
            instrument = normalize_drum_instrument(str(raw_instrument))
            converted.append((timestamp, instrument, velocity))

    converted.sort(key=lambda value: (value[0], value[1]))
    return tuple(
        DrumEvent(
            id=f"drums-{index:06d}",
            detected_time_seconds=timestamp,
            instrument=instrument,
            velocity=velocity,
            # DrumScript 0.2 is deterministic and does not expose calibrated
            # probabilities, so inventing a confidence would be misleading.
            confidence=None,
        )
        for index, (timestamp, instrument, velocity) in enumerate(converted)
    )


def _onset_level(audio: Any, sample_rate: int, timestamp: float, np: Any) -> float:
    start = max(0, round(timestamp * sample_rate))
    end = min(len(audio), start + max(1, round(sample_rate * 0.05)))
    if end <= start:
        return 0.0
    window = np.asarray(audio[start:end], dtype=np.float32)
    return float(np.sqrt(np.mean(np.square(window), dtype=np.float64)))


def _velocity(level: float, reference_level: float) -> int:
    ratio = max(0.0, min(1.0, level / max(reference_level, 1e-8)))
    return max(1, min(127, round(45 + 82 * math.sqrt(ratio))))
