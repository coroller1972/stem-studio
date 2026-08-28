"""Audio decoding and encoding behind a backend-independent contract."""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

MAX_AUDIO_SECONDS = 30 * 60


class AudioIOError(RuntimeError):
    pass


class AudioDependencyError(AudioIOError):
    pass


class AudioDecodingError(AudioIOError):
    pass


class AudioEncodingError(AudioIOError):
    pass


@runtime_checkable
class AudioIO(Protocol):
    def load(self, source: Path, sample_rate: int, channels: int) -> Any:
        """Return a channels-first floating point waveform."""

    def save_wav(self, audio: Any, path: Path, sample_rate: int) -> None:
        """Write one channels-first waveform to a WAV file."""


class FfmpegAudioIO:
    """FFmpeg-first I/O with torchaudio and standard-library fallbacks."""

    def load(self, source: Path, sample_rate: int, channels: int) -> Any:
        try:
            import numpy
            import torch
        except ImportError as error:
            raise AudioDependencyError(
                "NumPy and PyTorch are required by the audio engine."
            ) from error

        errors: list[str] = []
        ffmpeg = resolve_ffmpeg_executable()
        if ffmpeg:
            try:
                result = subprocess.run(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        str(source),
                        "-vn",
                        "-f",
                        "f32le",
                        "-acodec",
                        "pcm_f32le",
                        "-ar",
                        str(sample_rate),
                        "-ac",
                        str(channels),
                        "-t",
                        str(MAX_AUDIO_SECONDS + 0.001),
                        "pipe:1",
                    ],
                    check=True,
                    capture_output=True,
                )
                pcm = numpy.frombuffer(result.stdout, dtype=numpy.float32)
                if pcm.size == 0:
                    raise ValueError("ffmpeg returned an empty audio stream")
                usable_samples = pcm.size - (pcm.size % channels)
                maximum_samples = sample_rate * channels * MAX_AUDIO_SECONDS
                if usable_samples >= maximum_samples:
                    raise AudioDecodingError(
                        "Audio duration exceeds the 30 minute processing limit."
                    )
                channels_last = pcm[:usable_samples].copy().reshape(-1, channels)
                return torch.from_numpy(channels_last).transpose(0, 1).contiguous()
            except (subprocess.CalledProcessError, OSError, ValueError) as error:
                detail = (
                    error.stderr.decode(errors="replace")
                    if isinstance(error, subprocess.CalledProcessError)
                    else str(error)
                )
                errors.append(f"ffmpeg: {detail.strip()}")
        else:
            errors.append("ffmpeg: executable not found")

        try:
            import torchaudio

            waveform, source_sample_rate = torchaudio.load(str(source))
            if source_sample_rate != sample_rate:
                waveform = torchaudio.functional.resample(
                    waveform,
                    source_sample_rate,
                    sample_rate,
                )
            if waveform.shape[0] != channels:
                mono = waveform.mean(dim=0, keepdim=True)
                waveform = mono.repeat(channels, 1)
            if waveform.shape[-1] >= sample_rate * MAX_AUDIO_SECONDS:
                raise AudioDecodingError(
                    "Audio duration exceeds the 30 minute processing limit."
                )
            return waveform
        except Exception as error:
            errors.append(f"torchaudio: {error}")
            raise AudioDecodingError("; ".join(errors)) from error

    def save_wav(self, audio: Any, path: Path, sample_rate: int) -> None:
        tensor = audio.detach().cpu().float()
        peak = tensor.abs().max().item()
        if peak > 0.99:
            tensor = tensor * (0.99 / peak)
        channels_last = tensor.transpose(0, 1).contiguous().numpy()
        channels = channels_last.shape[1]

        ffmpeg = resolve_ffmpeg_executable()
        if ffmpeg:
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-f",
                        "f32le",
                        "-ar",
                        str(sample_rate),
                        "-ac",
                        str(channels),
                        "-i",
                        "pipe:0",
                        "-c:a",
                        "pcm_f32le",
                        "-y",
                        str(path),
                    ],
                    input=channels_last.astype("<f4", copy=False).tobytes(),
                    check=True,
                    capture_output=True,
                )
                return
            except (subprocess.CalledProcessError, OSError) as error:
                detail = (
                    error.stderr.decode(errors="replace")
                    if isinstance(error, subprocess.CalledProcessError)
                    else str(error)
                )
                raise AudioEncodingError(detail.strip()) from error

        pcm16 = (channels_last.clip(-1, 1) * 32767).astype("<i2", copy=False)
        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm16.tobytes())
        except (OSError, wave.Error) as error:
            raise AudioEncodingError(str(error)) from error


def resolve_ffmpeg_executable() -> str | None:
    configured = os.environ.get("STEM_STUDIO_FFMPEG")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ffmpeg")
