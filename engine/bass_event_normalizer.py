"""Conservative monophonic normalization shared by bass transcription engines."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from transcription_domain import NoteEvent


@dataclass(frozen=True)
class BassEventNormalizerSettings:
    simultaneous_onset_tolerance_seconds: float = 0.055
    minimum_trimmed_duration_seconds: float = 0.025
    continuity_weight: float = 0.12
    duration_weight: float = 0.08


def normalize_bass_events(
    events: Sequence[NoteEvent],
    settings: BassEventNormalizerSettings | None = None,
) -> tuple[NoteEvent, ...]:
    """Return a stable monophonic sequence without inventing new pitches.

    Simultaneous Basic Pitch candidates are reduced to the strongest plausible
    event. Later attacks are preserved by trimming an earlier note's release,
    rather than discarding the new note. Adjacent zero-gap notes remain distinct
    because they can represent deliberate repeated attacks.
    """

    config = settings or BassEventNormalizerSettings()
    ordered = sorted(
        events,
        key=lambda event: (
            event.detected_start_seconds,
            event.detected_end_seconds,
            -_confidence(event),
            event.midi_pitch,
        ),
    )
    onset_groups = _group_simultaneous_onsets(
        ordered,
        config.simultaneous_onset_tolerance_seconds,
    )
    selected: list[NoteEvent] = []
    for group in onset_groups:
        previous = selected[-1] if selected else None
        selected.append(max(group, key=lambda event: _candidate_score(event, previous, config)))

    monophonic: list[NoteEvent] = []
    for event in selected:
        if not monophonic or event.detected_start_seconds >= monophonic[-1].detected_end_seconds:
            monophonic.append(event)
            continue

        previous = monophonic[-1]
        trimmed_duration = event.detected_start_seconds - previous.detected_start_seconds
        if trimmed_duration >= config.minimum_trimmed_duration_seconds:
            monophonic[-1] = replace(previous, detected_end_seconds=event.detected_start_seconds)
            monophonic.append(event)
            continue

        before_previous = monophonic[-2] if len(monophonic) > 1 else None
        if _candidate_score(event, before_previous, config) > _candidate_score(
            previous,
            before_previous,
            config,
        ):
            monophonic[-1] = event

    return tuple(monophonic)


def _group_simultaneous_onsets(
    events: Sequence[NoteEvent],
    tolerance: float,
) -> list[list[NoteEvent]]:
    groups: list[list[NoteEvent]] = []
    for event in events:
        if not groups:
            groups.append([event])
            continue
        group = groups[-1]
        anchor = group[0].detected_start_seconds
        overlaps_group = any(
            event.detected_start_seconds < candidate.detected_end_seconds
            for candidate in group
        )
        if event.detected_start_seconds - anchor <= tolerance and overlaps_group:
            group.append(event)
        else:
            groups.append([event])
    return groups


def _candidate_score(
    event: NoteEvent,
    previous: NoteEvent | None,
    settings: BassEventNormalizerSettings,
) -> float:
    duration = event.detected_end_seconds - event.detected_start_seconds
    score = _confidence(event) + min(1.0, duration) * settings.duration_weight
    if previous is not None:
        interval = abs(event.midi_pitch - previous.midi_pitch)
        score += max(0.0, 1.0 - interval / 12.0) * settings.continuity_weight
    return score


def _confidence(event: NoteEvent) -> float:
    if event.confidence is not None:
        return max(0.0, min(1.0, event.confidence))
    return event.velocity / 127.0
