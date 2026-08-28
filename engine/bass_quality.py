"""Deterministic quality metrics for monophonic bass transcription outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from transcription_domain import NoteEvent


@dataclass(frozen=True)
class BassQualityMetrics:
    note_count: int
    overlapping_pairs: int
    octave_overlap_pairs: int
    multi_pitch_grid_cells: int
    same_pitch_grid_duplicates: int

    def to_payload(self) -> dict[str, int]:
        return {
            "noteCount": self.note_count,
            "overlappingPairs": self.overlapping_pairs,
            "octaveOverlapPairs": self.octave_overlap_pairs,
            "multiPitchGridCells": self.multi_pitch_grid_cells,
            "samePitchGridDuplicates": self.same_pitch_grid_duplicates,
        }


def measure_bass_quality(events: Sequence[NoteEvent]) -> BassQualityMetrics:
    ordered = sorted(events, key=lambda event: (event.detected_start_seconds, event.detected_end_seconds))
    overlapping_pairs = 0
    octave_overlap_pairs = 0
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if right.detected_start_seconds >= left.detected_end_seconds:
                break
            if left.detected_start_seconds >= right.detected_end_seconds:
                continue
            overlapping_pairs += 1
            if abs(left.midi_pitch - right.midi_pitch) == 12:
                octave_overlap_pairs += 1

    grid_pitches: dict[float, set[int]] = {}
    grid_pitch_counts: dict[tuple[float, int], int] = {}
    for event in ordered:
        if event.quantized_start_beat is None:
            continue
        start = event.quantized_start_beat
        grid_pitches.setdefault(start, set()).add(event.midi_pitch)
        key = (start, event.midi_pitch)
        grid_pitch_counts[key] = grid_pitch_counts.get(key, 0) + 1

    return BassQualityMetrics(
        note_count=len(ordered),
        overlapping_pairs=overlapping_pairs,
        octave_overlap_pairs=octave_overlap_pairs,
        multi_pitch_grid_cells=sum(len(pitches) > 1 for pitches in grid_pitches.values()),
        same_pitch_grid_duplicates=sum(count > 1 for count in grid_pitch_counts.values()),
    )
