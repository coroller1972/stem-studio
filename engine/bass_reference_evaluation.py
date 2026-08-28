"""Reference-MIDI evaluation for monophonic bass transcription."""

from __future__ import annotations

import bisect
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from transcription_domain import NoteEvent, PitchBendPoint


@dataclass(frozen=True)
class NoteMatch:
    reference: NoteEvent
    prediction: NoteEvent
    onset_error_seconds: float


@dataclass(frozen=True)
class AlignmentResult:
    offset_seconds: float
    exact_pitch_matches: int
    median_onset_error_seconds: float

    def to_payload(self) -> dict[str, int | float]:
        return {
            "offsetSeconds": self.offset_seconds,
            "exactPitchMatches": self.exact_pitch_matches,
            "medianOnsetErrorSeconds": self.median_onset_error_seconds,
        }


@dataclass(frozen=True)
class BassReferenceMetrics:
    reference_note_count: int
    prediction_note_count: int
    exact_pitch_matches: int
    onset_matches: int
    note_precision: float
    note_recall: float
    note_f1: float
    onset_precision: float
    onset_recall: float
    onset_f1: float
    pitch_accuracy_on_matched_onsets: float
    octave_errors: int
    octave_errors_up: int
    octave_errors_down: int
    octave_error_rate: float
    median_onset_error_seconds: float
    p95_onset_error_seconds: float
    median_duration_error_seconds: float
    median_duration_iou: float
    short_note_count: int
    short_note_recall: float
    repeated_note_count: int
    repeated_note_recall: float
    low_b_count: int
    low_b_recall: float

    def to_payload(self) -> dict[str, int | float]:
        return {
            "referenceNoteCount": self.reference_note_count,
            "predictionNoteCount": self.prediction_note_count,
            "exactPitchMatches": self.exact_pitch_matches,
            "onsetMatches": self.onset_matches,
            "notePrecision": self.note_precision,
            "noteRecall": self.note_recall,
            "noteF1": self.note_f1,
            "onsetPrecision": self.onset_precision,
            "onsetRecall": self.onset_recall,
            "onsetF1": self.onset_f1,
            "pitchAccuracyOnMatchedOnsets": self.pitch_accuracy_on_matched_onsets,
            "octaveErrors": self.octave_errors,
            "octaveErrorsUp": self.octave_errors_up,
            "octaveErrorsDown": self.octave_errors_down,
            "octaveErrorRate": self.octave_error_rate,
            "medianOnsetErrorSeconds": self.median_onset_error_seconds,
            "p95OnsetErrorSeconds": self.p95_onset_error_seconds,
            "medianDurationErrorSeconds": self.median_duration_error_seconds,
            "medianDurationIoU": self.median_duration_iou,
            "shortNoteCount": self.short_note_count,
            "shortNoteRecall": self.short_note_recall,
            "repeatedNoteCount": self.repeated_note_count,
            "repeatedNoteRecall": self.repeated_note_recall,
            "lowBCount": self.low_b_count,
            "lowBRecall": self.low_b_recall,
        }


@dataclass(frozen=True)
class BassReferenceReport:
    prediction_path: Path
    reference_path: Path
    reference_bpm: float
    onset_tolerance_seconds: float
    alignment: AlignmentResult
    metrics: BassReferenceMetrics

    def to_payload(self) -> dict[str, object]:
        return {
            "predictionPath": str(self.prediction_path),
            "referencePath": str(self.reference_path),
            "referenceBpm": self.reference_bpm,
            "onsetToleranceSeconds": self.onset_tolerance_seconds,
            "alignment": self.alignment.to_payload(),
            "metrics": self.metrics.to_payload(),
        }


def evaluate_bass_reference(
    prediction_path: Path,
    reference_midi_path: Path,
    *,
    reference_bpm: float,
    onset_tolerance_seconds: float = 0.08,
    alignment_offset_seconds: float | None = None,
) -> BassReferenceReport:
    predictions = load_prediction_events(prediction_path)
    references = load_reference_midi(reference_midi_path, bpm_override=reference_bpm)
    if not predictions:
        raise ValueError("The prediction contains no bass events.")
    if not references:
        raise ValueError("The reference MIDI contains no notes.")
    if alignment_offset_seconds is None:
        alignment = estimate_alignment(references, predictions)
    else:
        if not math.isfinite(alignment_offset_seconds):
            raise ValueError("The alignment offset must be finite.")
        matches = match_notes(
            references,
            predictions,
            alignment_offset_seconds,
            tolerance_seconds=max(0.12, onset_tolerance_seconds),
            require_pitch=True,
        )
        alignment = AlignmentResult(
            alignment_offset_seconds,
            len(matches),
            _median([match.onset_error_seconds for match in matches]),
        )
    window_predictions = _prediction_window(references, predictions, alignment.offset_seconds)
    metrics = measure_reference_quality(
        references,
        window_predictions,
        alignment.offset_seconds,
        onset_tolerance_seconds=onset_tolerance_seconds,
    )
    return BassReferenceReport(
        prediction_path.expanduser().resolve(),
        reference_midi_path.expanduser().resolve(),
        reference_bpm,
        onset_tolerance_seconds,
        alignment,
        metrics,
    )


def load_prediction_events(path: Path) -> tuple[NoteEvent, ...]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    values = payload.get("sourceEvents") or payload.get("events") or []
    return tuple(_note_from_payload(item) for item in values)


def load_reference_midi(path: Path, *, bpm_override: float | None = None) -> tuple[NoteEvent, ...]:
    try:
        import mido
    except ImportError as error:
        raise RuntimeError("Install mido from engine/requirements.txt.") from error
    if bpm_override is not None and not 20 <= bpm_override <= 400:
        raise ValueError("Reference BPM must be between 20 and 400.")
    midi = mido.MidiFile(path.expanduser())
    tempo = mido.bpm2tempo(bpm_override) if bpm_override is not None else mido.bpm2tempo(120)
    absolute_seconds = 0.0
    active: dict[tuple[int, int], list[tuple[float, int]]] = {}
    notes: list[NoteEvent] = []
    for message in mido.merge_tracks(midi.tracks):
        absolute_seconds += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        if message.type == "set_tempo" and bpm_override is None:
            tempo = message.tempo
            continue
        if message.type == "note_on" and message.velocity > 0:
            active.setdefault((message.channel, message.note), []).append(
                (absolute_seconds, message.velocity)
            )
            continue
        if message.type not in ("note_off", "note_on"):
            continue
        key = (message.channel, message.note)
        starts = active.get(key)
        if not starts:
            continue
        start, velocity = starts.pop(0)
        if absolute_seconds <= start:
            continue
        notes.append(
            NoteEvent(
                id=f"reference-{len(notes)}",
                detected_start_seconds=start,
                detected_end_seconds=absolute_seconds,
                midi_pitch=message.note,
                velocity=max(1, velocity),
                confidence=1.0,
            )
        )
    return tuple(sorted(notes, key=lambda note: (note.detected_start_seconds, note.midi_pitch)))


def estimate_alignment(
    references: Sequence[NoteEvent],
    predictions: Sequence[NoteEvent],
    *,
    bin_seconds: float = 0.02,
    tolerance_seconds: float = 0.12,
) -> AlignmentResult:
    """Estimate where a reference excerpt occurs inside a longer prediction."""
    histogram: Counter[int] = Counter()
    predictions_by_pitch: dict[int, list[NoteEvent]] = {}
    for prediction in predictions:
        predictions_by_pitch.setdefault(prediction.midi_pitch, []).append(prediction)
    for reference in references:
        for prediction in predictions_by_pitch.get(reference.midi_pitch, ()):
            delta = prediction.detected_start_seconds - reference.detected_start_seconds
            histogram[round(delta / bin_seconds)] += 1
    if not histogram:
        raise ValueError("No common pitch was found between prediction and reference.")

    candidates = [bucket * bin_seconds for bucket, _count in histogram.most_common(80)]
    best: tuple[int, float, float, tuple[NoteMatch, ...]] | None = None
    for candidate in candidates:
        matches = match_notes(
            references,
            predictions,
            candidate,
            tolerance_seconds=tolerance_seconds,
            require_pitch=True,
        )
        if not matches:
            continue
        refined = candidate + statistics.median(
            match.prediction.detected_start_seconds
            - (match.reference.detected_start_seconds + candidate)
            for match in matches
        )
        refined_matches = match_notes(
            references,
            predictions,
            refined,
            tolerance_seconds=tolerance_seconds,
            require_pitch=True,
        )
        median_error = _median([match.onset_error_seconds for match in refined_matches])
        score = (len(refined_matches), -median_error, -abs(refined), refined_matches)
        if best is None or score[:3] > best[:3]:
            best = score
            best_offset = refined
    if best is None:
        raise ValueError("Unable to align the reference MIDI with the prediction.")
    return AlignmentResult(best_offset, best[0], -best[1])


def match_notes(
    references: Sequence[NoteEvent],
    predictions: Sequence[NoteEvent],
    offset_seconds: float,
    *,
    tolerance_seconds: float,
    require_pitch: bool,
) -> tuple[NoteMatch, ...]:
    ordered_predictions = sorted(predictions, key=lambda note: note.detected_start_seconds)
    starts = [note.detected_start_seconds for note in ordered_predictions]
    edges: list[tuple[float, int, int]] = []
    for reference_index, reference in enumerate(references):
        target = reference.detected_start_seconds + offset_seconds
        left = bisect.bisect_left(starts, target - tolerance_seconds)
        right = bisect.bisect_right(starts, target + tolerance_seconds)
        for prediction_index in range(left, right):
            prediction = ordered_predictions[prediction_index]
            if require_pitch and prediction.midi_pitch != reference.midi_pitch:
                continue
            edges.append((abs(prediction.detected_start_seconds - target), reference_index, prediction_index))
    used_references: set[int] = set()
    used_predictions: set[int] = set()
    matches: list[NoteMatch] = []
    for error, reference_index, prediction_index in sorted(edges):
        if reference_index in used_references or prediction_index in used_predictions:
            continue
        used_references.add(reference_index)
        used_predictions.add(prediction_index)
        matches.append(
            NoteMatch(references[reference_index], ordered_predictions[prediction_index], error)
        )
    return tuple(sorted(matches, key=lambda match: match.reference.detected_start_seconds))


def measure_reference_quality(
    references: Sequence[NoteEvent],
    predictions: Sequence[NoteEvent],
    offset_seconds: float,
    *,
    onset_tolerance_seconds: float,
) -> BassReferenceMetrics:
    exact = match_notes(
        references,
        predictions,
        offset_seconds,
        tolerance_seconds=onset_tolerance_seconds,
        require_pitch=True,
    )
    onsets = match_notes(
        references,
        predictions,
        offset_seconds,
        tolerance_seconds=onset_tolerance_seconds,
        require_pitch=False,
    )
    exact_reference_ids = {match.reference.id for match in exact}
    pitch_correct = sum(match.reference.midi_pitch == match.prediction.midi_pitch for match in onsets)
    octave_errors = sum(
        abs(match.reference.midi_pitch - match.prediction.midi_pitch) == 12 for match in onsets
    )
    octave_errors_up = sum(
        match.prediction.midi_pitch - match.reference.midi_pitch == 12 for match in onsets
    )
    octave_errors_down = sum(
        match.prediction.midi_pitch - match.reference.midi_pitch == -12 for match in onsets
    )
    onset_errors = [match.onset_error_seconds for match in exact]
    duration_errors = [
        abs(_duration(match.reference) - _duration(match.prediction)) for match in exact
    ]
    duration_ious = [_duration_iou(match, offset_seconds) for match in exact]
    short_ids = {
        note.id for note in references if _duration(note) < 0.13
    }
    repeated_ids = _repeated_note_ids(references)
    low_b_ids = {note.id for note in references if note.midi_pitch == 23}
    note_precision, note_recall, note_f1 = _scores(len(exact), len(predictions), len(references))
    onset_precision, onset_recall, onset_f1 = _scores(len(onsets), len(predictions), len(references))
    return BassReferenceMetrics(
        reference_note_count=len(references),
        prediction_note_count=len(predictions),
        exact_pitch_matches=len(exact),
        onset_matches=len(onsets),
        note_precision=note_precision,
        note_recall=note_recall,
        note_f1=note_f1,
        onset_precision=onset_precision,
        onset_recall=onset_recall,
        onset_f1=onset_f1,
        pitch_accuracy_on_matched_onsets=_ratio(pitch_correct, len(onsets)),
        octave_errors=octave_errors,
        octave_errors_up=octave_errors_up,
        octave_errors_down=octave_errors_down,
        octave_error_rate=_ratio(octave_errors, len(onsets)),
        median_onset_error_seconds=_median(onset_errors),
        p95_onset_error_seconds=_percentile(onset_errors, 0.95),
        median_duration_error_seconds=_median(duration_errors),
        median_duration_iou=_median(duration_ious),
        short_note_count=len(short_ids),
        short_note_recall=_ratio(len(short_ids & exact_reference_ids), len(short_ids)),
        repeated_note_count=len(repeated_ids),
        repeated_note_recall=_ratio(len(repeated_ids & exact_reference_ids), len(repeated_ids)),
        low_b_count=len(low_b_ids),
        low_b_recall=_ratio(len(low_b_ids & exact_reference_ids), len(low_b_ids)),
    )


def _prediction_window(
    references: Sequence[NoteEvent],
    predictions: Sequence[NoteEvent],
    offset_seconds: float,
) -> tuple[NoteEvent, ...]:
    start = min(note.detected_start_seconds for note in references) + offset_seconds - 0.15
    end = max(note.detected_end_seconds for note in references) + offset_seconds + 0.15
    return tuple(
        note for note in predictions if start <= note.detected_start_seconds <= end
    )


def _note_from_payload(payload: dict[str, object]) -> NoteEvent:
    return NoteEvent(
        id=str(payload["id"]),
        detected_start_seconds=float(payload["detectedStartSeconds"]),
        detected_end_seconds=float(payload["detectedEndSeconds"]),
        midi_pitch=int(payload["midiPitch"]),
        velocity=int(payload["velocity"]),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        pitch_bends=tuple(
            PitchBendPoint(float(point["timeOffsetSeconds"]), float(point["semitones"]))
            for point in payload.get("pitchBends", ())
        ),
    )


def _repeated_note_ids(references: Sequence[NoteEvent], maximum_gap_seconds: float = 0.25) -> set[str]:
    ordered = sorted(references, key=lambda note: note.detected_start_seconds)
    result: set[str] = set()
    for left, right in zip(ordered, ordered[1:]):
        if (
            left.midi_pitch == right.midi_pitch
            and right.detected_start_seconds - left.detected_start_seconds <= maximum_gap_seconds
        ):
            result.update((left.id, right.id))
    return result


def _duration(note: NoteEvent) -> float:
    return note.detected_end_seconds - note.detected_start_seconds


def _duration_iou(match: NoteMatch, offset_seconds: float) -> float:
    reference_start = match.reference.detected_start_seconds + offset_seconds
    reference_end = match.reference.detected_end_seconds + offset_seconds
    prediction_start = match.prediction.detected_start_seconds
    prediction_end = match.prediction.detected_end_seconds
    intersection = max(0.0, min(reference_end, prediction_end) - max(reference_start, prediction_start))
    union = max(reference_end, prediction_end) - min(reference_start, prediction_start)
    return _ratio(intersection, union)


def _scores(matches: int, predictions: int, references: int) -> tuple[float, float, float]:
    precision = _ratio(matches, predictions)
    recall = _ratio(matches, references)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return precision, recall, f1


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def _percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]
