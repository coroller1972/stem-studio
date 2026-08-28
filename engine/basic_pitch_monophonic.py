"""Monophonic temporal decoder for Basic Pitch bass activations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from transcription_domain import NoteEvent, PitchBendPoint

BASIC_PITCH_MIDI_OFFSET = 21


@dataclass(frozen=True)
class MonophonicDecoderSettings:
    minimum_midi_pitch: int = 23
    maximum_midi_pitch: int = 67
    frame_threshold: float = 0.35
    onset_threshold: float = 0.55
    minimum_note_length_ms: float = 130.0
    minimum_onset_note_length_ms: float = 55.0
    maximum_fragment_gap_ms: float = 35.0
    pitch_change_penalty: float = 0.72
    interval_penalty: float = 0.035
    silence_transition_penalty: float = 0.38
    onset_bonus: float = 0.65
    harmonic_penalty: float = 0.75
    fundamental_prior_bonus: float = 0.90
    fundamental_prior_penalty: float = 0.55
    fundamental_tolerance_semitones: float = 0.8


def decode_monophonic_bass(
    note_probabilities: np.ndarray,
    onset_probabilities: np.ndarray,
    frame_times: Sequence[float],
    settings: MonophonicDecoderSettings | None = None,
    *,
    fundamental_midi: Sequence[float] | None = None,
    fundamental_confidence: Sequence[float] | None = None,
    contour_probabilities: np.ndarray | None = None,
) -> tuple[NoteEvent, ...]:
    """Decode one pitch or silence per frame, then reconstruct note attacks."""

    config = settings or MonophonicDecoderSettings()
    notes, onsets, times = _validated_inputs(
        note_probabilities,
        onset_probabilities,
        frame_times,
        config,
    )
    if notes.shape[0] == 0:
        return ()

    emissions = _emission_scores(
        notes,
        onsets,
        config,
        fundamental_midi,
        fundamental_confidence,
    )
    states = _viterbi_path(emissions, config)
    contours = _validated_contours(contour_probabilities, notes.shape[0])
    return _states_to_events(states, notes, onsets, times, config, contours)


def _validated_contours(
    contour_probabilities: np.ndarray | None,
    frame_count: int,
) -> np.ndarray | None:
    if contour_probabilities is None:
        return None
    contours = np.asarray(contour_probabilities, dtype=np.float64)
    if contours.ndim != 2 or contours.shape[0] != frame_count:
        raise ValueError("Basic Pitch contours must align with note frames.")
    return np.clip(np.nan_to_num(contours), 0.0, 1.0)


def _validated_inputs(
    note_probabilities: np.ndarray,
    onset_probabilities: np.ndarray,
    frame_times: Sequence[float],
    settings: MonophonicDecoderSettings,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    notes = np.asarray(note_probabilities, dtype=np.float64)
    onsets = np.asarray(onset_probabilities, dtype=np.float64)
    times = np.asarray(frame_times, dtype=np.float64)
    if notes.ndim != 2 or onsets.ndim != 2:
        raise ValueError("Basic Pitch note and onset outputs must be two-dimensional.")
    if notes.shape != onsets.shape:
        raise ValueError("Basic Pitch note and onset outputs must share a shape.")
    if len(times) != notes.shape[0]:
        raise ValueError("Basic Pitch frame times must align with model outputs.")
    start = settings.minimum_midi_pitch - BASIC_PITCH_MIDI_OFFSET
    end = settings.maximum_midi_pitch - BASIC_PITCH_MIDI_OFFSET + 1
    if start < 0 or end > notes.shape[1] or start >= end:
        raise ValueError("The configured bass range is outside Basic Pitch note bins.")
    return (
        np.clip(np.nan_to_num(notes[:, start:end]), 0.0, 1.0),
        np.clip(np.nan_to_num(onsets[:, start:end]), 0.0, 1.0),
        times,
    )


def _emission_scores(
    notes: np.ndarray,
    onsets: np.ndarray,
    settings: MonophonicDecoderSettings,
    fundamental_midi: Sequence[float] | None,
    fundamental_confidence: Sequence[float] | None,
) -> np.ndarray:
    epsilon = 1e-5
    pitch_scores = np.log(np.clip(notes, epsilon, 1.0))
    pitch_scores += settings.onset_bonus * onsets

    # When a plausible fundamental is active, reduce the score of its octave
    # harmonic. A weak lower bin never pulls a valid upper fundamental down.
    if notes.shape[1] > 12:
        lower_support = np.maximum(0.0, notes[:, :-12] - settings.frame_threshold)
        pitch_scores[:, 12:] -= settings.harmonic_penalty * lower_support

    _apply_fundamental_prior(
        pitch_scores,
        settings,
        fundamental_midi,
        fundamental_confidence,
    )

    strongest = np.max(notes, axis=1)
    silence_probability = np.clip(1.0 - strongest, epsilon, 1.0)
    silence_scores = np.log(silence_probability)
    return np.column_stack((pitch_scores, silence_scores))


def _apply_fundamental_prior(
    pitch_scores: np.ndarray,
    settings: MonophonicDecoderSettings,
    fundamental_midi: Sequence[float] | None,
    fundamental_confidence: Sequence[float] | None,
) -> None:
    if fundamental_midi is None:
        return
    pitches = np.asarray(fundamental_midi, dtype=np.float64)
    if len(pitches) != pitch_scores.shape[0]:
        raise ValueError("The fundamental track must align with Basic Pitch frames.")
    confidence = (
        np.ones(len(pitches), dtype=np.float64)
        if fundamental_confidence is None
        else np.asarray(fundamental_confidence, dtype=np.float64)
    )
    if len(confidence) != len(pitches):
        raise ValueError("Fundamental confidence must align with its pitch track.")
    midi_states = np.arange(
        settings.minimum_midi_pitch,
        settings.maximum_midi_pitch + 1,
        dtype=np.float64,
    )
    for frame in np.flatnonzero(np.isfinite(pitches)):
        weight = float(np.clip(confidence[frame], 0.0, 1.0))
        if weight <= 0:
            continue
        distance = np.abs(midi_states - pitches[frame])
        support = np.maximum(
            0.0,
            1.0 - distance / settings.fundamental_tolerance_semitones,
        )
        disagreement = np.minimum(1.0, distance / 6.0)
        pitch_scores[frame] += weight * (
            settings.fundamental_prior_bonus * support
            - settings.fundamental_prior_penalty * disagreement
        )


def _viterbi_path(
    emissions: np.ndarray,
    settings: MonophonicDecoderSettings,
) -> np.ndarray:
    frame_count, state_count = emissions.shape
    pitch_count = state_count - 1
    transition_cost = np.zeros((state_count, state_count), dtype=np.float64)
    pitch_indices = np.arange(pitch_count)
    intervals = np.abs(pitch_indices[:, None] - pitch_indices[None, :])
    pitch_changes = intervals > 0
    transition_cost[:pitch_count, :pitch_count] = np.where(
        pitch_changes,
        settings.pitch_change_penalty
        + settings.interval_penalty * np.minimum(intervals, 24),
        0.0,
    )
    transition_cost[pitch_count, :pitch_count] = settings.silence_transition_penalty
    transition_cost[:pitch_count, pitch_count] = settings.silence_transition_penalty

    backpointers = np.zeros((frame_count, state_count), dtype=np.uint8)
    scores = emissions[0].copy()
    for frame in range(1, frame_count):
        candidates = scores[:, None] - transition_cost
        previous = np.argmax(candidates, axis=0)
        scores = candidates[previous, np.arange(state_count)] + emissions[frame]
        backpointers[frame] = previous

    states = np.empty(frame_count, dtype=np.int16)
    states[-1] = int(np.argmax(scores))
    for frame in range(frame_count - 1, 0, -1):
        states[frame - 1] = backpointers[frame, states[frame]]
    return states


def _states_to_events(
    states: np.ndarray,
    notes: np.ndarray,
    onsets: np.ndarray,
    times: np.ndarray,
    settings: MonophonicDecoderSettings,
    contours: np.ndarray | None,
) -> tuple[NoteEvent, ...]:
    pitch_count = notes.shape[1]
    hop_seconds = _median_hop(times)
    minimum_frames = max(
        1,
        math.ceil((settings.minimum_note_length_ms / 1000) / hop_seconds),
    )
    minimum_onset_frames = max(
        1,
        math.ceil((settings.minimum_onset_note_length_ms / 1000) / hop_seconds),
    )
    onset_peaks = _onset_peaks(onsets, settings.onset_threshold)
    segments: list[tuple[int, int, int, bool]] = []
    start = 0
    while start < len(states):
        state = int(states[start])
        end = start + 1
        while end < len(states) and states[end] == state:
            end += 1
        if state < pitch_count:
            boundaries = [
                frame
                for frame in onset_peaks.get(state, ())
                if start + minimum_onset_frames <= frame <= end - minimum_onset_frames
            ]
            starts = [start, *boundaries]
            ends = [*boundaries, end]
            for segment_start, segment_end in zip(starts, ends):
                onset_confirmed = _has_nearby_onset(
                    onset_peaks.get(state, ()),
                    segment_start,
                )
                required = minimum_onset_frames if onset_confirmed else minimum_frames
                if segment_end - segment_start >= required:
                    segments.append((segment_start, segment_end, state, onset_confirmed))
        start = end

    maximum_gap_frames = max(
        0,
        round((settings.maximum_fragment_gap_ms / 1000) / hop_seconds),
    )
    merged_segments: list[tuple[int, int, int, bool]] = []
    for segment in segments:
        segment_start, segment_end, state, onset_confirmed = segment
        if (
            merged_segments
            and merged_segments[-1][2] == state
            and not onset_confirmed
            and segment_start - merged_segments[-1][1] <= maximum_gap_frames
        ):
            previous_start, _previous_end, previous_state, previous_onset = merged_segments[-1]
            merged_segments[-1] = (
                previous_start,
                segment_end,
                previous_state,
                previous_onset,
            )
        else:
            merged_segments.append(segment)

    events: list[NoteEvent] = []
    for start, end, state, _onset_confirmed in merged_segments:
        start_seconds = max(0.0, float(times[start]))
        end_seconds = float(times[end]) if end < len(times) else float(times[-1] + hop_seconds)
        if end_seconds <= start_seconds:
            continue
        confidence = float(np.mean(notes[start:end, state]))
        midi_pitch = settings.minimum_midi_pitch + state
        events.append(
            NoteEvent(
                id=f"bass-basic-monophonic-{len(events):06d}",
                detected_start_seconds=start_seconds,
                detected_end_seconds=end_seconds,
                midi_pitch=midi_pitch,
                velocity=max(1, min(127, round(confidence * 127))),
                confidence=max(0.0, min(1.0, confidence)),
                pitch_bends=_pitch_bend_points(
                    contours,
                    start,
                    end,
                    midi_pitch,
                    times,
                ),
            )
        )
    return tuple(events)


def _pitch_bend_points(
    contours: np.ndarray | None,
    start: int,
    end: int,
    midi_pitch: int,
    times: np.ndarray,
) -> tuple[PitchBendPoint, ...]:
    if contours is None or end <= start:
        return ()
    bins_per_semitone = 3
    center = (midi_pitch - BASIC_PITCH_MIDI_OFFSET) * bins_per_semitone
    radius = 2 * bins_per_semitone
    lower = max(0, center - radius)
    upper = min(contours.shape[1], center + radius + 1)
    if lower >= upper:
        return ()
    offsets = np.arange(lower, upper, dtype=np.float64) - center
    weights = np.exp(-0.5 * (offsets / 2.0) ** 2)
    window = contours[start:end, lower:upper] * weights
    raw = offsets[np.argmax(window, axis=1)] / bins_per_semitone
    if len(raw) >= 3:
        padded = np.pad(raw, (1, 1), mode="edge")
        raw = np.array(
            [np.median(padded[index : index + 3]) for index in range(len(raw))],
            dtype=np.float64,
        )
    note_start = float(times[start])
    return tuple(
        PitchBendPoint(
            time_offset_seconds=max(0.0, float(times[frame] - note_start)),
            semitones=float(np.clip(value, -2.0, 2.0)),
        )
        for frame, value in zip(range(start, end), raw)
    )


def _onset_peaks(onsets: np.ndarray, threshold: float) -> dict[int, tuple[int, ...]]:
    result: dict[int, tuple[int, ...]] = {}
    for state in range(onsets.shape[1]):
        peaks = []
        for frame in range(onsets.shape[0]):
            value = onsets[frame, state]
            left = onsets[frame - 1, state] if frame > 0 else -math.inf
            right = onsets[frame + 1, state] if frame + 1 < len(onsets) else -math.inf
            if value >= threshold and value >= left and value > right:
                peaks.append(frame)
        if peaks:
            result[state] = tuple(peaks)
    return result


def _has_nearby_onset(peaks: Sequence[int], frame: int) -> bool:
    return any(abs(peak - frame) <= 1 for peak in peaks)


def _median_hop(times: np.ndarray) -> float:
    if len(times) < 2:
        return 256 / 22_050
    differences = np.diff(times)
    positive = differences[differences > 0]
    return float(np.median(positive)) if len(positive) else 256 / 22_050
