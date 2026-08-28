"""Demucs implementation of the backend-independent StemSeparator contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from audio_io import (
    AudioDecodingError,
    AudioDependencyError,
    AudioEncodingError,
    AudioIO,
    FfmpegAudioIO,
)
from domain import ProgressReporter, STEM_NAMES, StemName, StemResult
from errors import SeparationError
from project_files import prepare_project, write_result_metadata
from runtime import preferred_torch_device, run_with_heartbeat

InferenceRunner = Callable[[Path, str, str, AudioIO], tuple[dict[str, Any], int]]
DeviceSelector = Callable[[], str]


class DemucsSeparator:
    backend_id = "demucs"

    def __init__(
        self,
        model_id: str = "htdemucs",
        *,
        profile_id: str = "standard",
        audio_io: AudioIO | None = None,
        device_selector: DeviceSelector | None = None,
        inference_runner: InferenceRunner | None = None,
    ) -> None:
        self.model_id = model_id
        self.profile_id = profile_id
        self._audio_io = audio_io or FfmpegAudioIO()
        self._device_selector = device_selector or preferred_torch_device
        self._inference_runner = inference_runner or run_demucs

    def separate(
        self,
        input_path: Path,
        output_dir: Path,
        progress: ProgressReporter,
    ) -> StemResult:
        source, output = prepare_project(
            input_path,
            output_dir,
            profile_id=self.profile_id,
            backend_id=self.backend_id,
            model_id=self.model_id,
        )

        progress.report(0.03, "Validating audio file")
        selected_device = self._device_selector()
        progress.report(0.08, f"Loading separation model on {selected_device.upper()}")
        final_device = selected_device
        warnings: tuple[str, ...] = ()

        try:
            separated, sample_rate = self._infer_with_heartbeat(
                source,
                selected_device,
                progress,
                start=0.12,
                end=0.82,
            )
        except SeparationError:
            raise
        except Exception as device_error:
            if selected_device != "mps":
                raise SeparationError("Stem separation failed.", str(device_error)) from device_error
            progress.report(0.14, "MPS failed; retrying safely on CPU")
            final_device = "cpu"
            warnings = ("MPS inference failed; CPU fallback was used.",)
            try:
                separated, sample_rate = self._infer_with_heartbeat(
                    source,
                    "cpu",
                    progress,
                    start=0.16,
                    end=0.82,
                )
            except SeparationError:
                raise
            except Exception as cpu_error:
                raise SeparationError("Stem separation failed.", str(cpu_error)) from cpu_error

        progress.report(0.86, "Writing WAV stems")
        stems = self._save_stems(separated, sample_rate, output)
        reference_stem = separated[STEM_NAMES[0]]
        result = StemResult(
            stems=stems,
            sample_rate=sample_rate,
            channels=int(reference_stem.shape[-2]),
            duration_seconds=float(reference_stem.shape[-1] / sample_rate),
            backend_id=self.backend_id,
            model_id=self.model_id,
            device=final_device,
            warnings=warnings,
        )
        write_result_metadata(output, result)
        progress.report(0.98, "Finalizing project")
        return result

    def _infer_with_heartbeat(
        self,
        source: Path,
        device: str,
        progress: ProgressReporter,
        *,
        start: float,
        end: float,
    ) -> tuple[dict[str, Any], int]:
        def operation() -> tuple[dict[str, Any], int]:
            return self._inference_runner(
                source,
                device,
                self.model_id,
                self._audio_io,
            )

        return run_with_heartbeat(
            operation,
            progress,
            start,
            end,
            thread_name="demucs",
        )

    def _save_stems(
        self,
        separated: dict[str, Any],
        sample_rate: int,
        output: Path,
    ) -> dict[StemName, Path]:
        paths: dict[StemName, Path] = {}
        for name in STEM_NAMES:
            path = output / f"{name}.wav"
            try:
                self._audio_io.save_wav(separated[name], path, sample_rate)
            except AudioEncodingError as error:
                raise SeparationError("Unable to write separated stems.", str(error)) from error
            paths[name] = path
        return paths


def run_demucs(
    source: Path,
    device: str,
    model_id: str,
    audio_io: AudioIO,
) -> tuple[dict[str, Any], int]:
    try:
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError as error:
        raise SeparationError(
            "Demucs engine is not installed.",
            "Install engine/requirements.txt in the development virtualenv.",
        ) from error

    try:
        model = get_model(model_id)
    except Exception as error:
        raise SeparationError(
            "Unable to load the separation model.",
            f"Check the network connection and PyTorch model cache: {error}",
        ) from error

    model.cpu()
    model.eval()
    try:
        waveform = audio_io.load(source, model.samplerate, model.audio_channels)
    except AudioDependencyError as error:
        raise SeparationError("Audio engine dependencies are not installed.", str(error)) from error
    except AudioDecodingError as error:
        raise SeparationError("Unable to decode this audio file.", str(error)) from error

    reference = waveform.mean(0)
    mean = reference.mean()
    standard_deviation = reference.std()
    if not standard_deviation.isfinite() or standard_deviation.item() < 1e-8:
        raise SeparationError("Unable to decode this audio file.", "The audio signal is empty.")

    normalized = (waveform - mean) / standard_deviation
    sources = apply_model(
        model,
        normalized[None],
        device=device,
        shifts=1,
        split=True,
        overlap=0.25,
        progress=False,
        num_workers=0,
    )[0]
    sources = sources * standard_deviation + mean
    separated = dict(zip(model.sources, sources))
    missing = set(STEM_NAMES).difference(separated.keys())
    if missing:
        raise SeparationError("Stem separation failed.", f"Missing Demucs stems: {sorted(missing)}")
    return separated, model.samplerate

