"""Canonical beat-domain spans shared by notation exporters and tests."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence

from transcription_domain import NoteEvent

DIVISIONS_PER_QUARTER = 24


@dataclass(frozen=True)
class MeasureWindow:
    number: int
    start_beat: float
    end_beat: float
    implicit: bool = False

    @property
    def duration_beats(self) -> float:
        return self.end_beat - self.start_beat


@dataclass(frozen=True)
class NotatedDuration:
    ticks: int
    note_type: str
    dots: int = 0
    actual_notes: int | None = None
    normal_notes: int | None = None


@dataclass(frozen=True)
class NoteSpan:
    event: NoteEvent
    start_beat: float
    end_beat: float


@dataclass(frozen=True)
class NotationAtom:
    event: NoteEvent
    measure_number: int
    start_beat: float
    duration: NotatedDuration
    tie_start: bool
    tie_stop: bool

    @property
    def duration_beats(self) -> float:
        return self.duration.ticks / DIVISIONS_PER_QUARTER


_DURATIONS = (
    NotatedDuration(96, "whole"),
    NotatedDuration(72, "half", dots=1),
    NotatedDuration(48, "half"),
    NotatedDuration(36, "quarter", dots=1),
    NotatedDuration(24, "quarter"),
    NotatedDuration(18, "eighth", dots=1),
    NotatedDuration(16, "quarter", actual_notes=3, normal_notes=2),
    NotatedDuration(12, "eighth"),
    NotatedDuration(9, "16th", dots=1),
    NotatedDuration(8, "eighth", actual_notes=3, normal_notes=2),
    NotatedDuration(6, "16th"),
    NotatedDuration(4, "16th", actual_notes=3, normal_notes=2),
    NotatedDuration(3, "32nd"),
    NotatedDuration(2, "32nd", actual_notes=3, normal_notes=2),
)


def measure_windows(
    earliest_beat: float,
    latest_beat: float,
    measure_beats: float,
) -> tuple[MeasureWindow, ...]:
    if measure_beats <= 0:
        raise ValueError("A measure must have a positive duration.")
    earliest = min(0.0, earliest_beat)
    latest = max(measure_beats, latest_beat)
    first_index = math.floor(earliest / measure_beats)
    last_index = max(0, math.ceil((latest - 1e-9) / measure_beats) - 1)
    windows: list[MeasureWindow] = []
    for index in range(first_index, last_index + 1):
        start = index * measure_beats
        if index == first_index and index < 0:
            start = earliest
        end = (index + 1) * measure_beats
        windows.append(
            MeasureWindow(
                number=index + 1,
                start_beat=start,
                end_beat=end,
                implicit=index < 0,
            )
        )
    return tuple(windows)


def monophonic_note_spans(events: Sequence[NoteEvent]) -> tuple[NoteSpan, ...]:
    """Return one non-overlapping strongest bass span per onset."""
    strongest: dict[float, NoteEvent] = {}
    for event in events:
        start = event.quantized_start_beat
        duration = event.quantized_duration_beats
        if start is None or duration is None or duration <= 0:
            continue
        previous = strongest.get(start)
        if previous is None or _event_strength(event) > _event_strength(previous):
            strongest[start] = event
    ordered = sorted(strongest.items())
    spans: list[NoteSpan] = []
    for index, (start, event) in enumerate(ordered):
        end = start + (event.quantized_duration_beats or 0)
        if index + 1 < len(ordered):
            end = min(end, ordered[index + 1][0])
        if end > start:
            spans.append(NoteSpan(event, start, end))
    return tuple(spans)


def notation_atoms(
    events: Sequence[NoteEvent],
    measure_beats: float,
) -> tuple[tuple[MeasureWindow, ...], tuple[NotationAtom, ...]]:
    spans = monophonic_note_spans(events)
    earliest = min((span.start_beat for span in spans), default=0.0)
    latest = max((span.end_beat for span in spans), default=measure_beats)
    windows = measure_windows(earliest, latest, measure_beats)
    provisional: list[NotationAtom] = []
    for span in spans:
        event_atoms: list[NotationAtom] = []
        for window in windows:
            start = max(span.start_beat, window.start_beat)
            end = min(span.end_beat, window.end_beat)
            if end <= start:
                continue
            cursor = start
            for duration in spell_duration(end - start):
                event_atoms.append(
                    NotationAtom(
                        event=span.event,
                        measure_number=window.number,
                        start_beat=cursor,
                        duration=duration,
                        tie_start=False,
                        tie_stop=False,
                    )
                )
                cursor += duration.ticks / DIVISIONS_PER_QUARTER
        for index, atom in enumerate(event_atoms):
            provisional.append(
                replace(
                    atom,
                    tie_stop=index > 0,
                    tie_start=index < len(event_atoms) - 1,
                )
            )
    return windows, tuple(sorted(provisional, key=lambda atom: (atom.start_beat, atom.event.id)))


def spell_duration(beats: float) -> tuple[NotatedDuration, ...]:
    ticks = round(beats * DIVISIONS_PER_QUARTER)
    if ticks <= 0:
        return ()
    result: list[NotatedDuration] = []
    remaining = ticks
    while remaining:
        duration = next((candidate for candidate in _DURATIONS if candidate.ticks <= remaining), None)
        if duration is None:
            raise ValueError(
                f"Duration {beats!r} beat(s) cannot be represented at "
                f"{DIVISIONS_PER_QUARTER} divisions per quarter."
            )
        result.append(duration)
        remaining -= duration.ticks
    return tuple(result)


def _event_strength(event: NoteEvent) -> tuple[float, int, float]:
    return (
        event.confidence if event.confidence is not None else -1.0,
        event.velocity,
        event.quantized_duration_beats or 0.0,
    )
