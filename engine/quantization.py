"""Pure time-to-beat conversion and explicit grid quantization."""

from __future__ import annotations

import math

from transcription_domain import DrumEvent, NoteEvent, TempoBeat, TempoMap, TimeSignature


def fixed_tempo_map(
    bpm: float,
    first_measure_seconds: float,
    end_time_seconds: float,
    *,
    time_signature: TimeSignature | None = None,
    tempo_candidates: tuple[float, ...] = (),
) -> TempoMap:
    """Build a stable beat grid whose beat zero is the first measure downbeat."""
    if not 20 <= bpm <= 400:
        raise ValueError("Tempo must be between 20 and 400 BPM.")
    if first_measure_seconds < 0 or not math.isfinite(first_measure_seconds):
        raise ValueError("The first measure timestamp must be a finite positive value.")
    if not math.isfinite(end_time_seconds):
        raise ValueError("The transcription duration must be finite.")
    signature = time_signature or TimeSignature()
    seconds_per_beat = 60.0 / bpm
    covered_duration = max(0.0, end_time_seconds - first_measure_seconds)
    beat_count = math.ceil(covered_duration / seconds_per_beat) + signature.numerator + 1
    beats = tuple(
        TempoBeat(index, first_measure_seconds + index * seconds_per_beat)
        for index in range(beat_count)
    )
    return TempoMap(
        bpm=bpm,
        beats=beats,
        time_signature=signature,
        tempo_candidates=tuple(dict.fromkeys((bpm, *tempo_candidates))),
    )


def time_to_beat(time_seconds: float, tempo_map: TempoMap) -> float:
    beats = tempo_map.beats
    seconds_per_beat = 60.0 / tempo_map.bpm
    if not beats:
        return max(0.0, time_seconds / seconds_per_beat)
    if len(beats) == 1 or time_seconds <= beats[0].time_seconds:
        return beats[0].beat_index + (time_seconds - beats[0].time_seconds) / seconds_per_beat
    for left, right in zip(beats, beats[1:]):
        if time_seconds <= right.time_seconds:
            ratio = (time_seconds - left.time_seconds) / (right.time_seconds - left.time_seconds)
            return left.beat_index + ratio * (right.beat_index - left.beat_index)
    last = beats[-1]
    return last.beat_index + (time_seconds - last.time_seconds) / seconds_per_beat


def quantize_beat(beat: float, subdivision: int) -> float:
    if subdivision not in (1, 2, 4, 3, 6):
        raise ValueError("Subdivision must represent quarter, eighth, sixteenth, or triplet grids.")
    return round(beat * subdivision) / subdivision


def quantize_notes(
    events: list[NoteEvent] | tuple[NoteEvent, ...],
    tempo_map: TempoMap,
    subdivision: int = 4,
) -> tuple[NoteEvent, ...]:
    minimum_duration = 1.0 / subdivision
    quantized: list[NoteEvent] = []
    for event in events:
        start = quantize_beat(time_to_beat(event.detected_start_seconds, tempo_map), subdivision)
        end = quantize_beat(time_to_beat(event.detected_end_seconds, tempo_map), subdivision)
        quantized.append(event.quantized(start, max(minimum_duration, end - start)))
    # A monophonic bass cannot contain a chord. Close attacks can collapse onto
    # one grid position after quantization, so keep its strongest candidate.
    strongest: dict[float | None, NoteEvent] = {}
    for event in quantized:
        key = event.quantized_start_beat
        previous = strongest.get(key)
        if previous is None or _note_strength(event) > _note_strength(previous):
            strongest[key] = event
    return tuple(
        sorted(
            strongest.values(),
            key=lambda event: (
                event.quantized_start_beat or 0,
                event.detected_start_seconds,
                event.midi_pitch,
            ),
        )
    )


def _note_strength(event: NoteEvent) -> tuple[float, int, float]:
    return (
        event.confidence if event.confidence is not None else -1.0,
        event.velocity,
        event.detected_end_seconds - event.detected_start_seconds,
    )


def quantize_drums(
    events: list[DrumEvent] | tuple[DrumEvent, ...],
    tempo_map: TempoMap,
    subdivision: int = 4,
) -> tuple[DrumEvent, ...]:
    quantized = tuple(
        event.quantized(quantize_beat(time_to_beat(event.detected_time_seconds, tempo_map), subdivision))
        for event in events
    )
    # Adjacent onsets can collapse into the same grid cell. Keep only the
    # strongest hit for one instrument at one musical position.
    strongest: dict[tuple[float | None, str], DrumEvent] = {}
    for event in quantized:
        key = (event.quantized_beat, event.instrument)
        previous = strongest.get(key)
        if previous is None or event.velocity > previous.velocity:
            strongest[key] = event
    return tuple(
        sorted(
            strongest.values(),
            key=lambda event: (event.quantized_beat or 0, event.detected_time_seconds, event.instrument),
        )
    )
