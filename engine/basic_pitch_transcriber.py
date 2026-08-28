"""Spotify Basic Pitch adapter with monophonic bass decoding."""

from __future__ import annotations

import math
import shutil
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from basic_pitch_monophonic import MonophonicDecoderSettings, decode_monophonic_bass
from bass_fundamental import FundamentalTrack, estimate_pyin_fundamental
from errors import TranscriptionError
from transcription_domain import NoteEvent

BASIC_PITCH_MODEL_ID = "spotify-basic-pitch-icassp-2022-monophonic-v1"


@dataclass(frozen=True)
class BasicPitchBassSettings:
    """Product-level decoder settings covering standard four- and five-string basses."""

    onset_threshold: float = 0.55
    frame_threshold: float = 0.35
    minimum_note_length_ms: float = 130
    minimum_onset_note_length_ms: float = 55
    minimum_midi_pitch: int = 23
    maximum_midi_pitch: int = 67
    melodia_trick: bool = False


class BasicPitchBassTranscriber:
    model_id = BASIC_PITCH_MODEL_ID

    def __init__(
        self,
        models_dir: Path | None = None,
        settings: BasicPitchBassSettings | None = None,
    ) -> None:
        self.models_dir = models_dir
        self.settings = settings or BasicPitchBassSettings()
        self._model: Any | None = None

    def transcribe(self, audio_path: Path) -> tuple[NoteEvent, ...]:
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model, run_inference
            from basic_pitch.note_creation import model_frames_to_time
        except ImportError as error:
            raise TranscriptionError(
                "Unable to load the bass transcription model.",
                "Basic Pitch requires Python 3.10 or 3.11 and engine/requirements.txt.",
            ) from error

        try:
            with redirect_stdout(sys.stderr):
                if self._model is None:
                    model_path = self._materialize_model(Path(ICASSP_2022_MODEL_PATH))
                    self._model = Model(model_path)
                model_output = run_inference(
                    audio_path,
                    self._model,
                )
        except Exception as error:
            raise TranscriptionError("Bass transcription failed.", str(error)) from error

        frame_times = model_frames_to_time(model_output["note"].shape[0])
        fundamental = self._fundamental_prior(audio_path, frame_times)
        try:
            return decode_monophonic_bass(
                model_output["note"],
                model_output["onset"],
                frame_times,
                self._decoder_settings(),
                fundamental_midi=fundamental.midi,
                fundamental_confidence=fundamental.confidence,
                contour_probabilities=model_output["contour"],
            )
        except Exception as error:
            raise TranscriptionError("Bass transcription decoding failed.", str(error)) from error

    def _fundamental_prior(
        self,
        audio_path: Path,
        frame_times: Any,
    ) -> FundamentalTrack:
        try:
            return estimate_pyin_fundamental(
                audio_path,
                frame_times,
                self.settings.minimum_midi_pitch,
                self.settings.maximum_midi_pitch,
            )
        except Exception as error:
            print(
                f"Basic Pitch fundamental verification unavailable; continuing without it: {error}",
                file=sys.stderr,
            )
            frame_count = len(frame_times)
            return FundamentalTrack(
                tuple(math.nan for _ in range(frame_count)),
                tuple(0.0 for _ in range(frame_count)),
            )

    def _decoder_settings(self) -> MonophonicDecoderSettings:
        return MonophonicDecoderSettings(
            minimum_midi_pitch=self.settings.minimum_midi_pitch,
            maximum_midi_pitch=self.settings.maximum_midi_pitch,
            frame_threshold=self.settings.frame_threshold,
            onset_threshold=self.settings.onset_threshold,
            minimum_note_length_ms=self.settings.minimum_note_length_ms,
            minimum_onset_note_length_ms=self.settings.minimum_onset_note_length_ms,
        )

    def _materialize_model(self, packaged_path: Path) -> Path:
        if self.models_dir is None:
            return packaged_path
        destination = self.models_dir / "basic-pitch" / packaged_path.name
        if destination.exists():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        if packaged_path.is_dir():
            shutil.copytree(packaged_path, destination)
        else:
            shutil.copyfile(packaged_path, destination)
        return destination


def _midi_frequency(midi_pitch: int) -> float:
    return 440.0 * math.pow(2.0, (midi_pitch - 69) / 12.0)
