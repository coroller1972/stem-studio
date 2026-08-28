"""Context-aware bass fretboard assignment using dynamic programming."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Sequence

from transcription_domain import NoteEvent, TabNote


@dataclass(frozen=True)
class FretPosition:
    string_index: int
    fret: int


@dataclass(frozen=True)
class FretboardWeights:
    fret_movement: float = 1.0
    string_movement: float = 1.35
    high_fret: float = 0.12
    open_string: float = -0.15
    chord_stretch: float = 1.8


class BassFretboardSolver:
    """Solve low-to-high string assignments; string 0 is the lowest string."""

    def __init__(
        self,
        tuning: Sequence[int] = (28, 33, 38, 43),
        max_fret: int = 24,
        weights: FretboardWeights = FretboardWeights(),
    ) -> None:
        if not tuning or any(pitch < 0 or pitch > 127 for pitch in tuning):
            raise ValueError("Bass tuning must contain valid MIDI pitches.")
        if max_fret < 1:
            raise ValueError("max_fret must be positive.")
        self.tuning = tuple(tuning)
        self.max_fret = max_fret
        self.weights = weights

    def positions_for_pitch(self, midi_pitch: int) -> tuple[FretPosition, ...]:
        return tuple(
            FretPosition(string_index, midi_pitch - open_pitch)
            for string_index, open_pitch in enumerate(self.tuning)
            if 0 <= midi_pitch - open_pitch <= self.max_fret
        )

    def transition_cost(self, previous: FretPosition, current: FretPosition) -> float:
        return (
            abs(current.fret - previous.fret) * self.weights.fret_movement
            + abs(current.string_index - previous.string_index) * self.weights.string_movement
            + max(0, current.fret - 12) * self.weights.high_fret
            + (self.weights.open_string if current.fret == 0 else 0)
        )

    def solve(self, events: Sequence[NoteEvent]) -> tuple[TabNote, ...]:
        playable = [event for event in sorted(events, key=lambda item: (item.detected_start_seconds, item.midi_pitch)) if self.positions_for_pitch(event.midi_pitch)]
        if not playable:
            return ()

        groups = _group_simultaneous(playable)
        choices = [self._group_choices(group) for group in groups]
        costs: list[dict[tuple[FretPosition, ...], tuple[float, tuple[FretPosition, ...] | None]]] = []
        for group_index, group_choices in enumerate(choices):
            layer: dict[tuple[FretPosition, ...], tuple[float, tuple[FretPosition, ...] | None]] = {}
            for choice in group_choices:
                intrinsic = self._group_cost(choice)
                if group_index == 0:
                    layer[choice] = (intrinsic, None)
                    continue
                best_cost = float("inf")
                best_previous = None
                for previous, (previous_cost, _) in costs[-1].items():
                    transition = self.transition_cost(previous[-1], choice[0])
                    total = previous_cost + transition + intrinsic
                    if total < best_cost:
                        best_cost, best_previous = total, previous
                layer[choice] = (best_cost, best_previous)
            costs.append(layer)

        selected: list[tuple[FretPosition, ...]] = [min(costs[-1], key=lambda item: costs[-1][item][0])]
        for layer in reversed(costs[1:]):
            previous = layer[selected[-1]][1]
            assert previous is not None
            selected.append(previous)
        selected.reverse()

        result: list[TabNote] = []
        for group, positions in zip(groups, selected):
            for event, position in zip(group, positions):
                result.append(
                    TabNote(
                        note_event_id=event.id,
                        string_index=position.string_index,
                        fret=position.fret,
                        start_beat=event.quantized_start_beat or 0.0,
                        duration_beats=event.quantized_duration_beats or 0.25,
                    )
                )
        return tuple(result)

    def _group_choices(self, events: Sequence[NoteEvent]) -> tuple[tuple[FretPosition, ...], ...]:
        all_choices = tuple(product(*(self.positions_for_pitch(event.midi_pitch) for event in events)))
        unique_strings = tuple(choice for choice in all_choices if len({position.string_index for position in choice}) == len(choice))
        return unique_strings or all_choices

    def _group_cost(self, positions: Sequence[FretPosition]) -> float:
        high_fret_cost = sum(max(0, position.fret - 12) * self.weights.high_fret for position in positions)
        open_cost = sum(self.weights.open_string for position in positions if position.fret == 0)
        stretch = (max(position.fret for position in positions) - min(position.fret for position in positions)) if len(positions) > 1 else 0
        return high_fret_cost + open_cost + max(0, stretch - 4) * self.weights.chord_stretch


def _group_simultaneous(events: Sequence[NoteEvent], tolerance_seconds: float = 0.025) -> list[list[NoteEvent]]:
    groups: list[list[NoteEvent]] = []
    for event in events:
        if groups and abs(event.detected_start_seconds - groups[-1][0].detected_start_seconds) <= tolerance_seconds:
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups

