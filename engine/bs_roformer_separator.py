"""BS-RoFormer MUSDB18HQ implementation of the StemSeparator contract."""

from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import redirect_stdout
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
from runtime import device_override, preferred_torch_device, run_with_heartbeat

BS_ROFORMER_MUSDB18HQ = "roformer-model-bs-roformer-musdb18hq-by-zfturbo"
SessionFactory = Callable[..., Any]
DeviceSelector = Callable[[], str]
# Seconds of CPU inference per second of audio on an Apple M4, measured in
# November 2026; the progress estimate assumes a slightly slower machine.
EXPECTED_SECONDS_PER_AUDIO_SECOND = 2.2


def bs_roformer_device() -> str:
    """The preferred accelerator, except Apple's GPU, which this model overflows.

    The model's configuration cuts audio into 11 s chunks. On Apple Silicon the
    GPU shares unified memory with the system, and its attention kernel builds
    each full attention matrix (about 2.2 GB per call for an 11 s chunk). On a
    16 GB Mac under macOS 27.2 with PyTorch 2.8 that pushes the machine into
    swap: 10 s of audio took 90 s on MPS but 18 s on the CPU, whose kernel works
    in blocks. With 8 s chunks the GPU was slightly faster than the CPU (Apple
    M4, November 2026). CUDA is unaffected. STEM_STUDIO_TORCH_DEVICE=mps
    re-enables the Apple GPU to measure again after a PyTorch or macOS update.
    """
    override = device_override()
    if override:
        return override
    device = preferred_torch_device()
    return "cpu" if device == "mps" else device


class BSRoFormerSeparator:
    backend_id = "bs_roformer"

    def __init__(
        self,
        model_id: str = BS_ROFORMER_MUSDB18HQ,
        *,
        profile_id: str = "high",
        audio_io: AudioIO | None = None,
        device_selector: DeviceSelector | None = None,
        session_factory: SessionFactory | None = None,
        models_dir: Path | None = None,
    ) -> None:
        self.model_id = model_id
        self.profile_id = profile_id
        self._audio_io = audio_io or FfmpegAudioIO()
        self._device_selector = device_selector or bs_roformer_device
        self._session_factory = session_factory or create_session
        self._models_dir = models_dir

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

        try:
            waveform = self._audio_io.load(source, sample_rate=44_100, channels=2)
        except AudioDependencyError as error:
            raise SeparationError("Audio engine dependencies are not installed.", str(error)) from error
        except AudioDecodingError as error:
            raise SeparationError("Unable to decode this audio file.", str(error)) from error

        selected_device = self._device_selector()
        progress.report(0.08, f"Loading high-quality model on {selected_device.upper()}")
        expected_seconds = EXPECTED_SECONDS_PER_AUDIO_SECOND * waveform.shape[-1] / 44_100
        final_device = selected_device
        warnings: tuple[str, ...] = ()

        with tempfile.TemporaryDirectory(prefix="stem-studio-bs-roformer-") as temporary:
            temporary_root = Path(temporary)
            input_folder = temporary_root / "input"
            stem_folder = temporary_root / "stems"
            input_folder.mkdir()
            stem_folder.mkdir()
            prepared_source = input_folder / "source.wav"
            try:
                self._audio_io.save_wav(waveform, prepared_source, 44_100)
            except AudioEncodingError as error:
                raise SeparationError("Unable to prepare audio for separation.", str(error)) from error

            try:
                manifest = self._infer_with_heartbeat(
                    input_folder,
                    stem_folder,
                    selected_device,
                    progress,
                    start=0.12,
                    end=0.82,
                    expected_seconds=expected_seconds,
                )
            except SeparationError:
                raise
            except Exception as device_error:
                if selected_device == "cpu":
                    raise SeparationError("High-quality separation failed.", str(device_error)) from device_error
                accelerator = selected_device.upper()
                progress.report(0.14, f"{accelerator} failed; retrying high quality on CPU")
                final_device = "cpu"
                warnings = (f"{accelerator} inference failed; CPU fallback was used.",)
                try:
                    manifest = self._infer_with_heartbeat(
                        input_folder,
                        stem_folder,
                        "cpu",
                        progress,
                        start=0.16,
                        end=0.82,
                        expected_seconds=expected_seconds,
                    )
                except SeparationError:
                    raise
                except Exception as cpu_error:
                    raise SeparationError("High-quality separation failed.", str(cpu_error)) from cpu_error

            progress.report(0.86, "Collecting high-quality WAV stems")
            stems = copy_standard_stems(manifest, output)

        result = StemResult(
            stems=stems,
            sample_rate=44_100,
            channels=int(waveform.shape[-2]),
            duration_seconds=float(waveform.shape[-1] / 44_100),
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
        input_folder: Path,
        stem_folder: Path,
        device: str,
        progress: ProgressReporter,
        *,
        start: float,
        end: float,
        expected_seconds: float = 225.0,
    ) -> Any:
        def operation() -> Any:
            session = self._session_factory(
                model_name=self.model_id,
                models_dir=self._models_dir,
                backend="torch",
                device=device,
                progress=False,
            )
            try:
                # The dependency prints human logs; keep stdout reserved for our JSON-lines protocol.
                with redirect_stdout(sys.stderr):
                    session.load()
                    return session.infer(
                        input_folder,
                        store_dir=stem_folder,
                        verbose=False,
                        output_format="wav_float32",
                    )
            finally:
                session.close()

        return run_with_heartbeat(
            operation,
            progress,
            start,
            end,
            thread_name="bs-roformer",
            message="Running high-quality separation",
            time_constant_seconds=expected_seconds / 3,
        )


def create_session(**kwargs: Any) -> Any:
    try:
        from bs_roformer import BSRoformerSession
    except ImportError as error:
        raise SeparationError(
            "High-quality engine is not installed.",
            "BS-RoFormer requires Python 3.10+ and engine/requirements.txt.",
        ) from error
    return BSRoformerSession(**kwargs)


def copy_standard_stems(manifest: Any, output: Path) -> dict[StemName, Path]:
    produced = {
        item.output_id: Path(item.output_path)
        for item in manifest.outputs
        if item.output_id in STEM_NAMES
    }
    missing = set(STEM_NAMES).difference(produced)
    if missing:
        raise SeparationError(
            "High-quality separation returned incomplete stems.",
            f"Missing BS-RoFormer stems: {sorted(missing)}",
        )

    stems: dict[StemName, Path] = {}
    for name in STEM_NAMES:
        destination = output / f"{name}.wav"
        shutil.copyfile(produced[name], destination)
        stems[name] = destination
    return stems
