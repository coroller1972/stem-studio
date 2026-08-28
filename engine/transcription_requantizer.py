"""Rebuild musical timing and exports from persisted detected events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import TranscriptionError
from fretboard import BassFretboardSolver
from midi_export import export_bass_midi, export_drums_midi
from musicxml_export import export_bass_musicxml, export_drums_musicxml
from quantization import fixed_tempo_map, quantize_drums, quantize_notes
from transcription_domain import (
    BassTranscription,
    DrumEvent,
    DrumTranscription,
    NoteEvent,
    PitchBendPoint,
    TimeSignature,
    TranscriptionFiles,
    TranscriptionProgressReporter,
    TranscriptionTrack,
)


def requantize_transcription(
    events_file: Path,
    output_dir: Path,
    track: TranscriptionTrack,
    bpm: float,
    first_measure_seconds: float,
    progress: TranscriptionProgressReporter,
    *,
    subdivision: int = 4,
) -> TranscriptionFiles:
    payload = _read_payload(events_file, track)
    output = output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    signature = _time_signature(payload)

    progress.report(track, "quantization", 0.15, "Rebuilding the beat grid")
    if track == "bass":
        source_events = _bass_events(payload.get("sourceEvents") or payload.get("events"))
        if not source_events:
            raise TranscriptionError("The bass transcription contains no reusable events.")
        tempo_map = fixed_tempo_map(
            bpm,
            first_measure_seconds,
            max(event.detected_end_seconds for event in source_events),
            time_signature=signature,
            tempo_candidates=_tempo_candidates(payload),
        )
        quantized = quantize_notes(source_events, tempo_map, subdivision)
        tuning = tuple(int(value) for value in payload.get("tuning", (28, 33, 38, 43)))
        progress.report(track, "fretboard", 0.55, "Updating bass positions")
        tab = BassFretboardSolver(tuning=tuning).solve(quantized)
        warnings = _manual_timing_warnings(payload)
        if len(tab) != len(quantized):
            warnings += ("Some notes could not be placed on the configured fretboard.",)
        transcription = BassTranscription(
            events=quantized,
            tab=tab,
            tempo_map=tempo_map,
            tuning=tuning,
            warnings=warnings,
            model_id=str(payload.get("modelId") or "unknown"),
            source_events=source_events,
        )
        progress.report(track, "export", 0.75, "Regenerating bass exports")
        json_path = _write_json(output / "bass.json", transcription.to_payload())
        midi_path = export_bass_midi(quantized, tempo_map, output / "bass.mid")
        xml_path = export_bass_musicxml(
            quantized,
            tab,
            tempo_map,
            output / "bass.musicxml",
            tuning=tuning,
        )
    else:
        source_events = _drum_events(payload.get("sourceEvents") or payload.get("events"))
        if not source_events:
            raise TranscriptionError("The drum transcription contains no reusable events.")
        tempo_map = fixed_tempo_map(
            bpm,
            first_measure_seconds,
            max(event.detected_time_seconds for event in source_events),
            time_signature=signature,
            tempo_candidates=_tempo_candidates(payload),
        )
        quantized = quantize_drums(source_events, tempo_map, subdivision)
        transcription = DrumTranscription(
            events=quantized,
            tempo_map=tempo_map,
            warnings=_manual_timing_warnings(payload),
            source_events=source_events,
        )
        progress.report(track, "export", 0.75, "Regenerating drum exports")
        json_path = _write_json(output / "drums.json", transcription.to_payload())
        midi_path = export_drums_midi(quantized, tempo_map, output / "drums.mid")
        xml_path = export_drums_musicxml(quantized, tempo_map, output / "drums.musicxml")

    progress.report(track, "completed", 1.0, "Timing update completed")
    return TranscriptionFiles(json_path, midi_path, xml_path, transcription)


def _read_payload(path: Path, expected_track: TranscriptionTrack) -> dict[str, Any]:
    source = path.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".json":
        raise TranscriptionError("The saved transcription could not be found.", str(source))
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TranscriptionError("The saved transcription could not be read.", str(error)) from error
    if not isinstance(payload, dict) or payload.get("track") != expected_track:
        raise TranscriptionError("The saved transcription does not match the selected track.")
    return payload


def _bass_events(value: object) -> tuple[NoteEvent, ...]:
    if not isinstance(value, list):
        raise TranscriptionError("The saved bass events are invalid.")
    try:
        return tuple(
            NoteEvent(
                id=str(item["id"]),
                detected_start_seconds=float(item["detectedStartSeconds"]),
                detected_end_seconds=float(item["detectedEndSeconds"]),
                midi_pitch=int(item["midiPitch"]),
                velocity=int(item["velocity"]),
                confidence=_optional_float(item.get("confidence")),
                pitch_bends=tuple(
                    PitchBendPoint(float(point["timeOffsetSeconds"]), float(point["semitones"]))
                    for point in item.get("pitchBends", [])
                ),
            )
            for item in value
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TranscriptionError("The saved bass events are invalid.", str(error)) from error


def _drum_events(value: object) -> tuple[DrumEvent, ...]:
    if not isinstance(value, list):
        raise TranscriptionError("The saved drum events are invalid.")
    try:
        return tuple(
            DrumEvent(
                id=str(item["id"]),
                detected_time_seconds=float(item["detectedTimeSeconds"]),
                instrument=item["instrument"],
                velocity=int(item["velocity"]),
                confidence=_optional_float(item.get("confidence")),
            )
            for item in value
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TranscriptionError("The saved drum events are invalid.", str(error)) from error


def _time_signature(payload: dict[str, Any]) -> TimeSignature:
    value = payload.get("tempoMap", {}).get("timeSignature", {})
    try:
        return TimeSignature(int(value.get("numerator", 4)), int(value.get("denominator", 4)))
    except (AttributeError, TypeError, ValueError) as error:
        raise TranscriptionError("The saved time signature is invalid.", str(error)) from error


def _manual_timing_warnings(payload: dict[str, Any]) -> tuple[str, ...]:
    previous = payload.get("warnings", [])
    warnings = tuple(
        str(value)
        for value in previous
        if not str(value).startswith("Metric tempo is ambiguous;")
        and not str(value).startswith("Tempo and first measure were adjusted manually.")
    )
    return warnings + ("Tempo and first measure were adjusted manually.",)


def _tempo_candidates(payload: dict[str, Any]) -> tuple[float, ...]:
    values = payload.get("tempoMap", {}).get("tempoCandidates", [])
    if not isinstance(values, list):
        return ()
    candidates: list[float] = []
    for value in values:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            continue
        if 20 <= candidate <= 400:
            candidates.append(candidate)
    return tuple(candidates)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
