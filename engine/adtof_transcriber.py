"""ADTOF-PyTorch adapter returning normalized Stem Studio DrumEvent values."""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

from errors import TranscriptionError
from gm_drums import normalize_adtof_instrument
from runtime import preferred_torch_device
from transcription_domain import DrumEvent

ADTOF_MODEL_ID = "adtof-pytorch-frame-rnn-5-class"
ADTOF_WEIGHTS_NAME = "adtof_frame_rnn_pytorch_weights.pth"
ADTOF_WEIGHTS_SHA256 = "1bc986e596ec47ba0b44916f87cd4a39f0b2bec23596df3fb5d0e87749217320"
ADTOF_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/xavriley/ADTOF-pytorch/"
    "85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9/"
    "src/adtof_pytorch/data/adtof_frame_rnn_pytorch_weights.pth"
)


class AdtofDrumTranscriber:
    model_id = ADTOF_MODEL_ID

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = models_dir

    def transcribe(self, audio_path: Path) -> tuple[DrumEvent, ...]:
        try:
            import numpy as np
            import torch
            from adtof_pytorch import (
                FRAME_RNN_THRESHOLDS,
                LABELS_5,
                PeakPicker,
                calculate_n_bins,
                create_frame_rnn_model,
                load_audio_for_model,
                load_pytorch_weights,
            )
        except ImportError as error:
            raise TranscriptionError(
                "Unable to load the drum transcription model.",
                "Install ADTOF-PyTorch from engine/requirements.txt.",
            ) from error

        weights_path = self._weights_path()
        device = preferred_torch_device()
        try:
            # The sidecar reserves stdout for JSONL protocol events. Some upstream
            # helpers print diagnostics, so route them to stderr instead.
            with redirect_stdout(sys.stderr):
                model = create_frame_rnn_model(calculate_n_bins())
                model = load_pytorch_weights(model, str(weights_path), strict=False).eval().to(device)
                audio = load_audio_for_model(str(audio_path)).to(device)
                with torch.no_grad():
                    activations = model(audio).cpu().numpy()
        except Exception as device_error:
            if device != "mps":
                raise TranscriptionError("Drum transcription failed.", str(device_error)) from device_error
            try:
                with redirect_stdout(sys.stderr):
                    model = create_frame_rnn_model(calculate_n_bins())
                    model = load_pytorch_weights(model, str(weights_path), strict=False).eval().to("cpu")
                    audio = load_audio_for_model(str(audio_path)).to("cpu")
                    with torch.no_grad():
                        activations = model(audio).cpu().numpy()
            except Exception as error:
                raise TranscriptionError("Drum transcription failed.", str(error)) from error

        picker = PeakPicker(thresholds=FRAME_RNN_THRESHOLDS, fps=100)
        peaks = picker.pick(activations, labels=LABELS_5)[0]
        events: list[DrumEvent] = []
        for label_index, label in enumerate(LABELS_5):
            for time in peaks.get(label, []):
                frame = min(activations.shape[1] - 1, max(0, round(float(time) * 100)))
                confidence = float(np.clip(activations[0, frame, label_index], 0, 1))
                events.append(
                    DrumEvent(
                        id="",
                        detected_time_seconds=float(time),
                        instrument=normalize_adtof_instrument(int(label)),
                        velocity=max(1, min(127, round(confidence * 127))),
                        confidence=confidence,
                    )
                )
        events.sort(key=lambda item: (item.detected_time_seconds, item.instrument))
        return tuple(
            DrumEvent(
                id=f"drums-{index:06d}",
                detected_time_seconds=event.detected_time_seconds,
                instrument=event.instrument,
                velocity=event.velocity,
                confidence=event.confidence,
            )
            for index, event in enumerate(events)
        )

    def _weights_path(self) -> Path:
        configured = os.environ.get("STEM_STUDIO_ADTOF_WEIGHTS")
        if configured:
            path = Path(configured).expanduser()
        elif self.models_dir is not None:
            path = self.models_dir / "adtof" / ADTOF_WEIGHTS_NAME
        else:
            path = Path.home() / ".cache" / "stem-studio" / "adtof" / ADTOF_WEIGHTS_NAME
        if path.is_file() and _sha256(path) == ADTOF_WEIGHTS_SHA256:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".download")
        try:
            urllib.request.urlretrieve(ADTOF_WEIGHTS_URL, temporary)
            if _sha256(temporary) != ADTOF_WEIGHTS_SHA256:
                raise ValueError("ADTOF weight checksum mismatch")
            temporary.replace(path)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise TranscriptionError("Unable to load the drum transcription model.", str(error)) from error
        return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
