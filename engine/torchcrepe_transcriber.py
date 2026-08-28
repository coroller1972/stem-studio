"""Experimental monophonic bass transcription powered by TorchCREPE."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from audio_io import FfmpegAudioIO
from errors import TranscriptionError
from runtime import preferred_torch_device
from transcription_domain import NoteEvent

# The v5 decoder keeps TorchCREPE in its stable range, recovers low B through
# the bounded spectral fallback and distinguishes fragments from real attacks.
TORCHCREPE_MODEL_ID = "torchcrepe-tiny-0.0.24-hybrid-v5"
# Enabling bin zero globally makes the 0.0.24 Viterbi decoder stick to its
# lower boundary. B0 (30.87 Hz) is therefore handled by the YIN fallback.
CREPE_STABLE_MINIMUM_FREQUENCY_HZ = 32.7


@dataclass(frozen=True)
class TorchCrepeBassSettings:
    """Conservative decoder settings for an isolated, monophonic bass stem."""

    sample_rate: int = 16_000
    hop_length: int = 160
    model: str = "tiny"
    batch_size: int = 1_024
    minimum_midi_pitch: int = 23
    maximum_midi_pitch: int = 67
    periodicity_on: float = 0.48
    periodicity_off: float = 0.32
    silence_threshold_db: float = -55.0
    median_filter_frames: int = 5
    stable_pitch_frames: int = 3
    pitch_jump_semitones: float = 0.72
    maximum_unvoiced_gap_ms: float = 20.0
    minimum_note_length_ms: float = 110.0
    minimum_onset_note_length_ms: float = 55.0
    merge_gap_ms: float = 30.0
    onset_fft_size: int = 1_024
    onset_frequency_max_hz: float = 3_000.0
    onset_peak_delta: float = 0.08
    onset_peak_wait_frames: int = 3
    onset_boundary_guard_ms: float = 55.0
    spectral_fallback_frame_length: int = 4_096
    spectral_fallback_trough_threshold: float = 0.12
    spectral_fallback_max_interval_ms: float = 800.0
    spectral_fallback_max_crepe_support: float = 0.30
    spectral_fallback_stability: float = 0.58
    spectral_fallback_pitch_tolerance: float = 0.75
    spectral_fallback_confidence: float = 0.50


@dataclass(frozen=True)
class PitchTrack:
    frequencies_hz: Sequence[float]
    periodicities: Sequence[float]
    loudness_db: Sequence[float]
    hop_seconds: float
    audio_duration_seconds: float
    onset_strengths: Sequence[float] = ()
    spectral_frequencies_hz: Sequence[float] = ()


class TorchCrepeBassTranscriber:
    """Convert TorchCREPE frame predictions to Stem Studio ``NoteEvent`` values."""

    model_id = TORCHCREPE_MODEL_ID

    def __init__(
        self,
        models_dir: Path | None = None,
        settings: TorchCrepeBassSettings | None = None,
        audio_io: Any | None = None,
    ) -> None:
        # Kept for parity with other transcribers. TorchCREPE currently ships its
        # tiny checkpoint with the Python package rather than downloading it.
        self.models_dir = models_dir
        self.settings = settings or TorchCrepeBassSettings()
        self.audio_io = audio_io or FfmpegAudioIO()

    def transcribe(self, audio_path: Path) -> tuple[NoteEvent, ...]:
        try:
            import torch
            import torchcrepe
        except ImportError as error:
            raise TranscriptionError(
                "Unable to load the experimental bass transcription model.",
                "TorchCREPE requires torchcrepe==0.0.24 and engine/requirements.txt.",
            ) from error

        try:
            audio = self.audio_io.load(audio_path, self.settings.sample_rate, 1).float()
            if audio.ndim != 2 or audio.shape[0] != 1 or audio.shape[1] == 0:
                raise ValueError("decoded bass audio is empty or has an invalid shape")
            frequencies, periodicities = self._predict(torchcrepe, audio)
            frame_count = int(frequencies.shape[-1])
            cpu_audio = audio[0].detach().cpu()
            loudness = _frame_loudness_db(cpu_audio, frame_count)
            onset_strengths = _detect_onset_strengths(
                cpu_audio,
                frame_count,
                self.settings,
            )
            spectral_frequencies = _spectral_pitch_frequencies(
                cpu_audio,
                frame_count,
                self.settings,
            )
            track = PitchTrack(
                frequencies_hz=frequencies[0].detach().cpu().tolist(),
                periodicities=periodicities[0].detach().cpu().tolist(),
                loudness_db=loudness,
                hop_seconds=self.settings.hop_length / self.settings.sample_rate,
                audio_duration_seconds=audio.shape[-1] / self.settings.sample_rate,
                onset_strengths=onset_strengths,
                spectral_frequencies_hz=spectral_frequencies,
            )
            del frequencies, periodicities
            if preferred_torch_device() == "mps":
                torch.mps.empty_cache()
            return segment_pitch_track(track, self.settings)
        except TranscriptionError:
            raise
        except Exception as error:
            raise TranscriptionError("Experimental bass transcription failed.", str(error)) from error

    def _predict(self, torchcrepe: Any, audio: Any) -> tuple[Any, Any]:
        device = preferred_torch_device()
        try:
            return self._predict_on_device(torchcrepe, audio, device)
        except Exception:
            if device == "cpu":
                raise
            # MPS support depends on the installed PyTorch build. A clean CPU
            # retry keeps the experimental engine usable on older macOS setups.
            return self._predict_on_device(torchcrepe, audio, "cpu")

    def _predict_on_device(self, torchcrepe: Any, audio: Any, device: str) -> tuple[Any, Any]:
        settings = self.settings
        return torchcrepe.predict(
            audio.to(device),
            settings.sample_rate,
            settings.hop_length,
            max(
                CREPE_STABLE_MINIMUM_FREQUENCY_HZ,
                _midi_frequency(settings.minimum_midi_pitch),
            ),
            _midi_frequency(settings.maximum_midi_pitch),
            model=settings.model,
            decoder=torchcrepe.decode.viterbi,
            return_periodicity=True,
            batch_size=settings.batch_size,
            device=device,
            pad=True,
        )


def segment_pitch_track(
    track: PitchTrack,
    settings: TorchCrepeBassSettings | None = None,
) -> tuple[NoteEvent, ...]:
    """Build conservative monophonic notes from pitch, periodicity and loudness."""

    config = settings or TorchCrepeBassSettings()
    frame_count = min(
        len(track.frequencies_hz), len(track.periodicities), len(track.loudness_db)
    )
    if frame_count == 0:
        return ()

    midi = [
        _frequency_to_midi(float(value)) if math.isfinite(float(value)) and value > 0 else math.nan
        for value in track.frequencies_hz[:frame_count]
    ]
    periodicity = [float(value) for value in track.periodicities[:frame_count]]
    loudness = [float(value) for value in track.loudness_db[:frame_count]]
    onset_strengths = _aligned_onset_strengths(track.onset_strengths, frame_count)
    spectral_midi = _aligned_spectral_midi(track.spectral_frequencies_hz, frame_count)
    _recover_onset_gaps(
        midi,
        periodicity,
        loudness,
        onset_strengths,
        spectral_midi,
        track.hop_seconds,
        config,
    )
    voiced = _hysteresis_voicing(midi, periodicity, loudness, config)
    smoothed = _median_smooth(midi, voiced, config.median_filter_frames)
    _bridge_short_gaps(smoothed, voiced, track.hop_seconds, config)

    minimum_frames = max(1, math.ceil((config.minimum_note_length_ms / 1000) / track.hop_seconds))
    minimum_onset_frames = max(
        1,
        math.ceil((config.minimum_onset_note_length_ms / 1000) / track.hop_seconds),
    )
    onset_guard_frames = max(
        minimum_onset_frames,
        math.ceil((config.onset_boundary_guard_ms / 1000) / track.hop_seconds),
    )
    events: list[NoteEvent] = []
    confirmed_attack_times: set[float] = set()
    for run_start, run_end in _true_runs(voiced):
        onset_boundaries = _onset_boundaries(
            onset_strengths,
            run_start,
            run_end,
            minimum_onset_frames,
            onset_guard_frames,
        )
        boundaries = _combine_boundaries(
            _pitch_boundaries(smoothed, run_start, run_end, config),
            onset_boundaries,
            run_start,
            run_end,
            minimum_onset_frames,
        )
        confirmed_onsets = set(onset_boundaries)
        starts = [run_start, *boundaries]
        ends = [*boundaries, run_end]
        for start, end in zip(starts, ends):
            onset_confirmed = start in confirmed_onsets or (
                start == run_start
                and _has_onset(
                    onset_strengths,
                    run_start,
                    min(run_end, run_start + onset_guard_frames + 1),
                )
            )
            required_frames = minimum_onset_frames if onset_confirmed else minimum_frames
            if end - start < required_frames:
                continue
            values = [smoothed[index] for index in range(start, end) if math.isfinite(smoothed[index])]
            if not values:
                continue
            pitch = round(_median(values))
            if not config.minimum_midi_pitch <= pitch <= config.maximum_midi_pitch:
                continue
            confidence = _clamp(_median(periodicity[start:end]), 0.0, 1.0)
            start_seconds = start * track.hop_seconds
            end_seconds = min(track.audio_duration_seconds, end * track.hop_seconds)
            if end_seconds <= start_seconds:
                continue
            if onset_confirmed:
                confirmed_attack_times.add(start_seconds)
            events.append(
                NoteEvent(
                    id="pending",
                    detected_start_seconds=start_seconds,
                    detected_end_seconds=end_seconds,
                    midi_pitch=pitch,
                    velocity=max(1, min(127, round(24 + confidence * 103))),
                    confidence=confidence,
                )
            )

    merged = _merge_adjacent_notes(
        events,
        config.merge_gap_ms / 1000,
        confirmed_attack_times,
    )
    return tuple(
        NoteEvent(
            id=f"bass-torchcrepe-{index:06d}",
            detected_start_seconds=event.detected_start_seconds,
            detected_end_seconds=event.detected_end_seconds,
            midi_pitch=event.midi_pitch,
            velocity=event.velocity,
            confidence=event.confidence,
        )
        for index, event in enumerate(merged)
    )


def _frame_loudness_db(audio: Any, frame_count: int) -> list[float]:
    import torch

    if frame_count <= 0:
        return []
    samples = audio.numel()
    if samples == 0:
        return [-120.0] * frame_count
    edges = torch.linspace(0, samples, frame_count + 1, dtype=torch.int64)
    result: list[float] = []
    for index in range(frame_count):
        start = int(edges[index])
        end = max(start + 1, int(edges[index + 1]))
        frame = audio[start:min(samples, end)]
        rms = float(torch.sqrt(torch.mean(frame * frame) + 1e-12))
        result.append(20 * math.log10(max(rms, 1e-6)))
    return result


def _detect_onset_strengths(
    audio: Any,
    frame_count: int,
    settings: TorchCrepeBassSettings,
) -> list[float]:
    """Return sparse normalized attack strengths aligned with CREPE frames."""

    import librosa
    import numpy

    if frame_count <= 0 or audio.numel() == 0:
        return [0.0] * max(0, frame_count)
    samples = audio.numpy()
    envelope = librosa.onset.onset_strength(
        y=samples,
        sr=settings.sample_rate,
        hop_length=settings.hop_length,
        n_fft=settings.onset_fft_size,
        fmax=settings.onset_frequency_max_hz,
        aggregate=numpy.median,
        detrend=True,
    )
    if envelope.size == 0 or not numpy.any(numpy.isfinite(envelope)):
        return [0.0] * frame_count
    envelope = numpy.nan_to_num(envelope, nan=0.0, posinf=0.0, neginf=0.0)
    scale = max(
        float(numpy.quantile(envelope, 0.95)),
        float(numpy.max(envelope)) * 0.1,
    )
    if scale <= 1e-8:
        return [0.0] * frame_count
    normalized = numpy.clip(envelope / scale, 0.0, 1.0)
    peaks = librosa.util.peak_pick(
        normalized,
        pre_max=2,
        post_max=2,
        pre_avg=8,
        post_avg=8,
        delta=settings.onset_peak_delta,
        wait=settings.onset_peak_wait_frames,
    )
    strengths = [0.0] * frame_count
    for peak in peaks:
        index = min(frame_count - 1, max(0, int(peak)))
        strengths[index] = float(normalized[int(peak)])
    return strengths


def _spectral_pitch_frequencies(
    audio: Any,
    frame_count: int,
    settings: TorchCrepeBassSettings,
) -> list[float]:
    """Estimate a cheap fallback F0 track, including the low B below CREPE's range."""

    import librosa
    import numpy

    if frame_count <= 0 or audio.numel() == 0:
        return [math.nan] * max(0, frame_count)
    frequencies = librosa.yin(
        audio.numpy(),
        fmin=_midi_frequency(settings.minimum_midi_pitch),
        fmax=_midi_frequency(settings.maximum_midi_pitch),
        sr=settings.sample_rate,
        frame_length=settings.spectral_fallback_frame_length,
        hop_length=settings.hop_length,
        trough_threshold=settings.spectral_fallback_trough_threshold,
    )
    aligned = numpy.full(frame_count, numpy.nan, dtype=float)
    copied = min(frame_count, len(frequencies))
    aligned[:copied] = frequencies[:copied]
    return aligned.tolist()


def _hysteresis_voicing(
    midi: Sequence[float],
    periodicity: Sequence[float],
    loudness: Sequence[float],
    settings: TorchCrepeBassSettings,
) -> list[bool]:
    active = False
    voiced: list[bool] = []
    for pitch, confidence, level in zip(midi, periodicity, loudness):
        threshold = settings.periodicity_off if active else settings.periodicity_on
        active = bool(
            math.isfinite(pitch)
            and math.isfinite(confidence)
            and level >= settings.silence_threshold_db
            and confidence >= threshold
        )
        voiced.append(active)
    return voiced


def _median_smooth(values: Sequence[float], voiced: Sequence[bool], width: int) -> list[float]:
    radius = max(0, width // 2)
    result: list[float] = []
    for index, value in enumerate(values):
        if not voiced[index]:
            result.append(math.nan)
            continue
        neighbours = [
            values[cursor]
            for cursor in range(max(0, index - radius), min(len(values), index + radius + 1))
            if voiced[cursor] and math.isfinite(values[cursor])
        ]
        result.append(_median(neighbours) if neighbours else value)
    return result


def _bridge_short_gaps(
    midi: list[float],
    voiced: list[bool],
    hop_seconds: float,
    settings: TorchCrepeBassSettings,
) -> None:
    maximum = max(0, round((settings.maximum_unvoiced_gap_ms / 1000) / hop_seconds))
    if maximum == 0:
        return
    index = 0
    while index < len(voiced):
        if voiced[index]:
            index += 1
            continue
        start = index
        while index < len(voiced) and not voiced[index]:
            index += 1
        end = index
        if (
            start > 0
            and end < len(voiced)
            and end - start <= maximum
            and abs(midi[start - 1] - midi[end]) < settings.pitch_jump_semitones
        ):
            left, right = midi[start - 1], midi[end]
            for offset, cursor in enumerate(range(start, end), start=1):
                midi[cursor] = left + (right - left) * offset / (end - start + 1)
                voiced[cursor] = True


def _pitch_boundaries(
    midi: Sequence[float],
    start: int,
    end: int,
    settings: TorchCrepeBassSettings,
) -> list[int]:
    stable = max(1, settings.stable_pitch_frames)
    boundaries: list[int] = []
    cursor = start + 1
    while cursor + stable <= end:
        left = midi[max(start, cursor - stable):cursor]
        right = midi[cursor:cursor + stable]
        if (
            left
            and right
            and abs(_median(right) - _median(left)) >= settings.pitch_jump_semitones
            and cursor - (boundaries[-1] if boundaries else start) >= stable
        ):
            search_start = max(start + 1, cursor - stable + 1)
            search_end = min(end, cursor + stable)
            boundary = max(
                range(search_start, search_end),
                key=lambda index: abs(midi[index] - midi[index - 1]),
            )
            if boundary - (boundaries[-1] if boundaries else start) >= stable:
                boundaries.append(boundary)
            cursor = boundary + stable
        else:
            cursor += 1
    return boundaries


def _aligned_onset_strengths(values: Sequence[float], frame_count: int) -> list[float]:
    strengths = [0.0] * frame_count
    for index, value in enumerate(values[:frame_count]):
        strengths[index] = max(0.0, float(value)) if math.isfinite(float(value)) else 0.0
    return strengths


def _aligned_spectral_midi(values: Sequence[float], frame_count: int) -> list[float]:
    midi = [math.nan] * frame_count
    for index, value in enumerate(values[:frame_count]):
        frequency = float(value)
        if math.isfinite(frequency) and frequency > 0:
            midi[index] = _frequency_to_midi(frequency)
    return midi


def _recover_onset_gaps(
    midi: list[float],
    periodicity: list[float],
    loudness: Sequence[float],
    onset_strengths: Sequence[float],
    spectral_midi: Sequence[float],
    hop_seconds: float,
    settings: TorchCrepeBassSettings,
) -> None:
    """Fill CREPE dropouts only for stable, onset-delimited spectral notes."""

    if not spectral_midi or hop_seconds <= 0:
        return
    onset_frames = [index for index, strength in enumerate(onset_strengths) if strength > 0]
    if not onset_frames:
        return
    maximum_frames = max(
        1,
        round((settings.spectral_fallback_max_interval_ms / 1000) / hop_seconds),
    )
    analysis_delay = max(1, settings.stable_pitch_frames)
    for onset_index, start in enumerate(onset_frames):
        next_onset = (
            onset_frames[onset_index + 1]
            if onset_index + 1 < len(onset_frames)
            else len(midi)
        )
        end = min(len(midi), next_onset, start + maximum_frames)
        if end - start < max(2, settings.stable_pitch_frames):
            continue
        analysis_start = min(end, start + analysis_delay)
        values = [
            value
            for value in spectral_midi[analysis_start:end]
            if math.isfinite(value)
        ]
        if len(values) < max(3, (end - analysis_start) // 2):
            continue
        pitch = _median(values)
        stable_fraction = sum(
            abs(value - pitch) < settings.spectral_fallback_pitch_tolerance
            for value in values
        ) / len(values)
        crepe_support = sum(
            math.isfinite(midi[index])
            and math.isfinite(periodicity[index])
            and periodicity[index] >= settings.periodicity_off
            for index in range(start, end)
        ) / (end - start)
        median_loudness = _median(loudness[start:end])
        if (
            stable_fraction < settings.spectral_fallback_stability
            or crepe_support > settings.spectral_fallback_max_crepe_support
            or median_loudness < settings.silence_threshold_db
        ):
            continue
        rounded_pitch = round(pitch)
        if not settings.minimum_midi_pitch <= rounded_pitch <= settings.maximum_midi_pitch:
            continue
        for index in range(start, end):
            # The fallback may bridge a neural dropout, but must never replace
            # a valid CREPE estimate merely because most of the interval was
            # unvoiced. This was a source of false octave substitutions.
            if (
                math.isfinite(midi[index])
                and math.isfinite(periodicity[index])
                and periodicity[index] >= settings.periodicity_off
            ):
                continue
            midi[index] = float(rounded_pitch)
            periodicity[index] = max(
                periodicity[index] if math.isfinite(periodicity[index]) else 0.0,
                settings.spectral_fallback_confidence,
            )


def _onset_boundaries(
    strengths: Sequence[float],
    start: int,
    end: int,
    minimum_frames: int,
    boundary_guard_frames: int,
) -> list[int]:
    return [
        index
        for index in range(start + boundary_guard_frames, end - minimum_frames + 1)
        if strengths[index] > 0
    ]


def _has_onset(strengths: Sequence[float], start: int, end: int) -> bool:
    return any(strength > 0 for strength in strengths[start:end])


def _combine_boundaries(
    pitch_boundaries: Sequence[int],
    onset_boundaries: Sequence[int],
    start: int,
    end: int,
    minimum_frames: int,
) -> list[int]:
    onset_set = set(onset_boundaries)
    candidates = sorted(set(pitch_boundaries) | onset_set)
    result: list[int] = []
    for boundary in candidates:
        if boundary - start < minimum_frames or end - boundary < minimum_frames:
            continue
        if result and boundary - result[-1] < minimum_frames:
            if boundary in onset_set and result[-1] not in onset_set:
                result[-1] = boundary
            continue
        result.append(boundary)
    return result


def _true_runs(values: Sequence[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate([*values, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    return runs


def _merge_adjacent_notes(
    events: Sequence[NoteEvent],
    maximum_gap: float,
    confirmed_attack_times: set[float] | None = None,
) -> list[NoteEvent]:
    attack_times = confirmed_attack_times or set()
    merged: list[NoteEvent] = []
    for event in events:
        gap = event.detected_start_seconds - merged[-1].detected_end_seconds if merged else math.inf
        if (
            merged
            and event.midi_pitch == merged[-1].midi_pitch
            and 0 <= gap <= maximum_gap
            and event.detected_start_seconds not in attack_times
        ):
            previous = merged[-1]
            confidence = max(previous.confidence or 0, event.confidence or 0)
            merged[-1] = NoteEvent(
                id="pending",
                detected_start_seconds=previous.detected_start_seconds,
                detected_end_seconds=event.detected_end_seconds,
                midi_pitch=event.midi_pitch,
                velocity=max(previous.velocity, event.velocity),
                confidence=confidence,
            )
        else:
            merged.append(event)
    return merged


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _frequency_to_midi(frequency: float) -> float:
    return 69 + 12 * math.log2(frequency / 440.0)


def _midi_frequency(midi_pitch: int) -> float:
    return 440.0 * math.pow(2.0, (midi_pitch - 69) / 12.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
